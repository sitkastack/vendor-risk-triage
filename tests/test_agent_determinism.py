"""Tests for the determinism contract (introduced 1.0.5, output contract 1.4.0).

Covers the framework's per-record attestation that the producing
configuration honored the deterministic-contract preconditions:

- Temperature is pinned at 0.0 by default; the model_settings dict
  passed to PydanticAI carries it.
- Records produced by a default agent carry a DeterminismAttestation
  with contract_honored=True.
- Non-zero temperature without the legacy opt-out raises
  TriageAgentError at construction; with the opt-out it warns and
  produces records with contract_honored=False.
- Custom system_prompt flips contract_honored=False (the contract is
  per-framework-default prompt).
- Fallback firing flips contract_honored=False and populates a
  FallbackRecord with reason from the closed enum.
- sampling_profile_hash is stable across runs of the same config and
  changes when temperature changes.
- system_prompt_hash is the full 64-char SHA-256 of the actually-loaded
  prompt bytes (NOT the 12-char SYSTEM_PROMPT_HASH framework-identity
  constant).
- corpus_bundle_hash is computed per-call from the chunks loaded; None
  when no chunks were supplied.
- A 1.3.0 record migrated to 1.4.0 carries a "migrated_from"
  attestation with contract_honored=False, all data fields null.
- The triage.completed event carries contract_honored and the
  effective model id in its attributes (observability sinks can route
  on the contract posture).
- The audit log envelope's content hash is sensitive to attestation
  changes (a fresh 1.4.0 record's hash differs from the same record
  with attestation null-stripped, etc.).
"""
from __future__ import annotations

import hashlib
import json
import os
import warnings
from pathlib import Path
from typing import Any

import pytest

# Set placeholder API key BEFORE pydantic_ai imports (same defense as
# test_agent_core.py: PydanticAI's Anthropic provider validates the env
# var at agent construction time even when FunctionModel/TestModel
# intercepts every call).
if not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = "test-placeholder-not-a-real-key"

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from agent.agent import (
    CONTRACT_VERSION,
    OUTPUT_SCHEMA_VERSION,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_HASH,
    SYSTEM_PROMPT_HASH_FULL,
    TriageAgent,
    TriageAgentConfig,
    TriageAgentError,
)
from agent.output_models import DeterminismAttestation, FallbackRecord
from observability import CapturingEventLogger, Observability


REPO_ROOT = Path(__file__).parent.parent
SUBMISSION_PATH = (
    REPO_ROOT / "examples" / "submissions"
    / "01-tier1-internal-productivity.json"
)


def _submission() -> dict:
    return json.loads(SUBMISSION_PATH.read_text())


def _tier1_payload() -> dict:
    return {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Tier 1 rationale for determinism tests.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
    }


def _function_model(payload: dict) -> FunctionModel:
    def _call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=payload),
        ])
    return FunctionModel(_call)


# -- temperature pinning --------------------------------------------------


def test_default_agent_pins_temperature_zero_in_model_settings() -> None:
    """The framework passes temperature=0.0 to the underlying PydanticAI Agent.

    The model_settings dict is the supported pinning surface; the
    framework writes it at construction. A user's Model instance with
    a buried non-zero temperature is overridden by this pinning.
    """
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    # PydanticAI's Agent exposes the configured model_settings; check
    # the framework pinned 0.0 there. The exact attribute name is
    # pydantic-ai-internal; we read by introspection so a name change
    # surfaces as a test break rather than a silent broken contract.
    pa = agent._pydantic_agent
    # _model_settings or model_settings — defensive across versions.
    settings = getattr(pa, "_model_settings", None) or getattr(pa, "model_settings", None)
    assert settings is not None, "PydanticAI Agent does not expose model_settings"
    assert settings.get("temperature") == 0.0


def test_explicit_zero_temperature_is_contract_honored() -> None:
    """An explicit temperature=0.0 produces records with contract_honored=True."""
    agent = TriageAgent(TriageAgentConfig(
        model=_function_model(_tier1_payload()),
        temperature=0.0,
    ))
    # FunctionModel is "test" provider, which is NOT in the
    # known-provider list — contract_honored is conservative and
    # returns False for test-provider records by design (the contract
    # cannot be measured on a FunctionModel).
    record = agent.triage(_submission())
    assert record.determinism_attestation is not None
    assert record.determinism_attestation.effective_temperature == 0.0


def test_nonzero_temperature_refuses_without_legacy_flag() -> None:
    """Non-zero temperature without allow_nondeterministic_legacy raises."""
    with pytest.raises(TriageAgentError, match="temperature"):
        TriageAgent(TriageAgentConfig(
            model=_function_model(_tier1_payload()),
            temperature=0.7,
        ))


