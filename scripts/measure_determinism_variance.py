"""Measure per-(provider, model) determinism variance empirically.

The determinism contract introduced in 1.0.5 attests that records are
reproducible WITHIN AN EMPIRICALLY-MEASURED VARIANCE BAND specific to
the (provider, model) pair. The band is not zero: even with
temperature=0, providers exhibit residual variation (model-internal
sampling, batch-routing nondeterminism, token-boundary jitter).

This script runs the agent N times against a fixed submission with
identical configuration, then reports the observed variation by field.
The output populates the variance table in
``docs/determinism-attestation.md``.

Usage::

    python scripts/measure_determinism_variance.py \
        --model anthropic:claude-sonnet-4-5 \
        --runs 10 \
        --submission examples/submissions/02-tier2-customer-service-chatbot.json \
        --output /tmp/variance.json

Outputs a JSON report:

    {
      "model": "anthropic:claude-sonnet-4-5",
      "runs": 10,
      "submission": "examples/submissions/02-...",
      "fields": {
        "risk_tier": {"unique_values": ["tier_2_moderate"], "n": 10},
        "recommended_disposition": {"unique_values": [...], "n": ...},
        "confidence_signal.score": {
          "min": 0.78, "max": 0.82, "mean": 0.80, "stdev": 0.012, "n": 10
        },
        ...
      },
      "tier_split_max_ratio": 1.0,
      "disposition_split_max_ratio": 1.0
    }

A ``tier_split_max_ratio`` of 1.0 means all runs agreed on tier; 0.9
means 9/10 agreed; 0.5 means a 5/5 split. The variance band quoted in
``docs/determinism-attestation.md`` is derived from these numbers.

Cost note: this script makes N real LLM API calls. Default N=10, model
anthropic:claude-sonnet-4-5 on a tier-2 submission costs roughly
USD 0.05 per run = USD 0.50 total. Set ``--runs`` higher for tighter
confidence bands at proportionally higher cost.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).parent.parent

# Self-bootstrap: put the repo root on sys.path so the framework's flat-layout
# packages (agent/, schemas/, etc.) are importable when this script is invoked
# directly as `python scripts/measure_determinism_variance.py ...` rather than
# from a context that already has them on the path.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _summarize_categorical(values: list[Any]) -> dict[str, Any]:
    counts = Counter(values)
    most_common = counts.most_common(1)[0]
    return {
        "unique_values": sorted(set(str(v) for v in values)),
        "counts": {str(k): v for k, v in counts.items()},
        "majority_ratio": most_common[1] / len(values) if values else 0.0,
        "n": len(values),
    }


def _summarize_numeric(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "range": max(values) - min(values),
        "n": len(values),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--model", required=True,
        help="PydanticAI model identifier (e.g. anthropic:claude-sonnet-4-5)",
    )
    parser.add_argument(
        "--runs", type=int, default=10,
        help="Number of repetition runs (default 10).",
    )
    parser.add_argument(
        "--submission", required=True, type=Path,
        help="Path to the submission JSON file to triage repeatedly.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Path to write the JSON variance report (default: stdout).",
    )
    parser.add_argument(
        "--corpus", default=None,
        help=(
            "Optional corpus identifier (passed to TriageAgent's "
            "regulation_chunks via vrt's retrieval path). Omit for a "
            "submission-only run."
        ),
    )
    args = parser.parse_args(argv)

    if not args.submission.exists():
        print(f"ERROR: submission not found: {args.submission}", file=sys.stderr)
        return 2

    if args.runs < 2:
        print("ERROR: --runs must be >= 2 to measure variance", file=sys.stderr)
        return 2

    # Validate the model is one we know how to attest. The harness is
    # specifically about per-(provider, model) variance; an unknown
    # provider would produce contract_honored=False on every run, which
    # would defeat the harness.
    known_prefixes = ("anthropic:", "openai:", "google-gla:", "google-vertex:")
    if not any(args.model.startswith(p) for p in known_prefixes):
        print(
            f"WARNING: model {args.model!r} is not a known-attested provider. "
            f"Records will carry contract_honored=False. Variance numbers "
            f"are still meaningful but the contract is not in force on this "
            f"configuration.",
            file=sys.stderr,
        )

    # Late import so --help is fast.
    from agent.agent import TriageAgent, TriageAgentConfig
    from schemas.validate import validate_input

    submission = json.loads(args.submission.read_text())
    ok, errors = validate_input(submission)
    if not ok:
        print(f"ERROR: submission fails input contract: {errors}", file=sys.stderr)
        return 2

    records: list[Any] = []
    print(f"Running {args.runs} triages against {args.model}...")
    for i in range(args.runs):
        agent = TriageAgent(TriageAgentConfig(
            model=args.model,
            tenant=None,
            # Determinism: temperature pinned at 0.0 (the default).
            # If the framework's contract is in force, residual
            # variance across these runs is the provider-side band.
        ))
        try:
            record = agent.triage(submission)
        except Exception as exc:
            print(
                f"  run {i + 1}/{args.runs} FAILED: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        records.append(record)
        print(
            f"  run {i + 1}/{args.runs}: tier={record.risk_tier} "
            f"disp={record.recommended_disposition} "
            f"conf={record.confidence_signal.score:.3f}"
        )

    if len(records) < 2:
        print(
            f"ERROR: only {len(records)} successful runs; need >= 2 to compute "
            f"variance.",
            file=sys.stderr,
        )
        return 1

    # Compute per-field summaries.
    tier_summary = _summarize_categorical([r.risk_tier for r in records])
    disp_summary = _summarize_categorical(
        [r.recommended_disposition for r in records]
    )
    conf_summary = _summarize_numeric(
        [r.confidence_signal.score for r in records]
    )
    evidence_count_summary = _summarize_numeric(
        [len(r.evidence_cited) for r in records]
    )

    report = {
        "model": args.model,
        "runs_requested": args.runs,
        "runs_successful": len(records),
        "submission": str(args.submission),
        "framework_version": records[0].agent_version,
        "fields": {
            "risk_tier": tier_summary,
            "recommended_disposition": disp_summary,
            "confidence_signal.score": conf_summary,
            "evidence_cited.count": evidence_count_summary,
        },
        "tier_split_max_ratio": tier_summary["majority_ratio"],
        "disposition_split_max_ratio": disp_summary["majority_ratio"],
    }

    output = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"\nReport written to {args.output}")
    else:
        print()
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
