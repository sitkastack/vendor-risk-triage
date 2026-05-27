"""Observability primitives for the vendor risk triage framework.

Public exports:

- ``Observability``: bundle that wires logger, metrics, and tracer
- ``Event``, ``EventName``, ``EventStatus``: event log structures
- ``EventLogger``: Protocol for event sinks
- ``NoopEventLogger``, ``JsonStderrEventLogger``,
  ``CapturingEventLogger``: built-in event sink implementations
- ``Metrics``: Protocol for metrics sinks
- ``MetricKind``, ``MetricRecord``: metric structures
- ``NoopMetrics``, ``CapturingMetrics``: built-in metric sink
  implementations
- ``Tracer``, ``Span``: Protocols for distributed tracing
- ``NoopTracer``, ``NoopSpan``: built-in trace sink implementations
- ``new_correlation_id``: helper to mint a correlation_id

Optional (requires the ``[otel]`` extra, ``pip install -e '.[otel]'``):

- ``OtelTracer``: adapter that ships spans via OpenTelemetry. Lazy-
  imported from ``observability.tracing`` so this module's import
  does not require the OTel packages.

See ``docs/observability-guide.md`` for the deployment integration
guide.
"""
from observability.bundle import Observability
from observability.correlation import new_correlation_id
from observability.events import (
    CapturingEventLogger,
    Event,
    EventLogger,
    EventName,
    EventStatus,
    JsonStderrEventLogger,
    NoopEventLogger,
)
from observability.metrics import (
    CapturingMetrics,
    MetricKind,
    MetricRecord,
    Metrics,
    NoopMetrics,
)
from observability.tracing import (
    NoopSpan,
    NoopTracer,
    Span,
    Tracer,
)


__all__ = [
    "CapturingEventLogger",
    "CapturingMetrics",
    "Event",
    "EventLogger",
    "EventName",
    "EventStatus",
    "JsonStderrEventLogger",
    "MetricKind",
    "MetricRecord",
    "Metrics",
    "NoopEventLogger",
    "NoopMetrics",
    "NoopSpan",
    "NoopTracer",
    "Observability",
    "Span",
    "Tracer",
    "new_correlation_id",
]
