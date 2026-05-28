# Model fallback guide

This document explains how a deployment configures automatic model fallback and circuit breaking in the vendor risk triage framework. It covers the configuration surface (`fallback_models` and `circuit_breaker`), the circuit breaker state machine, the observability signals the framework emits, the pluggable state backend for multi-process deployments, and the operational caveats that matter when you rely on fallback in production.

Fallback is opt-in. A deployment that configures neither `fallback_models` nor `circuit_breaker` gets exactly the behavior of prior framework versions: the primary model is called, and any error propagates to the caller.

## Why fallback

Provider outages and rate limits are facts of operational life. When your primary LLM provider rate-limits you, returns a 5xx, or times out, you have two choices: fail the triage call, or try a different provider. Model fallback automates the second choice. A deployment configures one or more alternate models; when the primary fails, the framework tries them in order.

The circuit breaker adds a layer of intelligence: instead of hammering a known-broken provider on every call, the breaker tracks recent failures and, once a model's failure rate crosses a threshold, stops routing to it for a cooldown period. After cooldown, a single trial call decides whether the provider has recovered.

This is the standard circuit breaker pattern from libraries like resilience4j (Java) and Polly (.NET), adapted for LLM provider routing.

## Configuration

Two new fields on `TriageAgentConfig`:

```python
from agent.agent import TriageAgent, TriageAgentConfig
from resilience import CircuitBreakerConfig

agent = TriageAgent(TriageAgentConfig(
    model="anthropic:claude-sonnet-4-5",          # primary
    fallback_models=[                              # tried in order on failure
        "openai:gpt-5.4",
        "google-gla:gemini-3-pro",
    ],
    circuit_breaker=CircuitBreakerConfig(          # optional health tracking
        failure_rate_threshold=0.5,
        window_seconds=60.0,
        cooldown_seconds=30.0,
        minimum_calls=5,
    ),
))
```

The four configurations this produces:

- **Neither field set** (the default): no fallback, no breaker. Identical to pre-0.9.0 behavior.
- **`fallback_models` set, `circuit_breaker` None**: simple fallback. Primary is tried; on any exception, fallbacks are tried in order. No health tracking, so every call always tries the primary first.
- **`circuit_breaker` set, `fallback_models` empty**: health tracking with no alternates. The breaker opens after sustained primary failures; opened-breaker calls have nowhere to fall back to and fail with a clear "all models had open breakers" error.
- **Both set** (full L4): health tracking plus fallback. The breaker routes around unhealthy models; calls flow to the first model whose breaker permits.

## The circuit breaker state machine

Each configured model has its own independent breaker. A breaker is in one of three states:

- **CLOSED**: normal operation. Calls flow through. Failures are counted.
- **OPEN**: the breaker has tripped. Calls to this model are skipped (fallback used if available) until the cooldown period elapses.
- **HALF_OPEN**: cooldown has elapsed. The next call is a trial: if it succeeds, the breaker closes; if it fails, the breaker re-opens and the cooldown restarts.

### Transitions

```
CLOSED --(failure rate >= threshold over window, with >= minimum_calls)--> OPEN
OPEN --(cooldown_seconds elapsed)--> HALF_OPEN
HALF_OPEN --(trial call succeeds)--> CLOSED
HALF_OPEN --(trial call fails)--> OPEN (cooldown restarts)
```

The breaker trips only when two conditions hold simultaneously: at least `minimum_calls` calls have accumulated in the rolling window, AND the failure rate over those calls equals or exceeds `failure_rate_threshold`. The `minimum_calls` guard prevents a single failure during a quiet period from tripping the breaker.

### Configuration parameters

`CircuitBreakerConfig` has four fields, all with defaults:

- `failure_rate_threshold` (default 0.5): the fraction of calls in the window that must fail to trip the breaker. 0.5 means "open when 50% of recent calls have failed." Must be in (0, 1].
- `window_seconds` (default 60.0): the width of the rolling window used to compute failure rate. Failures older than this are pruned and stop counting.
- `cooldown_seconds` (default 30.0): how long the breaker stays open before transitioning to half-open.
- `minimum_calls` (default 5): the minimum number of calls in the window before the failure rate is evaluated.

All four are validated at construction: a zero or out-of-range threshold, a non-positive window or cooldown, or a `minimum_calls` below 1 raises `ValueError`.

## Failure counting is permissive

This is the most important operational detail. The framework counts **any exception** from the LLM call as a failure: rate limits, timeouts, 5xx errors, but also authentication errors, malformed-output validation errors, and Pydantic schema failures.

This is a deliberate design choice (the "permissive" option). It means:

