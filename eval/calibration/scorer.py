"""Calibration measurement for confidence_signal.score values.

The agent's output contract requires every TriageRecord to carry a
confidence_signal with a score in [0, 1] and a discrete interpretation
band. Whether those scores actually correspond to empirical accuracy
is the auditor's question: "your AI says it is 85% confident. Show me
that 85% confidence means 85% accuracy."

This module computes the standard calibration metrics over a set of
(predicted_score, was_correct) outcomes:

- Brier score: mean squared error between confidence and outcome.
  Lower is better. Bounded [0, 1]. Industry standard.
- Expected Calibration Error (ECE): the |mean_confidence - accuracy|
  gap in each confidence bin, weighted by bin population. The number
  auditors most often quote.
- Maximum Calibration Error (MCE): the worst single-bin gap. Surfaces
  bins where the agent is severely miscalibrated even if ECE looks
  acceptable.
- Reliability diagram data: per-bin (mean_confidence, accuracy) pairs
  for plotting. The chart itself is presentation-layer work; this
  module ships the data only.

The module is deterministic, makes no LLM calls, has no external
dependencies beyond Python's standard library and pydantic. No
scipy/sklearn: those would couple the framework to a particular vendor
of statistics, and the math here is short enough to be auditable
in-place.

What "correct" means:

A prediction is correct when the agent's risk_tier matches the
expected risk_tier, when the agent's recommended_disposition matches
the expected recommended_disposition, or when both match -- depending
on the dimension passed in. The default dimension is "tier", because
tier is the primary classification and disposition typically follows
from it. Other dimensions are available for use cases where the
disposition is the meaningful target.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from eval.runner import EvalReport


__all__ = [
    "BinStats",
    "BinningMethod",
    "CalibrationDimension",
    "CalibrationReport",
    "ConfidenceOutcome",
    "TieredCalibrationReport",
    "compute_calibration",
    "compute_calibration_from_report",
    "compute_tier_breakdown_calibration",
    "compute_tier_breakdown_calibration_from_report",
]


CalibrationDimension = Literal["tier", "disposition", "both"]
"""Which dimension defines correctness for calibration.

- "tier": predicted risk_tier matches expected risk_tier
- "disposition": predicted recommended_disposition matches expected
- "both": both must match for the prediction to count as correct
"""


BinningMethod = Literal["equal_width", "equal_frequency"]
"""How confidence scores are partitioned into bins for ECE / MCE.

- "equal_width": fixed-width bins partitioning [0, 1] into num_bins
  equal intervals. The default. Industry standard ECE definition
  (Niculescu-Mizil & Caruana 2005, Guo et al. 2017). Bin bounds are
  prescriptive: bin i covers [i/k, (i+1)/k), with the final bin
  inclusive at 1.0. Per ADR-017.
- "equal_frequency": data-defined bins where each bin holds an
  approximately equal count of observations. Useful when the agent's
  confidence distribution is concentrated (e.g., most predictions in
  0.6-0.8) and equal-width leaves the extreme bins sparsely
  populated. Bin bounds become descriptive: the lower_bound and
  upper_bound of a bin are the min and max confidence scores in the
  bucket, not fixed cutoffs.
"""


class ConfidenceOutcome(BaseModel):
    """One (confidence_score, was_correct) data point for calibration.

    Attributes:
        confidence_score: The agent's emitted confidence_signal.score
            for this prediction, in [0, 1].
        was_correct: Whether the prediction was correct for the
            chosen calibration dimension.
        tier: Optional predicted tier for this outcome. Required only
            when used with compute_tier_breakdown_calibration; ignored
            by compute_calibration. Matches the agent's predicted
            risk_tier value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence_score: float = Field(ge=0.0, le=1.0)
    was_correct: bool
    tier: Optional[str] = None


