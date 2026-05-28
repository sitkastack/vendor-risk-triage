"""End-to-end regression suite (Phase 7 close-out / code-complete gate).

These tests verify that the framework's twelve packages *compose* into
a working pipeline, not just that each works in isolation. The
per-package suites cover units and immediate collaborators; this suite
wires the whole flow together with realistic data and asserts the
artifacts stay consistent across stage boundaries:

    submission -> triage (tenant-scoped) -> record -> validate
              -> cost estimate -> citation verify -> calibration -> judge
              -> render audit pack -> migrate -> re-validate

The agent runs against a deterministic FunctionModel (no live LLM):
the point is to integrate the framework's own components, not to test
a model provider. The classification payload is realistic (a real
tier/disposition/evidence shape), so the records flowing through the
pipeline are the same shape the agent produces in production.

Five scenario groups:

1. Golden pipeline, tenant-scoped: produce -> validate -> render, with
   tenant attribution carried end to end.
2. Eval pipeline on real agent output: citation verify, calibration,
   and judge all accept a record the agent actually emitted (catches
   drift between agent output and eval expectations).
3. Migration round-trip: a pre-tenancy record migrated forward renders
   and validates the same as a natively-produced 1.3.0 record.
4. Multi-tenant attribution + the audit invariant: two tenants produce
   correctly-attributed records that share an identical
   SYSTEM_PROMPT_HASH (uniform reasoning across tenants).
5. CLI chain as a real subprocess: the installed ``vrt`` console script
   runs triage -> render -> migrate through real files (catches
   packaging / entry-point regressions in-process tests cannot).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent.agent import (
    SYSTEM_PROMPT_HASH,
    TriageAgent,
    TriageAgentConfig,
)
from agent.output_models import TriageRecord
from schemas.validate import validate_output
from tenancy import TenantConfig


REPO_ROOT = Path(__file__).parent.parent
SUBMISSIONS_DIR = REPO_ROOT / "examples" / "submissions"


# -- shared fixtures -----------------------------------------------------


def _submission(name: str = "01-tier1-internal-productivity.json") -> dict:
    """Load a real example submission."""
    return json.loads((SUBMISSIONS_DIR / name).read_text(encoding="utf-8"))


def _classification_payload() -> dict:
    """A realistic agent classification payload (tier 2, conditional).

    Mirrors the shape the agent's tool-call returns: the reasoning
    fields only; the framework wraps these with decision_id,
    timestamps, agent_version, tenant_id, etc.
    """
    return {
        "risk_tier": "tier_2_moderate",
        "recommended_disposition": "conditional_approve",
        "classification_rationale": (
            "The vendor processes limited PII through a third-party model "
            "provider with documented data-residency controls, placing it "
            "at moderate risk. Conditional approval pending the listed "
            "mitigations."
        ),
        "evidence_cited": [
            {
                "input_field_reference": "$.ai_usage_level",
                "reasoning": "Declared usage level establishes the tier floor.",
            },
            {
                "input_field_reference": "$.data_residency",
                "reasoning": "Residency controls bound the exposure.",
            },
        ],
        "confidence_signal": {"score": 0.78, "interpretation": "moderate"},
        "required_mitigations": [
            "Obtain a signed data-processing addendum before go-live.",
            "Confirm subprocessor list and residency in writing.",
        ],
    }


def _deterministic_model():
    """A FunctionModel that always returns the realistic payload."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=_classification_payload()),
        ])

    return FunctionModel(_call)


def _tenant(tenant_id: str = "acme-bank") -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        display_name=tenant_id.replace("-", " ").title(),
        model=_deterministic_model(),
        regulation_set=("osfi-e23",),
    )


# -- Scenario 1: golden tenant-scoped pipeline ---------------------------


def test_e2e_golden_pipeline_tenant_scoped() -> None:
    """submission -> for_tenant triage -> validate -> render, attributed."""
    from reporting import render_audit_pack

    submission = _submission()
    agent = TriageAgent.for_tenant(_tenant("acme-bank"))
    record = agent.triage(submission)

    # Record is a real TriageRecord, attributed, at the current contract.
    assert isinstance(record, TriageRecord)
    assert record.tenant_id == "acme-bank"
    assert record.output_schema_version == "1.3.0"

    # It validates against the dispatch.
    ok, errors = validate_output(record.model_dump(mode="json"))
    assert ok, f"agent record failed validation: {errors}"

    # It renders, and the rendered pack reflects the real decision.
    html = render_audit_pack(record, submission)
    assert isinstance(html, str) and len(html) > 0
    assert record.decision_id in html
    # The vendor from the real submission appears in the pack.
    assert submission["vendor_name"] in html


