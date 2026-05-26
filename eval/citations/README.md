# Citation verification

This package gives the framework its first concrete hallucination
signal. The agent's output contract requires every classification
decision to carry `evidence_cited` entries pointing at submission
fields, documents, or regulation chunks. Citation verification answers
two questions for each record:

1. **Reference verifiability** (deterministic): does the cited path
   actually resolve in the inputs?
2. **Chunk grounding** (heuristic): when the LLM cites a regulation
   chunk and makes a claim about it, does the claim's vocabulary
   actually appear in that chunk?

What this package does NOT measure is semantic grounding - whether the
chunk actually *entails* the LLM's specific claim. Token overlap is
necessary but not sufficient for grounding. Sub-system 4 (LLM-as-judge)
addresses semantic verification.

## What ships

- `citation_verifier.py`: the `CitationVerifier` class and result models
  (`FieldCitationResult`, `ChunkCitationResult`,
  `RecordVerificationResult`)
- `citation_metrics.py`: `CitationAggregateMetrics` and
  `compute_citation_metrics()` for dataset-level rollups
- `__init__.py`: public API surface

The verifier is fully deterministic: no LLM calls, no network, no
credentials needed in test or runtime.

## Reference resolution

The agent populates `evidence_cited[i].input_field_reference` with a
reference to a submission field. The output contract describes the
format as "a field name or JSON pointer." The verifier supports both
the bare-field convention and a JSONPath-lite convention:

```
vendor_id
$.vendor_id
$.pii_processing_claims.handling_notes
$.documentation_artifacts[0]
$.documentation_artifacts[0].artifact_type
```

The parser is a small in-file implementation (no external JSONPath
dependency). It handles the patterns the contract uses; anything more
exotic surfaces as `unresolvable_path` rather than crashing.

Statuses surfaced per field citation:

- `resolved`: the reference points at an existing field
- `unresolvable_path`: the path does not navigate to anything (missing
  field, wrong type)
- `out_of_bounds`: an array index exceeded the array length

## Chunk citation extraction

The Phase 3 sub-system 5 system prompt instructs the LLM to cite
regulation chunks in the reasoning text by their `chunk_id`. The
verifier extracts chunk_id mentions with a regex matching the
framework's chunk_id format (`{corpus}:{document}:page-{N}`).

For each mention:

- If the `chunk_id` exists in the supplied `regulation_chunks` list,
  status is `resolved`
- If it does not, status is `unknown_chunk` (the LLM cited a chunk
  that was not retrieved for it - strong hallucination signal)

The regex is heuristic. It may miss creative phrasings ("see OSFI E-23
page 7") and may rarely false-positive on incidental colons in prose.
A future contract bump adding a structured `cited_chunk_ids: list[str]`
field to `EvidenceCitation` would replace this heuristic with exact
extraction; it's tagged `[deferred-phase-4-followup]`.

## Token-overlap grounding score

For each `resolved` chunk citation, the verifier computes Jaccard
similarity between the tokenized reasoning text and the tokenized
chunk text:

```
grounding_score = |reasoning_tokens ∩ chunk_tokens| / |reasoning_tokens ∪ chunk_tokens|
```

A low score indicates the LLM's reasoning and the cited chunk share
few tokens, which is a candidate hallucination signal. A high score
indicates strong vocabulary alignment but does NOT prove correct
grounding - the LLM could be repeating the chunk's tokens while
asserting the opposite.

The threshold for flagging a chunk citation as `is_possibly_ungrounded`
defaults to `0.15`. Tune to your model and corpus: empirical
calibration on a labelled dataset is the only way to set this with
confidence. Setting `grounding_threshold=0.0` disables the flag while
still emitting the score.

Tokenization reuses `retrieval.tokenize()` so the rules match the BM25
indexing pipeline: lowercase, preserve regulation-acronym punctuation
(`e-23`, `cc6.1`), skip pure-punctuation tokens.

## Usage

Per record:

```python
from eval.citations import CitationVerifier

verifier = CitationVerifier()
result = verifier.verify_record(
    record=triage_record,
    submission=submission_dict,
    documents=docs_list,
    regulation_chunks=chunks_list,
)
for fc in result.field_citations:
    if fc.status != "resolved":
        print(fc.input_field_reference, fc.detail)
for cc in result.chunk_citations:
    if cc.is_possibly_ungrounded:
        print(cc.chunk_id, cc.grounding_score, cc.reasoning_excerpt)
```

Across a dataset of records:

```python
from eval.citations import compute_citation_metrics

results = [verifier.verify_record(rec, sub, docs, chunks) for rec, sub, docs, chunks in pairs]
metrics = compute_citation_metrics(results)
print(f"Field resolution rate: {metrics.overall_field_resolution_rate:.1%}")
print(f"Chunk resolution rate: {metrics.overall_chunk_resolution_rate:.1%}")
print(f"Grounding avg: {metrics.overall_chunk_grounding_avg}")
print(f"Records with grounding flag: {metrics.records_with_any_grounding_flag}/{metrics.total_records}")
```

## Composing with the graded-eval and attack datasets

The verifier is a primitive. It composes naturally with:

- The graded-example dataset (sub-system 3): run the agent over the
  dataset, then verify citations on each TriageRecord produced. Low
  resolution rate on a tier-correct agent indicates the LLM produces
  unreliable citations even when its top-level classification is right.
- The attack dataset (sub-system 1): after an attack runs, the
  resulting record (if the agent returned one) can be verified. A
  citation pattern shift under attack indicates injection bypass even
  when the attack pass-rate looks healthy.

## Deferred

- `[deferred-phase-4-followup]` Structured `cited_chunk_ids: list[str]`
  field on `EvidenceCitation` (output contract 1.1.0). Replaces the
  regex-based chunk-id extraction with exact extraction.
- `[deferred-phase-5]` Semantic grounding via NLI / entailment models
  (heavyweight; requires a model dependency)
- `[deferred-phase-5]` Position-aware citations within a chunk (e.g.,
  "paragraph 3" or character offsets)
- `[deferred-phase-5]` Citation completeness check (did the LLM cite
  every source it actually used?). Requires a model-of-the-model and is
  closer to interpretability than verification.

Out of scope, intentionally:

- Auto-correction of bad citations. If the agent hallucinates, the
  record is invalid. The verifier surfaces it; downstream code decides
  whether to retry, escalate, or reject.
