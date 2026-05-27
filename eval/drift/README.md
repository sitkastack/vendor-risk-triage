# eval/drift

Drift detection for the vendor risk triage agent. Catches unexpected classification changes between framework versions.

## What problem this solves

Every time the SYSTEM_PROMPT changes, the framework version bumps, or the eval logic shifts, the agent might produce different decisions on the same inputs. Drift detection turns "might" into a verifiable check.

The pattern: a baseline file records what the framework produces today for each of the five demo scenarios. After any agent or framework change, `python scripts/check_drift.py` re-runs the same scenarios and diffs the results against the baseline. Differences surface as drift; the developer either fixes the regression or accepts the change by regenerating the baseline.

## What gets checked

**Hard drift** (always a CI failure):

- `risk_tier` value changed
- `recommended_disposition` value changed
- `accountable_owner` presence changed (was None, now set, or vice versa)
- `evidence_cited` entry count changed
- `regulatory_framework_tags` set changed

Hard drift indicates a real classification change with workflow impact.

**Soft drift** (CI failure with bypass message):

- `confidence_signal.score` differs by more than threshold (default ±0.05)
- `classification_rationale` text differs
- `required_mitigations` text differs
- `accountable_owner` text differs (when both records have an owner)
- Any `evidence_cited` entry's `input_field_reference` or `reasoning` text differs

Soft drift catches stylistic and tonal changes within the same classification.

**Always ignored**:

- `decision_id`, `decision_timestamp` (per-run, not meaningful drift signals)
- `agent_version` (changes when intentional; recorded for traceability but not diffed)
- `input_submission_id`, `input_schema_version`, `output_schema_version` (input-dependent or schema-migration concerns, not drift)

## Usage

```bash
# Check for drift against the current baseline (CI integration)
python scripts/check_drift.py

# Regenerate the baseline after accepting a drift as intentional
python scripts/check_drift.py --update-baseline

# Override the confidence-delta threshold
python scripts/check_drift.py --threshold 0.10
```

Programmatic usage:

```python
from eval.drift import check_drift, load_baselines

baselines = load_baselines()
currents = your_runner_function()
report = check_drift(baselines=baselines, currents=currents)
if report.has_any_drift:
    print(f"{report.scenarios_with_hard_drift} scenarios with hard drift")
```

## Bypass mechanism

When a SYSTEM_PROMPT change or framework refinement intentionally shifts classifications:

1. Run `python scripts/check_drift.py --update-baseline`
2. Inspect the diff to `eval/baselines/demo-scenarios.baseline.jsonl`
3. Commit the new baseline along with the changes that produced the drift
4. A code reviewer asks "is this drift expected?" at review time

The bypass is intentional friction. A maintainer thinks before accepting a drift; the framework does not silently update the baseline on every change.

## What this catches vs. doesn't

**Catches**:

- Changes to the framework's record-construction logic
- Changes to the schema validation behavior
- Changes to evidence citation handling
- Changes to the agent's classification rules (via SYSTEM_PROMPT edits)
- Changes to the agent_version hash (caught at the assertion layer)

**Does NOT catch**:

- Actual LLM behavior changes (Claude updates, OpenAI model updates)
- Real-LLM nondeterminism

The check uses the deterministic FunctionModel-backed test double from `tests/test_demo_scenarios.py`. For real-LLM drift, the existing `real_llm` marker in `tests/integration/` is the right tool but requires API key + cost. A future Phase 6 deliverable adds `--real-llm` to the drift CLI.

## Deferred

- `[deferred-phase-6]` Real-LLM drift mode (`--real-llm` flag, gated by API key)
- `[deferred-phase-6]` Drift detection on a deployment's own scenario library (not just the framework's five demo scenarios). Customers would point the check at their own JSONL baseline.
- `[deferred-phase-7]` Continuous drift monitoring infrastructure (storage, scheduler, alerting). Out of scope; not framework code. See the planned sitkastack consulting-tooling repo.

## Testing

`tests/test_drift.py` covers:

- All hard-drift categories (tier, disposition, accountable_owner presence, evidence count, framework tags)
- All soft-drift categories (confidence delta, rationale, mitigations, owner text, evidence text)
- Float-tolerance on the confidence threshold (edge case: `abs(0.80 - 0.75)` is `~0.0500000000000001`)
- Always-ignored fields (decision_id, decision_timestamp, agent_version)
- check_drift cross-scenario aggregation
- Missing-from-current is hard drift; extra-in-current is ignored
- Baseline file round-trip (save then load)
- Baseline load error paths (missing file, malformed JSON, non-object, missing keys, invalid record)
- Comment-line skipping in baseline files
- revoked_at parsing on baseline load
- Demo scenarios baseline loads cleanly (5 records, tier 1 through tier 4 present)

47 tests total. 100% coverage on the package.
