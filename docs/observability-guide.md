# Observability guide

This document explains how a deployment integrates observability with the vendor risk triage framework. It covers structured event logging, metrics emission, distributed tracing via OpenTelemetry, and correlation across the three.

The framework's default is silent: a deployment that does nothing sees no observability output. Observability is opt-in via the `Observability` bundle passed to `TriageAgentConfig`.

## What the framework emits

Every triage operation emits three classes of observability signals:

**Events** are structured records describing what happened. The framework emits seventeen event names, each with a documented shape: `agent.constructed`, `triage.started`, `triage.completed`, `llm.call.started`, `llm.call.completed`, `llm.call.cost_recorded`, `llm.call.fallback_triggered`, `retrieval.started`, `retrieval.completed`, `validation.started`, `validation.completed`, `drift.check.started`, `drift.check.completed`, `audit_pack.rendered`, `circuit_breaker.opened`, `circuit_breaker.half_opened`, `circuit_breaker.closed`. Each event includes a timestamp, status, optional duration_ms, optional correlation_id, and an attributes dict.

**Metrics** are numeric observations: counters for things happening, histograms for distributions, gauges for point-in-time values. The framework defines ten built-in metric names with bounded label cardinality, suitable for Prometheus, StatsD, or OpenTelemetry collectors.

**Traces** are parent-child trees of spans showing the structure of an operation. The framework emits five span types per triage operation: a root `vrt.triage` span with `vrt.llm_call`, `vrt.retrieval`, `vrt.validation`, and `vrt.audit_pack.render` as children. Deployments configure an OpenTelemetry exporter to ship spans to Honeycomb, Datadog, Jaeger, or any OTLP-compatible backend.

Every signal carries the same `correlation_id` for a given triage operation, so consumers can join the operation's logs, metrics, and traces by filtering on this single value.

## Quick start

Three lines to get structured events on stderr:

```python
from observability import Observability, JsonStderrEventLogger
from agent.agent import TriageAgent, TriageAgentConfig

agent = TriageAgent(TriageAgentConfig(
    observability=Observability(event_logger=JsonStderrEventLogger()),
))
record = agent.triage(submission)
```

Now every triage operation emits seven JSON lines to stderr, one per event. Pipe to `jq`, ship to your log aggregator, or grep for specific event names.

## The Observability bundle

The `Observability` class holds three sinks: an event logger, a metrics sink, and a tracer. Each defaults to a no-op implementation. A deployment configures only the sinks it cares about; the rest stay silent.

```python
from observability import (
    Observability,
    JsonStderrEventLogger,
    NoopMetrics,    # silent metrics (the default)
    NoopTracer,     # silent tracing (the default)
)

obs = Observability(
    event_logger=JsonStderrEventLogger(),
    metrics=NoopMetrics(),
    tracer=NoopTracer(),
)
```

A single `Observability` instance is constructed once and passed to every `TriageAgent`. Deployments using dependency injection or service locators register the bundle as a singleton.

## Structured event logging

### The event schema

Every event has the same top-level shape:

```json
{
  "timestamp": "2026-05-27T18:32:14.123456Z",
  "event": "triage.completed",
  "status": "success",
  "correlation_id": "f7a3e9b2c8d145e6",
  "duration_ms": 1842.357,
  "attributes": {
    "decision_id": "d-abc123",
    "tier": "tier_3_elevated",
    "disposition": "escalate_senior_review",
    "confidence_score": 0.82
  }
}
```

The five top-level fields appear on every event. The `attributes` dict is event-specific; see the event reference below for what each event includes.

### Twelve event names

The event names are part of the framework's public surface as of 0.7.0. Renames or removals require a major version bump.

`agent.constructed` fires once per TriageAgent instance. Attributes: `agent_version`, `framework_version`, `system_prompt_hash`, `retries`. Use this event to confirm which framework version a deployment is running.

