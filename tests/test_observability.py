"""Tests for the observability package.

Covers correlation_id generation, the Event/EventLogger surface (Noop,
JsonStderr, Capturing implementations), the Metrics protocol (Noop and
Capturing), the Tracer protocol (NoopTracer and NoopSpan), the
Observability bundle, the OtelTracer adapter (skipped if the [otel]
extra is not installed), and the agent's emission of events/metrics/
spans during triage().
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

import pytest

from observability import (
    CapturingEventLogger,
    CapturingMetrics,
    Event,
    EventName,
    EventStatus,
    JsonStderrEventLogger,
    MetricKind,
    MetricRecord,
    NoopEventLogger,
    NoopMetrics,
    NoopSpan,
    NoopTracer,
    Observability,
    new_correlation_id,
)


# -- correlation_id ------------------------------------------------------


def test_correlation_id_is_16_char_lowercase_hex() -> None:
    """new_correlation_id returns a 16-char lowercase hexadecimal string."""
    cid = new_correlation_id()
    assert len(cid) == 16
    assert re.match(r"^[a-f0-9]{16}$", cid), f"unexpected format: {cid!r}"


def test_correlation_ids_are_unique() -> None:
    """Two consecutive correlation_id() calls produce different values."""
    ids = {new_correlation_id() for _ in range(100)}
    # 100 random 64-bit values; collision probability is ~5.4e-18
    assert len(ids) == 100


def test_observability_helper_mints_correlation_id() -> None:
    """Observability.new_correlation_id() works as a static method."""
    cid = Observability.new_correlation_id()
    assert len(cid) == 16


# -- EventName and EventStatus enums -------------------------------------


def test_event_name_values_stable() -> None:
    """The public event names are stable as documented."""
    expected = {
        "agent.constructed", "triage.started", "triage.completed",
        "llm.call.started", "llm.call.completed", "llm.call.cost_recorded",
        "llm.call.fallback_triggered",
        "retrieval.started", "retrieval.completed",
        "validation.started", "validation.completed",
        "drift.check.started", "drift.check.completed",
        "audit_pack.rendered",
        "circuit_breaker.opened", "circuit_breaker.half_opened",
        "circuit_breaker.closed",
    }
    actual = {member.value for member in EventName}
    assert actual == expected


def test_event_status_values() -> None:
    """The three status states."""
    assert EventStatus.IN_PROGRESS.value == "in_progress"
    assert EventStatus.SUCCESS.value == "success"
    assert EventStatus.ERROR.value == "error"


# -- Event dataclass ------------------------------------------------------


def test_event_is_frozen() -> None:
    """Event is immutable after construction."""
    e = Event(
        event="x", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
    )
    with pytest.raises(Exception):
        e.event = "different"  # type: ignore[misc]


def test_event_to_dict_minimal() -> None:
    """Minimal event serializes cleanly."""
    e = Event(
        event="x", timestamp=datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
        status=EventStatus.SUCCESS,
    )
    d = e.to_dict()
    assert d["event"] == "x"
    assert d["status"] == "success"
    assert "timestamp" in d
    assert "correlation_id" not in d
    assert "duration_ms" not in d
    assert "attributes" not in d


def test_event_to_dict_with_all_fields() -> None:
    """Event with all fields serializes them all."""
    e = Event(
        event="x", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
        correlation_id="abc123",
        duration_ms=42.5,
        attributes={"k": "v", "n": 3},
    )
    d = e.to_dict()
    assert d["correlation_id"] == "abc123"
    assert d["duration_ms"] == 42.5
    assert d["attributes"] == {"k": "v", "n": 3}


# -- NoopEventLogger -----------------------------------------------------


def test_noop_event_logger_discards() -> None:
    """NoopEventLogger.emit() returns None and does nothing."""
    logger = NoopEventLogger()
    result = logger.emit(Event(
        event="x", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
    ))
    assert result is None


# -- JsonStderrEventLogger -----------------------------------------------


def test_json_stderr_logger_writes_jsonl() -> None:
    """Each event becomes one JSON line on the stream."""
    buf = io.StringIO()
    logger = JsonStderrEventLogger(stream=buf)
    logger.emit(Event(
        event="x", timestamp=datetime(2026, 5, 27, tzinfo=timezone.utc),
        status=EventStatus.SUCCESS,
        attributes={"k": "v"},
    ))
    line = buf.getvalue().strip()
    parsed = json.loads(line)
    assert parsed["event"] == "x"
    assert parsed["attributes"] == {"k": "v"}


def test_json_stderr_logger_handles_serialize_error() -> None:
    """A non-serializable value in attributes does not raise."""
    buf = io.StringIO()
    logger = JsonStderrEventLogger(stream=buf)
    # Pass a non-JSON-serializable object
    logger.emit(Event(
        event="x", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
        attributes={"non_serializable": object()},
    ))
    # No exception; nothing written
    assert buf.getvalue() == ""


# -- CapturingEventLogger ------------------------------------------------


def test_capturing_logger_records_events() -> None:
    """CapturingEventLogger.events grows on each emit."""
    logger = CapturingEventLogger()
    assert logger.events == []
    logger.emit(Event(
        event="a", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
    ))
    logger.emit(Event(
        event="b", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
    ))
    assert len(logger.events) == 2
    assert logger.events[0].event == "a"
    assert logger.events[1].event == "b"


def test_capturing_logger_filter_by_event_name() -> None:
    """filter(event_name=...) returns matching events."""
    logger = CapturingEventLogger()
    for name in ["a", "b", "a", "c", "a"]:
        logger.emit(Event(
            event=name, timestamp=datetime.now(timezone.utc),
            status=EventStatus.SUCCESS,
        ))
    a_events = logger.filter(event_name="a")
    assert len(a_events) == 3


def test_capturing_logger_filter_by_correlation_id() -> None:
    logger = CapturingEventLogger()
    for cid in ["x", "y", "x"]:
        logger.emit(Event(
            event="e", timestamp=datetime.now(timezone.utc),
            status=EventStatus.SUCCESS, correlation_id=cid,
        ))
    x_events = logger.filter(correlation_id="x")
    assert len(x_events) == 2


def test_capturing_logger_filter_by_status() -> None:
    logger = CapturingEventLogger()
    logger.emit(Event(
        event="a", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
    ))
    logger.emit(Event(
        event="b", timestamp=datetime.now(timezone.utc),
        status=EventStatus.ERROR,
    ))
    success = logger.filter(status=EventStatus.SUCCESS)
    assert len(success) == 1
    assert success[0].event == "a"


def test_capturing_logger_clear() -> None:
    logger = CapturingEventLogger()
    logger.emit(Event(
        event="a", timestamp=datetime.now(timezone.utc),
        status=EventStatus.SUCCESS,
    ))
    logger.clear()
    assert logger.events == []


# -- Metrics: NoopMetrics ------------------------------------------------


def test_noop_metrics_all_methods_return_none() -> None:
    m = NoopMetrics()
    assert m.counter_inc("x") is None
    assert m.histogram_observe("x", 1.0) is None
    assert m.gauge_set("x", 1.0) is None


# -- Metrics: CapturingMetrics -------------------------------------------


def test_capturing_metrics_records_counter() -> None:
    m = CapturingMetrics()
    m.counter_inc("vrt_triage_total", labels={"tier": "tier_1_low"})
    assert len(m.records) == 1
    assert m.records[0].kind == MetricKind.COUNTER
    assert m.records[0].name == "vrt_triage_total"
    assert m.records[0].value == 1.0
    assert m.records[0].labels == {"tier": "tier_1_low"}


def test_capturing_metrics_records_histogram() -> None:
    m = CapturingMetrics()
    m.histogram_observe("vrt_triage_duration_seconds", 0.5)
    assert m.records[0].kind == MetricKind.HISTOGRAM
    assert m.records[0].value == 0.5


def test_capturing_metrics_records_gauge() -> None:
    m = CapturingMetrics()
    m.gauge_set("vrt_framework_info", 1.0, labels={"version": "0.7.0"})
    assert m.records[0].kind == MetricKind.GAUGE


def test_capturing_metrics_filter_by_name() -> None:
    m = CapturingMetrics()
    m.counter_inc("a")
    m.counter_inc("b")
    m.counter_inc("a")
    a_records = m.filter(name="a")
    assert len(a_records) == 2


def test_capturing_metrics_filter_by_kind() -> None:
    m = CapturingMetrics()
    m.counter_inc("a")
    m.histogram_observe("b", 1.0)
    counters = m.filter(kind=MetricKind.COUNTER)
    assert len(counters) == 1
    assert counters[0].name == "a"


def test_capturing_metrics_clear() -> None:
    m = CapturingMetrics()
    m.counter_inc("a")
    m.clear()
    assert m.records == []


def test_metric_record_is_frozen() -> None:
    r = MetricRecord(
        kind=MetricKind.COUNTER, name="x", value=1.0,
    )
    with pytest.raises(Exception):
        r.name = "other"  # type: ignore[misc]


# -- Tracer: NoopTracer + NoopSpan ---------------------------------------


def test_noop_tracer_yields_noop_span() -> None:
    tracer = NoopTracer()
    with tracer.start_span("x") as span:
        # NoopSpan accepts but ignores everything
        span.set_attribute("k", "v")
        span.record_error(RuntimeError("test"))
    # No exceptions raised


def test_noop_tracer_accepts_attributes_argument() -> None:
    tracer = NoopTracer()
    with tracer.start_span("x", attributes={"a": 1}) as span:
        pass


def test_noop_span_returns_none_on_set_attribute() -> None:
    s = NoopSpan()
    assert s.set_attribute("k", "v") is None


def test_noop_span_returns_none_on_record_error() -> None:
    s = NoopSpan()
    assert s.record_error(ValueError("x")) is None


# -- Observability bundle ------------------------------------------------


def test_observability_default_is_all_noop() -> None:
    """Observability() with no args uses noop sinks."""
    obs = Observability()
    assert isinstance(obs.event_logger, NoopEventLogger)
    assert isinstance(obs.metrics, NoopMetrics)
    assert isinstance(obs.tracer, NoopTracer)


def test_observability_accepts_custom_sinks() -> None:
    """Observability(...) wires custom sinks."""
    cap_log = CapturingEventLogger()
    cap_met = CapturingMetrics()
    obs = Observability(event_logger=cap_log, metrics=cap_met)
    obs.emit_event("test", correlation_id="x")
    obs.counter_inc("y")
    assert len(cap_log.events) == 1
    assert len(cap_met.records) == 1


def test_observability_emit_event_records_event() -> None:
    cap = CapturingEventLogger()
    obs = Observability(event_logger=cap)
    obs.emit_event(
        "triage.completed",
        status=EventStatus.SUCCESS,
        correlation_id="abc123",
        duration_ms=42.5,
        attributes={"tier": "tier_1_low"},
    )
    assert len(cap.events) == 1
    e = cap.events[0]
    assert e.event == "triage.completed"
    assert e.status == EventStatus.SUCCESS
    assert e.correlation_id == "abc123"
    assert e.duration_ms == 42.5
    assert e.attributes == {"tier": "tier_1_low"}


def test_observability_event_logger_exception_suppressed() -> None:
    """A logger that raises does not break the operational path."""
    class _BrokenLogger:
        def emit(self, _event):
            raise RuntimeError("simulated logger failure")

    obs = Observability(event_logger=_BrokenLogger())
    # Must not raise
    obs.emit_event("x")


def test_observability_metrics_exception_suppressed() -> None:
    """A metrics sink that raises does not break the operational path."""
    class _BrokenMetrics:
        def counter_inc(self, *a, **kw): raise RuntimeError("x")
        def histogram_observe(self, *a, **kw): raise RuntimeError("x")
        def gauge_set(self, *a, **kw): raise RuntimeError("x")

    obs = Observability(metrics=_BrokenMetrics())
    # Must not raise
    obs.counter_inc("x")
    obs.histogram_observe("x", 1.0)
    obs.gauge_set("x", 1.0)


def test_observability_start_span_yields_span() -> None:
    obs = Observability()
    with obs.start_span("x") as span:
        # Span supports set_attribute and record_error
        span.set_attribute("k", "v")


def test_observability_start_span_with_attributes() -> None:
    obs = Observability()
    with obs.start_span("x", attributes={"a": 1}) as span:
        pass


# -- TriageAgent integration ---------------------------------------------


def _make_function_model(record_payload: dict):
    """Build a FunctionModel that returns a canned classification."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _call(_messages, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=record_payload),
        ])
    return FunctionModel(_call)


