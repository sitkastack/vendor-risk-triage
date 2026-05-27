"""Model pricing for cost tracking.

Public exports:

- ``ModelPrice``: frozen dataclass for a single model's pricing entry.
- ``ModelPriceTable``: lookup class wrapping a dict of price entries.
- ``PRICE_TABLE_VERSION``: the date string identifying the current
  published table's revision.
- ``PRICE_TABLE``: the module-level dict of published prices.
- ``lookup_price``: convenience function over the default table.
- ``compute_cost``: convenience function over the default table.

See ``pricing/pricing.py`` for full documentation of the table's
contents, design choices, and maintenance workflow.
"""
from pricing.pricing import (
    PRICE_TABLE,
    PRICE_TABLE_VERSION,
    ModelPrice,
    ModelPriceTable,
    compute_cost,
    lookup_price,
)


__all__ = [
    "PRICE_TABLE",
    "PRICE_TABLE_VERSION",
    "ModelPrice",
    "ModelPriceTable",
    "compute_cost",
    "lookup_price",
]
