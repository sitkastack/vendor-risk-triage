"""Tests for TriageAgent model fallback and circuit breaker integration.

Covers the agent's behavior with fallback_models and circuit_breaker
configuration: fallback triggered on primary failure, multiple
fallbacks tried in order, breaker tripping after threshold,
breaker-opened model being skipped, half-open trial calls,
observability events fired at state transitions, and the all-failed
case where every configured model raises.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from observability import (
    CapturingEventLogger,
    CapturingMetrics,
    EventStatus,
    Observability,
)


REPO_ROOT = Path(__file__).parent.parent
SUBMISSION_PATH = (
    REPO_ROOT / "examples" / "submissions"
    / "01-tier1-internal-productivity.json"
)


def _success_payload() -> dict:
    return {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Success rationale for fallback test.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
    }


def _make_success_model():
    """A FunctionModel that always succeeds."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=_success_payload()),
        ])
    return FunctionModel(_call)


def _make_failing_model(error_class: type = RuntimeError):
    """A FunctionModel that always raises."""
    from pydantic_ai.models.function import FunctionModel

    def _call(_msgs, _info):
        raise error_class("simulated provider failure")
    return FunctionModel(_call)


def _submission() -> dict:
    return json.loads(SUBMISSION_PATH.read_text())


# -- No fallback, no breaker: backwards compatibility -------------------


def test_no_fallback_no_breaker_works_unchanged() -> None:
    """The default (no fallback_models, no circuit_breaker) behaves identically."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(model=_make_success_model()))
    record = agent.triage(_submission())
    assert record.decision_id is not None
    tier_val = record.risk_tier.value if hasattr(record.risk_tier, "value") else record.risk_tier
    assert str(tier_val) == "tier_1_low"


def test_no_fallback_propagates_primary_error() -> None:
    """Without fallback_models, primary failure propagates."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(model=_make_failing_model()))
    with pytest.raises(RuntimeError, match="simulated provider failure"):
        agent.triage(_submission())


# -- Fallback without breaker --------------------------------------------


def test_fallback_used_when_primary_fails() -> None:
    """Primary fails -> fallback succeeds -> triage returns from fallback."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_success_model()],
    ))
    record = agent.triage(_submission())
    assert record.decision_id is not None


def test_fallback_emits_fallback_triggered_event() -> None:
    """The fallback_triggered event fires when fallback is invoked."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_success_model()],
        observability=obs,
    ))
    agent.triage(_submission())
    fallback_events = cap_log.filter(event_name="llm.call.fallback_triggered")
    assert len(fallback_events) == 1
    e = fallback_events[0]
    assert e.attributes["trigger_error_type"] == "RuntimeError"
    assert e.attributes["attempt_index"] == 1


def test_fallback_emits_fallback_total_metric() -> None:
    """vrt_llm_fallback_total counter increments when fallback is invoked."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_success_model()],
        observability=obs,
    ))
    agent.triage(_submission())
    fallback_counters = cap_met.filter(name="vrt_llm_fallback_total")
    assert len(fallback_counters) == 1
    assert "fallback" in fallback_counters[0].labels
    assert fallback_counters[0].labels["reason"] == "RuntimeError"


def test_chain_of_fallbacks_tries_in_order() -> None:
    """Primary fails -> first fallback fails -> second fallback succeeds."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_failing_model(), _make_success_model()],
    ))
    record = agent.triage(_submission())
    assert record.decision_id is not None


def test_all_models_failing_raises_last_error() -> None:
    """If primary + all fallbacks fail, the last exception propagates."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(ValueError),
        fallback_models=[
            _make_failing_model(RuntimeError),
            _make_failing_model(KeyError),
        ],
    ))
    with pytest.raises(KeyError):
        agent.triage(_submission())


# -- Breaker only (no fallback) ------------------------------------------


def test_breaker_only_propagates_after_threshold() -> None:
    """With breaker but no fallbacks, the breaker opens but errors still propagate.

    The breaker tracks failures; without fallbacks, opened-breaker calls
    have nowhere to go and fail with RuntimeError (no-attempts message).
    """
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig

    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
            window_seconds=60.0,
            cooldown_seconds=30.0,
        ),
    ))
    # Trip the breaker by failing 4 times
    for _ in range(4):
        with pytest.raises(Exception):
            agent.triage(_submission())
    # Next call: breaker is open, no fallback configured -> all-failed
    with pytest.raises(Exception):
        agent.triage(_submission())


# -- Breaker + fallback together (full L4) -------------------------------


def test_breaker_opens_after_failures() -> None:
    """4 failures on primary at 50% threshold -> breaker opens."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig, CircuitState

    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)

    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_success_model()],
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
        ),
        observability=obs,
    ))

    # 4 triages: each time primary fails (counted by breaker), fallback
    # succeeds (counted as success for fallback's own breaker).
    for _ in range(4):
        agent.triage(_submission())

    # The primary's breaker should now be OPEN
    primary_id = str(agent._config.model)
    assert agent._circuit_breaker.get_state(primary_id) == CircuitState.OPEN

    # The circuit_breaker.opened event should have fired
    opened_events = cap_log.filter(event_name="circuit_breaker.opened")
    assert len(opened_events) >= 1