`triage.started` fires at the beginning of every `triage()` call. Status is `in_progress`. Attributes: `input_submission_id`, `input_schema_version`, `document_count`, `regulation_chunk_count`.

`triage.completed` fires when `triage()` returns or raises. Status is `success` or `error`. Duration_ms covers the entire triage call. Attributes on success: `decision_id`, `tier`, `disposition`, `confidence_score`. Attributes on error: `error_type`.

`llm.call.started` and `llm.call.completed` bracket the LLM provider call inside triage. Attributes include `model` and `error_type` (on error). Duration_ms on completion captures just the LLM round trip.

`llm.call.cost_recorded` fires after a successful LLM call (added in 0.8.0). Attributes: `model_id`, `input_tokens`, `output_tokens`, `estimated_cost_usd`, `price_table_version`, plus `reason` when the model is not in the price table (set to `model_id_not_in_price_table`). The event fires for both known and unknown models so deployments can aggregate token usage across all model configurations; the dollar figure is null for unknown models. Use this event to track LLM spend per triage operation.

`llm.call.fallback_triggered` fires when the agent is about to try a fallback model, or when it skips a model because that model's circuit breaker is open (added in 0.9.0). Attributes: `fallback_model` (when falling back after a failure) or `skipped_model` (when skipping an open breaker), `primary_model`, `trigger_error_type` (the exception that caused the fallback) or `reason=circuit_breaker_open`, and `attempt_index`. See `docs/model-fallback-guide.md`.

`circuit_breaker.opened`, `circuit_breaker.half_opened`, and `circuit_breaker.closed` fire on breaker state transitions (added in 0.9.0). The opened event includes `model` and `error_type`; half_opened and closed include `model`. These track which providers the framework considers healthy. See `docs/model-fallback-guide.md`.

`validation.started` and `validation.completed` bracket TriageRecord validation. Useful for diagnosing whether classification failures are LLM errors or schema-validation errors.

`retrieval.started` and `retrieval.completed` are reserved for future retrieval observability; the framework emits them when retrieval is invoked through observability-aware retriever wrappers (a Phase 6 SS4 deliverable). Phase 6 SS2 ships the event names but does not emit them from the agent's `triage()` path because retrieval is caller-driven; deployments that want to track retrieval emit these events themselves around their `Retriever.search()` calls.

`drift.check.started` and `drift.check.completed` are emitted by `scripts/check_drift.py` when invoked through an observability-aware wrapper. Phase 6 SS2 ships the event names; the drift CLI's direct integration is a follow-up.

`audit_pack.rendered` fires when `render_audit_pack()` produces HTML for a TriageRecord. Attributes: `record_id`, `byte_size`. Useful for tracking how often audit packs are generated and how large they tend to be.

### The three built-in event sinks

`NoopEventLogger` is the default. All `emit()` calls return without effect. The framework runs silently.

`JsonStderrEventLogger` writes one JSON object per line to stderr. The constructor accepts an optional `stream` argument for redirection; for production use, leave it as the default (stderr) and let your container or systemd unit capture the stream.

`CapturingEventLogger` retains every event in memory as a Python list. The list is exposed as `.events`. Useful for tests and for any scenario where you want to assert what the framework emitted. Also exposes `.filter(event_name=..., correlation_id=..., status=...)` for targeted lookup.

### Custom event sinks

Implement the `EventLogger` protocol: a single method `emit(event: Event) -> None`. The implementation must not raise; framework code suppresses logger exceptions, but well-behaved sinks should handle their own errors internally.

```python
from observability import EventLogger, Event

class MyAppEventLogger:
    """Routes framework events to the deployment's log aggregator."""

    def __init__(self, app_logger):
        self._log = app_logger

    def emit(self, event: Event) -> None:
        try:
            self._log.info(
                event.event,
                extra={
                    "correlation_id": event.correlation_id,
                    "duration_ms": event.duration_ms,
                    **event.attributes,
                },
            )
        except Exception:
            pass  # never break the operational path
```