- A deployment with a **misconfigured API key** will trip the primary's breaker after a handful of calls, because each call fails with an auth error. The breaker will then route to fallbacks. If the fallbacks are also misconfigured, every breaker opens and calls fail with the all-models-down error. This is arguably correct behavior ("if I can't reach the provider, route around it"), but it can be surprising when the root cause is your own config rather than the provider's health.
- A deployment where the **LLM occasionally produces malformed output** that fails Pydantic validation will count those validation failures toward the breaker's rate, even though the provider itself is healthy. If your prompts produce frequent validation failures, the breaker may open on a perfectly functional provider.

The alternative (filtering to only provider-side errors) was considered and rejected for this version. If your deployment needs filtered counting, the cleanest path is a custom `BreakerStateStore` that inspects the failure type before recording it, or wrapping the agent in your own retry logic. A future framework version may add a configurable failure-classification hook.

Watch your observability signals. The `circuit_breaker.opened` event includes the `error_type` that triggered the trip; if you see breakers opening on `AuthenticationError` or `ValidationError` rather than `RateLimitError`, the breaker is doing its job but the root cause is not provider health.

## Observability

When observability is enabled (see `docs/observability-guide.md`), fallback and breaker activity emit these signals.

### Events

- `llm.call.fallback_triggered`: a fallback model is about to be tried (or a model was skipped because its breaker was open). Attributes: `fallback_model` or `skipped_model`, `primary_model`, `trigger_error_type` (when a previous attempt failed) or `reason=circuit_breaker_open` (when skipped), and `attempt_index`.
- `circuit_breaker.opened`: a model's breaker tripped from CLOSED or HALF_OPEN to OPEN. Attributes: `model`, `error_type`.
- `circuit_breaker.half_opened`: a model's breaker transitioned from OPEN to HALF_OPEN after cooldown elapsed. Attributes: `model`.
- `circuit_breaker.closed`: a model's breaker closed after a successful half-open trial. Attributes: `model`.

### Metrics

- `vrt_llm_fallback_total{primary, fallback, reason}` (or `{primary, skipped, reason}` for breaker-skips): counter of fallback events.
- `vrt_circuit_state_changes_total{model, from_state, to_state}`: counter of breaker state transitions.

These join the existing `vrt_llm_*` metric family. The full reference is in the observability guide.

### A worked trace

A deployment with primary Claude and fallback GPT, where Claude is rate-limiting:

1. `llm.call.started` (model=anthropic:claude-sonnet-4-5)
2. `llm.call.completed` (status=error, error_type=RateLimitError)
3. `llm.call.fallback_triggered` (fallback_model=openai:gpt-5.4, trigger_error_type=RateLimitError)
4. `llm.call.started` (model=openai:gpt-5.4)
5. `llm.call.completed` (status=success)
6. `llm.call.cost_recorded` (model_id=openai:gpt-5.4)

If this pattern repeats and Claude's failure rate crosses the threshold:

7. `circuit_breaker.opened` (model=anthropic:claude-sonnet-4-5, error_type=RateLimitError)

Subsequent calls skip Claude entirely:

1. `llm.call.fallback_triggered` (skipped_model=anthropic:claude-sonnet-4-5, reason=circuit_breaker_open)
2. `llm.call.started` (model=openai:gpt-5.4)
3. `llm.call.completed` (status=success)

After 30 seconds (the cooldown), the next call probes Claude:

1. `circuit_breaker.half_opened` (model=anthropic:claude-sonnet-4-5)
2. `llm.call.started` (model=anthropic:claude-sonnet-4-5)
3. If Claude has recovered: `llm.call.completed` (status=success), `circuit_breaker.closed` (model=anthropic:claude-sonnet-4-5)
4. If Claude is still down: `llm.call.completed` (status=error), `circuit_breaker.opened` again, fall through to GPT.

## State storage and multi-process deployments

The circuit breaker stores per-model health in a `BreakerStateStore`. The framework ships `InMemoryBreakerStateStore` as the default.

### The single-process case

For a long-running server process handling many triage calls, the in-memory store works well: the breaker accumulates enough call history to make statistical decisions, and state persists for the process's lifetime.

### The multi-process problem

If your deployment runs multiple framework instances (parallel workers, multiple servers, or one-shot CLI invocations), each process has its own in-memory store and therefore its own independent view of breaker state. Consequences:

- A worker that just learned "Claude is rate-limiting" does not share that knowledge with sibling workers. Each worker independently discovers the failure and independently trips its breaker.
- One-shot CLI invocations (`vrt triage`) start with a fresh, empty breaker every time, so the breaker never accumulates history and effectively never trips. For CLI use, fallback (without the breaker) is the useful pattern; the breaker needs a long-lived process.

### Shared state via a custom store

Deployments wanting shared breaker state across processes implement the `BreakerStateStore` protocol with a backend like Redis:

