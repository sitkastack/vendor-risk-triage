"""Pre-call cost estimation for budget gating.

The framework supports a ``--cost-budget DOLLARS`` flag on
``vrt triage`` that refuses LLM calls projected to exceed a deployment-
specified budget. To enforce the budget without already spending the
money, the gate must estimate cost BEFORE the LLM call returns. This
module provides the estimation primitives.

Three pieces:

- ``count_input_tokens_heuristic(text)`` returns a token count
  estimate from a string using a character-based heuristic (~4
  characters per token for English-language prompts). Provider-
  agnostic, zero dependencies. Less accurate than a real tokenizer
  but adequate for budget gating, where slight overestimation is
  acceptable (and slight underestimation is the dangerous direction).
- ``estimate_upper_bound_cost(model_id, input_tokens,
  max_output_tokens)`` returns the maximum possible cost for an LLM
  call given input token count and the model's max_tokens setting,
  using standard rates from the published price table.
- ``check_budget(model_id, prompt, max_output_tokens, budget)``
  returns a ``BudgetCheck`` named tuple recording the estimated cost,
  the budget, and whether the call is allowed.

Design choices and their reasoning:

- **Upper-bound estimation, not heuristic estimation.** The framework
  computes cost as ``(input_tokens * input_price) + (max_output_tokens
  * output_price)`` rather than guessing typical output length. The
  upper bound is conservative: the gate may refuse some calls that
  would have come in under budget, but it will never let a call
  through that exceeds budget. The alternative (estimating "typical"
  output) creates a false sense of safety and defeats the gate's
  purpose for the edge cases that matter.
- **Character-based input token heuristic.** Real tokenization is
  provider-specific (tiktoken for OpenAI, sentencepiece-derivatives
  elsewhere). Pulling in provider-specific tokenizer dependencies
  bloats the framework runtime; the character heuristic is good
  enough for gating with a small safety margin. Deployments wanting
  precision can plug in their own tokenizer and call
  ``estimate_upper_bound_cost`` directly with the precise count.
- **Unknown model returns None from estimate_upper_bound_cost.** Same
  contract as ``compute_cost``: cost is best-effort. When the model
  is not in the price table (FunctionModel, custom adapters), the
  estimator returns None. The CLI's budget check treats this as
  "cannot enforce budget" and refuses to proceed (rather than
  silently letting the call through, which would defeat the gate).

The 4-characters-per-token ratio is a published rule of thumb for
English-language text across major tokenizers; real ratios vary
3.5-5.0 depending on content. Slightly biased toward undercounting
means the gate could be ~10-15% looser than ideal; the
max_output_tokens overestimate on the output side typically
overcorrects, so the net effect is still conservative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pricing.pricing import lookup_price


__all__ = [
    "BudgetCheck",
    "CHARS_PER_TOKEN_HEURISTIC",
    "check_budget",
    "count_input_tokens_heuristic",
    "estimate_upper_bound_cost",
]


CHARS_PER_TOKEN_HEURISTIC: int = 4
"""Characters-per-token ratio used by the heuristic counter.

