"""Tests for the resilience package.

Covers the CircuitBreaker state machine, CircuitBreakerConfig
validation, ModelHealth + state derivation, InMemoryBreakerStateStore
thread safety and shallow-copy isolation, and the BreakerStateStore
Protocol.

Uses a controlled clock injected via the breaker's ``time_fn``
parameter so state transitions are deterministic.
"""
from __future__ import annotations

import threading

import pytest

from resilience import (
    BreakerStateStore,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    InMemoryBreakerStateStore,
    ModelHealth,
)


class _Clock:
    """Controlled monotonic clock for deterministic tests."""

    def __init__(self) -> None:
        self.t: float = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _make_breaker(
    *,
    threshold: float = 0.5,
    window: float = 60.0,
    cooldown: float = 30.0,
    minimum: int = 4,
) -> tuple[CircuitBreaker, _Clock]:
    """Build a breaker with controlled clock and reasonable defaults."""
    clock = _Clock()
    config = CircuitBreakerConfig(
        failure_rate_threshold=threshold,
        window_seconds=window,
        cooldown_seconds=cooldown,
        minimum_calls=minimum,
    )
    return CircuitBreaker(config=config, time_fn=clock), clock


# -- CircuitBreakerConfig validation -------------------------------------


def test_default_config_values() -> None:
    """Defaults match the documented values."""
    config = CircuitBreakerConfig()
    assert config.failure_rate_threshold == 0.5
    assert config.window_seconds == 60.0
    assert config.cooldown_seconds == 30.0
    assert config.minimum_calls == 5


def test_config_rejects_zero_failure_rate() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfig(failure_rate_threshold=0.0)


def test_config_rejects_failure_rate_above_one() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfig(failure_rate_threshold=1.5)


def test_config_accepts_failure_rate_equal_to_one() -> None:
    """100% failure rate is valid (trip only when all calls fail)."""
    config = CircuitBreakerConfig(failure_rate_threshold=1.0)
    assert config.failure_rate_threshold == 1.0


def test_config_rejects_zero_window() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfig(window_seconds=0.0)


def test_config_rejects_negative_cooldown() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfig(cooldown_seconds=-1.0)


def test_config_rejects_zero_minimum_calls() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfig(minimum_calls=0)


def test_config_is_frozen() -> None:
    config = CircuitBreakerConfig()
    with pytest.raises(Exception):
        config.failure_rate_threshold = 0.9  # type: ignore[misc]


# -- CircuitState enum ---------------------------------------------------


def test_circuit_state_values() -> None:
    assert CircuitState.CLOSED.value == "closed"
    assert CircuitState.OPEN.value == "open"
    assert CircuitState.HALF_OPEN.value == "half_open"


# -- ModelHealth dataclass -----------------------------------------------


def test_model_health_defaults() -> None:
    health = ModelHealth()
    assert health.state == CircuitState.CLOSED
    assert len(health.recent_events) == 0
    assert health.opened_at is None


# -- InMemoryBreakerStateStore -------------------------------------------


def test_store_returns_fresh_health_for_unknown_model() -> None:
    store = InMemoryBreakerStateStore()
    health = store.get_health("nonexistent")
    assert health.state == CircuitState.CLOSED
    assert len(health.recent_events) == 0


def test_store_persists_updates() -> None:
    store = InMemoryBreakerStateStore()
    health = ModelHealth(state=CircuitState.OPEN, opened_at=42.0)
    store.update_health("model-x", health)
    retrieved = store.get_health("model-x")
    assert retrieved.state == CircuitState.OPEN
    assert retrieved.opened_at == 42.0


def test_store_returns_shallow_copies() -> None:
    """Mutating a returned ModelHealth should not affect the store."""
    store = InMemoryBreakerStateStore()
    h1 = store.get_health("model-x")
    h1.recent_events.append((1.0, True))
    h2 = store.get_health("model-x")
    # The store didn't see the mutation
    assert len(h2.recent_events) == 0


def test_store_implements_breaker_state_store_protocol() -> None:
    """InMemoryBreakerStateStore satisfies the BreakerStateStore Protocol."""
    store = InMemoryBreakerStateStore()
    assert isinstance(store, BreakerStateStore)


def test_store_thread_safe_under_concurrent_writes() -> None:
    """Concurrent updates to the same model don't crash or corrupt state."""
    store = InMemoryBreakerStateStore()

    def writer(value: int) -> None:
        for _ in range(50):
            h = store.get_health("contended-model")
            h.recent_events.append((value, True))
            store.update_health("contended-model", h)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = store.get_health("contended-model")
    # We don't assert exact length (race-y); just that state is internally
    # consistent and didn't blow up.
    assert final.state == CircuitState.CLOSED


# -- CircuitBreaker: CLOSED -> OPEN transition ---------------------------


def test_initial_state_is_closed() -> None:
    cb, _ = _make_breaker()
    assert cb.get_state("model-x") == CircuitState.CLOSED


def test_should_attempt_returns_true_when_closed() -> None:
    cb, _ = _make_breaker()
    assert cb.should_attempt("model-x") is True


def test_breaker_does_not_trip_below_minimum_calls() -> None:
    """Three failures with minimum=4 should not trip."""
    cb, _ = _make_breaker(minimum=4)
    for _ in range(3):
        cb.record_failure("model-x")
    assert cb.get_state("model-x") == CircuitState.CLOSED