class BinStats(BaseModel):
    """Per-bin reliability data for one confidence bin.

    A bin's lower bound is inclusive; its upper bound is exclusive,
    except for the final bin whose upper bound is inclusive. The
    convention matches the standard ECE definition and means a
    prediction with score=1.0 lands in the top bin.

    Empty bins (count=0) carry None for mean_confidence, accuracy, and
    gap. Reliability diagrams skip empty bins by convention.

    Attributes:
        lower_bound: The bin's lower confidence bound (inclusive).
        upper_bound: The bin's upper confidence bound (inclusive only
            for the final bin).
        count: Number of outcomes in this bin.
        mean_confidence: Mean confidence_score across outcomes in the
            bin. None when count=0.
        accuracy: Fraction of outcomes in the bin that were correct.
            None when count=0.
        gap: |mean_confidence - accuracy|. None when count=0. The
            absolute calibration error for this bin.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)
    count: int = Field(ge=0)
    mean_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    gap: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class CalibrationReport(BaseModel):
    """Aggregate calibration metrics across a set of predictions.

    Attributes:
        total_predictions: Number of outcomes the report aggregates.
        dimension: The "correct" dimension used to compute the report.
        binning_method: How the bins were defined. Recorded on the
            report for audit traceability; an auditor verifying ECE
            values can identify the method that produced them.
        accuracy: Overall fraction of correct predictions. 0.0 when
            total_predictions is 0 (documented vacuous).
        mean_confidence: Overall mean confidence across all
            predictions. 0.0 when total_predictions is 0.
        brier_score: Mean squared error between confidence and outcome,
            in [0, 1]. Lower is better. Bin-independent. 0.0 when
            total_predictions is 0 (documented vacuous; not a
            "perfect score").
        expected_calibration_error: Population-weighted mean of per-bin
            |mean_confidence - accuracy| gaps, in [0, 1]. Lower is
            better. 0.0 when total_predictions is 0.
        maximum_calibration_error: Worst per-bin gap across non-empty
            bins, in [0, 1]. Lower is better. 0.0 when no non-empty
            bins exist.
        bins: Per-bin reliability data, lowest-to-highest confidence.
            For equal_width, bin bounds are prescriptive ([i/k, (i+1)/k)).
            For equal_frequency, bin bounds are descriptive (min and
            max confidence within the bucket). Empty equal_frequency
            bins (which occur when total < num_bins) carry bounds
            (0.0, 0.0) by convention.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_predictions: int = Field(ge=0)
    dimension: CalibrationDimension
    binning_method: BinningMethod = "equal_width"
    accuracy: float = Field(ge=0.0, le=1.0)
    mean_confidence: float = Field(ge=0.0, le=1.0)
    brier_score: float = Field(ge=0.0, le=1.0)
    expected_calibration_error: float = Field(ge=0.0, le=1.0)
    maximum_calibration_error: float = Field(ge=0.0, le=1.0)
    bins: list[BinStats]


