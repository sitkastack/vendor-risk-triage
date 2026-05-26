# Calibration measurement

This package answers the auditor's question: "when the agent says it
is 85% confident, is it actually right 85% of the time?" Without a
calibration story, the `confidence_signal.score` field is decoration;
with one, it is auditable signal.

## What ships

- `scorer.py`: the `CalibrationScorer` math and result models
  (`ConfidenceOutcome`, `BinStats`, `CalibrationReport`)
- Two entry points:
  - `compute_calibration(outcomes, dimension, num_bins)`: the primitive
    over flat `(confidence_score, was_correct)` pairs
  - `compute_calibration_from_report(report, dimension, num_bins)`: a
    convenience wrapper that extracts outcomes from a sub-system 3
    `EvalReport`
- `__init__.py`: public API surface

The package is fully deterministic. No LLM calls, no I/O, no
dependencies beyond pydantic and Python's standard library. The math
runs in milliseconds even over large datasets.

## Metrics

### Brier score

Mean squared error between the agent's confidence score and the binary
outcome:

```
brier = (1/N) * Σ (confidence_score_i - was_correct_i)^2
```

Where `was_correct_i` is 1 if the prediction was correct, 0 otherwise.
Bounded `[0, 1]`. Lower is better. A perfectly calibrated agent that
also achieves perfect accuracy gets Brier = 0; an always-wrong agent
at 100% confidence gets Brier = 1.

### Expected Calibration Error (ECE)

The population-weighted mean of per-bin gaps:

```
ece = Σ (n_bin / N) * |mean_confidence_in_bin - accuracy_in_bin|
```

Bounded `[0, 1]`. Lower is better. The number auditors most often
quote. ECE = 0.1 means on average, the agent's stated confidence
differs from its actual accuracy by 10 percentage points.

### Maximum Calibration Error (MCE)

The worst single-bin gap across non-empty bins. Surfaces bins where
the agent is severely miscalibrated even if ECE looks acceptable. For
example, an agent might have ECE = 0.05 but MCE = 0.4, meaning one
specific confidence range is badly off even though the average is
fine. Auditors care about both.

### Reliability diagram data

Per-bin `(mean_confidence, accuracy)` tuples for plotting. The chart
itself is presentation-layer concern; this module ships the data only.
A perfectly calibrated agent's reliability diagram lies on the
diagonal `y = x`; deviations from the diagonal show miscalibration.

## Calibration dimensions

A prediction is "correct" against one of three dimensions:

- `tier`: predicted `risk_tier` matches expected. Default. This is the
  primary classification and what tier-driven downstream controls rely
  on.
- `disposition`: predicted `recommended_disposition` matches expected.
  Useful when the disposition is the consequential action (e.g., auto-
  approve flows).
- `both`: both tier and disposition must match. Strictest dimension;
  use when audit policy requires joint correctness.

The dimension is recorded on the report for traceability.

## Binning

Default: 10 equal-width bins over `[0, 1]`. Bin `i` covers
`[i/N, (i+1)/N)` for all but the final bin, which is inclusive on the
right end so a score of 1.0 lands in the top bin.

Equal-frequency (quantile) binning is `[deferred-phase-4-followup]`.
Equal-width is more interpretable for audit and matches the standard
ECE definition.

`num_bins` is configurable. 10 is the published default in most
calibration papers; 20 gives finer-grained signal at the cost of
sparser bins; 5 trades resolution for stability with small datasets.

## Usage

### From a graded eval report

```python
from eval.calibration import compute_calibration_from_report
from eval.runner import TriageEvalRunner
from eval.dataset import load_dataset

dataset = load_dataset("eval/datasets/tier-classification-baseline.jsonl")
report = TriageEvalRunner(agent).run(dataset)

calibration = compute_calibration_from_report(report, dimension="tier")

print(f"Brier score: {calibration.brier_score:.4f}")
print(f"ECE: {calibration.expected_calibration_error:.4f}")
print(f"MCE: {calibration.maximum_calibration_error:.4f}")
print(f"Overall accuracy: {calibration.accuracy:.1%}")
print(f"Overall mean confidence: {calibration.mean_confidence:.1%}")
print()
print("Reliability diagram:")
for b in calibration.bins:
    if b.count > 0:
        print(f"  [{b.lower_bound:.1f}, {b.upper_bound:.1f}): "
              f"n={b.count} mean_conf={b.mean_confidence:.2f} "
              f"acc={b.accuracy:.2f} gap={b.gap:.2f}")
```

