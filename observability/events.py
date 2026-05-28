"""Structured event logging for the vendor risk triage framework.

Every meaningful framework operation emits an ``Event`` with a
consistent schema: timestamp, event name, correlation_id, optional
duration_ms, status, and an ``attributes`` dict for event-specific
fields. Deployments consume these events by configuring an
``EventLogger`` implementation; the default writes one JSON object
per line to stderr.

Design choices and their reasoning:

- **Stderr default.** Operational logs default to stderr, not stdout,
  so users piping ``vrt triage submission.json | jq`` get clean JSON
  on stdout without log lines polluting the stream.
- **JSON lines.** One JSON object per line is the lingua franca of
  log aggregators (Splunk, Datadog, Loki, Cloud Logging, Honeycomb).
  Deployments shipping logs to these systems do not need a parser.
- **Protocol-based logger.** ``EventLogger`` is a ``typing.Protocol``,
  not an abstract base class. Deployments inject any callable that
  matches the shape; no inheritance required. The framework
  provides three built-in implementations: ``NoopEventLogger`` (silent;
  the default for library use), ``JsonStderrEventLogger`` (the
  default when emit() is enabled), and ``CapturingEventLogger``
  (records events in memory; useful for testing).
- **Event names are stable.** The 12 event names this module defines
  in ``EventName`` are part of the framework's public surface as of
  0.7.0. Renames or removals require a major version bump per the
  maintenance doc.

Event names emitted by the framework:

- ``agent.constructed``: TriageAgent built; emits config summary
- ``triage.started``: triage() called; emits submission_id
- ``triage.completed``: triage() returned; emits decision_id, tier,
  disposition, duration_ms, status
- ``llm.call.started``: LLM provider call about to start
- ``llm.call.completed``: LLM call returned (success or failure);
  emits duration_ms, status, retry_count if applicable
- ``retrieval.started``: regulation chunk retrieval call begins
- ``retrieval.completed``: retrieval finished; emits chunk_count,
  duration_ms
- ``validation.started``: TriageRecord validation begins
- ``validation.completed``: validation finished; emits status, errors
- ``drift.check.started``: a drift detection run begins (CLI-driven)
- ``drift.check.completed``: drift run finished; emits scenario_count,
  hard_drift_count, soft_drift_count
- ``audit_pack.rendered``: an audit pack HTML was rendered for a
  TriageRecord; emits record_id and byte_size

Each event has these top-level fields: ``timestamp`` (UTC ISO 8601),
``event`` (one of the names above), ``correlation_id`` (16-char hex
when the event is part of a triage operation; absent for orphan
events like drift check), ``attributes`` (event-specific dict), and
``status`` (success / error / in_progress).

Attributes are event-specific. The framework documents the expected
attribute keys per event in ``docs/observability-guide.md``.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable


__all__ = [
    "Event",
    "EventLogger",
    "EventName",
    "EventStatus",
    "JsonStderrEventLogger",
    "NoopEventLogger",
    "CapturingEventLogger",
]


class EventName(str, Enum):
    """Stable identifiers for framework events.

    Public surface as of 0.7.0. Renames or removals require a major
    version bump. Additions are minor bumps.
    """

    AGENT_CONSTRUCTED = "agent.constructed"
    TRIAGE_STARTED = "triage.started"
    TRIAGE_COMPLETED = "triage.completed"
    LLM_CALL_STARTED = "llm.call.started"
    LLM_CALL_COMPLETED = "llm.call.completed"
    LLM_CALL_COST_RECORDED = "llm.call.cost_recorded"
    LLM_CALL_FALLBACK_TRIGGERED = "llm.call.fallback_triggered"
    RETRIEVAL_STARTED = "retrieval.started"
    RETRIEVAL_COMPLETED = "retrieval.completed"
    VALIDATION_STARTED = "validation.started"
    VALIDATION_COMPLETED = "validation.completed"
    DRIFT_CHECK_STARTED = "drift.check.started"
    DRIFT_CHECK_COMPLETED = "drift.check.completed"
    AUDIT_PACK_RENDERED = "audit_pack.rendered"
    CIRCUIT_BREAKER_OPENED = "circuit_breaker.opened"
    CIRCUIT_BREAKER_HALF_OPENED = "circuit_breaker.half_opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker.closed"


class EventStatus(str, Enum):
    """Outcome state for an event."""

    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    """A single structured log event.

    Frozen to make events safe to share across threads and to prevent
    accidental mutation by handlers.
    """

    event: str
    timestamp: datetime
    status: EventStatus
    correlation_id: Optional[str] = None
    duration_ms: Optional[float] = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a flat dict suitable for JSON serialization."""
        out: dict[str, Any] = {
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "event": self.event,
            "status": self.status.value,
        }
        if self.correlation_id is not None:
            out["correlation_id"] = self.correlation_id
        if self.duration_ms is not None:
            out["duration_ms"] = round(self.duration_ms, 3)
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        return out


@runtime_checkable
class EventLogger(Protocol):
    """Sink for framework events.

    Deployments implement this protocol to route events to their log
    aggregator. The framework provides three built-in implementations:
    ``NoopEventLogger`` (default, silent), ``JsonStderrEventLogger``
    (one JSON object per line on stderr), and
    ``CapturingEventLogger`` (in-memory; for testing).

    Implementations must be thread-safe: a triage operation may emit
    events from multiple threads if the deployment runs triage()
    concurrently. The built-in JsonStderrEventLogger uses
    ``print()`` which is atomic at the line level on POSIX-compatible
    streams.
    """

    def emit(self, event: Event) -> None:
        """Handle a single event. Must not raise.

        Implementations should catch and suppress their own errors
        rather than propagating them up into the framework's
        operational path. A failed log write should never break a
        triage operation.
        """
        ...


class NoopEventLogger:
    """Default logger: discards all events.

    Library users who do not configure an EventLogger see no
    observability output. This is the right default: a framework
    importing into someone else's process should not write to their
    stderr unless asked.
    """

    def emit(self, event: Event) -> None:  # noqa: D401 - protocol impl
        """Discard the event."""
        return None


class JsonStderrEventLogger:
    """JSON-lines logger writing to stderr.

    Each event becomes one line of JSON on stderr. Suitable as the
    default sink when a deployment enables observability without
    configuring a custom logger.

    Args:
        stream: Optional override of the stderr stream. Useful for
            testing or for deployments that want to redirect events
            to a different file descriptor.
    """

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def emit(self, event: Event) -> None:
        try:
            line = json.dumps(event.to_dict(), sort_keys=True)
            print(line, file=self._stream, flush=True)
        except Exception:
            # Logging must never break the operational path. A failed
            # JSON serialize or write is silently dropped.
            return None


class CapturingEventLogger:
    """In-memory logger that retains every event for inspection.

    Useful for tests that want to verify the framework emits the
    expected events without parsing log output. Events are appended
    in the order they arrive.

    Attributes:
        events: The list of recorded events, in arrival order.
    """

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def filter(
        self,
        *,
        event_name: Optional[str] = None,
        correlation_id: Optional[str] = None,
        status: Optional[EventStatus] = None,
    ) -> list[Event]:
        """Return events matching the given filters."""
        results = list(self.events)
        if event_name is not None:
            results = [e for e in results if e.event == event_name]
        if correlation_id is not None:
            results = [e for e in results if e.correlation_id == correlation_id]
        if status is not None:
            results = [e for e in results if e.status == status]
        return results

    def clear(self) -> None:
        """Discard recorded events."""
        self.events = []


def _utcnow() -> datetime:
    """Return the current UTC time. Helper for events; mockable in tests."""
    return datetime.now(timezone.utc)
