"""Tests for the pricing package.

Covers the ModelPrice dataclass, the ModelPriceTable lookup interface,
the PRICE_TABLE contents (all four providers, 33 models), the
compute_cost function (known and unknown models, edge cases), and the
module-level convenience functions.
"""
from __future__ import annotations

import re

import pytest

from pricing import (
    PRICE_TABLE,
    PRICE_TABLE_VERSION,
    ModelPrice,
    ModelPriceTable,
    compute_cost,
    lookup_price,
)


# -- PRICE_TABLE_VERSION format ------------------------------------------


def test_price_table_version_is_iso_date() -> None:
    """PRICE_TABLE_VERSION is a YYYY-MM-DD date string."""
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", PRICE_TABLE_VERSION)


# -- PRICE_TABLE contents ------------------------------------------------


def test_price_table_has_thirty_three_models() -> None:
    """The framework ships pricing for all four providers' lineups."""
    assert len(PRICE_TABLE) == 33


def test_price_table_covers_four_providers() -> None:
    """Anthropic, OpenAI, Google, Mistral."""
    providers = {entry.provider for entry in PRICE_TABLE.values()}
    assert providers == {"anthropic", "openai", "google", "mistral"}


def test_every_entry_has_required_fields() -> None:
    """Every ModelPrice entry has the required fields with valid shapes."""
    for model_id, entry in PRICE_TABLE.items():
        assert entry.model_id == model_id, (
            f"key {model_id!r} != entry.model_id {entry.model_id!r}"
        )
        assert entry.provider in {"anthropic", "openai", "google", "mistral"}
        assert entry.input_price_per_mtok >= 0
        assert entry.output_price_per_mtok >= 0
        assert entry.source_url.startswith("https://")
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", entry.last_verified_date)


def test_provider_prefix_matches_provider_field() -> None:
    """model_id provider prefix matches the provider field."""
    provider_prefixes = {
        "anthropic": "anthropic:",
        "openai": "openai:",
        "google": "google-gla:",
        "mistral": "mistral:",
    }
    for entry in PRICE_TABLE.values():
        expected_prefix = provider_prefixes[entry.provider]
        assert entry.model_id.startswith(expected_prefix), (
            f"{entry.model_id!r} has provider {entry.provider!r} but "
            f"prefix should be {expected_prefix!r}"
        )


def test_anthropic_current_flagship_pricing() -> None:
    """Sonnet 4.5 (framework's default model) prices verified."""
    entry = PRICE_TABLE["anthropic:claude-sonnet-4-5"]
    assert entry.input_price_per_mtok == 3.00
    assert entry.output_price_per_mtok == 15.00


def test_anthropic_opus_4_7_pricing() -> None:
    """Opus 4.7 (current Anthropic flagship as of May 2026)."""
    entry = PRICE_TABLE["anthropic:claude-opus-4-7"]
    assert entry.input_price_per_mtok == 5.00
    assert entry.output_price_per_mtok == 25.00


def test_openai_gpt_5_5_pricing() -> None:
    """GPT-5.5 (current OpenAI flagship)."""
    entry = PRICE_TABLE["openai:gpt-5.5"]
    assert entry.input_price_per_mtok == 5.00
    assert entry.output_price_per_mtok == 30.00


def test_google_gemini_3_pro_pricing() -> None:
    """Gemini 3 Pro standard tier (under 200K context)."""
    entry = PRICE_TABLE["google-gla:gemini-3-pro"]
    assert entry.input_price_per_mtok == 2.00
    assert entry.output_price_per_mtok == 12.00


def test_mistral_large_3_pricing() -> None:
    """Mistral Large 3 (current Mistral flagship).

    Source conflict in the wild: some report $0.50/$1.50; the framework
    uses $2/$6 based on more authoritative sources. This test pins the
    framework's chosen value.
    """
    entry = PRICE_TABLE["mistral:mistral-large-3"]
    assert entry.input_price_per_mtok == 2.00
    assert entry.output_price_per_mtok == 6.00


# -- ModelPrice dataclass ------------------------------------------------


def test_model_price_is_frozen() -> None:
    """ModelPrice instances are immutable."""
    entry = ModelPrice(
        model_id="x:y", provider="x",
        input_price_per_mtok=1.0, output_price_per_mtok=2.0,
        source_url="https://example.com", last_verified_date="2026-05-27",
    )
    with pytest.raises(Exception):
        entry.input_price_per_mtok = 99.0  # type: ignore[misc]