### Direct from outcomes

```python
from eval.calibration import ConfidenceOutcome, compute_calibration

outcomes = [
    ConfidenceOutcome(confidence_score=record.confidence_signal.score,
                      was_correct=(record.risk_tier == expected_tier))
    for record, expected_tier in pairs
]

calibration = compute_calibration(outcomes, dimension="tier")
```

## Interpretation

A well-calibrated agent has Brier and ECE both low. A useful agent has
high accuracy. These are independent: an agent can be highly accurate
but poorly calibrated (always 50% confident, but always right) or
poorly accurate but well calibrated (always 50% confident, and right
exactly half the time).

For audit, both signals matter:

- **Accuracy** answers "is the agent useful?"
- **Calibration** answers "should we trust the agent's stated
  confidence?"

A common failure mode is high accuracy with severe overconfidence: the
agent is right most of the time but claims 99% confidence on every
prediction. Brier and ECE catch this; raw accuracy does not.

## Limitations

The sample size of the bundled graded baseline (8 examples) is too
small to draw production calibration conclusions from. Real
calibration measurement requires hundreds to thousands of graded
examples. The framework provides the machinery; deploying organisations
provide the labeled data.

Bins with very few outcomes have high-variance accuracy estimates. A
bin with 3 outcomes and 2 correct shows accuracy=0.67 but the confidence
interval is wide. Bootstrap confidence intervals on ECE are tagged
`[deferred-phase-5]`.

Calibration is also model-and-corpus-specific. A LLM tuned on one
domain will not necessarily be calibrated on another. Re-measure when
the model changes, the dataset changes, or the prompt changes.

## Per-tier breakdown

A single calibration number across all predictions can hide tier-specific miscalibration. An agent might be well-calibrated overall (ECE 0.08) while being severely miscalibrated on tier_3_elevated (ECE 0.20). Auditors ask this question routinely: "is your tier-3 calibration the same as your tier-1?"

`compute_tier_breakdown_calibration()` answers it. Pass `ConfidenceOutcome` instances carrying the predicted `tier` and the function returns a `TieredCalibrationReport` containing both the overall report and per-tier reports keyed by predicted tier.

```python
from eval.calibration import (
    ConfidenceOutcome,
    compute_tier_breakdown_calibration,
)

outcomes = [
    ConfidenceOutcome(confidence_score=0.95, was_correct=True,  tier="tier_1_low"),
    ConfidenceOutcome(confidence_score=0.55, was_correct=False, tier="tier_3_elevated"),
    # ...
]

r = compute_tier_breakdown_calibration(outcomes)
print(f"Overall ECE: {r.overall.expected_calibration_error:.3f}")
for tier, report in sorted(r.by_tier.items()):
    print(f"  {tier}: ECE={report.expected_calibration_error:.3f}, n={report.total_predictions}")
```

The convenience entry point `compute_tier_breakdown_calibration_from_report()` pulls the predicted tier from `record.risk_tier`. The breakdown groups by the AGENT'S predicted tier, not the expected tier; this is the more useful production-monitoring framing since the expected tier is not always known.

Tiers with zero outcomes are omitted from the `by_tier` dict rather than producing vacuous-zeros reports.

## Deferred

- `[deferred-phase-4-followup]` Equal-frequency (quantile) binning option
- `[deferred-phase-4-followup]` Reliability diagram rendering (SVG)
- `[deferred-phase-5]` Bootstrap confidence intervals on ECE / Brier
- `[deferred-phase-5]` Calibration drift detection across time windows
- `[deferred-phase-5]` Per-disposition calibration breakdown (analogous to per-tier)