## Metrics

### The Metrics protocol

Three methods, all of which must be safe to call from multiple threads:

```python
class Metrics(Protocol):
    def counter_inc(self, name, value=1.0, labels=None): ...
    def histogram_observe(self, name, value, labels=None): ...
    def gauge_set(self, name, value, labels=None): ...
```

`counter_inc` records a monotonic increment. `histogram_observe` records one observation of a distribution. `gauge_set` records a point-in-time value. The three primitives map cleanly onto Prometheus, StatsD, OpenTelemetry metrics, and most other metrics libraries.

### Fourteen built-in metric names

Counters (monotonic; reset only on process restart):

- `vrt_triage_total{tier, disposition, status}`: count of completed triages, labeled by tier (tier_1_low through tier_4_high), disposition (approve, conditional_approve, escalate_senior_review, reject), and status (success, error).
- `vrt_llm_call_total{status}`: count of LLM provider calls, labeled by status (success, error).
- `vrt_llm_errors_total{error_type}`: count of LLM errors, labeled by Python exception class name.
- `vrt_llm_cost_usd_total{model, status}`: cumulative LLM spend in USD (added in 0.8.0), labeled by model_id and status. Only incremented for models in the framework's price table; unknown models do not contribute to this counter but their token counts still appear in `vrt_llm_tokens_total`.
- `vrt_llm_fallback_total{primary, fallback, reason}`: count of fallback events (added in 0.9.0), labeled by primary model, fallback model (or `skipped` model for breaker-skips), and reason (the triggering error type, or `circuit_breaker_open`).
- `vrt_circuit_state_changes_total{model, from_state, to_state}`: count of circuit breaker state transitions (added in 0.9.0), labeled by model and the from/to states.
- `vrt_validation_errors_total{error_type}`: count of validation failures, labeled by error type.
- `vrt_drift_runs_total{outcome}`: count of drift check runs, labeled by outcome (no_drift, soft_drift, hard_drift).

Histograms (distribution of observed values):

- `vrt_triage_duration_seconds`: wall-clock duration of a complete triage call.
- `vrt_llm_call_duration_seconds`: wall-clock duration of an LLM provider call.
- `vrt_llm_tokens_total{kind, model}`: token counts per LLM call (added in 0.8.0), labeled by kind (input or output) and model_id. Emitted for every LLM call regardless of whether the model is in the price table.
- `vrt_retrieval_duration_seconds`: wall-clock duration of a retrieval call (emitted by observability-aware retriever wrappers).
- `vrt_retrieval_chunk_count`: number of chunks returned by a retrieval call.
- `vrt_audit_pack_size_bytes`: size in bytes of a rendered audit pack.

Gauges (point-in-time values):

- `vrt_framework_info{version, system_prompt_hash}`: always set to 1.0; the labels carry the operational fingerprint. Useful for "show me all deployments running framework version X" dashboards.

### Label cardinality discipline

The framework constrains labels to enumerated low-cardinality sets. `tier` has four values; `disposition` has four; `status` has two. The framework never uses high-cardinality labels like `vendor_id` or `correlation_id` as metric labels. Vendor-specific identifiers go on event attributes and trace span attributes, not metric labels, because high-cardinality metric labels break Prometheus and similar systems.

### A Prometheus adapter

The framework does not ship a Prometheus implementation; deployments construct their own. The shape is small:

```python
from observability import Metrics
from prometheus_client import Counter, Histogram, Gauge

class PrometheusMetrics:
    """Metrics adapter that ships to Prometheus."""

    def __init__(self):
        self._counters = {}
        self._histograms = {}
        self._gauges = {}

    def counter_inc(self, name, value=1.0, labels=None):
        try:
            label_names = sorted(labels.keys()) if labels else []
            key = (name, tuple(label_names))
            if key not in self._counters:
                self._counters[key] = Counter(name, name, label_names)
            counter = self._counters[key]
            if labels:
                counter.labels(**labels).inc(value)
            else:
                counter.inc(value)
        except Exception:
            pass

    # histogram_observe and gauge_set follow the same pattern
```

