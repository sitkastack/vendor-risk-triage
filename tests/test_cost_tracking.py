"""Tests for cost capture in TriageAgent.

Covers the agent's behavior when LLM token usage can and cannot be
resolved to a dollar figure: unknown model_id (FunctionModel and
TestModel test fixtures) produces cost_estimate=None on the record
but still emits the cost_recorded event and token histograms; known
model_id produces a populated CostEstimate plus the dollar counter.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from observability import (
    CapturingEventLogger,
    CapturingMetrics,
    EventStatus,
    MetricKind,
    Observability,
)


REPO_ROOT = Path(__file__).parent.parent


def _make_function_model(record_payload: dict):
    """Build a FunctionModel that returns a canned classification."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _call(_messages, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=record_payload),
        ])
    return FunctionModel(_call)


def _make_known_model(record_payload: dict, model_id: str):
    """Return a FunctionModel whose str() reports a real model_id.

    Uses a per-instance subclass to avoid mutating the global
    FunctionModel.__class__.__str__, which would leak across tests.
    """
    from pydantic_ai.models.function import FunctionModel
    fm = _make_function_model(record_payload)
    # Create a per-instance subclass with overridden __str__
    class _NamedFunctionModel(type(fm)):
        def __str__(self):
            return model_id
    fm.__class__ = _NamedFunctionModel
    return fm


def _tier1_payload() -> dict:
    return {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for cost capture.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "review_interval_days": 365,
    }


def _tier1_submission() -> dict:
    return json.loads((
        REPO_ROOT / "examples" / "submissions"
        / "01-tier1-internal-productivity.json"
    ).read_text())


# -- Unknown model path --------------------------------------------------


def test_unknown_model_produces_none_cost_estimate() -> None:
    """FunctionModel (unknown to price table) -> cost_estimate=None."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
    ))
    record = agent.triage(_tier1_submission())
    assert record.cost_estimate is None


def test_unknown_model_still_emits_cost_recorded_event() -> None:
    """The cost_recorded event fires even for unknown models."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
        observability=obs,
    ))
    agent.triage(_tier1_submission())
    cost_events = cap_log.filter(event_name="llm.call.cost_recorded")
    assert len(cost_events) == 1
    e = cost_events[0]
    assert e.attributes["estimated_cost_usd"] is None
    assert e.attributes["reason"] == "model_id_not_in_price_table"
    assert "input_tokens" in e.attributes
    assert "output_tokens" in e.attributes


def test_unknown_model_still_emits_token_histograms() -> None:
    """Token observations are emitted regardless of cost lookup."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
        observability=obs,
    ))
    agent.triage(_tier1_submission())
    token_histograms = cap_met.filter(name="vrt_llm_tokens_total")
    assert len(token_histograms) == 2  # input + output
    kinds = {r.labels.get("kind") for r in token_histograms}
    assert kinds == {"input", "output"}


def test_unknown_model_does_not_emit_cost_counter() -> None:
    """vrt_llm_cost_usd_total is NOT incremented for unknown models."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
        observability=obs,
    ))
    agent.triage(_tier1_submission())
    cost_counters = cap_met.filter(name="vrt_llm_cost_usd_total")
    assert len(cost_counters) == 0


# -- Known model path ----------------------------------------------------


def test_known_model_produces_populated_cost_estimate() -> None:
    """Spoofing a known model_id produces a populated cost_estimate."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_known_model(
            _tier1_payload(), "anthropic:claude-sonnet-4-5",
        ),
    ))
    record = agent.triage(_tier1_submission())
    assert record.cost_estimate is not None
    assert record.cost_estimate.model_id == "anthropic:claude-sonnet-4-5"
    assert record.cost_estimate.input_tokens > 0
    assert record.cost_estimate.output_tokens > 0
    assert record.cost_estimate.estimated_cost_usd > 0
    assert record.cost_estimate.price_table_version == "2026-05-27"


def test_known_model_cost_math_matches_price_table() -> None:
    """Cost on the record equals price_table.compute_cost(tokens)."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from pricing import compute_cost
    agent = TriageAgent(TriageAgentConfig(
        model=_make_known_model(
            _tier1_payload(), "anthropic:claude-sonnet-4-5",
        ),
    ))
    record = agent.triage(_tier1_submission())
    expected_cost = compute_cost(
        "anthropic:claude-sonnet-4-5",
        record.cost_estimate.input_tokens,
        record.cost_estimate.output_tokens,
    )
    assert record.cost_estimate.estimated_cost_usd == expected_cost