def compute_calibration(
    outcomes: list[ConfidenceOutcome],
    dimension: CalibrationDimension = "tier",
    num_bins: int = 10,
    binning: BinningMethod = "equal_width",
) -> CalibrationReport:
    """Compute calibration metrics over a list of ConfidenceOutcomes.

    The dimension argument here is informational only: the outcomes
    have already been graded against the chosen dimension by the
    caller. The dimension is recorded on the report for audit
    traceability.

    Args:
        outcomes: List of (confidence_score, was_correct) pairs to
            aggregate. May be empty.
        dimension: Which correctness dimension the was_correct flags
            were computed against. Recorded on the report; does not
            change the math.
        num_bins: Number of bins. Must be >= 1. Default 10 matches the
            standard ECE definition.
        binning: How bins are defined. "equal_width" (default) uses
            fixed [i/k, (i+1)/k) intervals; "equal_frequency" uses
            quantile-defined bins of approximately equal observation
            count. See BinningMethod docstring for details. Per ADR-017.

    Returns:
        A CalibrationReport with all metrics and per-bin breakdowns.

    Raises:
        ValueError: If num_bins is less than 1.
    """
    if num_bins < 1:
        raise ValueError(f"num_bins must be >= 1, got {num_bins}")

    total = len(outcomes)
    if total == 0:
        # Vacuous report: every metric reads as 0.0. Bins default to
        # equal-width bounds for the vacuous case regardless of the
        # requested method, since there is no data to derive
        # quantile-defined bins from.
        return CalibrationReport(
            total_predictions=0,
            dimension=dimension,
            binning_method=binning,
            accuracy=0.0,
            mean_confidence=0.0,
            brier_score=0.0,
            expected_calibration_error=0.0,
            maximum_calibration_error=0.0,
            bins=_empty_bins(num_bins),
        )

    # Bin the outcomes by the chosen method.
    if binning == "equal_width":
        buckets_with_bounds = _bin_equal_width(outcomes, num_bins)
    else:
        buckets_with_bounds = _bin_equal_frequency(outcomes, num_bins)

    # Aggregate per-bin metrics. Same math for both methods.
    bins, weighted_gap_sum, max_gap = _aggregate_bins(buckets_with_bounds, total)

    # Overall metrics. Bin-independent.
    overall_accuracy = sum(1 for o in outcomes if o.was_correct) / total
    overall_mean_conf = sum(o.confidence_score for o in outcomes) / total
    brier = sum(
        (o.confidence_score - (1.0 if o.was_correct else 0.0)) ** 2
        for o in outcomes
    ) / total

    return CalibrationReport(
        total_predictions=total,
        dimension=dimension,
        binning_method=binning,
        accuracy=overall_accuracy,
        mean_confidence=overall_mean_conf,
        brier_score=brier,
        expected_calibration_error=weighted_gap_sum,
        maximum_calibration_error=max_gap,
        bins=bins,
    )


def compute_calibration_from_report(
    report: EvalReport,
    dimension: CalibrationDimension = "tier",
    num_bins: int = 10,
    binning: BinningMethod = "equal_width",
) -> CalibrationReport:
    """Compute calibration over the predictions in a sub-system 3 EvalReport.

    Extracts confidence_signal.score and the matching ground-truth
    comparison from each ExampleResult that produced a TriageRecord.
    ExampleResults that errored (record is None) are skipped: there is
    no confidence signal to calibrate when the agent failed to produce
    a record.

    Args:
        report: An EvalReport from running an agent over a graded dataset.
        dimension: Which dimension to grade against. Default "tier".
        num_bins: Bins. Default 10.
        binning: Binning method. Default "equal_width". Per ADR-017.

    Returns:
        A CalibrationReport. If no examples in the report produced
        records, the report is the vacuous total_predictions=0 case.
    """
    outcomes: list[ConfidenceOutcome] = []
    for example in report.results:
        if example.record is None:
            continue
        was_correct = _is_correct(
            example.record.risk_tier,
            example.record.recommended_disposition,
            example.expected_tier,
            example.expected_disposition,
            dimension,
        )
        outcomes.append(ConfidenceOutcome(
            confidence_score=example.record.confidence_signal.score,
            was_correct=was_correct,
        ))
    return compute_calibration(
        outcomes,
        dimension=dimension,
        num_bins=num_bins,
        binning=binning,
    )


# -- tier breakdown -------------------------------------------------------