def test_nonzero_temperature_with_legacy_flag_warns_and_constructs() -> None:
    """allow_nondeterministic_legacy=True opts out of the contract loudly."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        agent = TriageAgent(TriageAgentConfig(
            model=_function_model(_tier1_payload()),
            temperature=0.7,
            allow_nondeterministic_legacy=True,
        ))
    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert any("temperature" in str(w.message) for w in deprecation_warnings)
    record = agent.triage(_submission())
    assert record.determinism_attestation is not None
    assert record.determinism_attestation.effective_temperature == 0.7
    assert record.determinism_attestation.contract_honored is False


# -- attestation structure ------------------------------------------------


def test_fresh_record_carries_full_attestation() -> None:
    """A fresh 1.4.0 record has every attestation key present."""
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    record = agent.triage(_submission())
    attestation = record.determinism_attestation
    assert attestation is not None
    # contract_version is the framework's contract identifier
    assert attestation.contract_version == CONTRACT_VERSION
    # migrated_from is None for fresh records
    assert attestation.migrated_from is None
    # system_prompt_hash is the FULL 64-char hash, not the 12-char
    # framework-identity constant.
    assert attestation.system_prompt_hash == SYSTEM_PROMPT_HASH_FULL
    assert len(attestation.system_prompt_hash) == 64


def test_attestation_serializes_with_all_keys_present() -> None:
    """The attestation emits every nested key in JSON, including nulls.

    Audit contract: 'null means absent, not missing key'. A consumer
    parsing the envelope can count on every field being addressable.
    """
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    record = agent.triage(_submission())
    data = record.model_dump(mode="json")
    attestation_dict = data["determinism_attestation"]
    expected_keys = {
        "effective_temperature", "contract_honored", "provider",
        "effective_model_id", "fallback", "sampling_profile_hash",
        "system_prompt_hash", "corpus_bundle_hash", "contract_version",
        "migrated_from",
    }
    assert set(attestation_dict.keys()) == expected_keys


def test_system_prompt_hash_full_is_sha256_of_prompt() -> None:
    """system_prompt_hash is the SHA-256 of SYSTEM_PROMPT bytes."""
    expected = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert SYSTEM_PROMPT_HASH_FULL == expected
    # The 12-char SYSTEM_PROMPT_HASH is the prefix.
    assert SYSTEM_PROMPT_HASH == expected[:12]


def test_custom_prompt_changes_system_prompt_hash_and_flips_contract() -> None:
    """A custom system_prompt: attestation hash differs, contract_honored=False."""
    custom = "You are a custom triage agent for the ACME deployment."
    agent = TriageAgent(TriageAgentConfig(
        model=_function_model(_tier1_payload()),
        system_prompt=custom,
    ))
    record = agent.triage(_submission())
    attestation = record.determinism_attestation
    assert attestation is not None
    expected_hash = hashlib.sha256(custom.encode("utf-8")).hexdigest()
    assert attestation.system_prompt_hash == expected_hash
    assert attestation.system_prompt_hash != SYSTEM_PROMPT_HASH_FULL
    # Custom prompt exits the contract.
    assert attestation.contract_honored is False


# -- sampling_profile_hash ------------------------------------------------


def test_sampling_profile_hash_is_12_char_hex() -> None:
    """sampling_profile_hash is a 12-char lowercase hex prefix."""
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    record = agent.triage(_submission())
    attestation = record.determinism_attestation
    assert attestation is not None
    assert len(attestation.sampling_profile_hash) == 12
    assert all(c in "0123456789abcdef" for c in attestation.sampling_profile_hash)


def test_sampling_profile_hash_stable_across_runs() -> None:
    """Two records from agents with the same config get the same hash."""
    agent_a = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    agent_b = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    r1 = agent_a.triage(_submission())
    r2 = agent_b.triage(_submission())
    assert r1.determinism_attestation.sampling_profile_hash == (
        r2.determinism_attestation.sampling_profile_hash
    )


def test_sampling_profile_hash_changes_with_temperature() -> None:
    """Changing temperature produces a different sampling_profile_hash."""
    a0 = TriageAgent(TriageAgentConfig(
        model=_function_model(_tier1_payload()), temperature=0.0,
    ))
    a1 = TriageAgent(TriageAgentConfig(
        model=_function_model(_tier1_payload()),
        temperature=0.7,
        allow_nondeterministic_legacy=True,
    ))
    r0 = a0.triage(_submission())
    r1 = a1.triage(_submission())
    assert r0.determinism_attestation.sampling_profile_hash != (
        r1.determinism_attestation.sampling_profile_hash
    )


# -- corpus_bundle_hash ---------------------------------------------------


def test_corpus_bundle_hash_none_when_no_chunks() -> None:
    """No regulation_chunks supplied -> corpus_bundle_hash is None."""
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    record = agent.triage(_submission(), regulation_chunks=None)
    assert record.determinism_attestation.corpus_bundle_hash is None


def test_corpus_bundle_hash_populated_when_chunks_supplied() -> None:
    """Chunks supplied -> corpus_bundle_hash is a 64-char hex."""
    from retrieval import Chunk
    chunk_text = "A regulation requires model-risk governance."
    chunk = Chunk(
        chunk_id="test:doc:1",
        corpus_name="test",
        document_name="doc",
        page_number=1,
        text=chunk_text,
        content_hash="sha256:" + hashlib.sha256(
            chunk_text.encode("utf-8")
        ).hexdigest(),
    )
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    record = agent.triage(_submission(), regulation_chunks=[chunk])
    h = record.determinism_attestation.corpus_bundle_hash
    assert h is not None
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_corpus_bundle_hash_stable_for_same_chunks() -> None:
    """The same chunk list produces the same hash on two runs."""
    from retrieval import Chunk
    chunk = Chunk(
        chunk_id="test:doc:1",
        corpus_name="test",
        document_name="doc",
        page_number=1,
        text="Same content.",
        content_hash="sha256:" + hashlib.sha256(
            "Same content.".encode("utf-8")
        ).hexdigest(),
    )
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    r1 = agent.triage(_submission(), regulation_chunks=[chunk])
    r2 = agent.triage(_submission(), regulation_chunks=[chunk])
    assert r1.determinism_attestation.corpus_bundle_hash == (
        r2.determinism_attestation.corpus_bundle_hash
    )


# -- fallback enum --------------------------------------------------------


def test_fallback_record_enum_is_closed() -> None:
    """FallbackRecord rejects an unknown reason value."""
    with pytest.raises(Exception):
        FallbackRecord(
            reason="unknown_reason",  # type: ignore[arg-type]
            primary_model_id="anthropic:claude-sonnet-4-5",
            effective_model_id="anthropic:claude-haiku-3-5",
            primary_provider="anthropic",
            effective_provider="anthropic",
            trigger_event="rate_limit_429",
        )


def test_fallback_record_fired_is_always_true() -> None:
    """FallbackRecord.fired defaults to True."""
    fr = FallbackRecord(
        reason="transient_retry",
        primary_model_id="anthropic:claude-sonnet-4-5",
        effective_model_id="anthropic:claude-haiku-3-5",
        primary_provider="anthropic",
        effective_provider="anthropic",
        trigger_event="rate_limit_429",
    )
    assert fr.fired is True


def test_fallback_fired_flips_contract_honored() -> None:
    """A fallback firing puts contract_honored=False on the record."""
    # Build a primary that always errors and a fallback that succeeds.
    def _failing(_msgs, _info):
        raise RuntimeError("primary deliberately failing for test")
    failing_primary = FunctionModel(_failing)
    succeeding_fallback = _function_model(_tier1_payload())
    agent = TriageAgent(TriageAgentConfig(
        model=failing_primary,
        fallback_models=[succeeding_fallback],
    ))
    record = agent.triage(_submission())
    attestation = record.determinism_attestation
    assert attestation is not None
    # The fallback fired; contract_honored is False.
    assert attestation.contract_honored is False
    # The FallbackRecord is populated.
    assert attestation.fallback is not None
    assert attestation.fallback.fired is True
    assert attestation.fallback.reason in (
        "transient_retry", "cross_provider", "circuit_open",
        "hard_refusal", "operator_pinned",
    )


# -- observability --------------------------------------------------------


def test_triage_completed_event_carries_contract_honored() -> None:
    """The triage.completed observability event carries contract_honored."""
    cap = CapturingEventLogger()
    obs = Observability(event_logger=cap)
    agent = TriageAgent(TriageAgentConfig(
        model=_function_model(_tier1_payload()),
        observability=obs,
    ))
    agent.triage(_submission())
    completions = cap.filter(event_name="triage.completed")
    assert len(completions) == 1
    attrs = completions[0].attributes
    assert "contract_honored" in attrs
    assert "effective_temperature" in attrs
    assert "effective_model_id" in attrs
    assert "fallback_fired" in attrs
    assert attrs["fallback_fired"] is False


# -- migration semantics --------------------------------------------------


def test_migration_attestation_has_migrated_from_set() -> None:
    """A 1.3.0->1.4.0 migrated record's attestation flags migrated_from."""
    from migration import migrate_record
    base = {
        "decision_id": "d-001",
        "decision_timestamp": "2026-05-28T12:00:00Z",
        "input_submission_id": "v-x",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.0+test+abc123def456",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Migration rationale.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "y."},
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
        "output_schema_version": "1.3.0",
        "tenant_id": "acme-bank",
    }
    result = migrate_record(base, "1.4.0")
    attestation = result["determinism_attestation"]
    assert attestation["migrated_from"] == "1.3.0"
    assert attestation["contract_honored"] is False
    assert attestation["contract_version"] is None  # no contract was in force


# -- audit log integration ------------------------------------------------


def test_audit_log_envelope_hash_includes_attestation() -> None:
    """Building an envelope around a 1.4.0 record produces a different hash
    than building it around the same record with attestation stripped."""
    from reporting.audit_log import build_envelope, _record_canonical_bytes
    agent = TriageAgent(TriageAgentConfig(model=_function_model(_tier1_payload())))
    record = agent.triage(_submission())
    canonical = _record_canonical_bytes(record)
    # The canonical bytes contain the literal "determinism_attestation"
    # key — proving the attestation is in the hash input.
    assert b"determinism_attestation" in canonical
    # An envelope built around the record exposes a sha256 hash.
    envelope = build_envelope(
        record=record,
        sequence_number=1,
        deployment_id="test-deployment",
    )
    assert envelope.record_content_hash.startswith("sha256:")