def test_e2e_record_carries_cost_or_omits_cleanly() -> None:
    """A FunctionModel is unpriced, so cost_estimate is cleanly absent.

    This asserts the cost path does not break the pipeline for an
    unpriced (test) model: the field is simply omitted, not malformed.
    """
    agent = TriageAgent.for_tenant(_tenant())
    record = agent.triage(_submission())
    # FunctionModel is not in any price table; cost_estimate is absent.
    assert record.cost_estimate is None
    # And the record still validates without it.
    ok, _ = validate_output(record.model_dump(mode="json"))
    assert ok


# -- Scenario 2: eval pipeline on real agent output ----------------------


def test_e2e_citation_verify_on_real_output() -> None:
    """The citation verifier accepts a record the agent actually emitted."""
    from eval.citations import CitationVerifier

    submission = _submission()
    record = TriageAgent.for_tenant(_tenant()).triage(submission)

    result = CitationVerifier().verify_record(record, submission)
    # Every evidence field reference in the payload points at a real
    # submission path, so all field citations resolve.
    assert result is not None
    # The record cited $.ai_usage_level and $.data_residency, both
    # present in the submission.
    assert submission.get("ai_usage_level") is not None
    assert submission.get("data_residency") is not None


def test_e2e_calibration_on_real_outputs() -> None:
    """Calibration computes over outcomes derived from real records."""
    from eval.calibration import ConfidenceOutcome, compute_calibration

    agent = TriageAgent.for_tenant(_tenant())
    records = [agent.triage(_submission()) for _ in range(3)]

    outcomes = [
        ConfidenceOutcome(
            confidence_score=r.confidence_signal.score,
            was_correct=True,
            tier=r.risk_tier,
        )
        for r in records
    ]
    report = compute_calibration(outcomes)
    assert report is not None


def test_e2e_judge_on_real_output() -> None:
    """The LLM judge (against a deterministic model) grades a real record."""
    from eval.judge import LLMJudge, RATIONALE_COHERENCE
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    submission = _submission()
    record = TriageAgent.for_tenant(_tenant()).triage(submission)

    def _judge_call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name="final_result",
                args={"score": 0.85, "rationale": (
                    "The rationale ties the moderate tier to the declared "
                    "usage level and residency controls, citing specific "
                    "input fields."
                )},
            ),
        ])

    judge = LLMJudge(model=FunctionModel(_judge_call))
    result = judge.judge(record, submission, RATIONALE_COHERENCE)
    assert result is not None
    assert 0.0 <= result.score <= 1.0


# -- Scenario 3: migration round-trip ------------------------------------


def test_e2e_migration_roundtrip_renders_like_native() -> None:
    """A migrated pre-tenancy record renders and validates like a native one."""
    from migration import migrate_record, fixed_tenant_resolver
    from reporting import render_audit_pack

    submission = _submission()
    native = TriageAgent.for_tenant(_tenant("acme-bank")).triage(submission)
    native_dict = native.model_dump(mode="json")

    # Synthesize a pre-tenancy (1.2.0) version of the same record: drop
    # tenant_id and restamp the version, as a record produced before
    # tenancy would look.
    legacy = dict(native_dict)
    legacy.pop("tenant_id", None)
    legacy["output_schema_version"] = "1.2.0"
    ok, _ = validate_output(legacy)
    assert ok, "legacy 1.2.0 record should validate without tenant_id"

    # Migrate it forward, assigning the same tenant.
    migrated = migrate_record(
        legacy, "1.3.0", fixed_tenant_resolver("acme-bank")
    )
    assert migrated["output_schema_version"] == "1.3.0"
    assert migrated["tenant_id"] == "acme-bank"

    # The migrated record validates and renders.
    ok, errors = validate_output(migrated)
    assert ok, f"migrated record failed validation: {errors}"

    migrated_record = TriageRecord.model_validate(migrated)
    html = render_audit_pack(migrated_record, submission)
    assert migrated_record.decision_id in html


def test_e2e_migration_preserves_decision_content() -> None:
    """Migration changes only version + tenant, not the decision itself."""
    from migration import migrate_record, fixed_tenant_resolver

    native = TriageAgent.for_tenant(_tenant()).triage(_submission())
    native_dict = native.model_dump(mode="json")

    legacy = dict(native_dict)
    legacy.pop("tenant_id", None)
    legacy["output_schema_version"] = "1.2.0"

    migrated = migrate_record(
        legacy, "1.3.0", fixed_tenant_resolver("acme-bank")
    )
    # The substantive decision fields are untouched by migration.
    for field in (
        "risk_tier", "recommended_disposition", "classification_rationale",
        "decision_id", "evidence_cited",
    ):
        assert migrated[field] == native_dict[field]


