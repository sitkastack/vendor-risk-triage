"""Tests for cli/output.py helpers.

Covers the color/formatting helpers used by all subcommands. The
subcommand-specific tests live in test_cli_dispatcher.py.
"""
from __future__ import annotations

import io
import os
import sys
from unittest.mock import patch

import pytest

from cli.output import (
    DISPOSITION_COLORS,
    TIER_COLORS,
    color,
    is_color_enabled,
    print_summary,
)


# -- is_color_enabled ----------------------------------------------------


def test_color_disabled_when_no_color_env_set(monkeypatch) -> None:
    """NO_COLOR env var disables color regardless of TTY status."""
    monkeypatch.setenv("NO_COLOR", "1")
    assert not is_color_enabled()


def test_color_disabled_when_stdout_not_tty(monkeypatch) -> None:
    """Non-TTY stdout disables color."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    # In pytest, stdout is normally captured (not a TTY)
    assert not is_color_enabled()


# -- color() ------------------------------------------------------------


def test_color_passthrough_when_disabled(monkeypatch) -> None:
    """color() returns plain text when color is disabled."""
    monkeypatch.setenv("NO_COLOR", "1")
    result = color("hello", "red")
    assert result == "hello"


def test_color_passthrough_for_unknown_color(monkeypatch) -> None:
    """Unknown color names pass text through unchanged (defensive)."""
    # Force color enabled by patching is_color_enabled
    with patch("cli.output.is_color_enabled", return_value=True):
        result = color("hello", "no-such-color")
        assert result == "hello"


def test_color_wraps_text_when_enabled() -> None:
    """color() wraps text in ANSI escapes when color is enabled."""
    with patch("cli.output.is_color_enabled", return_value=True):
        result = color("hello", "red")
        assert "\033[" in result
        assert "hello" in result
        assert result.endswith("\033[0m")


def test_color_bold_adds_bold_prefix() -> None:
    """bold=True adds the bold ANSI prefix."""
    with patch("cli.output.is_color_enabled", return_value=True):
        result = color("hello", "red", bold=True)
        assert "\033[1m" in result


# -- color mappings -----------------------------------------------------


def test_disposition_colors_cover_all_dispositions() -> None:
    """Every disposition value has a color mapping."""
    expected = {
        "approve", "conditional_approve",
        "escalate_senior_review", "reject",
    }
    assert set(DISPOSITION_COLORS.keys()) == expected


def test_tier_colors_cover_all_tiers() -> None:
    """Every tier value has a color mapping."""
    expected = {
        "tier_1_low", "tier_2_moderate",
        "tier_3_elevated", "tier_4_high",
    }
    assert set(TIER_COLORS.keys()) == expected


# -- print_summary ------------------------------------------------------


def _minimal_record() -> dict:
    """Build a minimal TriageRecord-shaped dict for summary tests."""
    return {
        "decision_id": "d-test-001",
        "risk_tier": "tier_2_moderate",
        "recommended_disposition": "conditional_approve",
        "confidence_signal": {"score": 0.78, "interpretation": "moderate"},
        "classification_rationale": "Test rationale text.",
        "required_mitigations": ["First mitigation."],
        "review_interval_days": 180,
    }


def test_print_summary_includes_tier_label() -> None:
    """Output contains a humanized tier label."""
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "Tier 2 (moderate)" in output


def test_print_summary_includes_disposition_label() -> None:
    """Output contains a humanized disposition label."""
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "Conditional approval" in output


def test_print_summary_includes_confidence_score() -> None:
    """Output shows the numeric confidence score."""
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "0.78" in output


def test_print_summary_includes_decision_id() -> None:
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "d-test-001" in output


def test_print_summary_includes_rationale() -> None:
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "Test rationale text" in output


def test_print_summary_includes_mitigations() -> None:
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "First mitigation" in output


def test_print_summary_includes_review_interval() -> None:
    buf = io.StringIO()
    print_summary(_minimal_record(), file=buf)
    output = buf.getvalue()
    assert "180 days" in output


def test_print_summary_includes_elapsed_when_supplied() -> None:
    buf = io.StringIO()
    print_summary(_minimal_record(), elapsed_seconds=2.34, file=buf)
    output = buf.getvalue()
    assert "2.34s" in output


def test_print_summary_omits_owner_when_absent() -> None:
    """Records without accountable_owner skip the owner line."""
    record = _minimal_record()
    record.pop("accountable_owner", None)
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    assert "Owner:" not in output


def test_print_summary_includes_owner_when_present() -> None:
    record = _minimal_record()
    record["accountable_owner"] = "Senior Risk Officer"
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    assert "Owner:" in output
    assert "Senior Risk Officer" in output


def test_print_summary_omits_mitigations_when_empty() -> None:
    record = _minimal_record()
    record["required_mitigations"] = []
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    assert "Required mitigations:" not in output


def test_print_summary_handles_missing_fields_gracefully() -> None:
    """A sparse record (mostly missing fields) does not crash."""
    sparse = {"decision_id": "d-x"}
    buf = io.StringIO()
    print_summary(sparse, file=buf)
    output = buf.getvalue()
    # Decision ID still appears
    assert "d-x" in output
    # Defaults: tier 'unknown', disposition 'unknown'
    assert "unknown" in output


def test_print_summary_handles_unknown_tier() -> None:
    """Unmapped tier values pass through (not crash)."""
    record = _minimal_record()
    record["risk_tier"] = "tier_99_alien"
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    # Falls through to the raw value
    assert "tier_99_alien" in output


def test_print_summary_handles_unknown_disposition() -> None:
    """Unmapped disposition values pass through."""
    record = _minimal_record()
    record["recommended_disposition"] = "send_to_lunch"
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    assert "send_to_lunch" in output


# -- output.py edge cases -------------------------------------------------


def test_is_color_enabled_returns_true_when_tty_and_no_env(monkeypatch) -> None:
    """Color is enabled when stdout is a TTY and NO_COLOR is unset."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    with patch("sys.stdout.isatty", return_value=True):
        assert is_color_enabled() is True


def test_print_summary_handles_multiline_rationale() -> None:
    """Rationale with explicit newlines wraps correctly."""
    record = _minimal_record()
    record["classification_rationale"] = (
        "First line.\nSecond line.\n\nFourth line after empty."
    )
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    assert "First line." in output
    assert "Second line." in output
    assert "Fourth line" in output


def test_print_summary_handles_very_long_unbroken_token() -> None:
    """A single word longer than width wraps onto its own line."""
    record = _minimal_record()
    record["classification_rationale"] = "x" * 200 + " short tail words here."
    buf = io.StringIO()
    print_summary(record, file=buf)
    output = buf.getvalue()
    # The long token appears (not truncated)
    assert "x" * 200 in output
    # And the tail words also appear
    assert "short tail words here" in output
