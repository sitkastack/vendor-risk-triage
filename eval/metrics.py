"""Metrics for eval results.

Pure functions and Pydantic models that compute aggregates from lists of
per-example results. No I/O, no side effects, no dependency on the
runner. The runner produces results; this module turns results into
numbers a reviewer can act on.

MVP metric set is deliberately small:

- Tier agreement: did the agent's risk_tier match the expected risk_tier?
- Disposition agreement: did recommended_disposition match expected?
- Evidence count: how many evidence_cited entries did the agent produce?
  (Bounded above by the rationale length and below by the schema's
  min_length=1; tracking the distribution helps catch agents that drift
  toward terse rationales over time.)
- Failure count: how many examples raised an exception that prevented
  the agent from producing any output?

Deferred to future eval work:

- [deferred-subsystem-3-followup] Per-tier breakdown of agreement
  (which tiers does the agent get wrong most often?)
- [deferred-subsystem-3-followup] Confusion matrix between expected and
  actual tier
- [deferred-phase-4] Calibration metrics (does confidence_signal.score
  predict correctness?)
- [deferred-phase-4] LLM-as-judge agreement on rationale quality
- [deferred-phase-4] Bias-attribute-conditioned agreement (does the agent
  perform differently on vendors with certain attributes?)
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from agent.output_models import Disposition, RiskTier, TriageRecord
from eval.dataset import GradedExample


__all__ = [
    "ExampleResult",
    "AggregateMetrics",
    "compute_metrics",
]


class ExampleResult(BaseModel):
    """Result of running the agent against a single graded example.

    Either ``record`` is non-None (the agent produced a TriageRecord) or
    ``error`` is non-None (the agent raised before producing one). Never
    both, never neither.

    Attributes:
        example_id: The GradedExample.id this result corresponds to.
        expected_tier: The graded example's expected tier (copied for
            convenience; the runner does not store the full example
            inside each result).
        expected_disposition: The graded example's expected disposition.
        record: The TriageRecord the agent produced, or None if the agent
            raised.
        error_type: The exception class name if the agent raised, else None.
        error_message: The exception message if the agent raised, else None.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    example_id: str = Field(min_length=1, max_length=128)
    expected_tier: RiskTier
    expected_disposition: Disposition
    record: Optional[TriageRecord] = None
    error_type: Optional[str] = Field(default=None, max_length=256)
    error_message: Optional[str] = Field(default=None, max_length=4000)

    @property
    def succeeded(self) -> bool:
        """True if the agent produced a TriageRecord."""
        return self.record is not None

    @property
    def tier_agrees(self) -> bool:
        """True if the agent's tier matched the expected tier.

        False if the agent raised (no tier to compare) OR if the tier
        differs from expected.
        """
        if self.record is None:
            return False
        return self.record.risk_tier == self.expected_tier

    @property
    def disposition_agrees(self) -> bool:
        """True if the agent's disposition matched the expected disposition.

        False if the agent raised OR if disposition differs from expected.
        """
        if self.record is None:
            return False
        return self.record.recommended_disposition == self.expected_disposition


class AggregateMetrics(BaseModel):
    """Aggregate metrics across a list of ExampleResults.

    Counts are reported as both absolute counts and rates (counts / total)
    so a reader can answer "how many?" and "what fraction?" without
    arithmetic. Rates are computed against the total dataset size (not
    against successful runs only) because a failure-to-produce-output is a
    real disagreement: the agent failed to do its job.

    Attributes:
        total: Total number of examples in the dataset.
        succeeded: Count of examples where the agent produced a record.
        failed: Count of examples where the agent raised.
        tier_agreement_count: Examples whose risk_tier matched expected.
        tier_agreement_rate: tier_agreement_count / total.
        disposition_agreement_count: Examples whose disposition matched.
        disposition_agreement_rate: disposition_agreement_count / total.
        evidence_count_min: Smallest evidence_cited length among
            successful results. None if no successes.
        evidence_count_max: Largest evidence_cited length among
            successful results. None if no successes.
        evidence_count_mean: Arithmetic mean of evidence_cited lengths
            among successful results. None if no successes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    tier_agreement_count: int = Field(ge=0)
    tier_agreement_rate: float = Field(ge=0.0, le=1.0)
    disposition_agreement_count: int = Field(ge=0)
    disposition_agreement_rate: float = Field(ge=0.0, le=1.0)
    evidence_count_min: Optional[int] = Field(default=None, ge=0)
    evidence_count_max: Optional[int] = Field(default=None, ge=0)
    evidence_count_mean: Optional[float] = Field(default=None, ge=0.0)


def compute_metrics(results: list[ExampleResult]) -> AggregateMetrics:
    """Compute aggregate metrics from a list of per-example results.

    The function is pure: no I/O, no mutation of the input. Called by the
    runner at the end of a run; can also be called by callers who have
    persisted ExampleResults and want to recompute aggregates without
    re-running the agent.

    Args:
        results: Per-example results, typically all results from one
            dataset run. Length zero is allowed (returns zero counts and
            zero rates).

    Returns:
        An AggregateMetrics with all counts and rates populated. Evidence
        statistics are None when no example produced a record.
    """
    total = len(results)
    succeeded = sum(1 for r in results if r.succeeded)
    failed = total - succeeded
    tier_agreement = sum(1 for r in results if r.tier_agrees)
    disposition_agreement = sum(1 for r in results if r.disposition_agrees)

    evidence_counts = [
        len(r.record.evidence_cited) for r in results if r.record is not None
    ]
    if evidence_counts:
        ev_min: Optional[int] = min(evidence_counts)
        ev_max: Optional[int] = max(evidence_counts)
        ev_mean: Optional[float] = sum(evidence_counts) / len(evidence_counts)
    else:
        ev_min = None
        ev_max = None
        ev_mean = None

    return AggregateMetrics(
        total=total,
        succeeded=succeeded,
        failed=failed,
        tier_agreement_count=tier_agreement,
        tier_agreement_rate=tier_agreement / total if total else 0.0,
        disposition_agreement_count=disposition_agreement,
        disposition_agreement_rate=disposition_agreement / total if total else 0.0,
        evidence_count_min=ev_min,
        evidence_count_max=ev_max,
        evidence_count_mean=ev_mean,
    )