def test_known_model_emits_cost_recorded_event_with_dollar_figure() -> None:
    """cost_recorded event includes the computed cost when model is known."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_known_model(
            _tier1_payload(), "anthropic:claude-sonnet-4-5",
        ),
        observability=obs,
    ))
    agent.triage(_tier1_submission())
    cost_events = cap_log.filter(event_name="llm.call.cost_recorded")
    assert len(cost_events) == 1
    e = cost_events[0]
    assert e.attributes["estimated_cost_usd"] is not None
    assert e.attributes["estimated_cost_usd"] > 0
    assert e.attributes["model_id"] == "anthropic:claude-sonnet-4-5"
    assert e.attributes["price_table_version"] == "2026-05-27"


def test_known_model_increments_cost_counter() -> None:
    """vrt_llm_cost_usd_total is incremented with the dollar figure."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_known_model(
            _tier1_payload(), "anthropic:claude-sonnet-4-5",
        ),
        observability=obs,
    ))
    agent.triage(_tier1_submission())
    cost_counters = cap_met.filter(name="vrt_llm_cost_usd_total")
    assert len(cost_counters) == 1
    r = cost_counters[0]
    assert r.kind == MetricKind.COUNTER
    assert r.value > 0
    assert r.labels["model"] == "anthropic:claude-sonnet-4-5"
    assert r.labels["status"] == "success"


# -- CostEstimate Pydantic model -----------------------------------------


def test_cost_estimate_is_frozen() -> None:
    """CostEstimate is immutable after construction."""
    from agent.output_models import CostEstimate
    ce = CostEstimate(
        input_tokens=100, output_tokens=50,
        model_id="anthropic:claude-sonnet-4-5",
        estimated_cost_usd=0.001, price_table_version="2026-05-27",
    )
    with pytest.raises(Exception):
        ce.input_tokens = 200  # type: ignore[misc]


def test_cost_estimate_rejects_negative_tokens() -> None:
    """Negative token counts are rejected at the model layer."""
    from agent.output_models import CostEstimate
    with pytest.raises(Exception):
        CostEstimate(
            input_tokens=-1, output_tokens=50,
            model_id="x", estimated_cost_usd=0.001,
            price_table_version="2026-05-27",
        )


def test_cost_estimate_rejects_bad_price_table_version() -> None:
    """price_table_version must be YYYY-MM-DD."""
    from agent.output_models import CostEstimate
    with pytest.raises(Exception):
        CostEstimate(
            input_tokens=10, output_tokens=5,
            model_id="x", estimated_cost_usd=0.001,
            price_table_version="not-a-date",
        )


def test_cost_estimate_rejects_negative_cost() -> None:
    """estimated_cost_usd must be non-negative."""
    from agent.output_models import CostEstimate
    with pytest.raises(Exception):
        CostEstimate(
            input_tokens=10, output_tokens=5,
            model_id="x", estimated_cost_usd=-0.001,
            price_table_version="2026-05-27",
        )


# -- Schema 1.2.0 validation ---------------------------------------------


def test_record_with_cost_estimate_validates_against_1_2_0() -> None:
    """A record with cost_estimate validates against the 1.2.0 schema."""
    from schemas.validate import validate_output
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_known_model(
            _tier1_payload(), "anthropic:claude-sonnet-4-5",
        ),
    ))
    record = agent.triage(_tier1_submission())
    record_dict = json.loads(record.model_dump_json())
    ok, errors = validate_output(record_dict)
    assert ok, f"validation errors: {errors}"


def test_record_without_cost_estimate_still_validates() -> None:
    """A record without cost_estimate also validates against 1.2.0."""
    from schemas.validate import validate_output
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
    ))
    record = agent.triage(_tier1_submission())
    record_dict = json.loads(record.model_dump_json())
    assert "cost_estimate" not in record_dict  # excluded when None
    ok, errors = validate_output(record_dict)
    assert ok, f"validation errors: {errors}"


