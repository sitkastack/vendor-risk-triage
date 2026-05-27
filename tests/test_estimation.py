"""Tests for pre-call cost estimation.

Covers count_input_tokens_heuristic, estimate_upper_bound_cost, and
check_budget. The CLI integration (--cost-budget and
--max-output-tokens flags) is tested separately in
test_cli_cost_budget.py.
"""
from __future__ import annotations

import pytest

from pricing import (
    BudgetCheck,
    CHARS_PER_TOKEN_HEURISTIC,
    check_budget,
    count_input_tokens_heuristic,
    estimate_upper_bound_cost,
)


# -- count_input_tokens_heuristic ----------------------------------------


def test_chars_per_token_constant() -> None:
    """The heuristic uses 4 chars per token."""
    assert CHARS_PER_TOKEN_HEURISTIC == 4


def test_count_empty_string_returns_zero() -> None:
    assert count_input_tokens_heuristic("") == 0


def test_count_short_string_returns_one() -> None:
    """Strings of 1-4 chars round up to 1 token (avoid undercount)."""
    assert count_input_tokens_heuristic("x") == 1
    assert count_input_tokens_heuristic("xx") == 1
    assert count_input_tokens_heuristic("xxx") == 1
    assert count_input_tokens_heuristic("xxxx") == 1


def test_count_uses_ceiling_division() -> None:
    """11-char string -> ceil(11/4) = 3 tokens."""
    assert count_input_tokens_heuristic("hello world") == 3


def test_count_long_string() -> None:
    """1000-char string -> 250 tokens."""
    assert count_input_tokens_heuristic("a" * 1000) == 250


def test_count_is_deterministic() -> None:
    """Same input always produces the same count."""
    text = "the quick brown fox jumps over the lazy dog"
    assert count_input_tokens_heuristic(text) == count_input_tokens_heuristic(text)


# -- estimate_upper_bound_cost -------------------------------------------


def test_estimate_known_model() -> None:
    """Known model produces upper-bound cost from price table."""
    # Sonnet 4.5: $3/$15 per MTok
    # 1000 input + 8192 max output:
    # (1000/1M)*3 + (8192/1M)*15 = 0.003 + 0.12288 = 0.12588
    est = estimate_upper_bound_cost(
        "anthropic:claude-sonnet-4-5", 1000, 8192,
    )
    assert est == pytest.approx(0.12588)


def test_estimate_unknown_model_returns_none() -> None:
    """Unknown model returns None."""
    assert estimate_upper_bound_cost("nonexistent:fake", 1000, 8192) is None


def test_estimate_zero_input_tokens() -> None:
    """Zero input tokens is valid (rare but possible)."""
    # Only output cost: (8192/1M)*15 = 0.12288
    est = estimate_upper_bound_cost(
        "anthropic:claude-sonnet-4-5", 0, 8192,
    )
    assert est == pytest.approx(0.12288)


def test_estimate_negative_input_raises() -> None:
    with pytest.raises(ValueError):
        estimate_upper_bound_cost(
            "anthropic:claude-sonnet-4-5", -1, 8192,
        )


def test_estimate_zero_max_output_raises() -> None:
    """Zero max output tokens is degenerate."""
    with pytest.raises(ValueError):
        estimate_upper_bound_cost(
            "anthropic:claude-sonnet-4-5", 1000, 0,
        )


def test_estimate_negative_max_output_raises() -> None:
    with pytest.raises(ValueError):
        estimate_upper_bound_cost(
            "anthropic:claude-sonnet-4-5", 1000, -100,
        )


def test_estimate_is_upper_bound_not_typical() -> None:
    """Estimate uses MAX output, not typical output.

    Verifies the estimate is higher than what compute_cost would
    return for a 'typical' 1500-token output.
    """
    from pricing import compute_cost
    typical = compute_cost("anthropic:claude-sonnet-4-5", 1000, 1500)
    upper_bound = estimate_upper_bound_cost(
        "anthropic:claude-sonnet-4-5", 1000, 8192,
    )
    assert upper_bound > typical


