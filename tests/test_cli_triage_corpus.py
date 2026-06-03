"""Tests for the ``vrt triage --corpus`` flag (introduced in 1.0.2).

Covers:
- argument parsing for ``--corpus`` and ``--top-k``
- corpus-not-found returns exit 2
- ``--top-k`` out-of-range returns exit 2
- happy path: corpus loads, BM25 retrieves, chunks reach
  ``agent.triage(regulation_chunks=...)``
- empty-retrieval path: bundle loads but query is empty → exit 1
- the ``_build_corpus_query`` helper concatenates expected fields

The tests construct argparse Namespaces directly and call
``cmd_triage.run()``, mocking ``TriageAgent`` so no API keys or
real LLM calls are needed. The corpus side uses the real
``corpora/nist-ai-rmf/nist-ai-rmf.bundle.tgz`` bundle shipped in
the repo (loading + BM25 against a small corpus is fast and
deterministic; no need to mock).
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
NIST_BUNDLE = REPO_ROOT / "corpora" / "nist-ai-rmf" / "nist-ai-rmf.bundle.tgz"


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
    """Build an argparse Namespace matching cmd_triage's expectations."""
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
    """Build a mock TriageAgent that captures the triage() call args."""
    mock_agent = MagicMock()
    mock_agent._config.model = model_id
    # Return a minimal-valid TriageRecord-like object via model_dump
    mock_record = MagicMock()
    mock_record.model_dump.return_value = {
        "decision_id": "d-test",
        "decision_timestamp": "2026-06-03T00:00:00Z",
        "input_submission_id": "v-test",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.2+test",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "test rationale.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "y"}
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
        "output_schema_version": "1.3.0",
        "tenant_id": "__default__",
    }
    mock_agent.triage.return_value = mock_record
    return mock_agent


# -- argument parsing -----------------------------------------------------


def test_add_arguments_registers_corpus_and_top_k() -> None:
    """add_arguments registers both new flags with correct dest names."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    dests = {a.dest for a in parser._actions if a.option_strings}
    assert "corpus" in dests
    assert "top_k" in dests


def test_default_corpus_is_none_and_top_k_is_5() -> None:
    """When --corpus is omitted, args.corpus is None and top_k is 5."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    ns = parser.parse_args(["dummy.json"])
    assert ns.corpus is None
    assert ns.top_k == 5


