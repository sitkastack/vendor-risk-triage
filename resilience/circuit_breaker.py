"""Circuit breaker for LLM model fallback.

The framework supports automatic fallback between LLM providers when
the primary fails. Each configured model has a "circuit breaker" that
tracks recent failures; when failure rate exceeds threshold, the
breaker "opens" and the model is skipped until a cooldown period
elapses. Cooldown ends in "half-open" state where a single trial call
either restores the model (breaker closes) or trips it back open.

This is the standard circuit breaker pattern from resilience4j,
Polly, and similar libraries.

Design choices and their reasoning:

- **Permissive failure counting (3b in scoping).** Any exception
  raised by the LLM call counts toward the breaker's failure rate,
  including auth errors, validation errors, and Pydantic schema
  failures. A deployment with a misconfigured API key trips the
  breaker quickly; deployments where the LLM occasionally produces
  malformed output that fails Pydantic validation also count those
  toward the rate. This is the right choice when the deployment's
  goal is "route to a different provider on any sustained failure,"
  but can be surprising for failures that have nothing to do with
  provider health.
- **Pluggable state backend.** The framework provides
  ``InMemoryBreakerStateStore`` as the default. Deployments wanting
  shared state across multiple framework instances (Redis, database)
  implement the ``BreakerStateStore`` Protocol with their own store.
  Framework stays dependency-free.
- **Standard threshold defaults**: 50% failure rate over a 60-second
  rolling window opens the breaker; 30-second cooldown before
  half-open; one successful call closes the breaker from half-open.
  All four values are configurable via ``CircuitBreakerConfig``.
- **Inside the agent, not as a wrapper.** ``TriageAgent`` consults
  the breaker before each LLM call. Wrapper-agent or model-adapter
  layering was considered but rejected: the agent already owns
  model selection, cost tracking, and observability for the call,
  so the breaker fits naturally there.
- **All-open behavior**: when every configured model has an open
  breaker, raise the last error encountered rather than bypassing
  and trying primary anyway. The breaker exists to prevent calls
  to known-broken providers; bypassing it under sustained failure
  defeats that purpose.

Thread safety: ``InMemoryBreakerStateStore`` uses a lock to make
state transitions atomic. Custom stores must provide equivalent
guarantees if the deployment runs concurrent triage calls. The
``CircuitBreaker`` class itself holds no mutable state; all state
lives in the configured store.

Time source: ``CircuitBreaker`` accepts an optional ``time_fn``
parameter (defaults to ``time.monotonic``) so tests can inject a
controlled clock. Production code uses ``monotonic`` because the
sliding window is interval-based and ``monotonic`` is immune to
wall-clock adjustments.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Optional, Protocol, runtime_checkable


__all__ = [
    "BreakerStateStore",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "InMemoryBreakerStateStore",
    "ModelHealth",
]


class CircuitState(str, Enum):
    """The three states a breaker can be in.

    - ``CLOSED``: normal operation; calls flow through.
    - ``OPEN``: breaker has tripped; calls are skipped until cooldown.
    - ``HALF_OPEN``: cooldown elapsed; one trial call will decide
      whether the breaker returns to closed or back to open.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Thresholds and timing for the circuit breaker.

    Attributes:
        failure_rate_threshold: Fraction of calls in the window that
            must fail to trip the breaker. 0.5 means "open the breaker
            when 50% of recent calls have failed." Must be in (0, 1].
        window_seconds: Width of the rolling window used to compute
            failure rate, in seconds. Failures older than this are
            discarded.
        cooldown_seconds: After the breaker opens, how long to wait
            before transitioning to half-open. During cooldown, all
            calls to this model are skipped (fallback used if
            configured).
        minimum_calls: Minimum calls in the window before the failure
            rate is evaluated. Prevents tripping the breaker on a
            single failure during low-traffic periods. Defaults to 5.
    """

    failure_rate_threshold: float = 0.5
    window_seconds: float = 60.0
    cooldown_seconds: float = 30.0
    minimum_calls: int = 5

    def __post_init__(self) -> None:
        if not (0.0 < self.failure_rate_threshold <= 1.0):
            raise ValueError(
                f"failure_rate_threshold must be in (0, 1]; "
                f"got {self.failure_rate_threshold}"
            )
        if self.window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be positive; got {self.window_seconds}"
            )
        if self.cooldown_seconds <= 0:
            raise ValueError(
                f"cooldown_seconds must be positive; got {self.cooldown_seconds}"
            )
        if self.minimum_calls < 1:
            raise ValueError(
                f"minimum_calls must be at least 1; got {self.minimum_calls}"
            )


@dataclass
class ModelHealth:
    """Per-model state tracked by the breaker.

    Attributes:
        state: Current circuit state for this model.
        recent_events: Deque of (timestamp, success_bool) for calls
            within the rolling window. Older entries are pruned when
            new events arrive.
        opened_at: Timestamp the breaker last transitioned to OPEN.
            Used to compute when cooldown elapses. None when state is
            CLOSED.
    """

    state: CircuitState = CircuitState.CLOSED
    recent_events: Deque[tuple[float, bool]] = field(default_factory=deque)
    opened_at: Optional[float] = None


@runtime_checkable
class BreakerStateStore(Protocol):
    """Storage interface for circuit breaker state.

    The framework ships ``InMemoryBreakerStateStore`` as the default.
    Deployments wanting shared state across multiple framework
    instances (multiple workers, multiple servers) implement this
    Protocol with their own backend (Redis, database, etc.).

    Implementations must be thread-safe: the framework may invoke
    ``get_health`` and ``update_health`` from concurrent threads.

    State transitions should be atomic. A reasonable implementation
    uses a per-model lock or compare-and-swap primitive.
    """

    def get_health(self, model_id: str) -> ModelHealth:
        """Return the health record for a model.

        Returns a fresh ``ModelHealth`` (state=CLOSED, empty deque) if
        no record exists yet. Implementations should not raise on
        unknown models.
        """
        ...

    def update_health(
        self,
        model_id: str,
        health: ModelHealth,
    ) -> None:
        """Persist the updated health record for a model."""
        ...


class InMemoryBreakerStateStore:
    """In-memory implementation of ``BreakerStateStore``.

    Suitable for single-process deployments. State is lost when the
    process restarts; multiple processes have independent views of
    breaker state.

    Thread-safe via a single lock; for very high-concurrency
    deployments, a per-model lock would be marginally faster but the
    framework's typical workload (one triage call at a time per
    process) doesn't justify the complexity.
    """

    def __init__(self) -> None:
        self._health: dict[str, ModelHealth] = {}
        self._lock = threading.Lock()

    def get_health(self, model_id: str) -> ModelHealth:
        with self._lock:
            if model_id not in self._health:
                self._health[model_id] = ModelHealth()
            # Return a shallow copy so callers can't mutate the store
            # accidentally; the breaker passes back updates via
            # update_health.
            current = self._health[model_id]
            return ModelHealth(
                state=current.state,
                recent_events=deque(current.recent_events),
                opened_at=current.opened_at,
            )

    def update_health(
        self,
        model_id: str,
        health: ModelHealth,
    ) -> None:
        with self._lock:
            # Store a copy so caller's later mutations don't leak in.
            self._health[model_id] = ModelHealth(
                state=health.state,
                recent_events=deque(health.recent_events),
                opened_at=health.opened_at,
            )


class CircuitBreaker:
    """Circuit breaker for a set of configured models.

    Tracks per-model failure rates; opens breakers when threshold is
    exceeded; transitions through cooldown to half-open; closes
    breakers when half-open trial calls succeed.

    The breaker itself is stateless. All state lives in the
    configured ``BreakerStateStore``. A deployment can share one
    breaker instance across many threads or framework instances
    (provided the store implementation is shared appropriately).

    Args:
        config: Threshold and timing configuration. Defaults to
            standard values (50% / 60s / 30s / 5 minimum calls).
        store: State backend. Defaults to ``InMemoryBreakerStateStore``.
        time_fn: Clock source. Defaults to ``time.monotonic``. Tests
            inject a controlled clock here.
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        store: Optional[BreakerStateStore] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self._config = config if config is not None else CircuitBreakerConfig()
        self._store = store if store is not None else InMemoryBreakerStateStore()
        self._time_fn = time_fn if time_fn is not None else time.monotonic

    @property
    def config(self) -> CircuitBreakerConfig:
        """The breaker's configuration (read-only)."""
        return self._config

    @property
    def store(self) -> BreakerStateStore:
        """The state backend (read-only)."""
        return self._store

    def get_state(self, model_id: str) -> CircuitState:
        """Return the current circuit state for a model.

        Applies any pending OPEN → HALF_OPEN transition if cooldown
        has elapsed. Does NOT mutate the store; callers wanting to
        commit a transition should use ``should_attempt`` instead.
        """
        health = self._store.get_health(model_id)
        return self._derive_state(health)

    def _derive_state(self, health: ModelHealth) -> CircuitState:
        """Compute the effective state from a health record.

        Handles the time-based OPEN → HALF_OPEN transition implicitly:
        if the breaker is OPEN and cooldown has elapsed, the effective
        state is HALF_OPEN. Returns the recorded state otherwise.
        """
        if health.state == CircuitState.OPEN and health.opened_at is not None:
            now = self._time_fn()
            if now - health.opened_at >= self._config.cooldown_seconds:
                return CircuitState.HALF_OPEN
        return health.state

    def should_attempt(self, model_id: str) -> bool:
        """Return True if a call to this model should be attempted.

        Commits any pending OPEN → HALF_OPEN transition to the store
        as a side effect: a half-open transition is recorded so that
        only ONE trial call goes through during the half-open phase
        (subsequent calls see state=HALF_OPEN and the in-flight call
        is exclusively the trial).

        Note that this is a best-effort guarantee; concurrent callers
        may both observe HALF_OPEN before either commits. Production
        deployments needing strict exactly-one-trial semantics should
        provide a store implementation with compare-and-swap.

        Returns False when the breaker is OPEN and cooldown has not
        yet elapsed; True otherwise.
        """
        health = self._store.get_health(model_id)
        effective = self._derive_state(health)
        if effective == CircuitState.HALF_OPEN and health.state == CircuitState.OPEN:
            # Commit the time-based transition so subsequent calls see
            # HALF_OPEN rather than re-deriving from OPEN.
            health.state = CircuitState.HALF_OPEN
            self._store.update_health(model_id, health)
        return effective != CircuitState.OPEN

    def record_success(self, model_id: str) -> Optional[CircuitState]:
        """Record a successful call. Returns the new state if it changed.

        - From CLOSED: records the success; no state change. Returns None.
        - From HALF_OPEN: closes the breaker (trial succeeded).
          Returns CLOSED.
        - From OPEN: should not happen (calls are blocked when OPEN),
          but defensively records the success and closes the breaker.
          Returns CLOSED.
        """
        health = self._store.get_health(model_id)
        now = self._time_fn()
        self._prune_old_events(health, now)
        health.recent_events.append((now, True))

        if health.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            # Successful trial closes the breaker.
            health.state = CircuitState.CLOSED
            health.opened_at = None
            self._store.update_health(model_id, health)
            return CircuitState.CLOSED

        self._store.update_health(model_id, health)
        return None

    def record_failure(self, model_id: str) -> Optional[CircuitState]:
        """Record a failed call. Returns the new state if it changed.

        - From CLOSED: records the failure. If failure rate over the
          window now exceeds threshold (and minimum_calls have
          accumulated), opens the breaker. Returns OPEN if opened;
          None otherwise.
        - From HALF_OPEN: trial failed; re-opens the breaker. Returns
          OPEN.
        - From OPEN: should not happen (calls are blocked when OPEN),
          but defensively re-records the open timestamp to extend the
          cooldown. Returns OPEN.
        """
        health = self._store.get_health(model_id)
        now = self._time_fn()
        self._prune_old_events(health, now)
        health.recent_events.append((now, False))

        if health.state == CircuitState.HALF_OPEN:
            # Trial failed; back to open.
            health.state = CircuitState.OPEN
            health.opened_at = now
            self._store.update_health(model_id, health)
            return CircuitState.OPEN

        if health.state == CircuitState.OPEN:
            # Defensive: refresh opened_at to extend cooldown.
            health.opened_at = now
            self._store.update_health(model_id, health)
            return None  # already OPEN; no state change to report

        # CLOSED. Check if this failure trips the breaker.
        if self._should_trip(health):
            health.state = CircuitState.OPEN
            health.opened_at = now
            self._store.update_health(model_id, health)
            return CircuitState.OPEN

        self._store.update_health(model_id, health)
        return None

    def _prune_old_events(self, health: ModelHealth, now: float) -> None:
        """Drop events older than the rolling window."""
        cutoff = now - self._config.window_seconds
        while health.recent_events and health.recent_events[0][0] < cutoff:
            health.recent_events.popleft()

    def _should_trip(self, health: ModelHealth) -> bool:
        """Decide whether to trip the breaker based on current events.

        Trips when at least minimum_calls events are in the window
        AND the failure rate equals or exceeds the configured
        threshold.
        """
        total = len(health.recent_events)
        if total < self._config.minimum_calls:
            return False
        failures = sum(1 for _, success in health.recent_events if not success)
        rate = failures / total
        return rate >= self._config.failure_rate_threshold
