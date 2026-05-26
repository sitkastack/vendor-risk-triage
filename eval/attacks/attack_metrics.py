"""Aggregate metrics computed over an AttackEvalReport.

Where the graded eval (eval/metrics.py) reports tier-match accuracy and
disposition-match accuracy, the attack eval reports:

- Overall attack pass rate (what fraction of attacks did the agent
  successfully resist?)
- Pass rate by attack_type (which categories of attack does the agent
  defend against and which does it fall to?)
- Pass rate by threat id (auditor question: "what's our T-AI1 attack
  pass rate?")

Lower attack success rate = better agent. To avoid double-negatives in
metric names, we report "attack PASS rate" where passing the attack
means the agent successfully resisted - i.e., high pass rate is good
for the agent.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from eval.attacks.attack_runner import AttackEvalReport, AttackOutcome


__all__ = [
    "AttackAggregateMetrics",
    "CategoryMetrics",
    "ThreatMetrics",
    "compute_attack_metrics",
]


class CategoryMetrics(BaseModel):
    """Pass-rate breakdown for one attack_type category."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attack_type: str
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)


class ThreatMetrics(BaseModel):
    """Pass-rate breakdown for one threat id.

    An attack contributes to ThreatMetrics for every threat id it
    declares; an attack declaring threat_ids=["T-AI1", "T-AI2"]
    contributes to both T-AI1 and T-AI2 metrics. This intentional
    double-counting is the right behavior because an attack that
    simultaneously tests two threats provides signal on both.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    threat_id: str
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)


class AttackAggregateMetrics(BaseModel):
    """Overall + per-category + per-threat-id pass-rate summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_attacks: int = Field(ge=0)
    total_passed: int = Field(ge=0)
    overall_pass_rate: float = Field(ge=0.0, le=1.0)
    by_category: list[CategoryMetrics]
    by_threat_id: list[ThreatMetrics]


def compute_attack_metrics(report: AttackEvalReport) -> AttackAggregateMetrics:
    """Aggregate an AttackEvalReport into pass-rate metrics.

    Args:
        report: The output of AttackEvalRunner.run().

    Returns:
        An AttackAggregateMetrics with overall, per-category, and
        per-threat-id pass rates. by_category and by_threat_id are
        sorted by category/threat id for stable output ordering.
    """
    total = len(report.outcomes)
    if total == 0:
        # An empty report is permitted (e.g., dataset with all attacks
        # filtered out by run-time selection) but produces vacuous
        # metrics. Return zero-everything rather than divide-by-zero.
        return AttackAggregateMetrics(
            total_attacks=0,
            total_passed=0,
            overall_pass_rate=0.0,
            by_category=[],
            by_threat_id=[],
        )

    total_passed = sum(1 for o in report.outcomes if o.passed)

    # Per category.
    by_cat: dict[str, list[AttackOutcome]] = defaultdict(list)
    for o in report.outcomes:
        by_cat[o.attack_type].append(o)
    by_category = [
        CategoryMetrics(
            attack_type=cat,
            total=len(outcomes),
            passed=sum(1 for o in outcomes if o.passed),
            pass_rate=sum(1 for o in outcomes if o.passed) / len(outcomes),
        )
        for cat, outcomes in sorted(by_cat.items())
    ]

    # Per threat id.
    by_threat: dict[str, list[AttackOutcome]] = defaultdict(list)
    for o in report.outcomes:
        for tid in o.threat_ids:
            by_threat[tid].append(o)
    by_threat_id = [
        ThreatMetrics(
            threat_id=tid,
            total=len(outcomes),
            passed=sum(1 for o in outcomes if o.passed),
            pass_rate=sum(1 for o in outcomes if o.passed) / len(outcomes),
        )
        for tid, outcomes in sorted(by_threat.items())
    ]

    return AttackAggregateMetrics(
        total_attacks=total,
        total_passed=total_passed,
        overall_pass_rate=total_passed / total,
        by_category=by_category,
        by_threat_id=by_threat_id,
    )
