"""``vrt triage`` subcommand: run the agent against a submission JSON.

Usage::

    # Print summary to stdout, write full record to file
    vrt triage submission.json --output record.json

    # Print summary only (no file output)
    vrt triage submission.json

    # Print full JSON to stdout (machine-readable, suitable for piping)
    vrt triage submission.json --json

    # Override the model
    vrt triage submission.json --model openai:gpt-4o

    # Refuse the call if estimated upper-bound cost exceeds budget.
    # --cost-budget requires --max-output-tokens to be specified.
    vrt triage submission.json --cost-budget 0.50 --max-output-tokens 8192

    # Corpus-grounded triage: load a regulation corpus, retrieve the
    # top-K BM25 chunks for a query derived from the submission, and
    # pass them to the agent as regulation_chunks for citation. The
    # corpus name resolves to the bundle at
    # corpora/<corpus>/<corpus>.bundle.tgz. Run 'vrt corpus list' to
    # see available corpora.
    vrt triage submission.json --corpus nist-ai-rmf
    vrt triage submission.json --corpus eu-ai-act --top-k 8

The submission JSON file must conform to the input contract
(``schemas/input-contract-1.0.0.schema.json``). The output, when
saved, conforms to the output contract.

Exit codes:

- ``0``: triage completed successfully
- ``1``: input validation failed (submission JSON malformed or
  missing required fields), or the agent raised an error, or the
  cost budget gate refused the call, or corpus retrieval returned
  no chunks
- ``2``: setup error (file not found, model not configured, missing
  API key with no clear remediation, --cost-budget without
  --max-output-tokens, --corpus name not found on disk, --top-k
  out of range)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


__all__ = ["add_arguments", "run"]


# Where corpus bundles live by default (relative to the framework repo root).
# Bundles are written to corpora/<name>/<name>.bundle.tgz by
# scripts/build_corpus_bundles.py; the same layout is read here.
_CORPORA_ROOT = Path(__file__).parent.parent / "corpora"

# Maximum reasonable top-K. The triage prompt is bounded by the model's
# context window; pushing K very high adds tokens without adding signal.
# 32 is a soft cap; users can override --top-k up to this value.
_TOP_K_MAX = 32


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``triage`` arguments."""
    parser.add_argument(
        "submission",
        type=Path,
        help="Path to the submission JSON file.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help=(
            "Optional path to write the full TriageRecord JSON. "
            "When omitted, only a human-readable summary is printed."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_only",
        help=(
            "Print the full TriageRecord JSON to stdout instead of "
            "the human-readable summary. Suitable for piping to jq."
        ),
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "PydanticAI model identifier. Defaults to the framework's "
            "DEFAULT_MODEL. Example: 'anthropic:claude-sonnet-4-5', "
            "'openai:gpt-4o'."
        ),
    )
    parser.add_argument(
        "--cost-budget",
        type=float,
        default=None,
        dest="cost_budget",
        metavar="DOLLARS",
        help=(
            "Maximum allowed cost for this LLM call in USD. Refuses "
            "the call if the upper-bound cost estimate (input tokens "
            "+ max output tokens at standard rates) exceeds the "
            "budget. Requires --max-output-tokens to be specified. "
            "Estimate uses a character-based heuristic (~4 chars per "
            "token) for input tokens and the published price table "
            "for dollar conversion."
        ),
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        dest="max_output_tokens",
        metavar="N",
        help=(
            "Maximum output tokens the LLM call can produce. Required "
            "when --cost-budget is set; ignored otherwise. The exact "
            "value depends on the configured PydanticAI model's "
            "max_tokens setting (typically 4096 or 8192)."
        ),
    )
    parser.add_argument(
        "--corpus",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Regulation corpus to load for retrieval grounding. The "
            "name resolves to corpora/<NAME>/<NAME>.bundle.tgz in the "
            "framework repo. Run 'vrt corpus list' to see available "
            "corpora. When omitted, triage runs without regulation "
            "context (the agent reasons from the submission prose "
            "alone)."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        dest="top_k",
        metavar="N",
        help=(
            "Number of regulation chunks to retrieve via BM25 when "
            "--corpus is set. Ignored otherwise. Default: 5. Range: "
            f"1 to {_TOP_K_MAX}."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Run a triage decision and emit results."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from cli.output import print_summary

    if not args.submission.exists():
        print(
            f"ERROR: submission file not found: {args.submission}",
            file=sys.stderr,
        )
        return 2

    try:
        submission = json.loads(args.submission.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: submission is not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 1

    if not isinstance(submission, dict):
        print(
            f"ERROR: submission must be a JSON object, got "
            f"{type(submission).__name__}",
            file=sys.stderr,
        )
        return 1

    # Validate --corpus / --top-k pairing before doing anything expensive.
    # --corpus is optional; --top-k has a default but must be in range
    # when --corpus is set. Both checks are cheap and surface clean
    # error messages.
    if args.corpus is not None:
        if args.top_k < 1 or args.top_k > _TOP_K_MAX:
            print(
                f"ERROR: --top-k must be between 1 and {_TOP_K_MAX}; "
                f"got {args.top_k}.",
                file=sys.stderr,
            )
            return 2
        bundle_path = _CORPORA_ROOT / args.corpus / f"{args.corpus}.bundle.tgz"
        if not bundle_path.exists():
            print(
                f"ERROR: corpus bundle not found: {bundle_path}\n"
                f"  Run 'vrt corpus list' to see available corpora, "
                f"or build a new one with 'vrt corpus build {args.corpus}'.",
                file=sys.stderr,
            )
            return 2

    # Validate budget-gate flag pairing before doing anything expensive.
    # The check itself runs after agent construction (so we have the
    # model resolved), but the flag-pairing errors should surface
    # immediately.
    if args.cost_budget is not None:
        if args.max_output_tokens is None:
            print(
                "ERROR: --cost-budget requires --max-output-tokens to "
                "be specified. Provide both flags or remove "
                "--cost-budget. The budget gate needs the max output "
                "token count to compute an upper bound on the LLM "
                "call's cost.",
                file=sys.stderr,
            )
            return 2
        if args.cost_budget < 0:
            print(
                f"ERROR: --cost-budget must be non-negative; "
                f"got {args.cost_budget}",
                file=sys.stderr,
            )
            return 2
        if args.max_output_tokens < 1:
            print(
                f"ERROR: --max-output-tokens must be at least 1; "
                f"got {args.max_output_tokens}",
                file=sys.stderr,
            )
            return 2

    # Build the agent. If the user supplied a real-LLM model and there's
    # no API key, surface a clear error rather than a stack trace.
    config_kwargs: dict[str, Any] = {}
    if args.model is not None:
        config_kwargs["model"] = args.model
        if not _has_api_key_for(args.model):
            provider = args.model.split(":", 1)[0] if ":" in args.model else args.model
            print(
                f"ERROR: no API key configured for provider '{provider}'. "
                f"Set the appropriate environment variable "
                f"(e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY) and retry.",
                file=sys.stderr,
            )
            return 2

    try:
        agent = TriageAgent(TriageAgentConfig(**config_kwargs))
    except Exception as exc:
        print(
            f"ERROR: failed to construct agent: {exc}",
            file=sys.stderr,
        )
        return 2

    # Budget gate: now that we have the resolved model_id, estimate the
    # LLM call's upper-bound cost and refuse to proceed if it exceeds
    # the budget. The estimate uses a character-based heuristic for
    # input tokens and the user-supplied max_output_tokens; the gate
    # is conservative by design (overestimates rather than
    # underestimates).
    if args.cost_budget is not None:
        from agent.agent import _format_user_prompt
        from pricing import check_budget
        prompt_text = _format_user_prompt(submission, None, None)
        model_id = str(agent._config.model)
        result = check_budget(
            model_id=model_id,
            prompt=prompt_text,
            max_output_tokens=args.max_output_tokens,
            budget_usd=args.cost_budget,
        )
        if not result.allowed:
            print(
                f"ERROR: cost budget check failed.\n  {result.reason}",
                file=sys.stderr,
            )
            return 1

    # Optional corpus-grounded retrieval. When --corpus is set, load the
    # IndexBundle, derive a BM25 query from the submission, retrieve the
    # top-K chunks, and pass them to agent.triage as regulation_chunks.
    # On retrieval producing zero chunks we exit 1: the user asked for
    # corpus grounding, the corpus loaded, and yet the query found
    # nothing — that's a data condition worth surfacing rather than
    # silently degrading to JSON-only triage.
    regulation_chunks = None
    if args.corpus is not None:
        try:
            regulation_chunks = _load_and_retrieve(
                corpus_name=args.corpus,
                submission=submission,
                top_k=args.top_k,
            )
        except _CorpusLoadError as exc:
            print(f"ERROR: corpus loading failed: {exc}", file=sys.stderr)
            return 1
        if not regulation_chunks:
            print(
                f"ERROR: corpus '{args.corpus}' returned no chunks for "
                f"the BM25 query derived from this submission. The "
                f"submission may not contain enough narrative text to "
                f"build a useful query.",
                file=sys.stderr,
            )
            return 1

    start = time.time()
    try:
        record = agent.triage(submission, regulation_chunks=regulation_chunks)
    except Exception as exc:
        # The agent surfaces TriageInputError, ValidationError, or
        # PydanticAI runtime errors. We catch broadly and emit a
        # clear, single-line failure rather than a stack trace.
        print(f"ERROR: triage failed: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - start

    record_dict = record.model_dump(mode="json", exclude_none=True)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(record_dict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json_only:
        print(json.dumps(record_dict, indent=2, sort_keys=True))
    else:
        print_summary(record_dict, elapsed_seconds=elapsed)
        if args.output is not None:
            print(
                f"  Full record written to: {args.output}",
                file=sys.stdout,
            )
            print()

    return 0


class _CorpusLoadError(Exception):
    """Raised when corpus bundle loading or retrieval setup fails.

    Distinct from "the query returned no chunks": this exception is
    for tooling failures (bundle file is corrupt, dependencies
    missing, etc.), not data conditions. The caller surfaces this
    as a triage-failed error rather than an empty-retrieval error.
    """


def _build_corpus_query(submission: dict) -> str:
    """Derive a BM25 retrieval query from a submission's narrative fields.

    Concatenates the AI feature description, PII handling notes,
    PII categories, model providers, vendor classification, and AI
    usage level into a single space-separated string. BM25's
    bag-of-words scoring uses every term, so the order doesn't
    matter; the goal is to maximize the surface area of submission
    vocabulary that can match corpus chunks.

    Returns the empty string if the submission carries no usable
    narrative (in which case retrieval will return no chunks and
    the caller surfaces the empty-retrieval error).
    """
    parts: list[str] = []
    for feat in submission.get("ai_features_disclosed", []):
        if not isinstance(feat, dict):
            continue
        parts.append(str(feat.get("feature_name", "")))
        parts.append(str(feat.get("description", "")))
    pii = submission.get("pii_processing_claims", {})
    if isinstance(pii, dict):
        parts.append(str(pii.get("handling_notes", "")))
        cats = pii.get("categories", [])
        if isinstance(cats, list):
            parts.extend(str(c) for c in cats)
    providers = submission.get("model_providers", [])
    if isinstance(providers, list):
        parts.extend(str(p) for p in providers)
    parts.append(str(submission.get("vendor_classification", "")))
    parts.append(str(submission.get("ai_usage_level", "")))
    return " ".join(p for p in parts if p)


def _load_and_retrieve(
    corpus_name: str,
    submission: dict,
    top_k: int,
) -> list[Any]:
    """Load a corpus bundle and retrieve top-K chunks via BM25.

    Returns the list of chunks ready to pass to
    ``agent.triage(regulation_chunks=...)``. Raises
    ``_CorpusLoadError`` on tooling failures. Returns an empty list
    if BM25 finds nothing for the derived query (caller surfaces
    that as a separate error).
    """
    bundle_path = _CORPORA_ROOT / corpus_name / f"{corpus_name}.bundle.tgz"
    try:
        from retrieval import BM25Index, Retriever
        from retrieval.bundle import IndexBundle
    except ImportError as exc:
        raise _CorpusLoadError(
            f"required retrieval modules unavailable: {exc}"
        ) from exc
    try:
        bundle = IndexBundle.load(bundle_path)
    except Exception as exc:
        raise _CorpusLoadError(
            f"could not load bundle {bundle_path}: {exc}"
        ) from exc

    query = _build_corpus_query(submission)
    if not query.strip():
        # Empty submission narrative — BM25 has nothing to match
        # against. Return empty list so the caller surfaces the
        # empty-retrieval error message.
        return []
    retriever = Retriever(BM25Index(bundle.chunks))
    return retriever.query(query, top_k=top_k)


def _has_api_key_for(model: str) -> bool:
    """Check whether the relevant API key is set for a provider-prefixed model.

    Best-effort: handles the common provider prefixes ('anthropic:',
    'openai:', 'google-gla:'). For non-string model identifiers (a
    Model instance), assume the caller configured credentials.
    """
    if not isinstance(model, str) or ":" not in model:
        return True
    provider = model.split(":", 1)[0]
    env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google-gla": "GEMINI_API_KEY",
        "google-vertex": "GOOGLE_APPLICATION_CREDENTIALS",
    }
    env_var = env_var_map.get(provider)
    if env_var is None:
        return True  # Unknown provider; don't gate on credentials
    return bool(os.environ.get(env_var))
