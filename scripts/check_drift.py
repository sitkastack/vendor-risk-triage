"""Drift detection CLI for the vendor risk triage framework.

Compares the framework's current decisions on the five demo
scenarios against a checked-in baseline. Exits 0 (no drift) or 1
(drift detected). Suitable for CI integration.

Usage::

    # Check for drift against the current baseline.
    python scripts/check_drift.py

    # Regenerate the baseline (after accepting a drift as intentional).
    python scripts/check_drift.py --update-baseline

    # Override the confidence-delta threshold (default 0.05).
    python scripts/check_drift.py --threshold 0.10

The check uses the FunctionModel-backed test double from the demo
scenario tests; it does NOT call a real LLM. Drift detection here
catches framework changes (record construction logic, schema
validation, evidence handling), not LLM behavior changes.

Exit codes:

- ``0``: No drift detected.
- ``1``: Drift detected (hard or soft).
- ``2``: Configuration or setup error (baseline file unreadable,
  demo scenarios dataset missing, etc.).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add repo root to path so the script can run standalone via
# 'python scripts/check_drift.py' from the repo root.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.output_models import TriageRecord  # noqa: E402
from eval.drift import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
    BaselineLoadError,
    DriftCategory,
    DriftReport,
    check_drift,
    load_baselines,
    save_baselines,
)


_DEMO_SCENARIOS_PATH = _REPO_ROOT / "eval" / "datasets" / "demo-scenarios.jsonl"


def _load_demo_scenarios() -> list[dict[str, Any]]:
    """Parse the demo scenarios JSONL, skipping comment lines."""
    if not _DEMO_SCENARIOS_PATH.exists():
        raise FileNotFoundError(
            f"Demo scenarios dataset not found at {_DEMO_SCENARIOS_PATH}. "
            f"Phase 5 sub-system 3 ships this file."
        )
    scenarios: list[dict[str, Any]] = []
    for raw_line in _DEMO_SCENARIOS_PATH.read_text().splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        scenarios.append(json.loads(line))
    return scenarios


def _run_current(scenarios: list[dict[str, Any]]) -> dict[str, TriageRecord]:
    """Run the framework against each scenario and return current records.

    Uses the same FunctionModel-backed test double as
    tests/test_demo_scenarios.py. For each scenario the agent returns
    the canned ``expected_record`` payload through the framework's
    pipeline; the returned TriageRecord reflects what the framework
    produces today given that classification.

    Returns a dict mapping scenario_id to the current TriageRecord.
    """
    from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel
    from agent.agent import TriageAgent, TriageAgentConfig

    currents: dict[str, TriageRecord] = {}
    for scenario in scenarios:
        expected = scenario["expected_record"]
        payload: dict[str, Any] = {
            "risk_tier": expected["risk_tier"],
            "recommended_disposition": expected["recommended_disposition"],
            "classification_rationale": expected["classification_rationale"],
            "evidence_cited": expected["evidence_cited"],
            "confidence_signal": expected["confidence_signal"],
        }
        for opt in (
            "required_mitigations", "accountable_owner",
            "review_interval_days", "regulatory_framework_tags",
        ):
            if opt in expected:
                payload[opt] = expected[opt]

        def _call(
            messages: list[ModelMessage], info: AgentInfo,
            _payload: dict[str, Any] = payload,  # bind per-iteration
        ) -> ModelResponse:
            return ModelResponse(parts=[
                ToolCallPart(tool_name="final_result", args=_payload),
            ])

        agent = TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))
        record = agent.triage(submission=scenario["submission"])
        currents[scenario["id"]] = record
    return currents


def _format_report(report: DriftReport) -> str:
    """Human-readable drift report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Drift detection report")
    lines.append("=" * 72)
    lines.append(
        f"Scenarios checked: {report.total_scenarios}  "
        f"Hard drift: {report.scenarios_with_hard_drift}  "
        f"Soft drift: {report.scenarios_with_soft_drift}  "
        f"Confidence threshold: {report.soft_confidence_threshold}"
    )
    lines.append("")

    if not report.has_any_drift:
        lines.append("No drift detected. All scenarios match baseline.")
        lines.append("")
        return "\n".join(lines)

    for scenario in report.scenarios:
        if not scenario.has_any_drift:
            continue
        lines.append(f"Scenario: {scenario.scenario_id}")
        lines.append("-" * 72)
        for entry in scenario.entries:
            tag = "HARD" if entry.category == DriftCategory.HARD else "SOFT"
            lines.append(f"  [{tag}] {entry.field_path}")
            lines.append(f"    baseline: {entry.baseline_value}")
            lines.append(f"    current:  {entry.current_value}")
            lines.append(f"    note:     {entry.message}")
        lines.append("")

    if report.has_hard_drift:
        lines.append(
            "Hard drift detected. This indicates a real classification "
            "change (tier, disposition, evidence count, framework tags). "
            "Investigate the cause before merging."
        )
    else:
        lines.append(
            "Soft drift detected. Text or confidence shifts within the "
            "same classification. If intentional, regenerate the baseline:"
        )
        lines.append("")
        lines.append("  python scripts/check_drift.py --update-baseline")
        lines.append("")
        lines.append(
            "Commit the new baseline file along with the framework "
            "changes that produced the drift."
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        Exit code: 0 for no drift, 1 for drift, 2 for setup error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Drift detection for the vendor risk triage framework. "
            "Compares current decisions on the five demo scenarios "
            "against a checked-in baseline."
        ),
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Regenerate the baseline file from the current framework's "
            "output. Use after accepting a drift as intentional. The "
            "diff is reviewable in the commit; a code reviewer asks "
            "'is this drift expected?' before approving."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
        help=(
            f"Confidence score delta below which differences are "
            f"ignored. Default {DEFAULT_SOFT_CONFIDENCE_THRESHOLD}."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help=(
            f"Path to the baseline JSONL file. Default "
            f"{DEFAULT_BASELINE_PATH.relative_to(_REPO_ROOT)}."
        ),
    )
    args = parser.parse_args(argv)

    try:
        scenarios = _load_demo_scenarios()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    currents = _run_current(scenarios)

    if args.update_baseline:
        save_baselines(currents, path=args.baseline)
        print(
            f"Baseline regenerated at {args.baseline} "
            f"({len(currents)} scenarios)."
        )
        return 0

    try:
        baselines = load_baselines(args.baseline)
    except BaselineLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    report = check_drift(
        baselines=baselines,
        currents=currents,
        soft_confidence_threshold=args.threshold,
    )
    print(_format_report(report))
    return 1 if report.has_any_drift else 0


if __name__ == "__main__":
    sys.exit(main())
