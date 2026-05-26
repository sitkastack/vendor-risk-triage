# LLM-as-judge evaluation

This package provides the framework's semantic evaluation signal:
whether the agent's reasoning is *defensible*, not just whether its
outputs match a label. The graded eval (sub-system 3) answers "did
the agent assign the right tier?". Citation verification (sub-system
2) answers "do the references resolve?". The LLM judge answers "does
the agent's reasoning actually justify the tier it assigned?"

These are the questions auditors ask in person. The previous Phase 4
sub-systems address them mechanically; this one addresses them
semantically.

## What ships

- `judge.py`: the `LLMJudge` class, `Rubric` model, `JudgeResult`
  model
- `rubrics.py`: three pre-built rubrics (`RATIONALE_COHERENCE`,
  `CITATION_GROUNDING`, `MITIGATION_APPROPRIATENESS`)
- `metrics.py`: `compute_judge_metrics()` and the aggregate models
- `__init__.py`: public API

The judge is vendor-agnostic: it wraps any PydanticAI Model. Cross-
model judging (e.g., agent on Claude, judge on GPT-4) is the
recommended setup but not enforced - that's a deploying-org policy
decision.

## Pre-built rubrics

### RATIONALE_COHERENCE

Does the agent's `classification_rationale` provide a defensible
chain of reasoning from the specific facts in the submission to the
assigned tier and disposition? Always goes to the LLM; no
short-circuit.

### CITATION_GROUNDING

For each chunk citation in the agent's `evidence_cited`, does the
cited regulation chunk actually support the claim?

Short-circuit: if no regulation chunks were supplied AND no chunk_ids
appear in any reasoning text, the rubric returns score=1.0 without an
LLM call (vacuously satisfied; nothing to grade). If chunks are
supplied OR reasoning mentions a chunk_id (potentially fabricated),
the LLM grades.

### MITIGATION_APPROPRIATENESS

When `recommended_disposition` is `conditional_approve`, do the
`required_mitigations` address the risks the rationale identifies?

Short-circuit: if disposition is not `conditional_approve`,
mitigations don't apply and the rubric returns score=1.0 without an
LLM call. Only `conditional_approve` records are graded by the LLM.

## Usage

```python
from pydantic_ai.models.anthropic import AnthropicModel  # or any other
from eval.judge import (
    LLMJudge,
    RATIONALE_COHERENCE,
    CITATION_GROUNDING,
    MITIGATION_APPROPRIATENESS,
    compute_judge_metrics,
)

judge = LLMJudge(model=AnthropicModel("claude-opus-4-5"))

results = []
for record, submission, docs, chunks in pairs:
    for rubric in (RATIONALE_COHERENCE, CITATION_GROUNDING, MITIGATION_APPROPRIATENESS):
        result = judge.judge(record, submission, rubric,
                             documents=docs, regulation_chunks=chunks)
        results.append(result)

metrics = compute_judge_metrics(results)
for rm in metrics.by_rubric:
    print(f"{rm.rubric_name}: mean={rm.mean_score:.3f} "
          f"min={rm.min_score:.3f} max={rm.max_score:.3f} "
          f"(stdev={rm.score_stdev:.3f if rm.score_stdev else 'n/a'})")
```

## Important caveats

### Self-judging is a known weakness

The same model producing and grading reasoning yields correlated
errors: the judge may approve of reasoning patterns the agent
generates because both share the same priors. For audit-grade
evaluation, run the judge on a different model from the triage agent.

A cheaper but weaker mitigation: use the same model with a
substantially different system prompt and temperature. Stronger
mitigation: actual cross-model.

The framework does not enforce cross-model setups. That's a deploying-
organization policy decision that depends on which models the org is
licensed to use.

### Non-determinism is acknowledged

The judge's score on a given record can differ between runs. This is
a property of LLMs, not a bug. Each `JudgeResult` carries
`judge_model_version` and `run_timestamp` so audit trails capture
which call produced which score.

Implications for metrics: a single judge run gives one estimate; for
audit, run the judge multiple times on critical examples and report
the score distribution, not just the mean. The framework supports this
naturally - just append more `JudgeResult`s to the aggregate input.

### The judge can hallucinate

The judge is itself an LLM. It may give high scores to reasoning that
appears authoritative but is incorrect, and low scores to reasoning
that is correct but unusually phrased. Treat judge scores as one
signal among several (graded accuracy, citation verification, attack
resistance, calibration), not as ground truth.

The hardest failure mode: the judge agreeing with confidently-stated
falsehoods. The README on citation verification (sub-system 2) gives
the deterministic counterweight - cross-reference judge scores
against the citation verifier's chunk_id resolution rates.

### Prompt injection reaches the judge

The judge's user prompt contains the full submission, which may carry
injection content in free-text fields (the same T-AI1 attack surface
the triage agent faces). Implications:

- The judge is grading reasoning, not producing actionable output. An
  injection that hijacks the judge produces a wrong score, not a
  wrong classification.
- The judge's output is constrained by Pydantic to `{score, rationale}`.
  Injection cannot produce malformed JSON or extra fields; PydanticAI
  enforces the structure.
- Score variance across repeated runs surfaces injection-induced
  instability. Records whose judge scores swing wildly between runs
  are candidates for human review.

This is a real concern, not a paper one. Run the attack dataset
(sub-system 1) against the judge separately if your threat model
warrants it.

### Cost is non-trivial

Each rubric call is one LLM round-trip. Three rubrics x 100 records =
300 calls. At typical pricing this is a few dollars per 100-record
run; consult your provider's rate sheet. The framework does not cap
or batch; that's `[deferred-phase-5]`.

For development, use `FunctionModel` or `TestModel` to avoid real LLM
costs. For dataset-level production evaluation, plan the budget.

## Custom rubrics

The pre-built rubrics are starting points. Add organization-specific
criteria with `Rubric()`:

```python
from eval.judge import Rubric, LLMJudge

regulatory_specificity = Rubric(
    name="regulatory_specificity",
    description=(
        "Does the agent's regulatory_framework_tags accurately identify "
        "every regulation that applies to this submission, with no "
        "missing frameworks and no inapplicable frameworks included? "
        "Score 1.0 if every applicable framework is tagged and no "
        "inapplicable framework appears. Score 0 if material frameworks "
        "are missing OR inapplicable ones are tagged."
    ),
)

result = judge.judge(record, submission, regulatory_specificity)
```

Rubric names must be snake_case starting with a letter (validated by
the model). Descriptions are embedded verbatim in the judge's user
prompt; tune them for specificity.

For criteria with deterministic short-circuit logic, pass an
`edge_case_handler` callable. See the pre-built rubrics for examples.

## Deferred

- `[deferred-phase-4-followup]` Multi-criterion bundling: one LLM
  call evaluates multiple rubrics simultaneously to reduce per-record
  cost
- `[deferred-phase-4-followup]` Paired comparison: present two records
  to the judge and ask which is more defensible. Useful for ranking
  comparisons.
- `[deferred-phase-5]` Rate limiting and batch scheduling for large
  dataset runs
- `[deferred-phase-5]` Judge model agreement metrics: how much do two
  judge models disagree on the same record?
- `[deferred-phase-5]` Judge calibration against human-graded gold
  standard: when the judge says 0.7, is it actually right 70% of the
  time against expert reviewers?