def test_breaker_trips_at_threshold_with_minimum_calls() -> None:
    """4 calls, 3 failures + 1 success = 75% > 50% threshold -> OPEN."""
    cb, _ = _make_breaker(threshold=0.5, minimum=4)
    cb.record_failure("model-x")
    cb.record_failure("model-x")
    cb.record_success("model-x")
    result = cb.record_failure("model-x")
    assert result == CircuitState.OPEN
    assert cb.get_state("model-x") == CircuitState.OPEN


def test_breaker_does_not_trip_below_threshold() -> None:
    """1 failure + 4 successes = 20% < 50% threshold -> stays CLOSED."""
    cb, _ = _make_breaker(threshold=0.5, minimum=4)
    for _ in range(4):
        cb.record_success("model-x")
    result = cb.record_failure("model-x")
    assert result is None
    assert cb.get_state("model-x") == CircuitState.CLOSED


def test_failures_outside_window_are_pruned() -> None:
    """Failures older than window_seconds don't count toward rate."""
    cb, clock = _make_breaker(threshold=0.5, window=60.0, minimum=4)
    # 3 failures at t=0
    for _ in range(3):
        cb.record_failure("model-x")
    # Advance past the window
    clock.advance(70.0)
    # A single recent failure shouldn't trip (only 1 in window now)
    result = cb.record_failure("model-x")
    assert result is None
    assert cb.get_state("model-x") == CircuitState.CLOSED


# -- CircuitBreaker: OPEN -> HALF_OPEN -> CLOSED -------------------------


def _trip_breaker(cb: CircuitBreaker, model: str = "model-x") -> None:
    """Helper: trip the breaker into OPEN state."""
    for _ in range(4):
        cb.record_failure(model)
    assert cb.get_state(model) == CircuitState.OPEN


def test_open_breaker_blocks_calls() -> None:
    cb, _ = _make_breaker()
    _trip_breaker(cb)
    assert cb.should_attempt("model-x") is False


def test_cooldown_transitions_to_half_open() -> None:
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(31.0)
    # get_state observes the transition without committing it
    assert cb.get_state("model-x") == CircuitState.HALF_OPEN


def test_should_attempt_during_cooldown_returns_false() -> None:
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(15.0)  # mid-cooldown
    assert cb.should_attempt("model-x") is False


def test_should_attempt_after_cooldown_returns_true() -> None:
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(31.0)
    assert cb.should_attempt("model-x") is True


def test_should_attempt_commits_half_open_transition() -> None:
    """should_attempt persists the OPEN -> HALF_OPEN state change."""
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(31.0)
    cb.should_attempt("model-x")
    # The store now reflects HALF_OPEN, not OPEN
    health = cb.store.get_health("model-x")
    assert health.state == CircuitState.HALF_OPEN


def test_successful_trial_closes_breaker() -> None:
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(31.0)
    cb.should_attempt("model-x")  # transitions to HALF_OPEN
    result = cb.record_success("model-x")
    assert result == CircuitState.CLOSED
    assert cb.get_state("model-x") == CircuitState.CLOSED


def test_failed_trial_reopens_breaker() -> None:
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(31.0)
    cb.should_attempt("model-x")
    result = cb.record_failure("model-x")
    assert result == CircuitState.OPEN


def test_failed_trial_resets_cooldown() -> None:
    """After a failed trial, the cooldown clock restarts."""
    cb, clock = _make_breaker(cooldown=30.0)
    _trip_breaker(cb)
    clock.advance(31.0)
    cb.should_attempt("model-x")
    cb.record_failure("model-x")
    # opened_at should be the current time, not the original trip time
    health = cb.store.get_health("model-x")
    assert health.opened_at == clock.t


# -- Custom config + store via constructor -------------------------------


def test_breaker_uses_default_config_when_unspecified() -> None:
    cb = CircuitBreaker()
    assert cb.config.failure_rate_threshold == 0.5


def test_breaker_uses_default_store_when_unspecified() -> None:
    cb = CircuitBreaker()
    assert isinstance(cb.store, InMemoryBreakerStateStore)


def test_breaker_accepts_custom_store() -> None:
    store = InMemoryBreakerStateStore()
    cb = CircuitBreaker(store=store)
    assert cb.store is store


# -- Independent models --------------------------------------------------


def test_breakers_are_per_model() -> None:
    """Tripping one model's breaker doesn't affect another's."""
    cb, _ = _make_breaker(minimum=4)
    _trip_breaker(cb, model="model-x")
    assert cb.get_state("model-x") == CircuitState.OPEN
    assert cb.get_state("model-y") == CircuitState.CLOSED


def test_record_failure_while_already_open_returns_none() -> None:
    """Defensive: a failure recorded while OPEN does not trigger a state change event.

    This branch exists because normal flow never reaches it (calls are
    blocked when OPEN), but the breaker still records the failure and
    refreshes opened_at to extend cooldown. Returns None (no state
    change to report).
    """
    cb, clock = _make_breaker()
    _trip_breaker(cb)
    initial_opened_at = cb.store.get_health("model-x").opened_at
    clock.advance(10.0)
    result = cb.record_failure("model-x")
    assert result is None  # no state change reported
    new_opened_at = cb.store.get_health("model-x").opened_at
    # opened_at refreshed to current time
    assert new_opened_at is not None
    assert new_opened_at > initial_opened_at


def test_record_success_while_already_open_closes_breaker() -> None:
    """Defensive: a success recorded while OPEN closes the breaker.

    Normal flow never reaches OPEN-during-success (calls are blocked),
    but defensively the breaker treats success as evidence the
    provider is healthy and closes.
    """
    cb, _ = _make_breaker()
    _trip_breaker(cb)
    result = cb.record_success("model-x")
    assert result == CircuitState.CLOSED
