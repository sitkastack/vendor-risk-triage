"""Metrics interface for the vendor risk triage framework.

Metrics are emitted via a ``Metrics`` Protocol with three primitives:
``counter_inc`` (monotonic counter), ``histogram_observe`` (latency
or size distribution), and ``gauge_set`` (point-in-time value).
Deployments inject a Prometheus adapter, StatsD adapter, OpenTelemetry
metrics adapter, or any other implementation matching the Protocol;
the framework default is ``NoopMetrics`` (silent).

Built-in metric names (stable as of 0.7.0):

Counters (monotonic):
- ``vrt_triage_total{tier, disposition, status}``: count of completed
  triages
- ``vrt_llm_call_total{status}``: count of LLM provider calls
- ``vrt_llm_errors_total{error_type}``: count of LLM errors
- ``vrt_validation_errors_total{error_type}``: count of validation
  failures
- ``vrt_drift_runs_total{outcome}``: count of drift check runs by
  outcome (no_drift, soft_drift, hard_drift)

Histograms (distribution):
- ``vrt_triage_duration_seconds``: wall-clock duration of a complete
  triage operation
- ``vrt_llm_call_duration_seconds``: wall-clock duration of an LLM
  provider call
- ``vrt_retrieval_duration_seconds``: wall-clock duration of a
  retrieval call
- ``vrt_retrieval_chunk_count``: number of chunks returned by a
  retrieval call
- ``vrt_audit_pack_size_bytes``: size of a rendered audit pack

Gauges (point-in-time):
- ``vrt_framework_info{version, system_prompt_hash}``: always 1; the
  labels carry the operational fingerprint. Useful for "show me all
  deployments running framework version X" dashboards.

Label cardinality is intentionally bounded. ``tier`` has 4 values,
``disposition`` has 4, ``status`` has 2 (success/error). High-
cardinality labels (vendor_id, correlation_id) are NOT used as
metric labels; they go on the structured event log and the trace
spans instead.

Design choices:

- **Protocol, not abstract base class.** ``Metrics`` is a
  ``typing.Protocol``; deployments inject any object with the four
  methods. No inheritance required.
- **Bounded cardinality.** The label sets defined above are
  enumerated; framework code never emits high-cardinality labels.
  This makes the metrics safe for Prometheus (which struggles with
  unbounded labels) and similar systems.
- **No global registry.** The framework does not maintain a
  module-level metrics registry. The Metrics implementation is
  passed explicitly to ``Observability`` or ``TriageAgent``.

Available built-in implementations:

- ``NoopMetrics``: the default. All methods are no-ops.
- ``CapturingMetrics``: records every metric call in memory. Useful
  for testing that the framework emits the expected metrics.

OpenTelemetry and Prometheus adapters are not in the framework
runtime; the deployment guide
(``docs/observability-guide.md``) provides example implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


__all__ = [
    "CapturingMetrics",
    "MetricRecord",
    "Metrics",
    "MetricKind",
    "NoopMetrics",
]


from enum import Enum


class MetricKind(str, Enum):
    """The three metric primitives."""

    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


@dataclass(frozen=True)
class MetricRecord:
    """A single metric observation recorded by ``CapturingMetrics``.

    Useful for tests asserting that the framework emits the expected
    metric. Not used by production sinks (Prometheus, OTel) which have
    their own internal representations.
    """

    kind: MetricKind
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Metrics(Protocol):
    """Sink for framework metrics.

    Three primitives:

    - ``counter_inc``: increment a monotonic counter by a non-negative
      amount (typically 1).
    - ``histogram_observe``: record a single observation into a
      distribution.
    - ``gauge_set``: set a point-in-time value.

    Implementations must be thread-safe; the framework may emit
    metrics from multiple threads if triage runs concurrently.
    Implementations must not raise; metric write failures should be
    suppressed internally rather than propagated into the operational
    path.
    """

    def counter_inc(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[dict[str, str]] = None,
    ) -> None: ...

    def histogram_observe(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None: ...

    def gauge_set(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None: ...


class NoopMetrics:
    """Default metrics sink: discards all observations.

    The framework's default. Deployments wanting metrics inject their
    own implementation (Prometheus, StatsD, OpenTelemetry, etc.).
    """

    def counter_inc(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        return None

    def histogram_observe(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        return None

    def gauge_set(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        return None


class CapturingMetrics:
    """In-memory metrics sink that records every observation.

    Attributes:
        records: All observations in arrival order.

    Useful for tests verifying the framework's metric emissions.
    Production deployments use a real adapter (Prometheus, OTel).
    """

    def __init__(self) -> None:
        self.records: list[MetricRecord] = []

    def counter_inc(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        self.records.append(MetricRecord(
            kind=MetricKind.COUNTER,
            name=name,
            value=value,
            labels=dict(labels) if labels else {},
        ))

    def histogram_observe(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        self.records.append(MetricRecord(
            kind=MetricKind.HISTOGRAM,
            name=name,
            value=value,
            labels=dict(labels) if labels else {},
        ))

    def gauge_set(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        self.records.append(MetricRecord(
            kind=MetricKind.GAUGE,
            name=name,
            value=value,
            labels=dict(labels) if labels else {},
        ))

    def filter(
        self,
        *,
        name: Optional[str] = None,
        kind: Optional[MetricKind] = None,
    ) -> list[MetricRecord]:
        """Return records matching the given filters."""
        results = list(self.records)
        if name is not None:
            results = [r for r in results if r.name == name]
        if kind is not None:
            results = [r for r in results if r.kind == kind]
        return results

    def clear(self) -> None:
        """Discard recorded metrics."""
        self.records = []