def test_corpus_flag_parses_value() -> None:
    """--corpus nist-ai-rmf is captured as a string."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    ns = parser.parse_args(["dummy.json", "--corpus", "nist-ai-rmf"])
    assert ns.corpus == "nist-ai-rmf"


def test_top_k_flag_parses_value() -> None:
    """--top-k 10 is captured as an int."""
    from cli import cmd_triage
    parser = argparse.ArgumentParser()
    cmd_triage.add_arguments(parser)
    ns = parser.parse_args(["dummy.json", "--corpus", "nist-ai-rmf", "--top-k", "10"])
    assert ns.top_k == 10


# -- validation errors ---------------------------------------------------


def test_unknown_corpus_returns_2(capsys) -> None:
    """A corpus name with no bundle on disk exits 2 with a clear error."""
    from cli.cmd_triage import run
    args = _make_args(corpus="does-not-exist")
    exit_code = run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "corpus bundle not found" in captured.err
    assert "vrt corpus list" in captured.err


def test_top_k_below_range_returns_2(capsys) -> None:
    """--top-k 0 exits 2 with a clear error when --corpus is set."""
    from cli.cmd_triage import run
    args = _make_args(corpus="nist-ai-rmf", top_k=0)
    exit_code = run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "--top-k must be between" in captured.err


def test_top_k_above_range_returns_2(capsys) -> None:
    """--top-k 999 exits 2 with a clear error when --corpus is set."""
    from cli.cmd_triage import run
    args = _make_args(corpus="nist-ai-rmf", top_k=999)
    exit_code = run(args)
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "--top-k must be between" in captured.err


def test_top_k_out_of_range_without_corpus_is_ignored() -> None:
    """--top-k validation only fires when --corpus is set (default behavior preserved)."""
    from cli.cmd_triage import run
    # top_k=0 with no corpus should not gate; agent construction will
    # proceed (and fail on missing API key, returning 2 for a different
    # reason).
    with patch("agent.agent.TriageAgent") as mock_agent_cls:
        mock_agent_cls.return_value = _make_mock_agent()
        args = _make_args(corpus=None, top_k=0)
        exit_code = run(args)
    # Exit code should be 0 (agent path) since corpus is not set.
    assert exit_code == 0


# -- _build_corpus_query helper -----------------------------------------


def test_build_corpus_query_concatenates_feature_fields() -> None:
    """The query helper pulls AI feature name + description into the query."""
    from cli.cmd_triage import _build_corpus_query
    submission = {
        "ai_features_disclosed": [
            {"feature_name": "Test feature", "description": "Test description"},
        ],
    }
    q = _build_corpus_query(submission)
    assert "Test feature" in q
    assert "Test description" in q


def test_build_corpus_query_includes_pii_and_providers() -> None:
    """The query helper pulls PII notes, categories, and model providers."""
    from cli.cmd_triage import _build_corpus_query
    submission = {
        "pii_processing_claims": {
            "handling_notes": "PII handling notes here",
            "categories": ["customer_pii", "transaction_data"],
        },
        "model_providers": ["OpenAI", "Anthropic"],
    }
    q = _build_corpus_query(submission)
    assert "PII handling notes here" in q
    assert "customer_pii" in q
    assert "transaction_data" in q
    assert "OpenAI" in q
    assert "Anthropic" in q


def test_build_corpus_query_empty_submission_returns_empty() -> None:
    """An empty submission yields the empty string (caller surfaces this)."""
    from cli.cmd_triage import _build_corpus_query
    assert _build_corpus_query({}) == ""


def test_build_corpus_query_handles_missing_or_malformed_fields() -> None:
    """The helper does not crash on submissions with missing nested fields."""
    from cli.cmd_triage import _build_corpus_query
    # ai_features_disclosed entry is not a dict
    assert _build_corpus_query({"ai_features_disclosed": ["bare string"]}) == ""
    # pii_processing_claims is not a dict
    assert _build_corpus_query({"pii_processing_claims": "string"}) == ""
    # categories is not a list
    submission = {"pii_processing_claims": {"categories": "not-a-list"}}
    assert _build_corpus_query(submission) == ""
    # model_providers is not a list
    assert _build_corpus_query({"model_providers": "string"}) == ""


# -- happy path: corpus loads + BM25 retrieves + chunks reach agent ----


@pytest.mark.skipif(
    not NIST_BUNDLE.exists(),
    reason="NIST AI RMF corpus bundle not built; run scripts/build_corpus_bundles.py",
)
def test_corpus_loads_and_chunks_reach_agent(tmp_path: Path) -> None:
    """Happy path: --corpus nist-ai-rmf retrieves chunks and passes them to agent.triage."""
    from cli.cmd_triage import run
    # Write a submission with enough narrative to produce a non-empty query
    submission = {
        "vendor_id": "v-test",
        "vendor_name": "Test Vendor",
        "schema_version": "1.0.0",
        "ai_features_disclosed": [
            {
                "feature_name": "AI risk management",
                "description": "Tools for AI governance and risk management",
                "decision_role": "informational",
                "autonomy": "human_confirmed",
            },
        ],
        "pii_processing_claims": {
            "processes_pii": True,
            "categories": ["personal_data"],
            "handling_notes": "Personal data is processed",
        },
        "model_providers": ["internal"],
        "vendor_classification": "SaaS",
        "ai_usage_level": "informational",
        "ai_act_self_classification": "limited_risk",
        "jurisdiction": "US",
        "primary_contact": {"name": "Test", "email": "t@example.com"},
        "documentation_artifacts": [],
        "submission_timestamp": "2026-06-03T00:00:00Z",
    }
    sub_path = tmp_path / "test-submission.json"
    sub_path.write_text(json.dumps(submission), encoding="utf-8")

    with patch("agent.agent.TriageAgent") as mock_agent_cls:
        mock_agent_cls.return_value = _make_mock_agent()
        args = _make_args(submission=sub_path, corpus="nist-ai-rmf", top_k=3)
        exit_code = run(args)

    assert exit_code == 0
    # The mock_agent.triage call captured regulation_chunks
    mock_agent = mock_agent_cls.return_value
    assert mock_agent.triage.called
    call_kwargs = mock_agent.triage.call_args.kwargs
    chunks = call_kwargs.get("regulation_chunks")
    assert chunks is not None, "agent.triage should have been called with regulation_chunks"
    assert len(chunks) == 3, f"expected top-3 chunks, got {len(chunks)}"
    # Sanity: each chunk has a chunk_id
    for c in chunks:
        assert hasattr(c, "chunk_id")


@pytest.mark.skipif(
    not NIST_BUNDLE.exists(),
    reason="NIST AI RMF corpus bundle not built; run scripts/build_corpus_bundles.py",
)
def test_corpus_with_empty_submission_narrative_returns_1(
    capsys, tmp_path: Path,
) -> None:
    """A submission carrying no usable narrative produces an empty query → exit 1."""
    from cli.cmd_triage import run
    # Minimal submission with no narrative fields the query helper looks at
    submission = {
        "vendor_id": "v-test",
        "vendor_name": "Test",
        "schema_version": "1.0.0",
        # No ai_features_disclosed, no pii_processing_claims, no model_providers
        # No vendor_classification, no ai_usage_level
    }
    sub_path = tmp_path / "thin-submission.json"
    sub_path.write_text(json.dumps(submission), encoding="utf-8")

    # Patch the agent so we don't error out on missing API key before
    # reaching the corpus-retrieval step the test cares about.
    with patch("agent.agent.TriageAgent") as mock_agent_cls:
        mock_agent_cls.return_value = _make_mock_agent()
        args = _make_args(submission=sub_path, corpus="nist-ai-rmf")
        exit_code = run(args)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "returned no chunks" in captured.err


# -- no-corpus path: 1.0.1 behavior preserved ---------------------------


def test_no_corpus_passes_none_to_agent() -> None:
    """When --corpus is omitted, agent.triage receives regulation_chunks=None."""
    from cli.cmd_triage import run
    with patch("agent.agent.TriageAgent") as mock_agent_cls:
        mock_agent_cls.return_value = _make_mock_agent()
        args = _make_args(corpus=None)
        exit_code = run(args)
    assert exit_code == 0
    mock_agent = mock_agent_cls.return_value
    call_kwargs = mock_agent.triage.call_args.kwargs
    assert call_kwargs.get("regulation_chunks") is None


# -- _load_and_retrieve helper ------------------------------------------


@pytest.mark.skipif(
    not NIST_BUNDLE.exists(),
    reason="NIST AI RMF corpus bundle not built",
)
def test_load_and_retrieve_returns_expected_count() -> None:
    """_load_and_retrieve returns exactly top_k chunks for a non-empty query."""
    from cli.cmd_triage import _load_and_retrieve
    submission = {
        "ai_features_disclosed": [
            {"feature_name": "AI risk management",
             "description": "Tools for AI governance and risk management"},
        ],
        "vendor_classification": "SaaS",
        "ai_usage_level": "informational",
    }
    chunks = _load_and_retrieve("nist-ai-rmf", submission, top_k=4)
    assert len(chunks) == 4


def test_load_and_retrieve_empty_query_returns_empty_list() -> None:
    """An empty-narrative submission produces an empty list (not an error)."""
    from cli.cmd_triage import _load_and_retrieve
    # No bundle load needed if the bundle exists; just want to confirm
    # the early-return on empty query. Use a real corpus name so we get
    # past the path check.
    if not NIST_BUNDLE.exists():
        pytest.skip("NIST bundle not present")
    chunks = _load_and_retrieve("nist-ai-rmf", {}, top_k=5)
    assert chunks == []


# -- error paths in _load_and_retrieve + run() -------------------------


def test_corpus_load_error_in_run_returns_1(capsys, tmp_path: Path) -> None:
    """When _load_and_retrieve raises _CorpusLoadError, run() exits 1 with a clear message."""
    from cli.cmd_triage import run, _CorpusLoadError
    # The corpus name has to pass the bundle-exists path check, then
    # _load_and_retrieve has to raise. Patch the helper directly.
    with patch("agent.agent.TriageAgent") as mock_agent_cls:
        mock_agent_cls.return_value = _make_mock_agent()
        with patch(
            "cli.cmd_triage._load_and_retrieve",
            side_effect=_CorpusLoadError("simulated bundle corruption"),
        ):
            # The path check happens before _load_and_retrieve is called,
            # so we still need a valid bundle path. Use nist-ai-rmf.
            if not NIST_BUNDLE.exists():
                pytest.skip("NIST bundle not present")
            args = _make_args(corpus="nist-ai-rmf")
            exit_code = run(args)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "corpus loading failed" in captured.err
    assert "simulated bundle corruption" in captured.err


def test_load_and_retrieve_corrupt_bundle_raises_corpusloaderror() -> None:
    """When IndexBundle.load raises, _load_and_retrieve wraps it as _CorpusLoadError."""
    from cli.cmd_triage import _load_and_retrieve, _CorpusLoadError
    submission = {
        "ai_features_disclosed": [
            {"feature_name": "Test", "description": "Test description"},
        ],
    }
    with patch(
        "retrieval.bundle.IndexBundle.load",
        side_effect=RuntimeError("simulated bundle file corrupt"),
    ):
        with pytest.raises(_CorpusLoadError) as exc_info:
            _load_and_retrieve("nist-ai-rmf", submission, top_k=5)
    assert "could not load bundle" in str(exc_info.value)
    assert "simulated bundle file corrupt" in str(exc_info.value)


def test_load_and_retrieve_missing_retrieval_module_raises_corpusloaderror() -> None:
    """When the retrieval module imports fail, _load_and_retrieve wraps as _CorpusLoadError."""
    from cli.cmd_triage import _load_and_retrieve, _CorpusLoadError
    import sys as _sys
    submission = {
        "ai_features_disclosed": [
            {"feature_name": "Test", "description": "Test description"},
        ],
    }
    # Temporarily make `retrieval` unimportable by injecting a builtin
    # that raises on import. We restore on teardown via the with block.
    real_retrieval = _sys.modules.get("retrieval")
    _sys.modules["retrieval"] = None  # forces ImportError on `from retrieval import ...`
    try:
        with pytest.raises(_CorpusLoadError) as exc_info:
            _load_and_retrieve("nist-ai-rmf", submission, top_k=5)
        assert "required retrieval modules unavailable" in str(exc_info.value)
    finally:
        if real_retrieval is not None:
            _sys.modules["retrieval"] = real_retrieval
        else:
            del _sys.modules["retrieval"]
