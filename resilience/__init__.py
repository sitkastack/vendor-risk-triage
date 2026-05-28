"""Resilience primitives for the vendor risk triage framework.

Public exports:

- ``CircuitBreaker``: stateless breaker that consults/updates a
  ``BreakerStateStore``.
- ``CircuitBreakerConfig``: frozen dataclass for thresholds and
  timing.
- ``CircuitState``: enum of CLOSED / OPEN / HALF_OPEN.
- ``ModelHealth``: per-model state record.
- ``BreakerStateStore``: Protocol for state backends.
- ``InMemoryBreakerStateStore``: default in-memory implementation.

The framework's L4 model fallback (added in 0.9.0) uses these
primitives. ``TriageAgent`` consults a ``CircuitBreaker`` before each
LLM call when fallback_models and circuit_breaker config are
provided; the breaker tracks per-model failure rates and routes
calls to healthy providers.

See ``docs/model-fallback-guide.md`` for the deployment integration
guide (added in 0.9.0).
"""
from resilience.circuit_breaker import (
    BreakerStateStore,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    InMemoryBreakerStateStore,
    ModelHealth,
)


__all__ = [
    "BreakerStateStore",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "InMemoryBreakerStateStore",
    "ModelHealth",
]