def _make_tier1_submission() -> dict:
    """Return a minimal valid submission for a tier-1 happy path."""
    import json
    from pathlib import Path
    repo_root = Path(__file__).parent.parent
    return json.loads((
        repo_root / "examples" / "submissions"
        / "01-tier1-internal-productivity.json"
    ).read_text())


def _tier1_classification_payload() -> dict:
    return {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for observability check.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "review_interval_days": 365,
    }


def test_agent_emits_construction_event() -> None:
    """agent.constructed event fires during TriageAgent construction."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)
    TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
        observability=obs,
    ))
    construction_events = cap_log.filter(event_name="agent.constructed")
    assert len(construction_events) == 1
    e = construction_events[0]
    assert e.status == EventStatus.SUCCESS
    assert "framework_version" in e.attributes
    assert "system_prompt_hash" in e.attributes


def test_agent_emits_framework_info_gauge_on_construction() -> None:
    """vrt_framework_info gauge is set when an agent is constructed."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)
    TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
        observability=obs,
    ))
    framework_info = cap_met.filter(name="vrt_framework_info")
    assert len(framework_info) == 1
    assert framework_info[0].kind == MetricKind.GAUGE
    assert framework_info[0].value == 1.0
    assert "version" in framework_info[0].labels


def test_triage_emits_complete_event_lifecycle() -> None:
    """A successful triage emits the expected 6 events with one correlation_id."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
        observability=obs,
    ))
    cap_log.clear()  # forget the construction event

    record = agent.triage(_make_tier1_submission())

    event_names = [e.event for e in cap_log.events]
    assert "triage.started" in event_names
    assert "llm.call.started" in event_names
    assert "llm.call.completed" in event_names
    assert "validation.started" in event_names
    assert "validation.completed" in event_names
    assert "triage.completed" in event_names

    # All non-construction events share the same correlation_id
    triage_correlation_ids = {
        e.correlation_id for e in cap_log.events if e.correlation_id is not None
    }
    assert len(triage_correlation_ids) == 1
    # And it matches the record's correlation_id
    assert record.correlation_id in triage_correlation_ids


def test_triage_completed_event_has_duration() -> None:
    """triage.completed event records duration_ms."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_log = CapturingEventLogger()
    obs = Observability(event_logger=cap_log)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
        observability=obs,
    ))
    agent.triage(_make_tier1_submission())
    completed = cap_log.filter(event_name="triage.completed")
    assert len(completed) == 1
    assert completed[0].duration_ms is not None
    assert completed[0].duration_ms >= 0


