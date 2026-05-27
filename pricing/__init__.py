"""Model pricing for cost tracking.

Public exports:

- ``ModelPrice``: frozen dataclass for a single model's pricing entry.
- ``ModelPriceTable``: lookup class wrapping a dict of price entries.
- ``PRICE_TABLE_VERSION``: the date string identifying the current
  published table's revision.
- ``PRICE_TABLE``: the module-level dict of published prices.
- ``lookup_price``: convenience function over the default table.
- ``compute_cost``: convenience function over the default table.

Pre-call estimation primitives (added in 0.8.1 for ``--cost-budget``
gating in the ``vrt triage`` CLI):

- ``BudgetCheck``: frozen dataclass capturing the outcome of a
  budget check.
- ``CHARS_PER_TOKEN_HEURISTIC``: the 4-chars-per-token constant used
  by the heuristic counter.
- ``count_input_tokens_heuristic``: estimate input tokens from a
  string without invoking a real tokenizer.
- ``estimate_upper_bound_cost``: compute the maximum possible cost
  for an LLM call (input tokens + max output tokens at standard
  rates).
- ``check_budget``: combine estimation and comparison into one call,
  returning a ``BudgetCheck`` with the decision and a human-readable
  reason.

See ``pricing/pricing.py`` and ``pricing/estimation.py`` for full
documentation of the table's contents, the estimation heuristic, and
the design choices.
"""
from pricing.estimation import (
    BudgetCheck,
    CHARS_PER_TOKEN_HEURISTIC,
    check_budget,
    count_input_tokens_heuristic,
    estimate_upper_bound_cost,
)
from pricing.pricing import (
    PRICE_TABLE,
    PRICE_TABLE_VERSION,
    ModelPrice,
    ModelPriceTable,
    compute_cost,
    lookup_price,
)


__all__ = [
    "BudgetCheck",
    "CHARS_PER_TOKEN_HEURISTIC",
    "PRICE_TABLE",
    "PRICE_TABLE_VERSION",
    "ModelPrice",
    "ModelPriceTable",
    "check_budget",
    "compute_cost",
    "count_input_tokens_heuristic",
    "estimate_upper_bound_cost",
    "lookup_price",
]