### A StatsD adapter

For deployments shipping to a StatsD aggregator (Datadog Agent, Telegraf, etc.):

```python
import statsd

class StatsDMetrics:
    """Metrics adapter that ships to StatsD."""

    def __init__(self, client=None):
        self._client = client or statsd.StatsClient()

    def counter_inc(self, name, value=1.0, labels=None):
        try:
            # StatsD uses tags in the metric name (DogStatsD style)
            tag_str = "".join(f",{k}:{v}" for k, v in (labels or {}).items())
            self._client.incr(f"{name}{tag_str}", count=int(value))
        except Exception:
            pass

    def histogram_observe(self, name, value, labels=None):
        try:
            tag_str = "".join(f",{k}:{v}" for k, v in (labels or {}).items())
            self._client.timing(f"{name}{tag_str}", value * 1000)  # ms
        except Exception:
            pass

    def gauge_set(self, name, value, labels=None):
        try:
            tag_str = "".join(f",{k}:{v}" for k, v in (labels or {}).items())
            self._client.gauge(f"{name}{tag_str}", value)
        except Exception:
            pass
```

### CapturingMetrics for testing

In tests, use `CapturingMetrics` to verify the framework emits the metrics you expect:

```python
from observability import CapturingMetrics, MetricKind

metrics = CapturingMetrics()
obs = Observability(metrics=metrics)
agent = TriageAgent(TriageAgentConfig(observability=obs))
agent.triage(submission)

triage_counts = metrics.filter(name="vrt_triage_total")
assert len(triage_counts) == 1
assert triage_counts[0].labels["tier"] == "tier_2_moderate"
```

## Distributed tracing

### The Tracer protocol

```python
class Tracer(Protocol):
    @contextmanager
    def start_span(self, name, attributes=None) -> Iterator[Span]: ...

class Span(Protocol):
    def set_attribute(self, key, value): ...
    def record_error(self, exc): ...
```

The framework code wraps each operation in a `with tracer.start_span(name) as span:` block. The span context manager auto-closes when the block exits. Inside the block, framework code calls `span.set_attribute()` to decorate the span and `span.record_error()` when an exception fires.

### Span hierarchy

A successful triage operation produces this span tree:

```
vrt.triage (root)
├── vrt.llm_call
└── vrt.validation
```

When the deployment uses observability-aware retrieval and audit pack rendering, the tree extends:

```
vrt.triage (root)
├── vrt.retrieval
├── vrt.llm_call
├── vrt.validation
└── vrt.audit_pack.render
```

Span attributes on the root `vrt.triage`: `vrt.submission_id`, `vrt.decision_id`, `vrt.tier`, `vrt.disposition`, `vrt.correlation_id`, `vrt.framework_version`. Child spans carry attributes specific to their operation.

### OpenTelemetry adapter

The framework ships an `OtelTracer` adapter, lazy-loaded so the core framework does not depend on OpenTelemetry packages. Install the `[otel]` extra to enable it:

```bash
pip install -e '.[otel]'
```

Configure a tracer provider and exporter, then construct an `OtelTracer`:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

from observability import Observability
from observability.tracing import OtelTracer

tracer = OtelTracer(otel_tracer=trace.get_tracer(__name__))
obs = Observability(tracer=tracer)
```

Replace `ConsoleSpanExporter` with an OTLP exporter to ship to Honeycomb, Datadog, Jaeger, Tempo, or any other backend.

### Correlating logs, metrics, and traces

Every triage operation generates a `correlation_id` that appears in three places: the event log (every event's `correlation_id` field), the metrics labels (none currently use it; this is intentional cardinality discipline), and the span attributes (on the root `vrt.triage` span as `vrt.correlation_id`).

To debug a specific decision: find the `decision_id` in your audit-pack archive. Look up the matching `correlation_id` in the TriageRecord's `correlation_id` field. Filter your log aggregator for that `correlation_id` to see the seven-event lifecycle. Search your trace backend for spans with `vrt.correlation_id` matching, and you have the complete span tree.

## Production patterns

### Disable observability for batch jobs

For batch backfills processing thousands of records, the default no-op is the right choice: zero logging overhead, zero metrics emission. Construct the agent without an `observability` argument and let the default Noop sinks handle it.

### Sample expensive observability

If your deployment runs millions of triages and shipping every event is expensive, implement a sampling event logger:

```python
import random

