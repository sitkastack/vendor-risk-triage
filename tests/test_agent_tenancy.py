"""Tests for tenant-scoped agent and the required tenant_id field (Phase 7 SS2).

Covers the framework's first breaking schema change (output contract
1.2.0 -> 1.3.0, tenant_id required):

- The agent stamps tenant_id from its configured tenant (decision C1).
- Without a tenant, the agent stamps the sentinel DEFAULT_TENANT_ID
  and logs a warning (decision B2: visible + loud, never silent).
- TriageAgent.for_tenant constructs from a TenantConfig, sourcing
  model routing and tenant identity.
- Tenant routing is explicit-over-implicit: an explicit config value
  wins over the tenant's.
- The 1.3.0 schema requires tenant_id; 1.0.0-1.2.0 schemas do not
  (decision A1: backward compatibility preserved).
- The Pydantic model enforces tenant_id conditionally by declared
  output_schema_version, mirroring the JSON-schema dispatch.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from agent.agent import TriageAgent, TriageAgentConfig
from agent.output_models import DEFAULT_TENANT_ID, TriageRecord
from schemas.validate import validate_output
from tenancy import TenantConfig


REPO_ROOT = Path(__file__).parent.parent
SUBMISSION_PATH = (
    REPO_ROOT / "examples" / "submissions"
    / "01-tier1-internal-productivity.json"
)


def _payload() -> dict:
    return {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Tenant test rationale.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
    }


def _model():
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=_payload()),
        ])
    return FunctionModel(_call)


def _submission() -> dict:
    return json.loads(SUBMISSION_PATH.read_text())


# -- Agent stamps tenant_id ----------------------------------------------


def test_agent_without_tenant_stamps_default() -> None:
    """A bare agent stamps DEFAULT_TENANT_ID."""
    agent = TriageAgent(TriageAgentConfig(model=_model()))
    assert agent.tenant_id == DEFAULT_TENANT_ID
    record = agent.triage(_submission())
    assert record.tenant_id == DEFAULT_TENANT_ID


def test_agent_without_tenant_logs_warning(caplog) -> None:
    """Constructing without a tenant logs a WARNING (decision B2: loud)."""
    with caplog.at_level(logging.WARNING, logger="vrt.agent"):
        TriageAgent(TriageAgentConfig(model=_model()))
    assert any(
        DEFAULT_TENANT_ID in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )


def test_agent_with_tenant_stamps_tenant_id() -> None:
    """An agent built with a tenant stamps that tenant's id."""
    tenant = TenantConfig(tenant_id="acme-bank", display_name="Acme Bank")
    agent = TriageAgent(TriageAgentConfig(model=_model(), tenant=tenant))
    assert agent.tenant_id == "acme-bank"
    record = agent.triage(_submission())
    assert record.tenant_id == "acme-bank"


def test_agent_with_tenant_does_not_warn(caplog) -> None:
    """Constructing with a tenant does not emit the default-tenant warning."""
    tenant = TenantConfig(tenant_id="acme-bank", display_name="Acme Bank")
    with caplog.at_level(logging.WARNING, logger="vrt.agent"):
        TriageAgent(TriageAgentConfig(model=_model(), tenant=tenant))
    assert not any(
        DEFAULT_TENANT_ID in r.message for r in caplog.records
    )


def test_agent_records_declare_current_contract() -> None:
    """The agent emits records declaring the current output contract.

    Asserts the agent's declared version equals the framework's
    OUTPUT_SCHEMA_VERSION constant rather than hardcoding a literal,
    so the assertion stays correct across contract bumps. The
    framework's responsibility is "declare the current version on
    every record"; the value of that version is a separate concern
    tracked by the schema file collection.
    """
    from agent.agent import OUTPUT_SCHEMA_VERSION
    agent = TriageAgent(TriageAgentConfig(model=_model()))
    record = agent.triage(_submission())
    assert record.output_schema_version == OUTPUT_SCHEMA_VERSION


def test_agent_output_validates_against_dispatch() -> None:
    """The agent's output validates via the framework's schema dispatch."""
    agent = TriageAgent(TriageAgentConfig(model=_model()))
    record = agent.triage(_submission())
    ok, errors = validate_output(record.model_dump(mode="json"))
    assert ok, f"agent output failed dispatch validation: {errors}"


# -- for_tenant constructor ----------------------------------------------


def test_for_tenant_constructs_agent() -> None:
    tenant = TenantConfig(
        tenant_id="globex", display_name="Globex", model=_model(),
    )
    agent = TriageAgent.for_tenant(tenant)
    assert agent.tenant_id == "globex"


def test_for_tenant_sources_model_from_tenant() -> None:
    """for_tenant adopts the tenant's model when the tenant specifies one."""
    fn_model = _model()
    tenant = TenantConfig(
        tenant_id="globex", display_name="Globex", model=fn_model,
    )
    agent = TriageAgent.for_tenant(tenant)
    # The agent's configured model is the tenant's.
    assert agent._config.model is fn_model


def test_for_tenant_sources_fallbacks_from_tenant() -> None:
    primary = _model()
    fallback = _model()
    tenant = TenantConfig(
        tenant_id="globex", display_name="Globex",
        model=primary, fallback_models=(fallback,),
    )
    agent = TriageAgent.for_tenant(tenant)
    assert list(agent._config.fallback_models) == [fallback]


