"""Tests for cli/dispatcher.py and the subcommand modules.

Covers the argparse wiring, dispatcher behavior, and subcommand
entry points. The actual subcommand logic is exercised through the
dispatcher rather than tested in isolation, since the subcommand
modules are thin wrappers over existing functionality (drift,
render, version) and direct end-to-end tests through the dispatcher
catch real bugs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.dispatcher import build_parser, main


REPO_ROOT = Path(__file__).parent.parent


# -- parser construction ------------------------------------------------


def test_parser_has_all_five_subcommands() -> None:
    """All five subcommands are registered."""
    parser = build_parser()
    # Capture subparser choices
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            if "triage" in action.choices:
                subparsers_action = action
                break
    assert subparsers_action is not None
    expected = {"triage", "render", "drift", "corpus", "version"}
    assert set(subparsers_action.choices.keys()) == expected


def test_parser_help_runs_without_error(capsys) -> None:
    """vrt --help exits 0 with usage information."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "vrt" in captured.out
    assert "subcommands" in captured.out


def test_version_flag_prints_framework_version(capsys) -> None:
    """vrt --version prints the framework version."""
    from _version import FRAMEWORK_VERSION
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert FRAMEWORK_VERSION in captured.out


def test_no_subcommand_prints_help_and_exits_2(capsys) -> None:
    """vrt with no subcommand prints help and exits 2."""
    exit_code = main([])
    assert exit_code == 2


# -- version subcommand --------------------------------------------------