def test_triage_emits_expected_metrics() -> None:
    """Triage emits counter + histogram + LLM call metrics."""
    from agent.agent import TriageAgent, TriageAgentConfig
    cap_met = CapturingMetrics()
    obs = Observability(metrics=cap_met)
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
        observability=obs,
    ))
    cap_met.clear()  # forget framework_info gauge from construction

    agent.triage(_make_tier1_submission())

    triage_total = cap_met.filter(name="vrt_triage_total")
    triage_duration = cap_met.filter(name="vrt_triage_duration_seconds")
    llm_total = cap_met.filter(name="vrt_llm_call_total")
    llm_duration = cap_met.filter(name="vrt_llm_call_duration_seconds")

    assert len(triage_total) == 1
    assert triage_total[0].labels.get("tier") == "tier_1_low"
    assert triage_total[0].labels.get("status") == "success"
    assert len(triage_duration) == 1
    assert len(llm_total) == 1
    assert len(llm_duration) == 1


def test_triage_record_has_correlation_id() -> None:
    """The returned TriageRecord includes the correlation_id."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
        # Default noop observability still generates a correlation_id
    ))
    record = agent.triage(_make_tier1_submission())
    assert record.correlation_id is not None
    assert len(record.correlation_id) == 16
    assert re.match(r"^[a-f0-9]{16}$", record.correlation_id)


def test_triage_with_noop_observability_still_emits_correlation_id() -> None:
    """Even with noop observability, the record still gets a correlation_id.

    correlation_id is part of the record's identity, not just an
    observability concern. The default agent (no observability config)
    still produces records with correlation_ids.
    """
    from agent.agent import TriageAgent, TriageAgentConfig
    # No observability arg - defaults to noop
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
    ))
    record = agent.triage(_make_tier1_submission())
    assert record.correlation_id is not None


def test_triage_llm_failure_emits_error_events() -> None:
    """If the LLM call fails, error events and metrics are emitted."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from pydantic_ai.models.function import FunctionModel

    def _failing(_msgs, _info):
        raise RuntimeError("simulated LLM provider failure")

    cap_log = CapturingEventLogger()
    cap_met = CapturingMetrics()
    obs = Observability(event_logger=cap_log, metrics=cap_met)
    agent = TriageAgent(TriageAgentConfig(
        model=FunctionModel(_failing),
        observability=obs,
    ))
    cap_log.clear()
    cap_met.clear()

    with pytest.raises(Exception):
        agent.triage(_make_tier1_submission())

    # llm.call.completed event has error status
    llm_completed = cap_log.filter(event_name="llm.call.completed")
    assert len(llm_completed) == 1
    assert llm_completed[0].status == EventStatus.ERROR
    assert "error_type" in llm_completed[0].attributes

    # triage.completed event has error status
    triage_completed = cap_log.filter(event_name="triage.completed")
    assert len(triage_completed) == 1
    assert triage_completed[0].status == EventStatus.ERROR

    # vrt_llm_errors_total counter incremented
    llm_errors = cap_met.filter(name="vrt_llm_errors_total")
    assert len(llm_errors) == 1


def test_triage_default_observability_does_not_crash() -> None:
    """Triage with no observability arg uses silent default and succeeds."""
    from agent.agent import TriageAgent, TriageAgentConfig
    agent = TriageAgent(TriageAgentConfig(
        model=_make_function_model(_tier1_classification_payload()),
    ))
    record = agent.triage(_make_tier1_submission())
    # risk_tier may be enum or string depending on validation path
    tier_val = record.risk_tier.value if hasattr(record.risk_tier, "value") else record.risk_tier
    assert str(tier_val) == "tier_1_low"


# -- OtelTracer (only if [otel] extra installed) ------------------------


def test_otel_tracer_importable_or_clear_error() -> None:
    """OtelTracer is importable when otel is installed; raises clearly otherwise."""
    try:
        from observability.tracing import OtelTracer
        # If we got here, the otel extra is installed
        assert OtelTracer is not None
    except ImportError as exc:
        # The error message tells the user how to fix it
        assert "[otel]" in str(exc) or "OpenTelemetry" in str(exc)