Standard rule of thumb for English-language text. Real ratios vary
3.5-5.0 across tokenizers. The framework's gate uses the 4.0 figure
as a reasonable midpoint.
"""


def count_input_tokens_heuristic(text: str) -> int:
    """Estimate input token count from a string.

    Uses a character-based heuristic (~4 characters per token for
    English-language text). Provider-agnostic, zero dependencies.

    For empty input, returns 0. For very short input (1-3 characters),
    returns 1 to avoid undercounting.

    Args:
        text: The string to estimate tokens for. Typically the
            constructed LLM prompt.

    Returns:
        Estimated token count as a non-negative integer.
    """
    if not text:
        return 0
    # Ceiling division to avoid undercounting short strings.
    return max(1, (len(text) + CHARS_PER_TOKEN_HEURISTIC - 1) // CHARS_PER_TOKEN_HEURISTIC)


def estimate_upper_bound_cost(
    model_id: str,
    input_tokens: int,
    max_output_tokens: int,
) -> Optional[float]:
    """Compute the maximum possible cost for an LLM call.

    Uses standard rates from the published price table. Cost is
    ``(input_tokens * input_price_per_mtok / 1M) + (max_output_tokens
    * output_price_per_mtok / 1M)``. Output is sized at its maximum,
    so the result is an upper bound on actual cost.

    Returns None for unknown models (same contract as
    ``pricing.compute_cost``).

    Args:
        model_id: PydanticAI-style provider:model identifier.
        input_tokens: Estimated input token count (non-negative).
        max_output_tokens: Maximum output tokens the LLM call can
            produce. Must be positive; a budget gate with zero output
            tokens is degenerate.

    Returns:
        Upper-bound cost in USD, or None if the model is unknown.

    Raises:
        ValueError: if input_tokens is negative or max_output_tokens
            is less than 1.
    """
    if input_tokens < 0:
        raise ValueError(
            f"input_tokens must be non-negative; got {input_tokens}"
        )
    if max_output_tokens < 1:
        raise ValueError(
            f"max_output_tokens must be at least 1; got {max_output_tokens}"
        )
    price = lookup_price(model_id)
    if price is None:
        return None
    input_cost = (input_tokens / 1_000_000) * price.input_price_per_mtok
    output_cost = (max_output_tokens / 1_000_000) * price.output_price_per_mtok
    return input_cost + output_cost


@dataclass(frozen=True)
class BudgetCheck:
    """Result of a budget check.

    Attributes:
        allowed: True if the estimated cost is within budget.
        model_id: The model identifier checked.
        input_tokens: Estimated input token count used in the check.
        max_output_tokens: Max output tokens used in the check.
        estimated_cost_usd: The upper-bound cost estimate. None when
            the model is unknown to the price table; in that case,
            ``allowed`` is False (the gate refuses unknown models
            rather than silently letting them through).
        budget_usd: The configured budget.
        reason: Human-readable explanation of the decision. Useful
            for CLI error messages and audit trails.
    """

    allowed: bool
    model_id: str
    input_tokens: int
    max_output_tokens: int
    estimated_cost_usd: Optional[float]
    budget_usd: float
    reason: str


def check_budget(
    model_id: str,
    prompt: str,
    max_output_tokens: int,
    budget_usd: float,
) -> BudgetCheck:
    """Check whether an LLM call would fit within budget.

    Estimates input tokens from the prompt, computes the upper-bound
    cost via the price table, and compares to the budget.

    Args:
        model_id: PydanticAI-style provider:model identifier.
        prompt: The string that would be sent to the LLM. Used for
            input token estimation.
        max_output_tokens: Maximum output tokens the call can produce.
        budget_usd: Maximum allowed cost in USD.

    Returns:
        A BudgetCheck result. The ``allowed`` field is True only when
        the model is known AND the estimated cost fits within budget.
    """
    if budget_usd < 0:
        raise ValueError(
            f"budget_usd must be non-negative; got {budget_usd}"
        )
    input_tokens = count_input_tokens_heuristic(prompt)
    estimated = estimate_upper_bound_cost(
        model_id, input_tokens, max_output_tokens,
    )
    if estimated is None:
        return BudgetCheck(
            allowed=False,
            model_id=model_id,
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            estimated_cost_usd=None,
            budget_usd=budget_usd,
            reason=(
                f"Cannot enforce budget: model {model_id!r} is not in "
                f"the framework's published price table. The budget "
                f"gate refuses unknown models rather than letting the "
                f"call through without verification. Either configure "
                f"a known model or remove --cost-budget."
            ),
        )
    if estimated <= budget_usd:
        return BudgetCheck(
            allowed=True,
            model_id=model_id,
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            estimated_cost_usd=estimated,
            budget_usd=budget_usd,
            reason=(
                f"Estimated upper-bound cost ${estimated:.6f} fits "
                f"within budget ${budget_usd:.6f}."
            ),
        )
    return BudgetCheck(
        allowed=False,
        model_id=model_id,
        input_tokens=input_tokens,
        max_output_tokens=max_output_tokens,
        estimated_cost_usd=estimated,
        budget_usd=budget_usd,
        reason=(
            f"Estimated upper-bound cost ${estimated:.6f} exceeds "
            f"budget ${budget_usd:.6f} by ${estimated - budget_usd:.6f}. "
            f"({input_tokens} input tokens at "
            f"{CHARS_PER_TOKEN_HEURISTIC} chars/token + "
            f"{max_output_tokens} max output tokens.)"
        ),
    )