def test_for_tenant_sources_circuit_breaker_from_tenant() -> None:
    from resilience import CircuitBreakerConfig
    cb = CircuitBreakerConfig(failure_rate_threshold=0.7)
    tenant = TenantConfig(
        tenant_id="globex", display_name="Globex",
        model=_model(), circuit_breaker=cb,
    )
    agent = TriageAgent.for_tenant(tenant)
    assert agent._circuit_breaker is not None
    assert agent._config.circuit_breaker.failure_rate_threshold == 0.7


# -- explicit-over-implicit ----------------------------------------------


def test_explicit_model_wins_over_tenant_model() -> None:
    """An explicit config.model overrides the tenant's model."""
    explicit = _model()
    tenant_model = _model()
    tenant = TenantConfig(
        tenant_id="globex", display_name="Globex", model="openai:gpt-5.4",
    )
    # Pass an explicit model alongside the tenant.
    agent = TriageAgent(TriageAgentConfig(model=explicit, tenant=tenant))
    # Explicit model wins; the tenant's "openai:gpt-5.4" is not adopted.
    assert agent._config.model is explicit
    # But the tenant_id is still the tenant's.
    assert agent.tenant_id == "globex"


# -- schema: 1.3.0 requires tenant_id, prior versions do not -------------


def _base_record(version: str, with_tenant: bool) -> dict:
    rec = {
        "decision_id": "d-x",
        "decision_timestamp": "2026-05-28T12:00:00Z",
        "input_submission_id": "v-x",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.0+test+abc123def456",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for schema check.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "y."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "output_schema_version": version,
    }
    if with_tenant:
        rec["tenant_id"] = "acme-bank"
    return rec


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "1.2.0"])
def test_prior_versions_valid_without_tenant_id(version: str) -> None:
    """1.0.0-1.2.0 records validate without tenant_id (decision A1)."""
    ok, errors = validate_output(_base_record(version, with_tenant=False))
    assert ok, f"{version} should be valid without tenant_id: {errors}"


def test_1_3_0_requires_tenant_id() -> None:
    """A 1.3.0 record without tenant_id is rejected (the breaking change)."""
    ok, errors = validate_output(_base_record("1.3.0", with_tenant=False))
    assert not ok


def test_1_3_0_valid_with_tenant_id() -> None:
    """A 1.3.0 record with a valid tenant_id passes."""
    ok, errors = validate_output(_base_record("1.3.0", with_tenant=True))
    assert ok, f"1.3.0 with tenant_id should be valid: {errors}"


def test_1_3_0_valid_with_default_sentinel() -> None:
    """A 1.3.0 record with the sentinel tenant_id passes."""
    rec = _base_record("1.3.0", with_tenant=False)
    rec["tenant_id"] = DEFAULT_TENANT_ID
    ok, errors = validate_output(rec)
    assert ok, f"sentinel tenant_id should be valid: {errors}"


def test_1_3_0_rejects_bad_tenant_id() -> None:
    """A 1.3.0 record with a malformed tenant_id is rejected."""
    rec = _base_record("1.3.0", with_tenant=False)
    rec["tenant_id"] = "Acme Bank!"
    ok, errors = validate_output(rec)
    assert not ok


# -- Pydantic model conditional enforcement ------------------------------


def test_pydantic_model_allows_prior_version_without_tenant_id() -> None:
    """The Pydantic model accepts a 1.2.0 record without tenant_id."""
    rec = TriageRecord.model_validate(_base_record("1.2.0", with_tenant=False))
    assert rec.tenant_id is None


def test_pydantic_model_requires_tenant_id_for_1_3_0() -> None:
    """The Pydantic model rejects a 1.3.0 record without tenant_id."""
    with pytest.raises(Exception):
        TriageRecord.model_validate(_base_record("1.3.0", with_tenant=False))


def test_pydantic_model_accepts_1_3_0_with_tenant_id() -> None:
    rec = TriageRecord.model_validate(_base_record("1.3.0", with_tenant=True))
    assert rec.tenant_id == "acme-bank"


def test_pydantic_model_rejects_bad_tenant_id() -> None:
    with pytest.raises(Exception):
        TriageRecord.model_validate(
            {**_base_record("1.3.0", with_tenant=False), "tenant_id": "BAD ID"}
        )


def test_pydantic_model_accepts_sentinel_tenant_id() -> None:
    rec = TriageRecord.model_validate(
        {**_base_record("1.3.0", with_tenant=False), "tenant_id": DEFAULT_TENANT_ID}
    )
    assert rec.tenant_id == DEFAULT_TENANT_ID


def test_pydantic_model_explicit_none_tenant_id_on_prior_version() -> None:
    """Explicitly passing tenant_id=None on a 1.2.0 record is accepted.

    Exercises the field validator's None branch directly (an omitted
    field uses the default without invoking the validator; an explicit
    None passes through it).
    """
    rec = TriageRecord.model_validate(
        {**_base_record("1.2.0", with_tenant=False), "tenant_id": None}
    )
    assert rec.tenant_id is None
