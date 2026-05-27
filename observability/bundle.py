"""Observability: bundle of logger + metrics + tracer + correlation_id helpers.

A deployment wanting observability constructs a single
``Observability`` instance and passes it to ``TriageAgent`` via
``TriageAgentConfig(observability=...)``. The bundle holds the three
sinks (event logger, metrics, tracer) and exposes high-level methods
the framework's internal code uses to emit events, increment metrics,
and open spans.

Default construction yields all-noop sinks:

    obs = Observability()  # silent

Common configurations:

    # All events on stderr as JSON; metrics + tracing noop
    obs = Observability(event_logger=JsonStderrEventLogger())

    # In-memory capture for testing
    obs = Observability(
        event_logger=CapturingEventLogger(),
        metrics=CapturingMetrics(),
    )

    # Production: structured logs + metrics + OTel tracing
    obs = Observability(
        event_logger=MyAppEventLogger(),
        metrics=PrometheusMetrics(),
        tracer=OtelTracer(otel_tracer=trace.get_tracer(__name__)),
    )

The framework imports nothing from the deployment side beyond the
three protocols. A deployment without observability needs to make
zero changes.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from observability.correlation import new_correlation_id
from observability.events import (
    CapturingEventLogger,
    Event,
    EventLogger,
    EventName,
    EventStatus,
    JsonStderrEventLogger,
    NoopEventLogger,
    _utcnow,
)
from observability.metrics import (
    CapturingMetrics,
    Metrics,
    NoopMetrics,
)
from observability.tracing import (
    NoopTracer,
    Span,
    Tracer,
)


__all__ = ["Observability"]


class Observability:
    """Bundle of event logger, metrics sink, and tracer.

    A single ``Observability`` instance is passed into ``TriageAgent``;
    framework code calls into the bundle to emit events, increment
    metrics, and open trace spans. The bundle's methods provide a
    convenient surface so framework code doesn't have to thread three
    separate objects through every call site.

    Args:
        event_logger: Sink for structured events. Defaults to
            ``NoopEventLogger`` (silent).
        metrics: Sink for metrics. Defaults to ``NoopMetrics``.
        tracer: Sink for trace spans. Defaults to ``NoopTracer``.
    """

    def __init__(
        self,
        event_logger: Optional[EventLogger] = None,
        metrics: Optional[Metrics] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self.event_logger = event_logger if event_logger is not None else NoopEventLogger()
        self.metrics = metrics if metrics is not None else NoopMetrics()
        self.tracer = tracer if tracer is not None else NoopTracer()

    # -- event helpers --------------------------------------------------

    def emit_event(
        self,
        event_name: str,
        *,
        status: EventStatus = EventStatus.SUCCESS,
        correlation_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> None:
        """Emit a single structured event.

        Wraps construction of an ``Event`` so callers can write a
        single line. The logger's emit() must not raise; this helper
        wraps it in a try-except as belt-and-suspenders defense.
        """
        event = Event(
            event=event_name,
            timestamp=_utcnow(),
            status=status,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
            attributes=attributes or {},
        )
        try:
            self.event_logger.emit(event)
        except Exception:
            # Observability never breaks the operational path.
            return None

    # -- metric helpers -------------------------------------------------

    def counter_inc(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        try:
            self.metrics.counter_inc(name, value, labels)
        except Exception:
            return None

    def histogram_observe(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        try:
            self.metrics.histogram_observe(name, value, labels)
        except Exception:
            return None

    def gauge_set(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        try:
            self.metrics.gauge_set(name, value, labels)
        except Exception:
            return None

    # -- tracing helpers ------------------------------------------------

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Iterator[Span]:
        """Open a trace span via the configured tracer."""
        with self.tracer.start_span(name, attributes) as span:
            yield span

    # -- correlation id -------------------------------------------------

    @staticmethod
    def new_correlation_id() -> str:
        """Mint a new correlation_id for a triage operation."""
        return new_correlation_id()