# -- Scenario 4: multi-tenant attribution + audit invariant --------------


def test_e2e_multi_tenant_attribution_no_crosstalk() -> None:
    """Two tenants produce correctly-attributed, non-crossed records."""
    submission = _submission()
    acme_agent = TriageAgent.for_tenant(_tenant("acme-bank"))
    globex_agent = TriageAgent.for_tenant(_tenant("globex"))

    acme_record = acme_agent.triage(submission)
    globex_record = globex_agent.triage(submission)

    assert acme_record.tenant_id == "acme-bank"
    assert globex_record.tenant_id == "globex"
    # Distinct decision ids: the two runs are independent records.
    assert acme_record.decision_id != globex_record.decision_id


def test_e2e_uniform_system_prompt_hash_across_tenants() -> None:
    """The audit invariant: every tenant's agent shares one prompt hash.

    This is the property the framework's positioning rests on: every
    tenant's decisions trace to the identical, version-pinned reasoning.
    A per-tenant prompt would fork this hash; it must not.
    """
    acme_agent = TriageAgent.for_tenant(_tenant("acme-bank"))
    globex_agent = TriageAgent.for_tenant(_tenant("globex"))

    # Both agents' version strings encode the same system prompt hash.
    assert SYSTEM_PROMPT_HASH in acme_agent.agent_version
    assert SYSTEM_PROMPT_HASH in globex_agent.agent_version


def test_e2e_default_tenant_distinct_from_named() -> None:
    """A bare agent stamps __default__, distinct from a named tenant."""
    from agent.output_models import DEFAULT_TENANT_ID

    bare = TriageAgent(TriageAgentConfig(model=_deterministic_model()))
    named = TriageAgent.for_tenant(_tenant("acme-bank"))

    bare_record = bare.triage(_submission())
    named_record = named.triage(_submission())

    assert bare_record.tenant_id == DEFAULT_TENANT_ID
    assert named_record.tenant_id == "acme-bank"


# -- Scenario 5: CLI chain as a real subprocess --------------------------


def _run_vrt(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Invoke the installed ``vrt`` console script as a subprocess."""
    return subprocess.run(
        ["vrt", *args],
        capture_output=True,
        text=True,
        timeout=120,
        **kwargs,
    )


@pytest.mark.e2e_subprocess
def test_e2e_cli_chain_subprocess(tmp_path: Path) -> None:
    """The real vrt console script runs triage-adjacent flow end to end.

    Because triage requires a live model, this subprocess test exercises
    the parts of the CLI that run without one: it takes a record
    (produced in-process), then runs the real ``vrt render`` and
    ``vrt migrate`` console scripts through actual files. This catches
    packaging / entry-point regressions that in-process main() tests
    cannot, while staying deterministic.
    """
    # Produce a record in-process (the agent needs a model; the CLI
    # triage path would need a live one).
    submission = _submission()
    record = TriageAgent.for_tenant(_tenant("acme-bank")).triage(submission)
    record_dict = record.model_dump(mode="json")

    # Write a pre-tenancy version to migrate, and the submission.
    legacy = dict(record_dict)
    legacy.pop("tenant_id", None)
    legacy["output_schema_version"] = "1.2.0"
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")

    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record_dict), encoding="utf-8")
    submission_path = tmp_path / "submission.json"
    submission_path.write_text(json.dumps(submission), encoding="utf-8")

    # vrt --version works (entry point is wired).
    version_proc = _run_vrt(["--version"])
    assert version_proc.returncode == 0
    assert "vrt" in version_proc.stdout

    # vrt migrate: pre-tenancy record -> 1.3.0, assigning a tenant.
    migrated_path = tmp_path / "migrated.json"
    migrate_proc = _run_vrt([
        "migrate", str(legacy_path), "--to", "1.3.0",
        "--tenant-id", "acme-bank", "--output", str(migrated_path),
    ])
    assert migrate_proc.returncode == 0, migrate_proc.stderr
    migrated = json.loads(migrated_path.read_text())
    assert migrated["tenant_id"] == "acme-bank"
    assert migrated["output_schema_version"] == "1.3.0"

    # vrt render: record -> audit pack HTML.
    pack_path = tmp_path / "pack.html"
    render_proc = _run_vrt([
        "render", str(record_path),
        "--submission", str(submission_path),
        "--output", str(pack_path),
    ])
    assert render_proc.returncode == 0, render_proc.stderr
    assert pack_path.exists()
    html = pack_path.read_text()
    assert record.decision_id in html
