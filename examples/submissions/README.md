# Demo vendor submissions

Five hand-curated vendor risk submissions used for sales demos, end-to-end testing, and as a worked example of what a real triage input looks like.

| # | File | Tier | Disposition | Lens |
|---|------|------|-------------|------|
| 1 | `01-tier1-internal-productivity.json` | Tier 1 low | approve | OSFI |
| 2 | `02-tier2-customer-service-chatbot.json` | Tier 2 moderate | conditional_approve | OSFI |
| 3 | `03-tier3-document-ocr-loans.json` | Tier 3 elevated | escalate_senior_review | OSFI (lead) |
| 4 | `04-tier4-autonomous-credit-decisioning.json` | Tier 4 high | reject | SOX + OSFI |
| 5 | `05-edge-embedded-ai-via-subprocessors.json` | Tier 3 elevated | escalate_senior_review | EU AI Act |

Each submission validates against `schemas/input-contract-1.0.0.schema.json`. The corresponding expected outputs live in `../expected-records/` paired by filename prefix.

## Using the scenarios

The combined dataset in `eval/datasets/demo-scenarios.jsonl` ties each submission to its expected record plus a `reviewer_notes` field explaining what behavior the scenario is meant to demonstrate.

For a live demo:

```bash
# View the scenario summary
cat examples/submissions/03-tier3-document-ocr-loans.json | jq '{
  vendor_name, jurisdiction, ai_usage_level,
  pii_categories: .pii_processing_claims.categories
}'

# View the expected output
cat examples/expected-records/03-tier3-document-ocr-loans.expected.json | jq '{
  risk_tier, recommended_disposition,
  required_mitigations
}'
```

## Editing a scenario

If you edit a submission or expected record:

1. Re-run `pytest tests/test_demo_scenarios.py` to verify schema conformance and internal consistency
2. Rebuild the JSONL dataset (the file-consistency tests will catch drift, but the dataset must be regenerated to reflect changes):

```bash
# The dataset is currently rebuilt manually via the scripts in the
# commit that created it. A `scripts/rebuild_demo_dataset.py` helper
# is a Phase 6 deliverable.
```

## What "hand-curated" means

These golden expected_records were authored by a human consulting the input contract and the framework's classification taxonomy in `docs/phase-0/01-risk-classification.md`. They are not LLM-generated. A future commit can regenerate them via a real LLM call once bundle distribution is wired up; the hand-curated baseline gives a deterministic anchor against which LLM-generated alternatives can be compared.