# -- lookup_price --------------------------------------------------------


def test_lookup_price_known_model() -> None:
    """Known model returns a ModelPrice entry."""
    result = lookup_price("anthropic:claude-sonnet-4-5")
    assert result is not None
    assert result.provider == "anthropic"


def test_lookup_price_unknown_model_returns_none() -> None:
    """Unknown model returns None (does not raise)."""
    assert lookup_price("nonexistent:fake-model") is None
    assert lookup_price("") is None
    assert lookup_price("FunctionModel(...)") is None


# -- compute_cost --------------------------------------------------------


def test_compute_cost_known_model() -> None:
    """Cost is computed correctly from token counts."""
    # Sonnet 4.5: $3/$15 per MTok
    # 1000 input + 500 output:
    # (1000/1M)*3 + (500/1M)*15 = 0.003 + 0.0075 = 0.0105
    cost = compute_cost("anthropic:claude-sonnet-4-5", 1000, 500)
    assert cost == pytest.approx(0.0105)


def test_compute_cost_unknown_model_returns_none() -> None:
    """Unknown model returns None rather than raising."""
    assert compute_cost("nonexistent:fake-model", 1000, 500) is None


def test_compute_cost_zero_tokens() -> None:
    """Zero tokens is a valid input that produces zero cost."""
    assert compute_cost("anthropic:claude-sonnet-4-5", 0, 0) == 0.0


def test_compute_cost_negative_input_tokens_raises() -> None:
    """Negative input tokens raise ValueError."""
    with pytest.raises(ValueError):
        compute_cost("anthropic:claude-sonnet-4-5", -1, 500)


def test_compute_cost_negative_output_tokens_raises() -> None:
    """Negative output tokens raise ValueError."""
    with pytest.raises(ValueError):
        compute_cost("anthropic:claude-sonnet-4-5", 1000, -1)


def test_compute_cost_large_volume() -> None:
    """Cost math works for million-token volumes."""
    # 1M input + 1M output at Sonnet 4.5 ($3 + $15):
    cost = compute_cost("anthropic:claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


# -- ModelPriceTable class -----------------------------------------------


def test_model_price_table_default_version() -> None:
    """Default table version matches the module-level constant."""
    table = ModelPriceTable()
    assert table.version == PRICE_TABLE_VERSION


def test_model_price_table_custom_version() -> None:
    """Custom version is honored."""
    table = ModelPriceTable(version="2026-12-31")
    assert table.version == "2026-12-31"


def test_model_price_table_custom_prices() -> None:
    """Custom prices override the default table."""
    custom = {
        "internal:test-model": ModelPrice(
            model_id="internal:test-model", provider="internal",
            input_price_per_mtok=0.01, output_price_per_mtok=0.02,
            source_url="https://internal/pricing",
            last_verified_date="2026-05-27",
        ),
    }
    table = ModelPriceTable(prices=custom)
    assert table.lookup("internal:test-model") is not None
    # The default table's models are NOT accessible
    assert table.lookup("anthropic:claude-sonnet-4-5") is None


def test_model_price_table_lookup() -> None:
    """ModelPriceTable.lookup returns entries for known models."""
    table = ModelPriceTable()
    entry = table.lookup("openai:gpt-5.5")
    assert entry is not None
    assert entry.input_price_per_mtok == 5.00


def test_model_price_table_compute_cost() -> None:
    """ModelPriceTable.compute_cost matches the module-level function."""
    table = ModelPriceTable()
    table_cost = table.compute_cost("anthropic:claude-sonnet-4-5", 1000, 500)
    module_cost = compute_cost("anthropic:claude-sonnet-4-5", 1000, 500)
    assert table_cost == module_cost


def test_model_ids_sorted() -> None:
    """model_ids() returns alphabetically sorted identifiers."""
    table = ModelPriceTable()
    ids = table.model_ids()
    assert ids == sorted(ids)
    assert len(ids) == len(PRICE_TABLE)


def test_providers_sorted_and_unique() -> None:
    """providers() returns the four provider names sorted."""
    table = ModelPriceTable()
    assert table.providers() == ["anthropic", "google", "mistral", "openai"]