def test_breaker_skips_open_model_routes_to_fallback() -> None:
    """When primary's breaker is open, the agent skips it and calls fallback."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig

    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)

    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_success_model()],
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
        ),
        observability=obs,
    ))

    # Trip the primary's breaker
    for _ in range(4):
        agent.triage(_submission())

    cap_log.clear()

    # Next triage: primary is OPEN, agent skips it and goes to fallback
    # without even attempting the primary
    record = agent.triage(_submission())
    assert record is not None

    # The primary should NOT have produced an llm.call.started event
    started_events = cap_log.filter(event_name="llm.call.started")
    # Only the fallback should have started
    assert len(started_events) == 1
    primary_id = str(agent._config.model)
    fallback_id = agent._fallback_agents[0][0]
    # The single started event is for the fallback, not the primary
    assert started_events[0].attributes["model"] == fallback_id


def test_circuit_breaker_opened_event_attributes() -> None:
    """The opened event records the model and error_type."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig

    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)

    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(ValueError),
        fallback_models=[_make_success_model()],
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
        ),
        observability=obs,
    ))

    for _ in range(4):
        agent.triage(_submission())

    opened_events = cap_log.filter(event_name="circuit_breaker.opened")
    assert len(opened_events) >= 1
    e = opened_events[0]
    assert "model" in e.attributes
    assert e.attributes["error_type"] == "ValueError"


def test_circuit_state_changes_metric() -> None:
    """vrt_circuit_state_changes_total fires on state transitions."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig

    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)

    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),
        fallback_models=[_make_success_model()],
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
        ),
        observability=obs,
    ))

    for _ in range(4):
        agent.triage(_submission())

    state_changes = cap_met.filter(name="vrt_circuit_state_changes_total")
    assert len(state_changes) >= 1
    # At least one OPEN transition
    open_transitions = [
        r for r in state_changes if r.labels.get("to_state") == "open"
    ]
    assert len(open_transitions) >= 1


def test_cost_estimate_records_fallback_model_not_primary() -> None:
    """When fallback is used, cost_estimate.model_id is the fallback's ID."""
    from agent.agent import TriageAgent, TriageAgentConfig

    # Build a success-model with a spoofed string identity
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _success_call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=_success_payload()),
        ])
    fallback = FunctionModel(_success_call)

    # Subclass to give it a known model_id string
    class _NamedFunctionModel(type(fallback)):
        def __str__(self):
            return "anthropic:claude-sonnet-4-5"
    fallback.__class__ = _NamedFunctionModel

    agent = TriageAgent(TriageAgentConfig(
        model=_make_failing_model(),  # primary fails
        fallback_models=[fallback],
    ))
    record = agent.triage(_submission())
    # Cost estimate should be present (fallback model is in price table)
    # and should record the fallback's model_id, NOT the primary's
    assert record.cost_estimate is not None
    assert record.cost_estimate.model_id == "anthropic:claude-sonnet-4-5"


# -- Backwards compat with FRAMEWORK_VERSION 0.8.1 records ---------------


def test_triage_with_breaker_disabled_emits_no_breaker_events() -> None:
    """A triage with no breaker config never emits breaker events."""
    from agent.agent import TriageAgent, TriageAgentConfig

    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)

    agent = TriageAgent(TriageAgentConfig(
        model=_make_success_model(),
        # No fallback_models, no circuit_breaker
        observability=obs,
    ))
    agent.triage(_submission())

    breaker_events = [
        e for e in cap_log.events
        if e.event.startswith("circuit_breaker.")
    ]
    assert len(breaker_events) == 0


