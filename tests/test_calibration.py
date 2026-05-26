"""Tests for the Phase 4 sub-system 3 calibration suite.

Covers the ConfidenceOutcome and BinStats models, the calibration math
(Brier, ECE, MCE) against known-result inputs, bin assignment edge
cases, the dimension-grading logic, and the EvalReport convenience
wrapper.

The scorer is fully deterministic (no LLM calls, no I/O); tests
construct inputs inline rather than running an agent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from agent.output_models import (
    ConfidenceSignal,
    EvidenceCitation,
    TriageRecord,
)
from eval.calibration import (
    BinStats,
    CalibrationReport,
    ConfidenceOutcome,
    compute_calibration,
    compute_calibration_from_report,
)
from eval.metrics import ExampleResult
from eval.runner import EvalReport


# -- helpers ---------------------------------------------------------------


def _outcome(score: float, correct: bool) -> ConfidenceOutcome:
    return ConfidenceOutcome(confidence_score=score, was_correct=correct)


def _make_record(
    tier: str = "tier_3_elevated",
    disposition: str = "conditional_approve",
    confidence: float = 0.7,
) -> TriageRecord:
    # ConfidenceSignal enforces consistency between score and interpretation:
    #   score <  0.5  -> "low"
    #   0.5 <= score < 0.8 -> "moderate"
    #   score >= 0.8 -> "high"
    if confidence < 0.5:
        interpretation = "low"
    elif confidence < 0.8:
        interpretation = "moderate"
    else:
        interpretation = "high"
    return TriageRecord(
        decision_id=f"d-{confidence}",
        decision_timestamp=datetime.now(timezone.utc),
        input_submission_id="v-test",
        input_schema_version="1.0.0",
        agent_version="test:0.0.0",
        risk_tier=tier,  # type: ignore[arg-type]
        recommended_disposition=disposition,  # type: ignore[arg-type]
        classification_rationale=(
            "Standard rationale text providing sufficient detail to satisfy "
            "the minimum length requirements of the output contract."
        ),
        evidence_cited=[EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning="Standard anchor reference for testing purposes.",
        )],
        confidence_signal=ConfidenceSignal(score=confidence, interpretation=interpretation),  # type: ignore[arg-type]
        output_schema_version="1.0.0",
        required_mitigations=["maintain monitoring across quarterly review cycles"],
    )


def _make_example_result(
    actual_tier: str,
    expected_tier: str,
    actual_disp: str = "conditional_approve",
    expected_disp: str = "conditional_approve",
    confidence: float = 0.7,
    example_id: str = "ex-1",
) -> ExampleResult:
    return ExampleResult(
        example_id=example_id,
        expected_tier=expected_tier,  # type: ignore[arg-type]
        expected_disposition=expected_disp,  # type: ignore[arg-type]
        record=_make_record(tier=actual_tier, disposition=actual_disp, confidence=confidence),
    )


def _make_report(results: list[ExampleResult]) -> EvalReport:
    from eval.metrics import AggregateMetrics
    return EvalReport(
        run_timestamp=datetime.now(timezone.utc),
        agent_version="test:0.0.0",
        dataset_name="test",
        dataset_content_hash="a" * 16,
        results=results,
        metrics=AggregateMetrics(
            total=len(results),
            succeeded=sum(1 for r in results if r.record is not None),
            failed=sum(1 for r in results if r.record is None),
            tier_agreement_count=0,
            tier_agreement_rate=0.0,
            disposition_agreement_count=0,
            disposition_agreement_rate=0.0,
        ),
    )


# -- model immutability + validation --------------------------------------


def test_confidence_outcome_is_frozen() -> None:
    o = _outcome(0.5, True)
    with pytest.raises(ValidationError):
        o.confidence_score = 0.7  # type: ignore[misc]


def test_confidence_outcome_score_must_be_in_unit() -> None:
    with pytest.raises(ValidationError):
        ConfidenceOutcome(confidence_score=1.5, was_correct=True)
    with pytest.raises(ValidationError):
        ConfidenceOutcome(confidence_score=-0.1, was_correct=True)


def test_bin_stats_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        BinStats(lower_bound=0.0, upper_bound=0.1, count=0, invented=True)  # type: ignore[call-arg]


def test_calibration_report_is_frozen() -> None:
    r = compute_calibration([])
    with pytest.raises(ValidationError):
        r.accuracy = 1.0  # type: ignore[misc]


# -- compute_calibration: arithmetic edge cases ---------------------------


def test_compute_calibration_empty_input() -> None:
    """Empty input produces a vacuous report with zero metrics."""
    r = compute_calibration([])
    assert r.total_predictions == 0
    assert r.brier_score == 0.0
    assert r.expected_calibration_error == 0.0
    assert r.maximum_calibration_error == 0.0
    assert all(b.count == 0 for b in r.bins)


def test_compute_calibration_perfect_calibration() -> None:
    """All score=1.0 correct, all score=0.0 wrong: Brier=0, ECE=0."""
    outcomes = (
        [_outcome(1.0, True)] * 10
        + [_outcome(0.0, False)] * 10
    )
    r = compute_calibration(outcomes)
    assert r.brier_score == 0.0
    assert r.expected_calibration_error == 0.0
    assert r.maximum_calibration_error == 0.0


def test_compute_calibration_worst_case() -> None:
    """All score=1.0 but always wrong: Brier=1, ECE=1, MCE=1."""
    outcomes = [_outcome(1.0, False)] * 10
    r = compute_calibration(outcomes)
    assert r.brier_score == 1.0
    assert r.expected_calibration_error == 1.0
    assert r.maximum_calibration_error == 1.0


def test_compute_calibration_overconfident() -> None:
    """Always 0.9 confident, only 50% correct: ECE=0.4, Brier=0.41."""
    outcomes = (
        [_outcome(0.9, True)] * 10
        + [_outcome(0.9, False)] * 10
    )
    r = compute_calibration(outcomes)
    assert r.expected_calibration_error == pytest.approx(0.4)
    assert r.brier_score == pytest.approx(0.41)
    assert r.accuracy == 0.5


def test_compute_calibration_underconfident() -> None:
    """Always 0.3 confident, but always correct: ECE=0.7."""
    outcomes = [_outcome(0.3, True)] * 10
    r = compute_calibration(outcomes)
    assert r.expected_calibration_error == pytest.approx(0.7)
    assert r.accuracy == 1.0


def test_compute_calibration_dimension_recorded() -> None:
    """The dimension argument is carried onto the report."""
    r = compute_calibration([_outcome(0.5, True)], dimension="disposition")
    assert r.dimension == "disposition"


# -- bin assignment edge cases --------------------------------------------


def test_score_zero_lands_in_first_bin() -> None:
    """score=0.0 goes to bin [0.0, 0.1)."""
    r = compute_calibration([_outcome(0.0, True)])
    assert r.bins[0].count == 1
    assert r.bins[0].lower_bound == 0.0


def test_score_one_lands_in_last_bin() -> None:
    """score=1.0 goes to the top bin (inclusive on right end of final bin)."""
    r = compute_calibration([_outcome(1.0, True)])
    assert r.bins[-1].count == 1
    assert r.bins[-1].upper_bound == 1.0


def test_score_at_bin_boundary_goes_to_higher_bin() -> None:
    """score=0.5 lands in bin [0.5, 0.6) not [0.4, 0.5)."""
    r = compute_calibration([_outcome(0.5, True)])
    # With 10 bins, idx for 0.5 = int(0.5 * 10) = 5, which is bin [0.5, 0.6)
    assert r.bins[5].count == 1
    assert r.bins[5].lower_bound == 0.5


def test_custom_num_bins() -> None:
    """num_bins=5 produces 5 bins of width 0.2 each."""
    r = compute_calibration([_outcome(0.1, True), _outcome(0.9, True)], num_bins=5)
    assert len(r.bins) == 5
    assert r.bins[0].count == 1  # 0.1 -> bin [0.0, 0.2)
    assert r.bins[4].count == 1  # 0.9 -> bin [0.8, 1.0]


def test_num_bins_must_be_positive() -> None:
    """num_bins < 1 raises ValueError."""
    with pytest.raises(ValueError, match="num_bins"):
        compute_calibration([_outcome(0.5, True)], num_bins=0)
    with pytest.raises(ValueError, match="num_bins"):
        compute_calibration([_outcome(0.5, True)], num_bins=-3)


# -- bin contents are correct ---------------------------------------------


def test_bin_stats_capture_mean_confidence_and_accuracy() -> None:
    """Per-bin mean and accuracy match the inputs that fell into the bin."""
    outcomes = [
        _outcome(0.91, True),
        _outcome(0.93, True),
        _outcome(0.95, False),  # 0.91+0.93+0.95 = 2.79/3 = 0.93 mean, 2/3 acc
    ]
    r = compute_calibration(outcomes)
    top_bin = r.bins[-1]  # [0.9, 1.0)
    assert top_bin.count == 3
    assert top_bin.mean_confidence == pytest.approx(0.93)
    assert top_bin.accuracy == pytest.approx(2 / 3)
    assert top_bin.gap == pytest.approx(abs(0.93 - 2/3))


def test_empty_bins_have_none_fields() -> None:
    """Empty bins carry None for mean, accuracy, and gap."""
    r = compute_calibration([_outcome(0.95, True)])
    for b in r.bins[:-1]:  # all but the top bin should be empty
        assert b.count == 0
        assert b.mean_confidence is None
        assert b.accuracy is None
        assert b.gap is None


def test_bin_bounds_partition_unit_interval() -> None:
    """The bins together cover [0, 1] without gaps or overlap."""
    r = compute_calibration([], num_bins=10)
    for i in range(9):
        # Each bin's upper bound equals the next bin's lower bound
        assert r.bins[i].upper_bound == r.bins[i + 1].lower_bound
    assert r.bins[0].lower_bound == 0.0
    assert r.bins[-1].upper_bound == 1.0


# -- maximum calibration error -------------------------------------------


def test_mce_picks_worst_bin() -> None:
    """MCE is the maximum gap across non-empty bins, not the average."""
    outcomes = (
        [_outcome(0.9, False), _outcome(0.9, False)]  # bin [0.9,1.0]: gap=0.9
        + [_outcome(0.5, True), _outcome(0.5, True)]  # bin [0.5,0.6]: gap=0.5
    )
    r = compute_calibration(outcomes)
    assert r.maximum_calibration_error == pytest.approx(0.9)


def test_mce_is_zero_for_perfect_calibration() -> None:
    """MCE = 0 when every non-empty bin has zero gap."""
    outcomes = (
        [_outcome(0.95, True)] * 10
        + [_outcome(0.05, False)] * 10
    )
    r = compute_calibration(outcomes)
    # mean conf in top bin = 0.95, acc = 1.0, gap = 0.05
    # mean conf in bottom bin = 0.05, acc = 0.0, gap = 0.05
    # Not "perfect" by ECE but the gaps are equal so MCE = 0.05.
    assert r.maximum_calibration_error == pytest.approx(0.05)


# -- compute_calibration_from_report --------------------------------------


def test_from_report_tier_dimension() -> None:
    """When dimension=tier, only tier match counts."""
    report = _make_report([
        _make_example_result(
            actual_tier="tier_3_elevated",
            expected_tier="tier_3_elevated",
            actual_disp="approve",
            expected_disp="reject",  # disposition wrong
            confidence=0.8,
        ),
    ])
    r = compute_calibration_from_report(report, dimension="tier")
    # Tier matches, so was_correct=True; only one outcome
    assert r.total_predictions == 1
    assert r.accuracy == 1.0


def test_from_report_disposition_dimension() -> None:
    """When dimension=disposition, only disposition match counts."""
    report = _make_report([
        _make_example_result(
            actual_tier="tier_1_low",
            expected_tier="tier_4_high",  # tier wrong
            actual_disp="approve",
            expected_disp="approve",  # disposition right
            confidence=0.8,
        ),
    ])
    r = compute_calibration_from_report(report, dimension="disposition")
    assert r.accuracy == 1.0


def test_from_report_both_dimension_requires_both_match() -> None:
    """When dimension=both, both tier and disposition must match."""
    report = _make_report([
        _make_example_result(
            actual_tier="tier_3_elevated",
            expected_tier="tier_3_elevated",
            actual_disp="approve",
            expected_disp="reject",  # disposition wrong
            confidence=0.8,
        ),
        _make_example_result(
            actual_tier="tier_3_elevated",
            expected_tier="tier_3_elevated",
            actual_disp="approve",
            expected_disp="approve",  # both right
            confidence=0.8,
        ),
    ])
    r = compute_calibration_from_report(report, dimension="both")
    assert r.total_predictions == 2
    assert r.accuracy == 0.5


def test_from_report_skips_errored_examples() -> None:
    """ExampleResults with no record are skipped, not counted as incorrect."""
    errored = ExampleResult(
        example_id="ex-errored",
        expected_tier="tier_3_elevated",
        expected_disposition="conditional_approve",
        record=None,
        error_type="UnexpectedModelBehavior",
        error_message="Model failed.",
    )
    good = _make_example_result(
        actual_tier="tier_3_elevated",
        expected_tier="tier_3_elevated",
    )
    report = _make_report([errored, good])
    r = compute_calibration_from_report(report)
    # Only the good example contributes; the errored one is skipped
    assert r.total_predictions == 1


def test_from_report_empty_results() -> None:
    """An EvalReport with no records produces a vacuous calibration report."""
    report = _make_report([])
    r = compute_calibration_from_report(report)
    assert r.total_predictions == 0


def test_from_report_extracts_confidence_score() -> None:
    """The score from confidence_signal.score lands on the outcomes."""
    report = _make_report([
        _make_example_result(
            actual_tier="tier_3_elevated",
            expected_tier="tier_3_elevated",
            confidence=0.42,
        ),
    ])
    r = compute_calibration_from_report(report)
    # The 0.42 score should land in bin [0.4, 0.5)
    bin_for_42 = next(b for b in r.bins if b.lower_bound == 0.4)
    assert bin_for_42.count == 1
    assert bin_for_42.mean_confidence == pytest.approx(0.42)


def test_from_report_carries_dimension_through() -> None:
    """The dimension argument flows through to the report."""
    report = _make_report([])
    r = compute_calibration_from_report(report, dimension="both")
    assert r.dimension == "both"


# -- overall metrics -----------------------------------------------------


def test_overall_metrics_match_summation_over_outcomes() -> None:
    """accuracy and mean_confidence are the simple means."""
    outcomes = [
        _outcome(0.2, False),
        _outcome(0.4, True),
        _outcome(0.6, True),
        _outcome(0.8, False),
    ]
    r = compute_calibration(outcomes)
    assert r.accuracy == 0.5  # 2 of 4 correct
    assert r.mean_confidence == pytest.approx(0.5)  # mean of 0.2 + 0.4 + 0.6 + 0.8 = 0.5


# -- tier breakdown -------------------------------------------------------


def _tiered_outcome(score: float, correct: bool, tier: str) -> ConfidenceOutcome:
    return ConfidenceOutcome(confidence_score=score, was_correct=correct, tier=tier)


def test_confidence_outcome_tier_defaults_to_none() -> None:
    """Existing callers not passing tier produce outcomes with tier=None."""
    o = ConfidenceOutcome(confidence_score=0.5, was_correct=True)
    assert o.tier is None


def test_confidence_outcome_accepts_tier_string() -> None:
    """The new tier field accepts arbitrary strings (caller responsibility to match contract)."""
    o = ConfidenceOutcome(confidence_score=0.5, was_correct=True, tier="tier_2_moderate")
    assert o.tier == "tier_2_moderate"


def test_tier_breakdown_empty_input() -> None:
    """Empty outcomes -> empty by_tier dict + vacuous overall."""
    from eval.calibration import compute_tier_breakdown_calibration

    r = compute_tier_breakdown_calibration([])
    assert r.overall.total_predictions == 0
    assert r.by_tier == {}


def test_tier_breakdown_no_tier_excluded_from_breakdown() -> None:
    """Outcomes with tier=None are counted in overall but not the breakdown."""
    from eval.calibration import compute_tier_breakdown_calibration

    outcomes = [
        _outcome(0.5, True),  # tier=None
        _outcome(0.7, False),
    ]
    r = compute_tier_breakdown_calibration(outcomes)
    assert r.overall.total_predictions == 2
    assert r.by_tier == {}


def test_tier_breakdown_groups_outcomes_by_tier() -> None:
    """Outcomes with the same tier land in the same breakdown bucket."""
    from eval.calibration import compute_tier_breakdown_calibration

    outcomes = [
        _tiered_outcome(0.95, True,  "tier_1_low"),
        _tiered_outcome(0.85, True,  "tier_1_low"),
        _tiered_outcome(0.55, True,  "tier_3_elevated"),
        _tiered_outcome(0.65, False, "tier_3_elevated"),
        _tiered_outcome(0.45, False, "tier_3_elevated"),
    ]
    r = compute_tier_breakdown_calibration(outcomes)
    assert set(r.by_tier.keys()) == {"tier_1_low", "tier_3_elevated"}
    assert r.by_tier["tier_1_low"].total_predictions == 2
    assert r.by_tier["tier_3_elevated"].total_predictions == 3


def test_tier_breakdown_overall_matches_compute_calibration() -> None:
    """The overall report equals what compute_calibration would produce on the same outcomes."""
    from eval.calibration import compute_calibration, compute_tier_breakdown_calibration

    outcomes = [
        _tiered_outcome(0.9, True,  "tier_1_low"),
        _tiered_outcome(0.6, False, "tier_3_elevated"),
        _tiered_outcome(0.7, True,  "tier_2_moderate"),
    ]
    tiered = compute_tier_breakdown_calibration(outcomes)
    plain = compute_calibration(outcomes)

    assert tiered.overall.total_predictions == plain.total_predictions
    assert tiered.overall.brier_score == pytest.approx(plain.brier_score)
    assert tiered.overall.expected_calibration_error == pytest.approx(plain.expected_calibration_error)
    assert tiered.overall.accuracy == pytest.approx(plain.accuracy)


def test_tier_breakdown_per_tier_brier_correct() -> None:
    """Per-tier Brier scores are computed correctly within each tier slice."""
    from eval.calibration import compute_tier_breakdown_calibration

    # tier_1: confidence=1.0 always, always correct -> Brier 0.0
    # tier_4: confidence=1.0 always, always wrong   -> Brier 1.0
    outcomes = [
        _tiered_outcome(1.0, True,  "tier_1_low"),
        _tiered_outcome(1.0, True,  "tier_1_low"),
        _tiered_outcome(1.0, False, "tier_4_high"),
        _tiered_outcome(1.0, False, "tier_4_high"),
    ]
    r = compute_tier_breakdown_calibration(outcomes)
    assert r.by_tier["tier_1_low"].brier_score == pytest.approx(0.0)
    assert r.by_tier["tier_4_high"].brier_score == pytest.approx(1.0)


def test_tier_breakdown_dimension_recorded_on_each_report() -> None:
    """The dimension argument flows through to overall AND every per-tier report."""
    from eval.calibration import compute_tier_breakdown_calibration

    outcomes = [
        _tiered_outcome(0.7, True,  "tier_2_moderate"),
        _tiered_outcome(0.4, False, "tier_2_moderate"),
    ]
    r = compute_tier_breakdown_calibration(outcomes, dimension="disposition")
    assert r.overall.dimension == "disposition"
    assert r.by_tier["tier_2_moderate"].dimension == "disposition"


def test_tier_breakdown_report_is_frozen() -> None:
    """TieredCalibrationReport is immutable."""
    from eval.calibration import (
        TieredCalibrationReport,
        compute_tier_breakdown_calibration,
    )

    r = compute_tier_breakdown_calibration([_tiered_outcome(0.5, True, "tier_1_low")])
    assert isinstance(r, TieredCalibrationReport)
    with pytest.raises(ValidationError):
        r.overall = r.overall  # type: ignore[misc]


def test_tier_breakdown_from_report_uses_predicted_tier_not_expected() -> None:
    """Breakdown groups by the AGENT'S predicted tier (record.risk_tier), not expected.

    This matters for production drift monitoring: in production the expected
    tier is often unknown, but the agent's predicted tier always is.
    """
    from eval.calibration import compute_tier_breakdown_calibration_from_report

    # Agent predicts tier_1_low; expected is tier_3_elevated (misclassification)
    res = _make_example_result(
        actual_tier="tier_1_low",
        expected_tier="tier_3_elevated",
        confidence=0.9,
    )
    report = _make_report([res])
    r = compute_tier_breakdown_calibration_from_report(report)
    # The outcome lands under tier_1_low (predicted), not tier_3_elevated (expected)
    assert "tier_1_low" in r.by_tier
    assert "tier_3_elevated" not in r.by_tier


def test_tier_breakdown_from_report_skips_errored_examples() -> None:
    """Same convention as compute_calibration_from_report."""
    from eval.calibration import compute_tier_breakdown_calibration_from_report

    success = _make_example_result(
        actual_tier="tier_2_moderate",
        expected_tier="tier_2_moderate",
    )
    errored = ExampleResult(
        example_id="ex-err",
        expected_tier="tier_2_moderate",  # type: ignore[arg-type]
        expected_disposition="conditional_approve",  # type: ignore[arg-type]
        record=None,
        error_message="agent raised",
    )
    report = _make_report([success, errored])
    r = compute_tier_breakdown_calibration_from_report(report)
    assert r.overall.total_predictions == 1


def test_tier_breakdown_num_bins_flows_through() -> None:
    """The num_bins argument flows through to every report in the breakdown."""
    from eval.calibration import compute_tier_breakdown_calibration

    outcomes = [_tiered_outcome(0.5, True, "tier_1_low")]
    r = compute_tier_breakdown_calibration(outcomes, num_bins=5)
    assert len(r.overall.bins) == 5
    assert len(r.by_tier["tier_1_low"].bins) == 5


def test_tier_breakdown_num_bins_validation() -> None:
    """Invalid num_bins surfaces via compute_calibration."""
    from eval.calibration import compute_tier_breakdown_calibration

    with pytest.raises(ValueError, match="num_bins"):
        compute_tier_breakdown_calibration([], num_bins=0)
