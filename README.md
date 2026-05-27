# vendor-risk-triage

A reference implementation of an AI agent that performs vendor and third-party AI risk triage, built in the open under Apache 2.0.

## What this is

Mid-market companies in regulated industries are now expected to assess the AI risk of every vendor they onboard. The list of obligations keeps growing: model provenance, data handling, prompt injection exposure, log retention, fine-tuning posture, and more, all driven by frameworks like NIST AI RMF, the EU AI Act, OSFI Guideline E-23, SOX/ICFR, and ISO/IEC 42001, plus sectoral regulators and internal audit committees. Most teams answer this with a spreadsheet and a vibe check.

This repository is a working pattern for doing it deliberately. An agent ingests a vendor's documentation, retrieves relevant regulation context, classifies the engagement against a defined risk taxonomy, and produces an audit-ready triage record. A full evaluation harness measures the agent's accuracy, calibration, citation grounding, and resistance to prompt injection.

It is part of the [sitkastack Framework](https://sitkastack.com), a public body of work on shipping audit-ready AI inside regulated mid-market companies. Everything here is intended to be forked, adapted, and pressure-tested against your own regulatory context.

## Status

**Phases 0 through 4 are live. The framework is feature-complete at the code level for vendor risk triage with full evaluation depth.**

| Phase | Status |
|---|---|
| Phase 0: Discovery & Risk Classification | live |
| Phase 1: Data Contracts & Privacy | live |
| Phase 2: Architecture & Threat Model | live |
| Phase 3: Agent + RAG + Ingestion + Eval | live |
| Phase 4: Eval Depth + Retrieval Quality | live |
| Phase 5: Operational Hardening | upcoming |
| Phase 6: Production Polish | upcoming |

Current framework version: `0.6.0`. Test suite: 568 tests, 100% coverage across all seven Python packages.

## What's in this repository

### Python packages

`agent/` is the PydanticAI-based triage agent, vendor-agnostic across LLM providers. It accepts a submission plus optional pre-extracted documents and retrieved regulation chunks, and produces a structured `TriageRecord` conforming to the output contract.

`ingestion/` is the PDF document parsing layer with bait-and-switch hash verification against the submission's claimed `content_hash` values. Any document whose extracted content fails the hash check causes the agent to refuse before any LLM call.

`retrieval/` provides three retrieval strategies over regulation corpora. `BM25Index` is lexical retrieval via `rank-bm25`. `VectorIndex` is dense semantic retrieval over the `Embedder` Protocol (with `HashEmbedder` and `SentenceTransformerEmbedder` shipped). `HybridIndex` combines both via Reciprocal Rank Fusion. The `Retriever` wraps any of them uniformly. `IndexBundle` persists chunks + pre-computed embeddings to disk as a single tar.gz file with content-hash verification and atomic save, eliminating the ~30-second cold-start embedding cost for production deployments.

`eval/` is the graded-example evaluation harness. It runs the agent over a JSONL dataset and produces tier-accuracy, disposition-accuracy, and joint-accuracy metrics.

`eval/attacks/` is a prompt-injection attack suite with 12 baseline attacks spanning 8 categories. Threats T-AI1 (prompt injection) and T-AI2 (output schema manipulation) are covered. Pass rate is reported overall, per category, and per threat ID.

`eval/citations/` is the deterministic citation verifier. It resolves `input_field_reference` paths via a JSONPath-lite parser, extracts chunk_id mentions from reasoning text, and computes Jaccard token-overlap grounding scores. No LLM calls. Four distinct outcome statuses preserve audit signal a boolean would collapse.

`eval/calibration/` is the calibration scorer: Brier score, Expected Calibration Error, Maximum Calibration Error, and reliability-diagram data over `(confidence_score, was_correct)` pairs. Tier, disposition, and both-match dimensions are configurable.

`eval/judge/` is the LLM-as-judge harness. It wraps any PydanticAI Model and grades a TriageRecord against a `Rubric`. Three pre-built rubrics ship: rationale coherence, citation grounding, and mitigation appropriateness. Edge-case short-circuits handle vacuous cases without an LLM call. Audit traceability through `judge_model_version` and `run_timestamp`.

### Documentation

The phase-by-phase design documents live in `docs/`:

- `docs/phase-0/` covers the problem definition, regulatory framework mapping, and scope boundaries
- `docs/phase-1/` covers data contracts, privacy spec, synthetic data specification, and the extension guide
- `docs/phase-2/` covers system architecture, trust boundaries, the full threat model (T-AI1 through T-AI8), and the architecture decision records
- Each Python package additionally carries its own `README.md` with package-specific design rationale

### Schemas and examples

`schemas/` holds the JSON Schema 2020-12 contracts for input submissions and output records. `examples/` holds runnable example records validated against the schemas in CI on every push.

## Installation

```bash
pip install -e .
```

Optional dense and hybrid retrieval (adds sentence-transformers, around 80MB for the default model):

```bash
pip install -e '.[vector]'
```

Development dependencies (pytest, pytest-cov):

```bash
pip install -e '.[dev]'
```

Python 3.11 or later required.

## Governance as code

The framework's governance is partially executable, not just documented:

- **Data contracts** are JSON Schema 2020-12 artifacts in `schemas/`. The Python utility in `schemas/validate.py` validates submissions and records against them. ADR-004 documents the closure properties (`unevaluatedProperties: false`, `additionalProperties: false`) the schemas enforce.
- **Examples** in `examples/` are verified against the schemas by `tests/test_examples_validate.py`, enforced on every push and PR by `.github/workflows/validate.yml`.
- **Bait-and-switch defense** is enforced at the agent boundary. Any document whose `content_hash` does not match the submission's claimed hash causes the agent to raise `TriageInputError` before any LLM call. See the threat model entry for T-AI4.
- **Prompt-injection resistance** is measurable through the `eval/attacks/` suite. The baseline dataset covers T-AI1 and T-AI2; deploying organizations are expected to extend with attacks specific to their threat surface.
- **Citation grounding** is measurable through `eval/citations/` (deterministic, token-overlap) and `eval/judge/` (semantic, LLM-graded).
- **Confidence calibration** is measurable through `eval/calibration/`. Every TriageRecord carries a `confidence_signal.score`; the calibration scorer answers whether stated confidence corresponds to empirical accuracy.
- **Style discipline** (no em dashes in prose) is enforced in CI.

What is still documented-only and not yet executable: model cards, DPIA templates, and the formal audit-log shipping format land in Phase 5. The framework's commitment is that wherever governance can be machine-readable, it will be.

## Roadmap

Phase 5 (Operational Hardening) covers multi-tenant corpora, schema migration patterns, audit-log shipping format, drift detection, and persistent indexes. Closes most of the remaining `[deferred-phase-5]` tags.

Phase 6 (Production Polish) covers observability hooks, cost tracking, model fallback, CI/CD patterns for deployers, and performance optimization. Closes the remaining `[deferred-phase-4-followup]` and `[deferred-phase-6]` tags.

The original Phase 7 (Sunset Planning) on the early roadmap will fold into Phase 6 if it lands at all. Decommissioning patterns for an AI system in regulated use are real but small in scope.

Phases ship when ready. Each phase lands as its own set of commits with design docs, code, tests, and audit results in the same commit history.

## Test discipline

Every code commit lands with:

- 100% line coverage on every Python package (enforced in CI at 95% with intent to hold 100%)
- A 23-persona brutal audit pass with zero must-fix findings. The roster covers 15 always-on personas (Solution Arch, App Arch, Security Arch, Data Arch, Cloud/Infra Arch, Integration Arch, Enterprise Arch, Tech Lead, two Peer Devs, QA Eng, AppSec Eng, Performance Eng, Tech Writer, Product Mgr), 9 certified-AI-governance personas (CISA, CISM, CRISC, CDPSE, CCOA, AAIA, AAIR, AAISM, CGEIT), and competitive-defense review.
- Three stability runs of the full test suite at the same passing count

Coverage and tests are enforced in CI. The audit discipline is enforced by the author.

### Integration tests against real corpora

The default `pytest` run is fast and offline (unit tests only). A separate integration test suite exercises the framework end-to-end against real regulation PDFs (OSFI E-23, NIST AI RMF, EU AI Act, SOX):

```bash
pytest -m integration                       # default agent (FunctionModel; free, fast)
pytest -m "integration and real_llm"        # real LLM (requires ANTHROPIC_API_KEY, costs money)
```

PDFs are fetched from authoritative sources on first run, cached to `~/.cache/sitkastack-vrt/corpora/`, and SHA-256 verified against pinned hashes. Network failures and missing PDFs skip cleanly rather than fail. See `tests/integration/README.md` for setup, pin-update workflow, and how to add a new corpus.

The OSFI E-23 corpus is not redistributed in the repo because Crown copyright reproduction terms are non-commercial-only; the integration test fetches it from osfi-bsif.gc.ca at run time. See `docs/corpus-manifest.md` for licensing details on every supported regulation.

## How to follow along

- Watch this repo for new phases as they land
- Read the docs phase by phase. They are numbered and intended to be read in order.
- Each Python package carries its own README walking through design rationale
- Follow [sitkastack.com](https://sitkastack.com) for the broader framework context
- Open an issue if something is unclear, wrong, or contradicts your real-world experience

## Limitations and known gaps

This is intentionally honest:

- **Reference implementation, not production audit defense out of the box.** Phases 0 through 4 ship the code and the evaluation discipline. Production readiness (Phase 5 and 6) covers operational concerns: corpus management, drift detection, audit-log export, deployment patterns. Do not point Phase 4 at a real vendor onboarding flow and assume the output will hold up under regulatory scrutiny without the Phase 5 and 6 work plus organization-specific calibration.
- **Real regulation corpora are user-provided.** The framework ships the retrieval machinery and a synthetic test corpus. Real corpora (OSFI E-23, ISO 42001, NIST AI RMF, EU AI Act, SOX/ICFR) are licensed differently and not redistributed. Deploying organizations provision their own authorised copies.
- **Calibration sample is small.** The bundled graded baseline has 8 examples, useful for exercising the math but too small for production calibration claims. Real calibration measurement requires hundreds to thousands of graded examples specific to the deploying organization.
- **LLM-as-judge is non-deterministic and can itself hallucinate.** The judge is an LLM. Cross-model judging (different model from the triage agent) is recommended but not enforced. Treat judge scores as one signal among several, not as ground truth.
- **Artifacts are adaptable templates, not finished compliance deliverables.** The risk taxonomy and contracts are designed to be modified for your specific regulatory context. They will not survive a serious audit unchanged.
- **Solo work, no external peer review at this stage.** Everything here reflects one author's judgment. Issues and PRs from practitioners with real audit and procurement experience are explicitly welcome.

If you spot something that is wrong or oversimplified, opening an issue is the most useful thing you can do.

## Examples

### Contract examples

The `examples/` directory contains illustrative JSON files used to verify integrations against the Phase 1 contracts. Every example validates against its schema in CI on every push and PR.

- `examples/input-submission.example.json` is a valid input submission against the Input Contract schema
- `examples/triage-record.example.json` is a valid triage record paired with the input example, against the Output Contract schema
- `examples/validation-error.example.json` is the shape of a structured validation error response from the intake validator

### Demo scenarios

Five hand-curated end-to-end scenarios spanning all four risk tiers plus an edge case live under `examples/submissions/` and `examples/expected-records/`. The scenarios mix jurisdictions (OSFI lead, SOX, EU AI Act, cross-jurisdiction) and demonstrate the framework's behavior on realistic vendor risk reviews:

- **01-tier1-internal-productivity**: Internal note-taking AI with no PII, productivity-only role. Approve.
- **02-tier2-customer-service-chatbot**: Customer-facing ticket triage with human-confirmed routing. Conditional approve with explicit mitigations.
- **03-tier3-document-ocr-loans**: Document OCR for KYC/loans with cross-border AI sub-processor. Escalate to senior review.
- **04-tier4-autonomous-credit-decisioning**: Fully autonomous credit decisioning system. Reject.
- **05-edge-embedded-ai-via-subprocessors**: Disclosure inconsistency: vendor claims minimal AI, sub-processors reveal otherwise. Escalate.

The full dataset is in `eval/datasets/demo-scenarios.jsonl` with each scenario carrying its submission, expected record, and reviewer notes explaining what audit-readiness behavior the scenario is meant to demonstrate.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contact

Built by Robyn Toor. Contact: [robyn@sitkastack.com](mailto:robyn@sitkastack.com).