# -- check_budget --------------------------------------------------------


def test_check_budget_allowed_under_budget() -> None:
    """Cost under budget allows the call."""
    result = check_budget(
        model_id="anthropic:claude-sonnet-4-5",
        prompt="short prompt",
        max_output_tokens=100,
        budget_usd=1.00,
    )
    assert result.allowed is True
    assert result.estimated_cost_usd is not None
    assert result.estimated_cost_usd < 1.00


def test_check_budget_refuses_over_budget() -> None:
    """Cost over budget refuses the call."""
    # Opus 4.7 with full 8192 max output is expensive
    result = check_budget(
        model_id="anthropic:claude-opus-4-7",
        prompt="any prompt",
        max_output_tokens=8192,
        budget_usd=0.0001,  # 1/100 of a cent
    )
    assert result.allowed is False
    assert result.estimated_cost_usd is not None
    assert result.estimated_cost_usd > result.budget_usd


def test_check_budget_unknown_model_refuses() -> None:
    """Unknown model refuses (cannot enforce budget)."""
    result = check_budget(
        model_id="nonexistent:fake",
        prompt="prompt",
        max_output_tokens=100,
        budget_usd=10.00,  # large budget
    )
    assert result.allowed is False
    assert result.estimated_cost_usd is None
    assert "not in the framework's published price table" in result.reason


def test_check_budget_at_exact_budget_allows() -> None:
    """Cost exactly equal to budget allows (<=, not <)."""
    # Compute the exact estimate, then set budget to that value
    from pricing import estimate_upper_bound_cost
    prompt = "test prompt"
    from pricing import count_input_tokens_heuristic
    input_tokens = count_input_tokens_heuristic(prompt)
    estimated = estimate_upper_bound_cost(
        "anthropic:claude-sonnet-4-5", input_tokens, 100,
    )
    result = check_budget(
        model_id="anthropic:claude-sonnet-4-5",
        prompt=prompt,
        max_output_tokens=100,
        budget_usd=estimated,
    )
    assert result.allowed is True


def test_check_budget_zero_budget_refuses_any_real_call() -> None:
    """Zero budget refuses any real LLM call."""
    result = check_budget(
        model_id="anthropic:claude-sonnet-4-5",
        prompt="any non-empty prompt",
        max_output_tokens=100,
        budget_usd=0.0,
    )
    assert result.allowed is False


def test_check_budget_negative_budget_raises() -> None:
    """Negative budget is a programming error."""
    with pytest.raises(ValueError):
        check_budget(
            model_id="anthropic:claude-sonnet-4-5",
            prompt="prompt",
            max_output_tokens=100,
            budget_usd=-0.50,
        )


def test_check_budget_reason_contains_amounts() -> None:
    """Refusal reason includes the estimated cost and the budget."""
    result = check_budget(
        model_id="anthropic:claude-opus-4-7",
        prompt="prompt",
        max_output_tokens=8192,
        budget_usd=0.001,
    )
    assert result.allowed is False
    assert "$" in result.reason
    # Should mention input and output token counts
    assert "input tokens" in result.reason or "tokens" in result.reason


def test_check_budget_records_token_counts() -> None:
    """The result records the input and max output tokens used."""
    result = check_budget(
        model_id="anthropic:claude-sonnet-4-5",
        prompt="abcd" * 100,  # 400 chars -> 100 input tokens
        max_output_tokens=512,
        budget_usd=100.0,
    )
    assert result.input_tokens == 100
    assert result.max_output_tokens == 512


# -- BudgetCheck dataclass -----------------------------------------------


def test_budget_check_is_frozen() -> None:
    """BudgetCheck instances are immutable."""
    result = check_budget(
        model_id="anthropic:claude-sonnet-4-5",
        prompt="prompt",
        max_output_tokens=100,
        budget_usd=1.00,
    )
    with pytest.raises(Exception):
        result.allowed = False  # type: ignore[misc]
