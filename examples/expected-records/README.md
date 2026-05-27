# Expected triage records

Golden TriageRecord outputs paired by filename prefix with the submissions in `../submissions/`.

Each record validates against `schemas/output-contract-1.0.0.schema.json` and reflects the classification a human risk reviewer would produce when given the corresponding submission and applying the framework's classification taxonomy in `docs/phase-0/01-risk-classification.md`.

## Provenance

These records were hand-curated, not LLM-generated. The intent is to provide a deterministic anchor for testing the framework's pipeline plumbing: when a `FunctionModel`-backed agent is configured to return one of these records' classification fields, the framework should produce the full record exactly (modulo `decision_id` and `decision_timestamp`, which the framework generates fresh).

A future commit will regenerate these via a real LLM call and compare against the hand-curated baseline. The deltas will surface where the framework's LLM behavior disagrees with the human reviewer's framing, which is itself a useful audit signal.

## What's in each record

- `risk_tier` and `recommended_disposition` are the headline classification
- `classification_rationale` is the prose explanation a reviewer would write
- `evidence_cited` lists the submission fields the reviewer relied on, with reasoning per field
- `confidence_signal` records the calibrated confidence band
- `required_mitigations` (where applicable) names specific verification steps
- `accountable_owner` (where the disposition is `escalate_senior_review`) names the role responsible
- `review_interval_days` recommends the re-triage cadence
- `regulatory_framework_tags` flag which regulatory regimes the classification engaged with

## Confidence scores

The confidence scores in these records were chosen to reflect the actual analytic confidence of the curated decision, not a uniform "high" or "moderate" placeholder:

- Tier 1 productivity-only with clean documentation: high confidence (0.92)
- Tier 2 with clear human-confirmed controls but real PII flow: moderate (0.78)
- Tier 3 with cross-border AI sub-processor risk: moderate (0.74)
- Tier 4 reject with specific documentation gaps: high (0.88)
- Edge case with disclosure inconsistency: moderate (0.71)

These values exercise the calibration pipeline (`eval/calibration/`) end-to-end on realistic data points.