class SampledEventLogger:
    """Forwards a fraction of events to an underlying logger."""

    def __init__(self, underlying, sample_rate=0.01):
        self._underlying = underlying
        self._sample_rate = sample_rate

    def emit(self, event):
        # Always forward errors; sample success events
        if event.status.value == "error" or random.random() < self._sample_rate:
            self._underlying.emit(event)
```

Note that sampling metrics is generally not appropriate; metrics aggregators expect to see every observation to compute correct distributions and rates. Sample only events.

### Add deployment-specific context

Events and metrics carry framework-emitted attributes. To add deployment-specific context (tenant ID, environment, region), wrap the framework's event logger:

```python
class DeploymentEventLogger:
    """Adds deployment context to every event."""

    def __init__(self, underlying, deployment_attrs):
        self._underlying = underlying
        self._deployment_attrs = deployment_attrs

    def emit(self, event):
        # Construct a new Event with merged attributes
        from observability import Event
        merged = {**self._deployment_attrs, **event.attributes}
        decorated = Event(
            event=event.event,
            timestamp=event.timestamp,
            status=event.status,
            correlation_id=event.correlation_id,
            duration_ms=event.duration_ms,
            attributes=merged,
        )
        self._underlying.emit(decorated)
```

### Persist correlation_id in audit records

The `correlation_id` is automatically stored in every TriageRecord as of 0.7.0. Records produced by deployments using observability include the ID. Records produced by deployments using only the noop default still include it (the framework generates the ID regardless of whether observability is configured).

For deployments persisting records to a database, ensure the `correlation_id` column is indexed if you expect to query records by their operational signals.

## Versioning and stability

The observability surface is part of the framework's public commitment as of 0.7.0. As of 0.9.0, the seventeen event names, fourteen metric names, and five span names are stable. Renames or removals require a major version bump per `docs/maintenance-workflow.md`.

New events, new metrics, and new spans can ship in minor versions. Deployments depending on specific event names should write code defensively (filter for the names they expect, ignore unknown names) rather than treating the framework's emissions as a closed schema.

The Protocol-based sink interfaces (`EventLogger`, `Metrics`, `Tracer`) are also stable. Adding methods to these protocols is a breaking change for any deployment with custom implementations; the framework will not do that without a major bump.

## Deferred and out-of-scope

Phase 6 SS2 ships the runtime, the schema change, and the agent integration. The following are explicitly deferred:

- `[deferred-phase-6-ss4]` Observability hooks in `retrieval/retriever.py` and `scripts/check_drift.py`. The event names are reserved, but the framework code does not emit them yet. Phase 6 SS4 (model fallback) is the natural place to wire these.
- `[deferred-phase-7]` Sampling configuration at the framework level. Currently sampling is a deployment-side concern (wrap a sink). The framework may grow first-class sampling support if real deployment feedback indicates the wrapper pattern is awkward.
- `[deferred-phase-7]` Prometheus metrics SDK as a built-in. Currently deployments construct their own adapter; the framework documents the pattern but does not ship the code, because the right shape varies by deployment (which Prometheus client library, what naming conventions, what registry strategy).

The OpenTelemetry adapter ships because OpenTelemetry is the emerging cross-vendor standard for traces and an adapter is small enough to ship without committing to specific backends. The same justification does not currently apply to a Prometheus adapter; if it does in the future, we add it.
