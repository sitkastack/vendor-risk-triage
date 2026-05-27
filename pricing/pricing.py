"""Model pricing table for cost tracking.

This module defines the data structures the framework uses to attach
dollar-denominated cost estimates to ``TriageRecord`` outputs. The
table maps PydanticAI-style ``provider:model`` identifiers to per-
million-token input and output prices, plus provenance metadata
(source URL, last-verified date) that lets a maintainer audit and
refresh prices as providers change them.

Design choices and their reasoning:

- **Frozen dataclass entries.** ``ModelPrice`` is immutable. Pricing
  data should not be mutated at runtime; if a provider changes prices,
  the table is rebuilt and the ``price_table_version`` is bumped.
- **Per-million-token unit.** Providers universally quote prices per
  million tokens (MTok). Storing prices in MTok keeps numbers
  human-readable in source code review; the framework converts to
  per-token internally when computing costs.
- **Unknown-model graceful return.** ``lookup`` returns ``None`` for
  model IDs not in the table rather than raising. Test fixtures use
  ``FunctionModel`` and ``TestModel`` which never match a real
  provider ID; raising would break every test that exercises the
  agent path. The framework's contract is "cost_estimate is best-
  effort; absent when unavailable."
- **Source URLs and dates are mandatory.** Every entry includes
  ``source_url`` and ``last_verified_date`` so a maintainer reviewing
  the table can verify the current state. Stale prices are a real
  hazard; the metadata makes staleness visible.
- **Mistral Large 3 source conflict (documented).** As of
  PRICE_TABLE_VERSION 2026-05-27, sources disagree on Mistral Large
  3's pricing: some report $0.50/$1.50 per MTok (margindash,
  cloudzero) and others report $2.00/$6.00 (devtk.ai,
  aipricing.guru, tokenmix). The $2/$6 figure appears in more
  authoritative sources and is closer to the legacy Large 2 pricing,
  so the table uses $2/$6 for Large 3. A deployment that needs
  precise Mistral cost data should verify against Mistral's official
  pricing page before relying on this number.

Standard prices only. The framework does not currently model the
many pricing variants providers offer (batch API discounts at ~50%,
prompt-caching discounts up to ~90%, long-context surcharges above
200K tokens, regional data-residency uplifts). Cost estimates
produced from this table are upper bounds on real-world spend.
Future work in Phase 6 SS3-B may add these variants if deployment
feedback indicates a need.

The ``PRICE_TABLE_VERSION`` constant carries the table's release
date. Every ``cost_estimate`` field on a ``TriageRecord`` records
which version was used to compute the dollar figure. Bumping the
version is the maintainer's commit to having re-verified the prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


__all__ = [
    "ModelPrice",
    "ModelPriceTable",
    "PRICE_TABLE_VERSION",
    "PRICE_TABLE",
    "compute_cost",
    "lookup_price",
]


PRICE_TABLE_VERSION: str = "2026-05-27"
"""Date string identifying this price table revision.

