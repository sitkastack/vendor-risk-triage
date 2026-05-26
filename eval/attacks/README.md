# Prompt-injection attack evaluation

This package adds attack-resistance evaluation to the framework's eval
harness. Where `eval/` (sub-system 3) measures tier and disposition
accuracy against graded examples, `eval/attacks/` measures the agent's
resistance to prompt-injection attacks.

## What ships

The package:

- `attack_example.py`: the `AttackExample` model carrying a payload
  (submission ± documents ± regulation chunks) and a set of
  assertions describing what the agent must (or must not) do
- `attack_dataset.py`: JSONL loader with content-hash provenance, the
  same pattern as the graded dataset
- `attack_runner.py`: `AttackEvalRunner` that constructs Document /
  Chunk instances from the dataset payload, invokes the agent, and
  grades against the assertions
- `attack_metrics.py`: overall, per-category, and per-threat-id
  pass-rate aggregation

Dataset:

- `eval/datasets/prompt-injection-baseline.jsonl`: 12 synthetic attacks
  covering eight attack categories and threats T-AI1 (prompt injection)
  and T-AI2 (output schema manipulation)

## Design decisions

### Separate runner from `TriageEvalRunner`

The attack runner is not an extension of the graded runner. The two
have fundamentally different success criteria: a graded example passes
when tier and disposition match a known-correct outcome, an attack
passes when the agent successfully resists the injection (which often
means producing *any* defensible classification, not a specific one).
Composing them through a shared base class would muddy both.

### Composable single-model assertion

A single `AttackExample` type covers all attack categories. Each
attack declares any subset of:

- `tier_must_be_in`: acceptable tier outcomes
- `disposition_must_be_in`: acceptable disposition outcomes
- `rationale_must_not_contain`: forbidden phrases (case insensitive)
- `expected_to_raise`: an exception class name; mutually exclusive with
  the three above

An attack passes only if every declared assertion holds. An attack with
no declared assertions is rejected at construction time; silently-
passing attacks are worse than no test.

### Synthetic attacks, not wild ones

The baseline dataset is hand-crafted attack patterns matched to T-AI
threat categories. The framework does not ship real jailbreak prompts
from the wild. Reasons:

- Reproducibility: a synthetic attack means the same outcome on every
  model version
- IP cleanliness: published jailbreak corpora often have licensing
  ambiguity
- Threat-model coverage: the synthetic set deliberately spans every
  T-AI1/T-AI2 attack class rather than over-indexing on whatever is
  popular this quarter

### Threat-id rollups

Each attack carries `threat_ids: list[str]` pointing at threat-model
entries. Aggregate metrics roll up pass rates per threat id so an
auditor can ask "what's our T-AI1 attack pass rate on this model
version?" and get a number.

Double-counting is intentional: an attack declaring
`threat_ids=["T-AI1", "T-AI2"]` contributes to both T-AI1 and T-AI2
metrics. The attack provides signal on both threats; both rollups
should reflect that signal.

### Pass rate = good (high is good)

The metrics report attack PASS rate, where passing means the agent
successfully resisted the injection. High pass rate = good agent.
This avoids the double-negative of "attack success rate" where lower
is better; pass-rate is more legible in dashboards and audit reports.

## Attack categories

The `AttackType` literal enumerates eight categories:

- `direct_injection_submission`: injection text in a free-text field of
  the submission (e.g., `pii_processing_claims.handling_notes`)
- `direct_injection_document`: injection text in a vendor document
  (e.g., a SOC 2 PDF whose extracted text contains "ignore previous
  instructions")
- `direct_injection_regulation`: injection text in a regulation chunk
  (corpus-tamper scenario)
- `tier_manipulation`: injection demanding a specific risk_tier outcome
- `disposition_manipulation`: injection demanding a specific
  recommended_disposition outcome
- `schema_manipulation`: injection attempting to break the output
  schema (extra fields, format override)
- `rationale_manipulation`: injection attempting to inject canary text
  into classification_rationale
- `bait_and_switch_document`: submitted document content_hash does not
  match the document's actual hash; agent must reject before LLM call

The categories are not exclusive (a `tier_manipulation` attack is also
a kind of injection), but each `AttackExample` picks one primary
category for metric rollup. `threat_ids` carries the precise threat-
model linkage.

## Usage

```python
from agent.agent import TriageAgent
from eval.attacks import (
    AttackEvalRunner,
    compute_attack_metrics,
    load_attack_dataset,
)

agent = TriageAgent()  # real or stub
runner = AttackEvalRunner(agent)
dataset = load_attack_dataset("eval/datasets/prompt-injection-baseline.jsonl")

report = runner.run(dataset)
metrics = compute_attack_metrics(report)

print(f"Overall attack pass rate: {metrics.overall_pass_rate:.1%}")
for cat in metrics.by_category:
    print(f"  {cat.attack_type}: {cat.pass_rate:.1%} ({cat.passed}/{cat.total})")
for tid in metrics.by_threat_id:
    print(f"  {tid.threat_id}: {tid.pass_rate:.1%} ({tid.passed}/{tid.total})")
```

Failed outcomes carry `failure_reasons` describing each assertion that
held false. Inspect them when triaging a regression in attack pass rate:

```python
for outcome in report.outcomes:
    if not outcome.passed:
        print(outcome.attack_id, outcome.failure_reasons)
```

## Building your own attack dataset

The baseline is a starting point. Real deploying organizations should
add attacks specific to their model, their regulators, and the social
engineering patterns they actually see. Each attack in the dataset is
one JSON object per line:

```jsonl
{"attack_id": "attack-yours-1", "attack_type": "tier_manipulation", "threat_ids": ["T-AI1"], "description": "...", "submission": {...}, "tier_must_be_in": ["tier_3_elevated", "tier_4_high"], "rationale_must_not_contain": ["..."], "notes": "..."}
```

Lines starting with `#` are comments. Blank lines are permitted. The
content_hash is computed over the raw file bytes (including comments)
so any change registers as a dataset change for audit purposes.

## Deferred

- `[deferred-phase-4-followup]` Automated attack generation from a
  templating grammar (more attack diversity from fewer hand-crafted
  templates)
- `[deferred-phase-4-followup]` Adversarial fine-tuning evaluation
  (does the LLM resist injection after fine-tuning on benign examples?)
- `[deferred-phase-5]` Continuous attack regression in CI (run nightly
  against latest model versions; alert on pass-rate drops)
- `[deferred-phase-5]` Real-world attack corpus integration (curated
  from OWASP LLM Top 10 published examples, with license-cleared
  redistribution)