def test_validate_output_dispatches_to_1_2_0() -> None:
    """validate_output picks the 1.2.0 schema for records declaring 1.2.0."""
    from schemas.validate import _OUTPUT_SCHEMA_FILES
    assert "1.2.0" in _OUTPUT_SCHEMA_FILES
    assert _OUTPUT_SCHEMA_FILES["1.2.0"] == "output-contract-1.2.0.schema.json"


def test_backwards_compat_1_0_0_records_still_validate() -> None:
    """Records declaring 1.0.0 still validate against their schema."""
    from schemas.validate import validate_output
    record = {
        "decision_id": "d-test-1",
        "decision_timestamp": "2026-05-27T12:00:00Z",
        "input_submission_id": "v-test",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.0+anthropic:test+abc123def456",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for backwards compat.",
        "evidence_cited": [
            {"input_field_reference": "$.test", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "output_schema_version": "1.0.0",
    }
    ok, errors = validate_output(record)
    assert ok, f"1.0.0 backwards compat broken: {errors}"


def test_backwards_compat_1_1_0_records_still_validate() -> None:
    """Records declaring 1.1.0 still validate against their schema."""
    from schemas.validate import validate_output
    record = {
        "decision_id": "d-test-1",
        "decision_timestamp": "2026-05-27T12:00:00Z",
        "input_submission_id": "v-test",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.0+anthropic:test+abc123def456",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for backwards compat.",
        "evidence_cited": [
            {"input_field_reference": "$.test", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "output_schema_version": "1.1.0",
        "correlation_id": "abc123def4567890",
    }
    ok, errors = validate_output(record)
    assert ok, f"1.1.0 backwards compat broken: {errors}"


# -- Defensive paths in _capture_cost_estimate ---------------------------
# Cover the fallback branches that exist for PydanticAI version
# compatibility. Current PydanticAI exposes ``result.usage`` as a
# property; older versions had ``usage()`` as a method. The agent's
# defensive code handles both shapes plus a "neither works" case.


class _StubUsage:
    """A usage object that exposes input_tokens/output_tokens directly."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _OldStyleResult:
    """Mimics a PydanticAI 0.0.x result where usage is a method, not a property.

    Reading ``self.usage.input_tokens`` raises AttributeError (a bound
    method has no input_tokens). The agent's code path then falls back
    to calling ``usage()`` and reads the resulting object's attributes.
    """

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self._stub = _StubUsage(input_tokens, output_tokens)

    def usage(self):
        return self._stub

    @property
    def output(self):
        return None


class _BrokenUsageResult:
    """A result whose usage object exposes nothing readable.

    Triggers the second-tier defensive return-None branch when neither
    the direct attribute read nor the call-fallback can extract tokens.
    """

    @property
    def usage(self):
        return object()  # has no input_tokens attribute

    @property
    def output(self):
        return None


def test_capture_cost_handles_old_style_method_usage() -> None:
    """When result.usage is callable, the fallback path reads tokens via call.

    Exercises the older-PydanticAI compatibility branch.
    """
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
    ))
    fake_result = _OldStyleResult(input_tokens=100, output_tokens=50)
    cost_estimate = agent._capture_cost_estimate(
        fake_result, correlation_id="test1234abcd5678",
    )
    # FunctionModel str() is not in the price table, so cost is None
    assert cost_estimate is None


def test_capture_cost_handles_old_style_method_usage_with_known_model() -> None:
    """Old-style usage path + known model produces a populated CostEstimate."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_known_model(
            _tier1_payload(), "anthropic:claude-sonnet-4-5",
        ),
    ))
    fake_result = _OldStyleResult(input_tokens=1000, output_tokens=500)
    cost_estimate = agent._capture_cost_estimate(
        fake_result, correlation_id="test1234abcd5678",
    )
    assert cost_estimate is not None
    assert cost_estimate.input_tokens == 1000
    assert cost_estimate.output_tokens == 500


def test_capture_cost_returns_none_when_usage_completely_unreadable() -> None:
    """When both direct-attribute and call-fallback fail, return None."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_payload()),
    ))
    fake_result = _BrokenUsageResult()
    cost_estimate = agent._capture_cost_estimate(
        fake_result, correlation_id="test1234abcd5678",
    )
    assert cost_estimate is None