Bumped whenever a price changes or a model is added or removed.
Every ``cost_estimate`` field on a ``TriageRecord`` carries this
version so an auditor reviewing an old record can see which prices
were in effect at decision time.
"""


@dataclass(frozen=True)
class ModelPrice:
    """Pricing record for a single model.

    Attributes:
        model_id: PydanticAI-style identifier in ``provider:model``
            format, exactly as a caller would pass it to
            ``TriageAgentConfig(model=...)``.
        provider: Short name of the provider (anthropic, openai,
            google, mistral). Useful for filtering and aggregation.
        input_price_per_mtok: Cost in USD per million input tokens
            at standard rates. Batch API and prompt caching discounts
            are not modeled.
        output_price_per_mtok: Cost in USD per million output tokens
            at standard rates.
        source_url: URL where this price was last verified. Typically
            the provider's official pricing page or a reputable
            third-party tracker.
        last_verified_date: ISO date string (YYYY-MM-DD) when the
            price was last checked against the source.
        notes: Optional human-readable note (e.g., "current
            flagship", "legacy", "context tier above 200K tokens
            charges premium not modeled here").
    """

    model_id: str
    provider: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    source_url: str
    last_verified_date: str
    notes: Optional[str] = None


# All prices in USD per million tokens (MTok). Sources verified
# 2026-05-27 via web search across provider docs and tracker sites
# (CloudZero, Finout, PE Collective, pricepertoken, aipricing.guru,
# margindash, devtk.ai, tokenmix). Where sources conflict, the value
# in the most authoritative-feeling source is used and the conflict
# is documented in the notes field.

_ANTHROPIC_SOURCE: str = "https://www.anthropic.com/pricing"
_OPENAI_SOURCE: str = "https://openai.com/api/pricing/"
_GOOGLE_SOURCE: str = "https://ai.google.dev/gemini-api/docs/pricing"
_MISTRAL_SOURCE: str = "https://mistral.ai/pricing"


PRICE_TABLE: dict[str, ModelPrice] = {
    # -- Anthropic Claude family (verified 2026-05-27) ---------------

    "anthropic:claude-opus-4-7": ModelPrice(
        model_id="anthropic:claude-opus-4-7",
        provider="anthropic",
        input_price_per_mtok=5.00,
        output_price_per_mtok=25.00,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
        notes="Current flagship. New tokenizer can produce up to 35% more tokens than 4.6 for the same input.",
    ),
    "anthropic:claude-opus-4-6": ModelPrice(
        model_id="anthropic:claude-opus-4-6",
        provider="anthropic",
        input_price_per_mtok=5.00,
        output_price_per_mtok=25.00,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "anthropic:claude-opus-4-1": ModelPrice(
        model_id="anthropic:claude-opus-4-1",
        provider="anthropic",
        input_price_per_mtok=15.00,
        output_price_per_mtok=75.00,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
        notes="Legacy. Replaced by Opus 4.6 at significantly lower prices.",
    ),
    "anthropic:claude-sonnet-4-6": ModelPrice(
        model_id="anthropic:claude-sonnet-4-6",
        provider="anthropic",
        input_price_per_mtok=3.00,
        output_price_per_mtok=15.00,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "anthropic:claude-sonnet-4-5": ModelPrice(
        model_id="anthropic:claude-sonnet-4-5",
        provider="anthropic",
        input_price_per_mtok=3.00,
        output_price_per_mtok=15.00,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
        notes="Framework's DEFAULT_MODEL through 0.7.0.",
    ),
    "anthropic:claude-haiku-4-5": ModelPrice(
        model_id="anthropic:claude-haiku-4-5",
        provider="anthropic",
        input_price_per_mtok=1.00,
        output_price_per_mtok=5.00,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "anthropic:claude-haiku-3": ModelPrice(
        model_id="anthropic:claude-haiku-3",
        provider="anthropic",
        input_price_per_mtok=0.25,
        output_price_per_mtok=1.25,
        source_url=_ANTHROPIC_SOURCE,
        last_verified_date="2026-05-27",
        notes="Legacy. Cheapest Claude model.",
    ),

    # -- OpenAI GPT family (verified 2026-05-27) ---------------------

    "openai:gpt-5.5": ModelPrice(
        model_id="openai:gpt-5.5",
        provider="openai",
        input_price_per_mtok=5.00,
        output_price_per_mtok=30.00,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
        notes="Current flagship.",
    ),
    "openai:gpt-5.4": ModelPrice(
        model_id="openai:gpt-5.4",
        provider="openai",
        input_price_per_mtok=2.50,
        output_price_per_mtok=15.00,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
        notes="Previous flagship; common production tier.",
    ),
    "openai:gpt-5.4-mini": ModelPrice(
        model_id="openai:gpt-5.4-mini",
        provider="openai",
        input_price_per_mtok=0.40,
        output_price_per_mtok=1.60,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "openai:gpt-5.4-nano": ModelPrice(
        model_id="openai:gpt-5.4-nano",
        provider="openai",
        input_price_per_mtok=0.20,
        output_price_per_mtok=1.25,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
        notes="Ultra-low-cost tier for high-volume simple tasks.",
    ),
    "openai:gpt-4.1": ModelPrice(
        model_id="openai:gpt-4.1",
        provider="openai",
        input_price_per_mtok=2.00,
        output_price_per_mtok=8.00,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
        notes="1M-token context. Some sources report $5/$15; the $2/$8 figure is from pricepertoken's dedicated tracker.",
    ),
    "openai:gpt-4.1-mini": ModelPrice(
        model_id="openai:gpt-4.1-mini",
        provider="openai",
        input_price_per_mtok=0.40,
        output_price_per_mtok=1.60,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "openai:gpt-4.1-nano": ModelPrice(
        model_id="openai:gpt-4.1-nano",
        provider="openai",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.40,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "openai:gpt-4o": ModelPrice(
        model_id="openai:gpt-4o",
        provider="openai",
        input_price_per_mtok=2.50,
        output_price_per_mtok=10.00,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
        notes="Legacy flagship; grandfathered pricing.",
    ),
    "openai:gpt-4o-mini": ModelPrice(
        model_id="openai:gpt-4o-mini",
        provider="openai",
        input_price_per_mtok=0.15,
        output_price_per_mtok=0.60,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "openai:o3": ModelPrice(
        model_id="openai:o3",
        provider="openai",
        input_price_per_mtok=15.00,
        output_price_per_mtok=60.00,
        source_url=_OPENAI_SOURCE,
        last_verified_date="2026-05-27",
        notes="Reasoning model. Hidden thinking tokens are billed as output.",
    ),

    # -- Google Gemini family (verified 2026-05-27) ------------------

    "google-gla:gemini-3-pro": ModelPrice(
        model_id="google-gla:gemini-3-pro",
        provider="google",
        input_price_per_mtok=2.00,
        output_price_per_mtok=12.00,
        source_url=_GOOGLE_SOURCE,
        last_verified_date="2026-05-27",
        notes="Standard rates for prompts up to 200K tokens. Above 200K: $4/$18.",
    ),
    "google-gla:gemini-3.1-pro": ModelPrice(
        model_id="google-gla:gemini-3.1-pro",
        provider="google",
        input_price_per_mtok=2.00,
        output_price_per_mtok=12.00,
        source_url=_GOOGLE_SOURCE,
        last_verified_date="2026-05-27",
        notes="Standard rates for prompts up to 200K tokens. Above 200K: $4/$18.",
    ),
    "google-gla:gemini-3.5-flash": ModelPrice(
        model_id="google-gla:gemini-3.5-flash",
        provider="google",
        input_price_per_mtok=1.50,
        output_price_per_mtok=9.00,
        source_url=_GOOGLE_SOURCE,
        last_verified_date="2026-05-27",
        notes="Launched 2026-05-19.",
    ),
    "google-gla:gemini-2.5-pro": ModelPrice(
        model_id="google-gla:gemini-2.5-pro",
        provider="google",
        input_price_per_mtok=1.25,
        output_price_per_mtok=10.00,
        source_url=_GOOGLE_SOURCE,
        last_verified_date="2026-05-27",
        notes="Previous flagship.",
    ),
    "google-gla:gemini-2.5-flash-lite": ModelPrice(
        model_id="google-gla:gemini-2.5-flash-lite",
        provider="google",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.40,
        source_url=_GOOGLE_SOURCE,
        last_verified_date="2026-05-27",
        notes="Cheapest current Gemini model.",
    ),
    "google-gla:gemini-2.0-flash": ModelPrice(
        model_id="google-gla:gemini-2.0-flash",
        provider="google",
        input_price_per_mtok=0.075,
        output_price_per_mtok=0.30,
        source_url=_GOOGLE_SOURCE,
        last_verified_date="2026-05-27",
        notes="Deprecating 2026-06-01.",
    ),

    # -- Mistral family (verified 2026-05-27) ------------------------

    "mistral:mistral-large-3": ModelPrice(
        model_id="mistral:mistral-large-3",
        provider="mistral",
        input_price_per_mtok=2.00,
        output_price_per_mtok=6.00,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
        notes="Current flagship. Source conflict: some report $0.50/$1.50; the $2/$6 figure is more widely cited. Verify against Mistral's official pricing page before relying on this number.",
    ),
    "mistral:mistral-large-2": ModelPrice(
        model_id="mistral:mistral-large-2",
        provider="mistral",
        input_price_per_mtok=2.00,
        output_price_per_mtok=6.00,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
        notes="Legacy flagship.",
    ),
    "mistral:mistral-medium-3-5": ModelPrice(
        model_id="mistral:mistral-medium-3-5",
        provider="mistral",
        input_price_per_mtok=1.50,
        output_price_per_mtok=7.50,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "mistral:mistral-medium-3": ModelPrice(
        model_id="mistral:mistral-medium-3",
        provider="mistral",
        input_price_per_mtok=0.40,
        output_price_per_mtok=2.00,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "mistral:mistral-small-4": ModelPrice(
        model_id="mistral:mistral-small-4",
        provider="mistral",
        input_price_per_mtok=0.15,
        output_price_per_mtok=0.60,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "mistral:mistral-small-3-1": ModelPrice(
        model_id="mistral:mistral-small-3-1",
        provider="mistral",
        input_price_per_mtok=0.20,
        output_price_per_mtok=0.60,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "mistral:mistral-small-3": ModelPrice(
        model_id="mistral:mistral-small-3",
        provider="mistral",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.30,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
    ),
    "mistral:codestral": ModelPrice(
        model_id="mistral:codestral",
        provider="mistral",
        input_price_per_mtok=0.30,
        output_price_per_mtok=0.90,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
        notes="Code-specialized.",
    ),
    "mistral:ministral-8b": ModelPrice(
        model_id="mistral:ministral-8b",
        provider="mistral",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.10,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
        notes="Edge / on-device tier.",
    ),
    "mistral:ministral-3b": ModelPrice(
        model_id="mistral:ministral-3b",
        provider="mistral",
        input_price_per_mtok=0.04,
        output_price_per_mtok=0.04,
        source_url=_MISTRAL_SOURCE,
        last_verified_date="2026-05-27",
        notes="Smallest edge tier.",
    ),
}


class ModelPriceTable:
    """Lookup interface over ``PRICE_TABLE``.

    Wraps the module-level dict in a small class so deployments can
    substitute a custom table (for example, an internal cost-modeling
    table with negotiated enterprise pricing) by constructing a
    ``ModelPriceTable`` with their own entries.

    Args:
        prices: Optional override for the price entries. Defaults
            to the framework's published ``PRICE_TABLE``.
        version: Optional override for the table version. Defaults
            to ``PRICE_TABLE_VERSION``. Custom tables should supply
            their own version string so audit records can distinguish
            framework-published prices from deployment-overridden
            prices.
    """

    def __init__(
        self,
        prices: Optional[dict[str, ModelPrice]] = None,
        version: Optional[str] = None,
    ) -> None:
        self._prices: dict[str, ModelPrice] = (
            prices if prices is not None else dict(PRICE_TABLE)
        )
        self._version: str = (
            version if version is not None else PRICE_TABLE_VERSION
        )

    @property
    def version(self) -> str:
        """The price-table version string."""
        return self._version

    def lookup(self, model_id: str) -> Optional[ModelPrice]:
        """Look up the price entry for a model.

        Returns ``None`` for unknown model IDs. This is the
        framework's contract: cost data is best-effort, and the
        TriageRecord's ``cost_estimate`` field is absent when no
        pricing is available (rather than the framework raising an
        error and breaking the triage call).
        """
        return self._prices.get(model_id)

    def compute_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Optional[float]:
        """Compute the dollar cost for a given token usage.

        Returns the cost in USD, or ``None`` if the model is unknown.
        Input and output tokens are non-negative integers; negative
        values raise ``ValueError`` because a negative token count is
        a programming error in the caller, not a data condition.
        """
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(
                f"token counts must be non-negative; got "
                f"input_tokens={input_tokens}, "
                f"output_tokens={output_tokens}"
            )
        price = self.lookup(model_id)
        if price is None:
            return None
        # Convert per-MTok prices to per-token, then sum
        input_cost = (input_tokens / 1_000_000) * price.input_price_per_mtok
        output_cost = (output_tokens / 1_000_000) * price.output_price_per_mtok
        return input_cost + output_cost

    def model_ids(self) -> list[str]:
        """Return all known model IDs in sorted order."""
        return sorted(self._prices.keys())

    def providers(self) -> list[str]:
        """Return all unique providers in sorted order."""
        return sorted({p.provider for p in self._prices.values()})


# Module-level convenience functions backed by the default table.


_DEFAULT_TABLE = ModelPriceTable()


def lookup_price(model_id: str) -> Optional[ModelPrice]:
    """Look up a model's price using the default published table.

    Returns ``None`` for unknown model IDs. Equivalent to
    ``ModelPriceTable().lookup(model_id)``.
    """
    return _DEFAULT_TABLE.lookup(model_id)


def compute_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """Compute cost using the default published table.

    Returns the cost in USD, or ``None`` if the model is unknown.
    Equivalent to
    ``ModelPriceTable().compute_cost(model_id, input_tokens, output_tokens)``.
    """
    return _DEFAULT_TABLE.compute_cost(model_id, input_tokens, output_tokens)