def test_triage_with_no_fallback_does_not_emit_fallback_events() -> None:
    """A triage with no fallback_models never emits fallback events."""
    from agent.agent import TriageAgent, TriageAgentConfig

    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)

    agent = TriageAgent(TriageAgentConfig(
        model=_make_success_model(),
        observability=obs,
    ))
    agent.triage(_submission())

    fallback_events = cap_log.filter(event_name="llm.call.fallback_triggered")
    assert len(fallback_events) == 0


# -- HALF_OPEN and CLOSED state transitions through the agent -----------


class _ToggleableModel:
    """Helper: a FunctionModel-like wrapper whose success/fail toggles per call."""

    def __init__(self, payload: dict):
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        self._should_fail = True
        self._payload = payload

        def _call(_msgs, _info):
            if self._should_fail:
                raise RuntimeError("toggled failure")
            return ModelResponse(parts=[
                ToolCallPart(tool_name="final_result", args=self._payload),
            ])

        self._model = FunctionModel(_call)

    def set_failing(self, failing: bool) -> None:
        self._should_fail = failing

    @property
    def model(self):
        return self._model


def test_breaker_half_opened_event_fires_after_cooldown() -> None:
    """After cooldown elapses, the next call sees the breaker in HALF_OPEN.

    Emits circuit_breaker.half_opened event. The agent's breaker uses
    monotonic by default; this test reaches in to replace its time_fn
    so we can simulate cooldown elapsing without waiting.
    """
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig, CircuitState

    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)

    toggleable = _ToggleableModel(_success_payload())
    agent = TriageAgent(TriageAgentConfig(
        model=toggleable.model,
        fallback_models=[_make_success_model()],
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
            cooldown_seconds=30.0,
        ),
        observability=obs,
    ))

    # Replace the breaker's clock with a controlled clock
    class _Clock:
        t = 0.0
        def __call__(self): return self.t
    clock = _Clock()
    agent._circuit_breaker._time_fn = clock

    # Trip the primary breaker (4 failures + fallback successes)
    toggleable.set_failing(True)
    for _ in range(4):
        agent.triage(_submission())

    primary_id = str(agent._config.model)
    assert agent._circuit_breaker.get_state(primary_id) == CircuitState.OPEN

    cap_log.clear()

    # Advance past cooldown
    clock.t = 31.0

    # Next triage: primary's breaker is now eligible for half-open
    # transition. The agent's check should detect OPEN -> HALF_OPEN
    # and emit the half_opened event before attempting the call.
    toggleable.set_failing(False)  # primary will succeed on the trial
    agent.triage(_submission())

    half_opened_events = cap_log.filter(event_name="circuit_breaker.half_opened")
    assert len(half_opened_events) == 1
    assert half_opened_events[0].attributes["model"] == primary_id


def test_breaker_closed_event_fires_on_successful_trial() -> None:
    """After a successful HALF_OPEN trial, the breaker closes.

    Emits circuit_breaker.closed event.
    """
    from agent.agent import TriageAgent, TriageAgentConfig
    from resilience import CircuitBreakerConfig, CircuitState

    cap_log = CapturingEventLogger()
    cap_met = CapturingMetrics()
    obs = Observability(event_logger=cap_log, metrics=cap_met)

    toggleable = _ToggleableModel(_success_payload())
    agent = TriageAgent(TriageAgentConfig(
        model=toggleable.model,
        fallback_models=[_make_success_model()],
        circuit_breaker=CircuitBreakerConfig(
            failure_rate_threshold=0.5,
            minimum_calls=4,
            cooldown_seconds=30.0,
        ),
        observability=obs,
    ))

    class _Clock:
        t = 0.0
        def __call__(self): return self.t
    clock = _Clock()
    agent._circuit_breaker._time_fn = clock

    # Trip the breaker
    toggleable.set_failing(True)
    for _ in range(4):
        agent.triage(_submission())

    # Advance past cooldown
    clock.t = 31.0

    # Primary now succeeds on trial
    toggleable.set_failing(False)
    cap_log.clear()
    cap_met.clear()
    agent.triage(_submission())

    closed_events = cap_log.filter(event_name="circuit_breaker.closed")
    assert len(closed_events) == 1
    primary_id = str(agent._config.model)
    assert closed_events[0].attributes["model"] == primary_id

    # Metric also fired
    state_changes = cap_met.filter(name="vrt_circuit_state_changes_total")
    closed_transitions = [
        r for r in state_changes
        if r.labels.get("to_state") == "closed"
    ]
    assert len(closed_transitions) >= 1
