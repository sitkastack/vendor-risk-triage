# Evaluation

This folder holds the eval harness and the graded example datasets used to
measure agent quality. Every meaningful change to the agent (a new prompt,
a new model, a new risk category) is run against the relevant datasets
before it lands, and the results are committed alongside the change.

## What ships now (Phase 3 sub-system 3)

The harness:

- `dataset.py`: the `GradedExample` and `Dataset` models and the JSONL loader
- `runner.py`: `TriageEvalRunner` plus `EvalReport`
- `metrics.py`: `ExampleResult`, `AggregateMetrics`, `compute_metrics`

One graded dataset:

- `datasets/tier-classification-baseline.jsonl`: eight graded examples, two
  per tier. Maps to **T-AI8 (Classification drift through provider model
  updates)** in `docs/phase-2/03-threat-model.md`. The baseline answers the
  question: when a provider silently updates its model, does the agent's
  classification still match human-graded expected outputs on a fixed
  stable suite? Running this dataset before and after a model update gives
  the audit answer.

Tier coverage in the baseline: two `tier_1_low`, two `tier_2_moderate`,
two `tier_3_elevated`, two `tier_4_high`. Two `tier_4` examples
deliberately differ in disposition (one expects `escalate_senior_review`,
one expects `reject`) so the eval also exercises the
mitigation-could-plausibly-reduce-risk decision boundary.

## What does not ship in sub-system 3 (and why)

The 2025 plan that originally lived in this README anticipated five
threat-mapped eval suites shipping in Phase 3. The honest MVP scope cuts
this to one suite plus the harness scaffolding, with the rest tagged for
follow-up work. Adding a new suite is just dropping a new JSONL file in
`datasets/` and writing the corresponding graded examples; no harness
code change is required.

Deferred eval suites (each is its own future commit):

| Suite | Threat | Why deferred |
|---|---|---|
| Prompt injection resistance | T-AI1 | Requires curated adversarial examples and a methodology for grading partial-bypass cases. Defer to a follow-up sub-system 3 commit. |
| Data exfiltration resistance | T-AI2 | Requires probes that try to elicit system-prompt content through valid output shapes. Methodology design needed. |
| Hallucination measurement | T-AI4 | Requires ground-truth knowledge of what the agent *should not* know plus a methodology for detecting confabulation. |
| Bias evaluation | T-AI6, T-AI7 | Requires careful methodology, expert review, and demographic attribute tagging on examples. Phase 4 work. |

Deferred eval-harness capabilities (Phase 4):

- **LLM-as-judge**: a second LLM grades the agent's rationale quality on
  axes (evidence sufficiency, framework citation accuracy) beyond exact
  tier/disposition match.
- **Calibration measurement**: many runs over the same dataset measure
  whether `confidence_signal.score` predicts correctness. Requires
  statistical aggregation across runs.
- **Concurrent execution**: the MVP runner is sequential. Concurrent
  execution matters at dataset sizes beyond ~50 examples or when LLM call
  latency dominates.

Deferred for Phase 5:

- **CI gating**: the validate workflow runs eval against the baseline
  dataset and fails if tier agreement drops below a configured threshold.
  Production deployment concern.
- **Drift detection**: scheduled eval runs detect classification drift
  over time. Requires a result store.

## Running an eval

```python
from pathlib import Path
from agent.agent import TriageAgent
from eval import TriageEvalRunner, load_dataset

agent = TriageAgent()  # default config; needs ANTHROPIC_API_KEY in env
dataset = load_dataset(Path("eval/datasets/tier-classification-baseline.jsonl"))
report = TriageEvalRunner(agent).run(dataset)

print(f"Agent: {report.agent_version}")
print(f"Dataset: {report.dataset_name} ({report.dataset_content_hash})")
print(f"Tier agreement: {report.metrics.tier_agreement_rate:.0%}")
print(f"Disposition agreement: {report.metrics.disposition_agreement_rate:.0%}")
```

## Adding a new graded example to the baseline

1. Append one line to `datasets/tier-classification-baseline.jsonl`
   following the existing format. Use a unique `id`.
2. Run `pytest tests/test_eval.py -v` to confirm the dataset still loads
   and the per-tier balance test still passes (if your example pushes one
   tier above two, you may need to rebalance by adding another).
3. Run the baseline eval to see the new example's behaviour.
4. Commit alongside the example.

## Adding a new suite

1. Create `datasets/<suite-name>.jsonl` with at least one graded example.
2. Add a row to the "Deferred eval suites" table above with the suite's
   threat mapping and (if applicable) move it out of "deferred" into the
   active suite list.
3. Add a test in `tests/test_eval.py` that loads the new dataset and
   asserts basic shape (non-empty, unique ids, expected fields populated).
4. Commit.