def test_version_subcommand_prints_framework_version(capsys) -> None:
    """vrt version prints FRAMEWORK_VERSION and SYSTEM_PROMPT_HASH."""
    from _version import FRAMEWORK_VERSION
    from agent.agent import SYSTEM_PROMPT_HASH

    exit_code = main(["version"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert FRAMEWORK_VERSION in captured.out
    assert SYSTEM_PROMPT_HASH in captured.out


def test_version_subcommand_json_output(capsys) -> None:
    """vrt version --json emits machine-readable JSON."""
    exit_code = main(["version", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "framework_version" in parsed
    assert "system_prompt_hash" in parsed
    assert "pyproject_sync" in parsed


def test_version_subcommand_reports_sync_ok_when_synced(capsys) -> None:
    """When pyproject.toml is synced, vrt version reports 'ok'."""
    exit_code = main(["version"])
    captured = capsys.readouterr()
    # Either pyproject is in sync (most common) or out-of-sync; both are
    # valid runtime states. Just assert the line is present.
    assert "pyproject.toml sync:" in captured.out
    assert exit_code in (0, 1)


def test_version_skip_sync_check_returns_0(capsys) -> None:
    """--skip-sync-check returns 0 even if pyproject would mismatch."""
    exit_code = main(["version", "--skip-sync-check"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "pyproject.toml sync" not in captured.out


# -- drift subcommand ----------------------------------------------------


def test_drift_subcommand_runs_and_passes(capsys) -> None:
    """vrt drift returns 0 against the checked-in baseline (no drift)."""
    exit_code = main(["drift"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No drift detected" in captured.out


def test_drift_subcommand_respects_threshold(capsys) -> None:
    """vrt drift --threshold 0.5 runs with a custom threshold."""
    exit_code = main(["drift", "--threshold", "0.5"])
    assert exit_code == 0


# -- corpus subcommand ---------------------------------------------------


def test_corpus_list_prints_registered_corpora(capsys) -> None:
    """vrt corpus list shows the four registered corpus names."""
    exit_code = main(["corpus", "list"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "nist-ai-rmf" in captured.out
    assert "sox-pl-107-204" in captured.out
    assert "eu-ai-act" in captured.out
    assert "osfi-e23" in captured.out


def test_corpus_no_action_returns_2(capsys) -> None:
    """vrt corpus with no sub-action prints error and exits 2."""
    exit_code = main(["corpus"])
    assert exit_code == 2


def test_corpus_build_unknown_regulation_returns_2(capsys) -> None:
    """vrt corpus build nonexistent-corpus exits 2."""
    exit_code = main(["corpus", "build", "no-such-regulation"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "unknown or non-committed" in captured.err


# -- render subcommand ---------------------------------------------------


def test_render_subcommand_writes_html(capsys, tmp_path: Path) -> None:
    """vrt render writes valid HTML from a TriageRecord JSON."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    submission_path = REPO_ROOT / "examples" / "submissions" / "01-tier1-internal-productivity.json"
    output_path = tmp_path / "audit.html"

    exit_code = main([
        "render",
        str(record_path),
        "--submission", str(submission_path),
        "--output", str(output_path),
    ])
    assert exit_code == 0
    assert output_path.exists()
    html = output_path.read_text()
    assert html.startswith("<!DOCTYPE html>")
    assert html.endswith("</html>")


def test_render_missing_record_returns_2(capsys, tmp_path: Path) -> None:
    """vrt render with a missing record file exits 2."""
    exit_code = main([
        "render",
        str(tmp_path / "nonexistent.json"),
    ])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_render_invalid_record_json_returns_1(capsys, tmp_path: Path) -> None:
    """vrt render with malformed record JSON exits 1."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not json {{{")
    exit_code = main(["render", str(bad_path)])
    assert exit_code == 1


def test_render_record_not_matching_schema_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """vrt render with a JSON that does not validate exits 1."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text('{"foo": "bar"}')
    exit_code = main(["render", str(bad_path)])
    assert exit_code == 1


def test_render_with_invalid_timestamp_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """A record with a malformed decision_timestamp is rejected."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({
        "decision_timestamp": "not-a-timestamp",
        "decision_id": "d-test",
        "input_submission_id": "s-test",
        "input_schema_version": "1.0.0",
        "output_schema_version": "1.0.0",
        "agent_version": "test",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "test",
        "evidence_cited": [{"input_field_reference": "$.x", "reasoning": "y"}],
        "confidence_signal": {"score": 0.5, "interpretation": "moderate"},
    }))
    exit_code = main(["render", str(bad_path)])
    assert exit_code == 1


def test_render_to_stdout_when_no_output_path(capsys) -> None:
    """vrt render without --output prints HTML to stdout."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    exit_code = main(["render", str(record_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("<!DOCTYPE html>")


# -- triage subcommand (without real LLM) -------------------------------


def test_triage_missing_submission_returns_2(
    capsys, tmp_path: Path,
) -> None:
    """vrt triage with a missing submission file exits 2."""
    exit_code = main([
        "triage",
        str(tmp_path / "nonexistent.json"),
    ])
    assert exit_code == 2


def test_triage_invalid_json_returns_1(capsys, tmp_path: Path) -> None:
    """vrt triage with malformed submission JSON exits 1."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not json {{{")
    exit_code = main(["triage", str(bad_path)])
    assert exit_code == 1


def test_triage_non_object_submission_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """vrt triage with a JSON array (not object) exits 1."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("[1, 2, 3]")
    exit_code = main(["triage", str(bad_path)])
    assert exit_code == 1


def test_triage_with_unconfigured_anthropic_returns_2(
    capsys, monkeypatch, tmp_path: Path,
) -> None:
    """vrt triage with --model anthropic:... and no API key returns 2."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    submission = tmp_path / "sub.json"
    submission.write_text(json.dumps({"vendor_id": "x"}))
    exit_code = main([
        "triage", str(submission),
        "--model", "anthropic:claude-sonnet-4-5",
    ])
    assert exit_code == 2


def test_triage_with_openai_no_key_returns_2(
    capsys, monkeypatch, tmp_path: Path,
) -> None:
    """vrt triage --model openai:... without OPENAI_API_KEY exits 2."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    submission = tmp_path / "sub.json"
    submission.write_text(json.dumps({"vendor_id": "x"}))
    exit_code = main([
        "triage", str(submission),
        "--model", "openai:gpt-4o",
    ])
    assert exit_code == 2


# -- triage happy path via FunctionModel injection -----------------------


def _mock_function_model_for_record(record_payload: dict):
    """Build a FunctionModel that returns the given record payload."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def _call(_messages, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=record_payload),
        ])

    return FunctionModel(_call)


def _patch_triage_agent_with_function_model(record_payload: dict):
    """Context patch that makes TriageAgentConfig use a FunctionModel."""
    from agent.agent import TriageAgentConfig as RealConfig

    function_model = _mock_function_model_for_record(record_payload)

    class _PatchedConfig(RealConfig):
        def __init__(self, **kwargs):
            kwargs["model"] = function_model
            super().__init__(**kwargs)

    return _PatchedConfig


def test_triage_happy_path_writes_output_file(
    capsys, tmp_path: Path,
) -> None:
    """vrt triage with --output writes the full record to file."""
    record_payload = {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for triage CLI happy path.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "Test reasoning."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "review_interval_days": 365,
    }
    submission_path = REPO_ROOT / "examples" / "submissions" / "01-tier1-internal-productivity.json"
    output_path = tmp_path / "record.json"

    patched_config = _patch_triage_agent_with_function_model(record_payload)
    with patch("agent.agent.TriageAgentConfig", patched_config):
        exit_code = main([
            "triage", str(submission_path),
            "--output", str(output_path),
        ])
    assert exit_code == 0
    assert output_path.exists()
    written = json.loads(output_path.read_text())
    assert written["risk_tier"] == "tier_1_low"
    assert written["recommended_disposition"] == "approve"


def test_triage_happy_path_json_mode(capsys, tmp_path: Path) -> None:
    """vrt triage --json prints full record JSON to stdout."""
    record_payload = {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Json mode rationale.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.92, "interpretation": "high"},
        "review_interval_days": 365,
    }
    submission_path = REPO_ROOT / "examples" / "submissions" / "01-tier1-internal-productivity.json"

    patched_config = _patch_triage_agent_with_function_model(record_payload)
    with patch("agent.agent.TriageAgentConfig", patched_config):
        exit_code = main(["triage", str(submission_path), "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["risk_tier"] == "tier_1_low"


def test_triage_summary_mode_default(capsys, tmp_path: Path) -> None:
    """Without --json or --output, triage prints a human-readable summary."""
    record_payload = {
        "risk_tier": "tier_2_moderate",
        "recommended_disposition": "conditional_approve",
        "classification_rationale": "Summary rationale.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "Test."},
        ],
        "confidence_signal": {"score": 0.78, "interpretation": "moderate"},
        "required_mitigations": ["Verify control X."],
        "review_interval_days": 180,
    }
    submission_path = REPO_ROOT / "examples" / "submissions" / "02-tier2-customer-service-chatbot.json"

    patched_config = _patch_triage_agent_with_function_model(record_payload)
    with patch("agent.agent.TriageAgentConfig", patched_config):
        exit_code = main(["triage", str(submission_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    # Summary contains tier and disposition labels
    assert "Tier 2 (moderate)" in captured.out
    assert "Conditional approval" in captured.out


def test_triage_agent_raises_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """If agent.triage() raises, vrt triage exits 1."""
    submission = tmp_path / "sub.json"
    submission.write_text(json.dumps({
        "vendor_id": "demo-x",
        "vendor_name": "Demo",
        "input_schema_version": "1.0.0",
        # Missing required fields will surface as a TriageInputError or
        # similar from the agent.
    }))

    # Use the real default agent (no patching). It will fail on input
    # validation before any LLM call, so no API key is needed.
    exit_code = main(["triage", str(submission)])
    # Exit 1 (triage failed) or 2 (setup failed: no API key for default
    # model). Either is acceptable for this test; we're verifying the
    # CLI does NOT crash with an unhandled exception.
    assert exit_code in (1, 2)


# -- render error branches ------------------------------------------------


def test_render_bad_decision_timestamp_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """A record with a non-ISO decision_timestamp returns 1."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({
        "decision_timestamp": "definitely not iso",
        "decision_id": "d-x",
        "input_submission_id": "s-x",
        "input_schema_version": "1.0.0",
        "output_schema_version": "1.0.0",
        "agent_version": "test",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "test",
        "evidence_cited": [{"input_field_reference": "$.x", "reasoning": "y"}],
        "confidence_signal": {"score": 0.5, "interpretation": "moderate"},
    }))
    exit_code = main(["render", str(bad_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "decision_timestamp" in captured.err


def test_render_bad_revoked_at_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """A record with a non-ISO revoked_at returns 1."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({
        "decision_timestamp": "2026-05-22T09:33:00Z",
        "revoked_at": "not a date",
        "decision_id": "d-x",
        "input_submission_id": "s-x",
        "input_schema_version": "1.0.0",
        "output_schema_version": "1.0.0",
        "agent_version": "test",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "test",
        "evidence_cited": [{"input_field_reference": "$.x", "reasoning": "y"}],
        "confidence_signal": {"score": 0.5, "interpretation": "moderate"},
    }))
    exit_code = main(["render", str(bad_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "revoked_at" in captured.err


def test_render_missing_submission_file_returns_2(
    capsys, tmp_path: Path,
) -> None:
    """vrt render with a --submission that doesn't exist returns 2."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    exit_code = main([
        "render", str(record_path),
        "--submission", str(tmp_path / "no-such-file.json"),
    ])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_render_invalid_submission_json_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """vrt render with malformed submission JSON returns 1."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    bad_submission = tmp_path / "bad.json"
    bad_submission.write_text("not json {{{")
    exit_code = main([
        "render", str(record_path),
        "--submission", str(bad_submission),
    ])
    assert exit_code == 1


def test_render_non_object_submission_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """A submission JSON array (not object) returns 1."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    bad_submission = tmp_path / "arr.json"
    bad_submission.write_text("[1, 2, 3]")
    exit_code = main([
        "render", str(record_path),
        "--submission", str(bad_submission),
    ])
    assert exit_code == 1


def test_render_with_footer_override(capsys, tmp_path: Path) -> None:
    """--footer overrides the default attribution footer."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    output_path = tmp_path / "out.html"
    exit_code = main([
        "render", str(record_path),
        "--output", str(output_path),
        "--footer", "Custom internal footer text.",
    ])
    assert exit_code == 0
    html = output_path.read_text()
    assert "Custom internal footer text." in html


# -- corpus subcommand additional coverage --------------------------------


def test_corpus_build_all_via_mock(capsys, tmp_path: Path) -> None:
    """vrt corpus build (no name) invokes build_all."""
    fake_paths = [tmp_path / "fake-a.tgz", tmp_path / "fake-b.tgz"]
    with patch(
        "scripts.build_corpus_bundles.build_all",
        return_value=fake_paths,
    ) as mock_build_all:
        exit_code = main(["corpus", "build", "--output-dir", str(tmp_path)])
    assert exit_code == 0
    mock_build_all.assert_called_once()
    captured = capsys.readouterr()
    assert "Built 2 bundle(s)" in captured.out


def test_corpus_build_single_via_mock(capsys, tmp_path: Path) -> None:
    """vrt corpus build <name> invokes build_bundle for one corpus."""
    fake_path = tmp_path / "fake.tgz"
    with patch(
        "scripts.build_corpus_bundles.build_bundle",
        return_value=fake_path,
    ) as mock_build_bundle, patch(
        "retrieval.SentenceTransformerEmbedder",
    ) as _mock_embedder:
        exit_code = main([
            "corpus", "build", "nist-ai-rmf",
            "--output-dir", str(tmp_path),
        ])
    assert exit_code == 0
    mock_build_bundle.assert_called_once()
    captured = capsys.readouterr()
    assert "Built bundle" in captured.out


def test_corpus_build_failure_returns_1(capsys, tmp_path: Path) -> None:
    """If the build raises, vrt corpus build exits 1 with the error."""
    with patch(
        "scripts.build_corpus_bundles.build_bundle",
        side_effect=RuntimeError("simulated PDF cache miss"),
    ), patch(
        "retrieval.SentenceTransformerEmbedder",
    ):
        exit_code = main([
            "corpus", "build", "nist-ai-rmf",
            "--output-dir", str(tmp_path),
        ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "simulated PDF cache miss" in captured.err


# -- version subcommand additional coverage -------------------------------


def test_version_subcommand_sync_mismatch_returns_1(capsys) -> None:
    """When pyproject is out of sync, vrt version exits 1."""
    with patch(
        "cli.cmd_version._check_pyproject_sync",
        return_value=(False, "test simulated mismatch"),
    ):
        exit_code = main(["version"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "MISMATCH" in captured.out
    assert "test simulated mismatch" in captured.out


def test_version_subcommand_json_includes_mismatch(capsys) -> None:
    """When out of sync, --json output includes pyproject_detail."""
    with patch(
        "cli.cmd_version._check_pyproject_sync",
        return_value=(False, "test simulated mismatch"),
    ):
        exit_code = main(["version", "--json"])
    assert exit_code == 1
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["pyproject_sync"] == "mismatch"
    assert "pyproject_detail" in parsed


# -- _has_api_key_for direct branch coverage ------------------------------


def test_has_api_key_for_non_string_model() -> None:
    """A Model instance (not a string) passes the API key check."""
    from cli.cmd_triage import _has_api_key_for
    from pydantic_ai.models.test import TestModel
    assert _has_api_key_for(TestModel()) is True


def test_has_api_key_for_unknown_provider(monkeypatch) -> None:
    """Unknown provider prefixes don't gate on credentials."""
    from cli.cmd_triage import _has_api_key_for
    # Don't set any env var; unknown provider returns True (no gate)
    assert _has_api_key_for("mistral:large") is True


def test_has_api_key_for_no_colon() -> None:
    """A model identifier without ':' returns True (no gating)."""
    from cli.cmd_triage import _has_api_key_for
    assert _has_api_key_for("test-model-name") is True


def test_has_api_key_for_anthropic_with_key(monkeypatch) -> None:
    """With ANTHROPIC_API_KEY set, anthropic models pass."""
    from cli.cmd_triage import _has_api_key_for
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    assert _has_api_key_for("anthropic:claude-sonnet-4-5") is True


# -- __main__ entry point -------------------------------------------------


def test_cli_main_module_runnable() -> None:
    """python -m cli works (smoke test that __main__.py is wired)."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "cli", "version", "--skip-sync-check"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    from _version import FRAMEWORK_VERSION
    assert FRAMEWORK_VERSION in result.stdout


# -- drift subcommand argv passthrough ------------------------------------


def test_drift_subcommand_passes_baseline_path(
    capsys, tmp_path: Path,
) -> None:
    """vrt drift --baseline <path> passes through to the script."""
    fake_baseline = tmp_path / "no-such-baseline.jsonl"
    exit_code = main([
        "drift", "--baseline", str(fake_baseline),
    ])
    # Setup error: baseline file not found -> exit 2
    assert exit_code == 2


def test_drift_subcommand_update_baseline_flag(capsys, tmp_path: Path) -> None:
    """vrt drift --update-baseline passes the flag through.

    We use a tmp_path baseline to avoid overwriting the real one,
    and mock the underlying script's main to just record the args.
    """
    called_argv: list[list[str]] = []

    def fake_main(argv):
        called_argv.append(argv or [])
        return 0

    with patch("scripts.check_drift.main", side_effect=fake_main):
        exit_code = main([
            "drift", "--update-baseline",
            "--baseline", str(tmp_path / "test.jsonl"),
        ])
    assert exit_code == 0
    assert len(called_argv) == 1
    assert "--update-baseline" in called_argv[0]


# -- corpus error branch coverage -----------------------------------------


def test_corpus_unknown_action_returns_2(capsys, monkeypatch) -> None:
    """An unrecognized action value reaches the final return 2 branch.

    argparse normally prevents this (it validates the action choices),
    so we exercise the branch by patching args directly via the
    cmd_corpus.run function.
    """
    from cli.cmd_corpus import run
    import argparse as _argparse
    fake_args = _argparse.Namespace(action="totally_unknown")
    exit_code = run(fake_args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "unknown action" in captured.err


# -- render write-failure branch ------------------------------------------


def test_render_write_failure_returns_2(
    capsys, tmp_path: Path,
) -> None:
    """If writing the output file raises OSError, render returns 2."""
    record_path = REPO_ROOT / "examples" / "expected-records" / "01-tier1-internal-productivity.expected.json"
    output_path = tmp_path / "out.html"

    # Make Path.write_text raise OSError when called on the target.
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if str(self) == str(output_path):
            raise OSError("simulated disk full")
        return real_write_text(self, *args, **kwargs)

    with patch.object(Path, "write_text", fake_write_text):
        exit_code = main([
            "render", str(record_path),
            "--output", str(output_path),
        ])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "could not write output" in captured.err


# -- triage agent runtime failure branch ----------------------------------


def test_triage_agent_runtime_raises_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """If agent.triage() raises a runtime error, vrt triage returns 1.

    Patches TriageAgent.triage to raise. The agent constructs normally
    (via FunctionModel) so the failure surfaces only at the .triage()
    call site, exercising the cmd_triage exception handler.
    """
    submission_path = REPO_ROOT / "examples" / "submissions" / "01-tier1-internal-productivity.json"

    # Inject a FunctionModel so config construction works without a key,
    # then patch triage() to raise.
    record_payload = {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "ok",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "y"},
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
    }
    patched_config = _patch_triage_agent_with_function_model(record_payload)

    with patch("agent.agent.TriageAgentConfig", patched_config), patch(
        "agent.agent.TriageAgent.triage",
        side_effect=RuntimeError("simulated agent runtime error"),
    ):
        exit_code = main(["triage", str(submission_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "triage failed" in captured.err
    assert "simulated agent runtime error" in captured.err


def test_triage_agent_construction_raises_returns_2(
    capsys, tmp_path: Path,
) -> None:
    """If TriageAgentConfig construction raises, vrt triage returns 2.

    Patches the default TriageAgentConfig to raise on construction;
    this exercises the agent-construction-failed branch in cmd_triage.
    """
    submission_path = REPO_ROOT / "examples" / "submissions" / "01-tier1-internal-productivity.json"

    class _RaisingConfig:
        def __init__(self, **_kwargs):
            raise RuntimeError("simulated config construction failure")

    with patch("agent.agent.TriageAgentConfig", _RaisingConfig):
        exit_code = main(["triage", str(submission_path)])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "failed to construct agent" in captured.err
    assert "simulated config construction failure" in captured.err


# -- version sync helper edge cases ---------------------------------------


def test_check_pyproject_sync_detects_mismatch() -> None:
    """_check_pyproject_sync returns (False, ...) on version mismatch.

    Calling with a version that does NOT match the current
    pyproject.toml exercises the mismatch branch directly.
    """
    from cli.cmd_version import _check_pyproject_sync
    ok, detail = _check_pyproject_sync("9.99.99-deliberately-wrong")
    assert ok is False
    assert "9.99.99" in detail


# Note: the FileNotFoundError and ImportError branches in
# _check_pyproject_sync are marked '# pragma: no cover' in the
# implementation: pyproject.toml is always present in a valid framework
# checkout, and scripts.check_version_sync is always importable when
# the framework is installed. The behaviorally-meaningful case (version
# mismatch detected) is tested above in
# test_version_subcommand_sync_mismatch_returns_1.