```python
from resilience import BreakerStateStore, ModelHealth, CircuitState

class RedisBreakerStateStore:
    """Shares breaker state across processes via Redis."""

    def __init__(self, redis_client, key_prefix="vrt:breaker:"):
        self._redis = redis_client
        self._prefix = key_prefix

    def get_health(self, model_id: str) -> ModelHealth:
        raw = self._redis.get(self._prefix + model_id)
        if raw is None:
            return ModelHealth()
        # Deserialize state, events, opened_at from the stored JSON
        return self._deserialize(raw)

    def update_health(self, model_id: str, health: ModelHealth) -> None:
        self._redis.set(self._prefix + model_id, self._serialize(health))
```

Then wire it in. Note that as of 0.9.0, the framework constructs its own `CircuitBreaker` internally using the config you pass; to inject a custom store, you currently construct the `CircuitBreaker` yourself and the agent uses it. A future version may add a `breaker_store` parameter to `TriageAgentConfig`. For now, deployments wanting a custom store should consult the agent source or open an issue; the protocol is stable and the integration point is small.

A robust Redis store implementation should handle concurrent updates with compare-and-swap or a per-model lock, because the framework's `should_attempt` is best-effort under concurrency: two processes may both observe HALF_OPEN and both send trial calls. For most deployments this is acceptable (two trial calls instead of one); deployments needing strict exactly-one-trial semantics need the CAS-based store.

## Cost tracking interaction

When fallback is triggered, the `cost_estimate` field on the TriageRecord records the **effective** model (the fallback that produced the result), not the primary that failed. This is correct for accounting "what did this decision cost," but note a subtlety: the failed primary call DID consume tokens at the provider (which the provider bills you for), and the framework's cost_estimate does not count those. In a fallback scenario, your actual provider spend is the failed primary's tokens PLUS the successful fallback's tokens; the framework records only the latter.

For deployments where this matters (high fallback rates, expensive primary models), track the `llm.call.completed` events with `status=error` and their associated token counts from `vrt_llm_tokens_total` to reconstruct the full spend including failed attempts.

## Operational caveats

- **The all-models-down case raises.** When every configured model has an open breaker, the framework raises a `RuntimeError` naming the primary and all fallbacks rather than silently bypassing the breakers. The breaker exists to stop calls to known-broken providers; bypassing it under sustained failure would defeat that purpose. Your orchestration layer should handle this exception (alert, queue for retry, degrade gracefully).
- **Fallback order matters.** Models are tried in the order you list them. Put your preferred-cost or preferred-quality model first and cheaper or lower-quality alternates later. The breaker does not reorder; it only skips open breakers.
- **Retries compound with fallback.** PydanticAI retries failed calls internally (the `retries` config, default 2). A single triage call that exhausts retries on the primary, then exhausts retries on each fallback, can make many provider calls. Budget for this in rate-limit planning.
- **The breaker is per-agent-instance unless you share the store.** Constructing a new TriageAgent constructs a new in-memory breaker. Long-lived deployments construct the agent once and reuse it.
- **Different models may produce different classifications.** A fallback model is a different LLM with potentially different judgment. A record produced via fallback declares the fallback model in its `agent_version` and `cost_estimate.model_id`, so an auditor can see which model made the call. If cross-model consistency matters for your audit posture, run the drift eval against each model you configure as a fallback.

## Versioning and stability

The `resilience` package's public surface (CircuitBreaker, CircuitBreakerConfig, CircuitState, ModelHealth, BreakerStateStore, InMemoryBreakerStateStore) is stable as of 0.9.0. The four new observability events and two new metrics are part of the framework's public observability surface; renames or removals require a major version bump per `docs/maintenance-workflow.md`.

The `fallback_models` and `circuit_breaker` fields on TriageAgentConfig are stable. Adding a `breaker_store` parameter (for custom state backends without manual CircuitBreaker construction) is a planned additive change for a future version; it will not break existing configurations.

## Deferred and out-of-scope

- **`TriageAgentConfig(breaker_store=...)` parameter.** Deployments wanting a custom state backend currently construct the CircuitBreaker manually. The config parameter is a non-controversial additive change deferred until a deployment needs it. Tagged `[deferred-future]`.
- **Configurable failure classification.** The permissive "any exception counts" policy is fixed in 0.9.0. A hook to classify which exceptions count toward the breaker (filtering out auth and validation errors) is deferred until deployment feedback indicates the permissive default causes problems.
- **Adaptive thresholds.** The breaker's thresholds are static. Adaptive thresholds (tightening under sustained load, loosening when healthy) are a possible future enhancement but add significant complexity and are not justified without real deployment data.
- **Fallback to a degraded mode** (e.g., rule-based classification when all LLMs are down). The framework's scope is LLM-based triage; a rule-based fallback is a deployment-layer concern.