class TieredCalibrationReport(BaseModel):
    """Calibration with both overall and per-tier breakdowns.

    Where CalibrationReport answers "how calibrated is the agent
    overall?", TieredCalibrationReport answers "how calibrated is the
    agent within each predicted risk tier?". An auditor's natural
    question: "your overall ECE is 0.08, but is your tier_3_elevated
    ECE the same as your tier_1_low ECE?"

    The per-tier breakdown keys are the predicted tier values that
    actually appear in the input outcomes. Tiers with zero outcomes
    are omitted from the by_tier dict (rather than producing a
    vacuous-zeros report that could be misread as data).

    Attributes:
        overall: The CalibrationReport computed across all outcomes
            regardless of tier. Identical to what compute_calibration
            would produce.
        by_tier: Per-tier CalibrationReports keyed by predicted tier
            string. Empty if every outcome lacks a tier value (which
            indicates a caller bug; documented).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: CalibrationReport
    by_tier: dict[str, CalibrationReport]


def compute_tier_breakdown_calibration(
    outcomes: list[ConfidenceOutcome],
    dimension: CalibrationDimension = "tier",
    num_bins: int = 10,
    binning: BinningMethod = "equal_width",
) -> TieredCalibrationReport:
    """Compute calibration overall and per predicted tier.

    Each ConfidenceOutcome must carry a non-None tier value. Outcomes
    with tier=None are included in the overall report but excluded
    from the per-tier breakdown.

    Args:
        outcomes: List of (confidence_score, was_correct, tier) data
            points. May be empty. Outcomes without tier are still
            counted in the overall report.
        dimension: Recorded on each report for audit traceability.
            Does not change the math.
        num_bins: Number of bins partitioning [0, 1]. Default 10.
        binning: Binning method, threaded through to overall and
            per-tier reports. Default "equal_width". Per ADR-017.

    Returns:
        A TieredCalibrationReport containing the overall report and
        the per-tier breakdown.

    Raises:
        ValueError: If num_bins is less than 1.
    """
    overall = compute_calibration(
        outcomes,
        dimension=dimension,
        num_bins=num_bins,
        binning=binning,
    )

    by_tier_outcomes: dict[str, list[ConfidenceOutcome]] = {}
    for o in outcomes:
        if o.tier is None:
            continue
        by_tier_outcomes.setdefault(o.tier, []).append(o)

    by_tier: dict[str, CalibrationReport] = {
        tier: compute_calibration(
            tier_outcomes,
            dimension=dimension,
            num_bins=num_bins,
            binning=binning,
        )
        for tier, tier_outcomes in by_tier_outcomes.items()
    }

    return TieredCalibrationReport(overall=overall, by_tier=by_tier)


def compute_tier_breakdown_calibration_from_report(
    report: EvalReport,
    dimension: CalibrationDimension = "tier",
    num_bins: int = 10,
    binning: BinningMethod = "equal_width",
) -> TieredCalibrationReport:
    """Compute tier-breakdown calibration from an EvalReport.

    Extracts confidence_signal.score AND the agent's predicted
    risk_tier from each ExampleResult. The tier dimension of the
    breakdown is the AGENT'S PREDICTED tier, not the expected tier:
    "for predictions where the agent said tier_3, was it well-
    calibrated?" This is the more useful production-monitoring
    framing, since the expected tier is not always known but the
    predicted tier always is.

    ExampleResults that errored (record is None) are skipped.

    Args:
        report: An EvalReport from running an agent over a graded
            dataset.
        dimension: Which dimension grades was_correct. Default "tier".
        num_bins: Bins over [0, 1]. Default 10.
        binning: Binning method. Default "equal_width". Per ADR-017.

    Returns:
        A TieredCalibrationReport. Empty by_tier if no examples
        produced records.
    """
    outcomes: list[ConfidenceOutcome] = []
    for example in report.results:
        if example.record is None:
            continue
        was_correct = _is_correct(
            example.record.risk_tier,
            example.record.recommended_disposition,
            example.expected_tier,
            example.expected_disposition,
            dimension,
        )
        outcomes.append(ConfidenceOutcome(
            confidence_score=example.record.confidence_signal.score,
            was_correct=was_correct,
            tier=example.record.risk_tier,
        ))
    return compute_tier_breakdown_calibration(
        outcomes,
        dimension=dimension,
        num_bins=num_bins,
        binning=binning,
    )


# -- private helpers -------------------------------------------------------


def _is_correct(
    actual_tier: str,
    actual_disposition: str,
    expected_tier: str,
    expected_disposition: str,
    dimension: CalibrationDimension,
) -> bool:
    """Apply the chosen dimension to grade a single prediction."""
    if dimension == "tier":
        return actual_tier == expected_tier
    if dimension == "disposition":
        return actual_disposition == expected_disposition
    # "both"
    return (
        actual_tier == expected_tier
        and actual_disposition == expected_disposition
    )


def _empty_bins(num_bins: int) -> list[BinStats]:
    """Build a list of empty BinStats partitioning [0, 1].

    Used for the vacuous (total_predictions=0) case. Bounds default
    to equal-width regardless of the requested binning method, since
    there is no data to derive quantile-defined bins from.
    """
    return [
        BinStats(
            lower_bound=i / num_bins,
            upper_bound=(i + 1) / num_bins,
            count=0,
        )
        for i in range(num_bins)
    ]


# -- binning ---------------------------------------------------------------


def _bin_equal_width(
    outcomes: list[ConfidenceOutcome],
    num_bins: int,
) -> list[tuple[list[ConfidenceOutcome], float, float]]:
    """Bin outcomes into fixed-width [i/k, (i+1)/k) intervals.

    The final bin is inclusive at 1.0 so an outcome with
    confidence_score=1.0 lands in the top bin.

    Returns:
        A list of (bucket, lower_bound, upper_bound) tuples, exactly
        num_bins entries long.
    """
    binned: list[list[ConfidenceOutcome]] = [[] for _ in range(num_bins)]
    for o in outcomes:
        idx = min(int(o.confidence_score * num_bins), num_bins - 1)
        binned[idx].append(o)
    return [
        (binned[i], i / num_bins, (i + 1) / num_bins)
        for i in range(num_bins)
    ]


def _bin_equal_frequency(
    outcomes: list[ConfidenceOutcome],
    num_bins: int,
) -> list[tuple[list[ConfidenceOutcome], float, float]]:
    """Bin outcomes into roughly-equal-size groups by sorted score.

    Sort outcomes ascending by confidence_score, slice into num_bins
    consecutive buckets using index arithmetic (i*total//k cutoffs).
    Buckets near the start of the data get the same or one fewer
    items than buckets later in the data; the distribution is as
    even as integer arithmetic allows.

    Tied scores at slice boundaries stay together with their
    neighbors in the sorted list; ties do not span buckets in a
    way that requires special handling.

    Bin bounds are descriptive: lower_bound = min score in bucket,
    upper_bound = max score in bucket. For empty buckets (which can
    occur when total < num_bins), bounds are 0.0 by convention, with
    count=0 as the signal that the bucket is unpopulated.

    Returns:
        A list of (bucket, lower_bound, upper_bound) tuples, exactly
        num_bins entries long.
    """
    total = len(outcomes)
    sorted_outcomes = sorted(outcomes, key=lambda o: o.confidence_score)
    result: list[tuple[list[ConfidenceOutcome], float, float]] = []
    for i in range(num_bins):
        start = (i * total) // num_bins
        end = ((i + 1) * total) // num_bins
        bucket = sorted_outcomes[start:end]
        if bucket:
            lower = bucket[0].confidence_score
            upper = bucket[-1].confidence_score
        else:
            lower = 0.0
            upper = 0.0
        result.append((bucket, lower, upper))
    return result


def _aggregate_bins(
    buckets_with_bounds: list[tuple[list[ConfidenceOutcome], float, float]],
    total: int,
) -> tuple[list[BinStats], float, float]:
    """Compute per-bin metrics and aggregate ECE / MCE.

    Same math regardless of binning method. Takes the binned outcomes
    plus their bounds, returns the BinStats list, the population-
    weighted gap sum (ECE), and the maximum per-bin gap (MCE).
    """
    bins: list[BinStats] = []
    weighted_gap_sum = 0.0
    max_gap = 0.0
    for bucket, lower, upper in buckets_with_bounds:
        if not bucket:
            bins.append(BinStats(
                lower_bound=lower,
                upper_bound=upper,
                count=0,
            ))
            continue
        bin_count = len(bucket)
        bin_mean_conf = sum(o.confidence_score for o in bucket) / bin_count
        bin_accuracy = sum(1 for o in bucket if o.was_correct) / bin_count
        bin_gap = abs(bin_mean_conf - bin_accuracy)
        bins.append(BinStats(
            lower_bound=lower,
            upper_bound=upper,
            count=bin_count,
            mean_confidence=bin_mean_conf,
            accuracy=bin_accuracy,
            gap=bin_gap,
        ))
        weighted_gap_sum += (bin_count / total) * bin_gap
        if bin_gap > max_gap:
            max_gap = bin_gap
    return bins, weighted_gap_sum, max_gap
