"""Tests for the ``vrt triage`` CLI subcommand's cost budget flags.

Covers argument parsing, the validation rules for the
``--cost-budget``/``--max-output-tokens`` flag pair, and the budget
gate behavior (refusal when over budget, allow when under budget,
refusal on unknown models).

The tests construct an argparse Namespace directly and call
``cmd_triage.run()``, mocking the TriageAgent construction so the
tests do not require API keys or real LLM calls.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).parent.parent
SUBMISSION_PATH = (
    REPO_ROOT / "examples" / "submissions"
    / "01-tier1-internal-productivity.json"
)


def _make_args(
    submission: Path = SUBMISSION_PATH,
    *,
    output: Path = None,
    json_only: bool = False,
    model: str = None,
    cost_budget: float = None,
    max_output_tokens: int = None,
    corpus: str = None,
    top_k: int = 5,
) -> argparse.Namespace:
    """Build an argparse Namespace matching cmd_triage's expectations.

    ``corpus`` and ``top_k`` default to "no corpus loaded" — matching
    the 1.0.1 behavior preserved by the 1.0.2 --corpus addition.
    """
    return argparse.Namespace(
        submission=submission,
        output=output,
        json_only=json_only,
        model=model,
        cost_budget=cost_budget,
        max_output_tokens=max_output_tokens,
        corpus=corpus,
        top_k=top_k,
    )


def _make_mock_agent(model_id: str = "anthropic:claude-sonnet-4-5"):
    """Build a mock TriageAgent with a configurable model_id."""
    mock_agent = MagicMock()
    mock_agent._config.model = model_id

    # The triage method returns a mock record that mimics the
    # interface cmd_triage uses (.model_dump()).
    mock_record = MagicMock()
    mock_record.model_dump = MagicMock(return_value={
        "decision_id": "d-test-1",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
        "output_schema_version": "1.2.0",
    })
    mock_agent.triage = MagicMock(return_value=mock_record)
    return mock_agent


# -- Flag pairing validation ---------------------------------------------


def test_cost_budget_without_max_output_tokens_errors(capsys) -> None:
    """--cost-budget alone is rejected."""
    from cli import cmd_triage
    args = _make_args(cost_budget=0.50, max_output_tokens=None)
    exit_code = cmd_triage.run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "--cost-budget requires --max-output-tokens" in captured.err


def test_max_output_tokens_without_cost_budget_is_ignored(capsys) -> None:
    """--max-output-tokens alone (no --cost-budget) does not trigger the gate.

    The flag is documented as ignored when --cost-budget is not set.
    A real LLM call would still happen (mocked here).
    """
    from cli import cmd_triage
    args = _make_args(cost_budget=None, max_output_tokens=8192)
    with patch("agent.agent.TriageAgent", return_value=_make_mock_agent()):
        exit_code = cmd_triage.run(args)
    # The triage succeeds; the lone flag is silently ignored.
    assert exit_code == 0


def test_negative_cost_budget_errors(capsys) -> None:
    """Negative budget is rejected before agent construction."""
    from cli import cmd_triage
    args = _make_args(cost_budget=-1.0, max_output_tokens=8192)
    exit_code = cmd_triage.run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "must be non-negative" in captured.err


def test_zero_max_output_tokens_errors(capsys) -> None:
    """Zero max output tokens is degenerate and rejected."""
    from cli import cmd_triage
    args = _make_args(cost_budget=1.00, max_output_tokens=0)
    exit_code = cmd_triage.run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "must be at least 1" in captured.err


def test_negative_max_output_tokens_errors(capsys) -> None:
    """Negative max output tokens is rejected."""
    from cli import cmd_triage
    args = _make_args(cost_budget=1.00, max_output_tokens=-100)
    exit_code = cmd_triage.run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "must be at least 1" in captured.err


# -- Budget gate behavior with mocked agent ------------------------------


def test_budget_under_threshold_allows_triage(capsys) -> None:
    """Cost under budget allows the call to proceed."""
    from cli import cmd_triage
    args = _make_args(cost_budget=10.00, max_output_tokens=8192)
    with patch(
        "agent.agent.TriageAgent",
        return_value=_make_mock_agent("anthropic:claude-sonnet-4-5"),
    ):
        exit_code = cmd_triage.run(args)
    assert exit_code == 0


def test_budget_over_threshold_refuses_triage(capsys) -> None:
    """Cost over budget refuses with a clear error message."""
    from cli import cmd_triage
    # Tiny budget against Opus 4.7 ensures the upper-bound exceeds budget
    args = _make_args(cost_budget=0.0001, max_output_tokens=8192)
    with patch(
        "agent.agent.TriageAgent",
        return_value=_make_mock_agent("anthropic:claude-opus-4-7"),
    ):
        exit_code = cmd_triage.run(args)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "cost budget check failed" in captured.err
    assert "exceeds budget" in captured.err


def test_unknown_model_with_budget_refuses(capsys) -> None:
    """Unknown model (no price entry) refuses when --cost-budget is set."""
    from cli import cmd_triage
    args = _make_args(cost_budget=10.00, max_output_tokens=8192)
    with patch(
        "agent.agent.TriageAgent",
        return_value=_make_mock_agent("nonexistent:fake-model"),
    ):
        exit_code = cmd_triage.run(args)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "cost budget check failed" in captured.err
    assert "not in the framework's published price table" in captured.err


def test_no_budget_does_not_invoke_gate(capsys) -> None:
    """Without --cost-budget, the gate is not exercised.

    Even with an unknown model, the call proceeds (the gate would have
    refused, but the gate is not active).
    """
    from cli import cmd_triage
    args = _make_args(cost_budget=None, max_output_tokens=None)
    with patch(
        "agent.agent.TriageAgent",
        return_value=_make_mock_agent("nonexistent:unknown-model"),
    ):
        exit_code = cmd_triage.run(args)
    assert exit_code == 0


# -- Argparse integration ------------------------------------------------


def test_argparse_parses_cost_budget_flag() -> None:
    """The CLI's add_arguments registers --cost-budget as float."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    args = parser.parse_args([
        "some-submission.json",
        "--cost-budget", "0.50",
        "--max-output-tokens", "8192",
    ])
    assert args.cost_budget == 0.50
    assert args.max_output_tokens == 8192


def test_argparse_omits_budget_flags_when_not_passed() -> None:
    """Without the flags, the namespace has None for both."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    args = parser.parse_args(["some-submission.json"])
    assert args.cost_budget is None
    assert args.max_output_tokens is None


def test_argparse_help_text_mentions_pairing(capsys) -> None:
    """--help text documents that --cost-budget requires --max-output-tokens."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    assert "--cost-budget" in captured.out
    assert "--max-output-tokens" in captured.out
    assert "Requires --max-output-tokens" in captured.out


# -- Error message readability -------------------------------------------


def test_refusal_error_includes_estimated_and_budget(capsys) -> None:
    """The error message shows both the estimated cost and the budget."""
    from cli import cmd_triage
    args = _make_args(cost_budget=0.0001, max_output_tokens=8192)
    with patch(
        "agent.agent.TriageAgent",
        return_value=_make_mock_agent("anthropic:claude-opus-4-7"),
    ):
        cmd_triage.run(args)
    captured = capsys.readouterr()
    # Both dollar amounts should appear
    assert "$0.0001" in captured.err or "0.000100" in captured.err
    assert "$" in captured.err
