# vendor-risk-triage

A reference implementation of an AI agent that performs vendor and third-party AI risk triage, built in the open under Apache 2.0.

## What this is

Mid-market companies in regulated industries are now expected to assess the AI risk of every vendor they onboard. The list of obligations keeps growing: model provenance, data handling, prompt injection exposure, log retention, fine-tuning posture, and more, all driven by frameworks like NIST AI RMF, the EU AI Act, OSFI Guideline E-23, SOX/ICFR, and ISO/IEC 42001, plus sectoral regulators and internal audit committees. Most teams answer this with a spreadsheet and a vibe check.

This repository is a working pattern for doing it deliberately. An agent ingests a vendor's documentation, retrieves relevant regulation context, classifies the engagement against a defined risk taxonomy, and produces an audit-ready triage record. A full evaluation harness measures the agent's accuracy, calibration, citation grounding, and resistance to prompt injection.

It is part of the [sitkastack Framework](https://sitkastack.com), a public body of work on shipping audit-ready AI inside regulated mid-market companies. Everything here is intended to be forked, adapted, and pressure-tested against your own regulatory context.

## Status

**Phases 0 through 7 are complete. The framework is code-complete for vendor risk triage: classification with full evaluation depth, observability, cost tracking, model fallback, release tooling, multi-tenancy, schema migration, and an end-to-end-verified pipeline.**

| Phase | Status |
|---|---|
| Phase 0: Discovery & Risk Classification | live |
| Phase 1: Data Contracts & Privacy | live |
| Phase 2: Architecture & Threat Model | live |
| Phase 3: Agent + RAG + Ingestion + Eval | live |
| Phase 4: Eval Depth + Retrieval Quality | live |
| Phase 5: Operational Hardening | live |
| Phase 6: Production Polish | live |
| Phase 7: Multi-tenancy + Schema Migration | live |

Current framework version: `1.0.1` (first stable release; published as `v1.0.1` on GitHub Releases). Test suite: 1,331 tests, 100% coverage across twelve Python packages. The full submission-to-audit-pack pipeline is verified end to end (`tests/test_e2e.py`) and validated against authoritative regulation PDFs (OSFI E-23 (2027) and EU AI Act Regulation 2024/1689) via the integration suite. See `docs/end-to-end-example.md` for a narrated walkthrough and `scripts/harvest_corpus_artifacts.py` for the real-corpus demo harness.

Output schema is frozen at `1.3.0`. CLI surface (`vrt {triage, render, migrate, drift, corpus, version}`) and `SYSTEM_PROMPT_HASH` (`69ef583c6dbe`) are stable. Breaking changes from this release forward ride in major version bumps; `vrt migrate` backfills records across schema versions.

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

`eval/drift/` is the drift detection package. Compares the framework's current decisions on the five demo scenarios against a checked-in baseline at `eval/baselines/demo-scenarios.baseline.jsonl`. Hard drift (tier, disposition, evidence count, framework tags) always fails CI; soft drift (confidence delta, rationale text, mitigation text) fails CI with a "regenerate baseline if intentional" bypass message. CI integrated via `scripts/check_drift.py`.

`reporting/` turns framework outputs into reader-facing HTML artifacts and ships records to operational pipelines. `audit_pack` renders one TriageRecord as a per-record document a risk committee or external auditor would read; `batch_index` renders a list of records as an overview index. `audit_log` wraps records in a content-hashed envelope for shipping to SIEMs, archives, and event buses. Self-contained HTML (inline CSS, no JavaScript, no external assets), print-stylesheet aware, white-label-friendly via a configurable attribution footer.

`observability/` provides structured event logging, metrics emission, and distributed tracing via Protocol-based sinks. Defaults are silent (no-op implementations); deployments wanting observability construct an `Observability` bundle with configured sinks and pass it to `TriageAgentConfig`. Twelve event names, ten metric names, and five span names are part of the public surface as of 0.7.0. The `[otel]` extra installs the OpenTelemetry tracer adapter for shipping spans to Honeycomb, Datadog, Jaeger, or any OTLP-compatible backend. See `docs/observability-guide.md` for Prometheus and StatsD adapter examples plus the correlation_id pattern for joining logs, metrics, and traces.

`pricing/` holds the model price table the framework uses to attach dollar cost estimates to TriageRecords. As of 0.8.0, the published table covers 33 models across four providers (Anthropic, OpenAI, Google, Mistral) with per-million-token input and output rates plus source URLs and verification dates. The `ModelPriceTable` class wraps the table in a lookup interface; deployments can substitute a custom table (with negotiated enterprise rates) by constructing `ModelPriceTable(prices=...)`. Standard rates only - batch API discounts, prompt caching, long-context surcharges, and regional uplifts are not modeled, so cost estimates are upper bounds on real-world spend. The `cost_estimate` field on TriageRecord records input_tokens, output_tokens, model_id, estimated_cost_usd, and the price_table_version that produced the figure, so an auditor reviewing an old record can see which prices were in effect at decision time.

`resilience/` provides automatic model fallback with circuit breaking. As of 0.9.0, `TriageAgentConfig` accepts `fallback_models` (a list of alternates tried in order when the primary fails) and `circuit_breaker` (an optional `CircuitBreakerConfig` enabling per-model failure tracking). The `CircuitBreaker` tracks each model's recent failure rate; when a model crosses the opening threshold (50% over 60s by default), its breaker opens and the model is skipped until a cooldown elapses, after which a half-open trial call restores or re-opens it. Failure counting is permissive (any exception counts). State storage is pluggable via the `BreakerStateStore` protocol with an in-memory default; deployments wanting shared state across processes implement the protocol with Redis or similar. Both fields default to off, so deployments not using fallback see behavior identical to prior versions. See `docs/model-fallback-guide.md`.

`tenancy/` provides per-tenant configuration for the consultancy deployment model, where one operator runs triage on behalf of several client organizations. As of 0.10.0, `TenantConfig` carries the settings that differ per client (model routing, fallback models, circuit breaker, applicable regulation set, and free-form metadata) and `TenantRegistry` holds the set of tenants with lookup by `tenant_id` and JSON file loading. Regulation sets are validated against the live corpus registry so a tenant cannot be configured for a regulation the framework has no corpus for. The `SYSTEM_PROMPT` stays uniform across all tenants by design, so every tenant's decisions trace to the identical version-pinned reasoning. As of 0.11.0, tenant-scoped agent construction (`TriageAgent.for_tenant(tenant_config)`) and a required `tenant_id` field on records shipped together; this was the framework's first breaking schema change (output contract 1.2.0 to 1.3.0). Single-organization deployments use the `__default__` sentinel and a runtime warning from the `vrt.agent` logger. See `docs/multi-tenancy-guide.md`.

`migration/` up-migrates triage records across output-contract versions (1.0.0 through 1.3.0). As of 0.12.0, `migrate_record` restamps additive hops and assigns a `tenant_id` on the 1.2.0-to-1.3.0 tenancy hop via a caller-supplied resolver (`fixed_tenant_resolver` for a whole batch, `mapping_tenant_resolver` for per-record assignment), optionally constrained to a `TenantRegistry`. The engine is idempotent at the target, refuses downward migration, validates output against the target contract, and never defaults a tenant silently. The `vrt migrate` CLI subcommand wraps it. This is the safety net for the 0.11.0 tenancy bump (output contract 1.2.0 to 1.3.0): it is how a deployment carries pre-1.3.0 records forward. See `docs/migration-guide.md`.

### Documentation

The phase-by-phase design documents live in `docs/`:

- `docs/phase-0/` covers the problem definition, regulatory framework mapping, and scope boundaries
- `docs/phase-1/` covers data contracts, privacy spec, synthetic data specification, and the extension guide
- `docs/phase-2/` covers system architecture, trust boundaries, the full threat model (T-AI1 through T-AI8), and the architecture decision records
- `docs/customization-guide.md` walks through customizing the framework for a specific deploying organization: intake checklist, configuration decision tree, extension points, a worked example, and anti-patterns to refuse
- `docs/audit-log-shipping.md` specifies the envelope format for shipping TriageRecords to SIEMs, archives, and event buses with content-hash integrity verification and replay semantics
- `docs/observability-guide.md` covers structured event logging, metrics emission, distributed tracing via OpenTelemetry, and correlating signals via correlation_id. The guide includes Prometheus and StatsD adapter examples for deployments wanting metrics; the OpenTelemetry tracer adapter ships in the framework's `[otel]` extra.
- `docs/cost-tracking-guide.md` covers the `cost_estimate` field on `TriageRecord`, the published price table (what's covered, what's not, how to refresh, how to override with negotiated enterprise rates), the `--cost-budget` CLI flag and its limitations, and the patterns for answering customer pricing conversations.
- `docs/model-fallback-guide.md` covers automatic model fallback and circuit breaking: the `fallback_models` and `circuit_breaker` config, the breaker state machine, the observability signals, the pluggable state backend for multi-process deployments, the permissive failure-counting caveat, and the cost-tracking interaction.
- `docs/multi-tenancy-guide.md` covers the per-tenant configuration model for the consultancy deployment: `TenantConfig`, `TenantRegistry`, the JSON config format, what is and is not per-tenant (and why the system prompt stays uniform), and the roadmap to tenant-scoped records.
- `docs/migration-guide.md` covers up-migrating records across output-contract versions: when migration is needed, the additive-versus-tenancy hop distinction, the explicit tenant-assignment decision and resolvers, the `vrt migrate` CLI, input shapes, exit codes, and programmatic usage.
- `docs/end-to-end-example.md` narrates the full pipeline on a single submission: tenant-scoped classification, the validated audit record, the eval controls running on real output, audit-pack rendering, and migration. The composition it shows is verified by the end-to-end regression suite.
- `docs/maintenance-workflow.md` documents the procedures for maintainers: version bumps, SYSTEM_PROMPT updates, corpus refreshes, price table refreshes, model dependency upgrades, schema evolution, security advisory response, and the release checklist
- `docs/corpus-manifest.md` documents the regulatory corpora the framework supports plus licensing notes per regulation
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

## CLI

After installation, the `vrt` command-line tool is available with six subcommands:

```bash
vrt triage submission.json --output record.json   # run the agent on a submission
vrt triage submission.json --corpus nist-ai-rmf   # corpus-grounded triage (added 1.0.2)
vrt render record.json --output audit-pack.html   # render an audit pack HTML
vrt migrate record.json --to 1.3.0 --tenant-id acme-bank  # up-migrate records to a newer contract
vrt drift                                         # check classification drift
vrt corpus list                                   # list registered regulation corpora
vrt corpus build nist-ai-rmf                      # build an IndexBundle
vrt version                                       # print framework version + verify pyproject sync
```

Each subcommand supports `--help` for full flag documentation. The CLI is a thin wrapper over the Python API; deployments integrating the framework typically use the API directly. The CLI exists for demos, first-run experience, and operational scripting.

Two invocation paths both work: the installed `vrt` console script, or `python -m cli`. The `vrt` command name and subcommand names are part of the framework's public surface; rename or remove is a breaking change per `docs/maintenance-workflow.md` section 1.

## Governance as code

The framework's governance is partially executable, not just documented:

- **Data contracts** are JSON Schema 2020-12 artifacts in `schemas/`. The Python utility in `schemas/validate.py` validates submissions and records against them. ADR-004 documents the closure properties (`unevaluatedProperties: false`, `additionalProperties: false`) the schemas enforce.
- **Examples** in `examples/` are verified against the schemas by `tests/test_examples_validate.py`, enforced on every push and PR by `.github/workflows/validate.yml`.
- **Bait-and-switch defense** is enforced at the agent boundary. Any document whose `content_hash` does not match the submission's claimed hash causes the agent to raise `TriageInputError` before any LLM call. See the threat model entry for T-AI4.
- **Prompt-injection resistance** is measurable through the `eval/attacks/` suite. The baseline dataset covers T-AI1 and T-AI2; deploying organizations are expected to extend with attacks specific to their threat surface.
- **Citation grounding** is measurable through `eval/citations/` (deterministic, token-overlap) and `eval/judge/` (semantic, LLM-graded).
- **Confidence calibration** is measurable through `eval/calibration/`. Every TriageRecord carries a `confidence_signal.score`; the calibration scorer answers whether stated confidence corresponds to empirical accuracy.
- **Style discipline** (no em dashes in prose) is enforced in CI.

The audit-log shipping format landed as part of `reporting/audit_log` (content-hashed envelopes with SIEM/archive/event-bus replay semantics; see `docs/audit-log-shipping.md`). What is still documented-only and not yet executable: model cards and DPIA templates. The framework's commitment is that wherever governance can be machine-readable, it will be.

## Roadmap

The eight-phase build (Phase 0 through Phase 7) is complete and shipped as `v1.0.1`. Post-1.0 work is driven by the people the framework was built for: regulated mid-market AI risk and compliance teams looking at the May 1, 2027 OSFI Guideline E-23 effective date and asking what audit-ready actually looks like.

The expected directions:

- **More authoritative corpora.** OSFI E-23, NIST AI RMF, SOX, and the EU AI Act are wired and pinned. ISO/IEC 42001 and additional jurisdictional regulations land as their pinning workflows mature. See `docs/corpus-manifest.md` for the current set.
- **Real-world calibration evidence.** The bundled graded baseline is intentionally small (see Limitations); production calibration claims need hundreds to thousands of organization-specific graded examples. Deployments running real triage volume will feed back the calibration data the framework needs to make defensible accuracy claims.
- **Deployment patterns from practitioners.** The integration suite proves end-to-end composition; what gets learned from real deployments (model fallback policy choices, observability sink choices, cost budget tuning) flows back as docs and reference configurations.
- **Bug fixes and security advisories.** Patch releases follow `docs/maintenance-workflow.md` (semver patches, no schema change). Security issues per `SECURITY.md`.

Major framework evolution (breaking schema changes, new public-surface packages) would ride in `2.0`. The `1.x` line commits to API and output-contract stability per the v1.0 release.

Phases ship when ready. Every release lands as commits with design docs, code, tests, and audit results in the same commit history.

## Test discipline

Every code commit lands with:

- 100% line coverage on every Python package (enforced in CI at 95% with intent to hold 100%)
- A 23-persona brutal audit pass with zero must-fix findings. The roster covers 15 always-on personas (Solution Arch, App Arch, Security Arch, Data Arch, Cloud/Infra Arch, Integration Arch, Enterprise Arch, Tech Lead, two Peer Devs, QA Eng, AppSec Eng, Performance Eng, Tech Writer, Product Mgr), 9 certified-AI-governance personas (CISA, CISM, CRISC, CDPSE, CCOA, AAIA, AAIR, AAISM, CGEIT), and competitive-defense review.
- Three stability runs of the full test suite at the same passing count

Coverage and tests are enforced in CI. The audit discipline is enforced by the author.

### End-to-end regression

Beyond the per-package unit suites, `tests/test_e2e.py` verifies that the twelve packages *compose* into a working pipeline: a submission flows through tenant-scoped classification, output-contract validation, the eval controls (citation verification, calibration, judge) running on the agent's real output, audit-pack rendering, and migration, with the artifacts asserted consistent across every stage boundary. One scenario invokes the installed `vrt` console script as a real subprocess to catch packaging and entry-point regressions. These run in the default suite (they use a deterministic model, not a live LLM). The narrated version is `docs/end-to-end-example.md`.

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

- **Reference implementation, not turnkey audit defense.** At `1.0.1`, the framework ships the code, the evaluation discipline, and operational concerns (corpus management, drift detection, audit-log export, observability, cost tracking, model fallback, multi-tenancy, schema migration). What it does not ship is your organization's calibration. The bundled graded baseline is small (eight examples); production accuracy and confidence-calibration claims require hundreds to thousands of organization-specific graded examples. Do not point this at a real vendor onboarding flow and assume the output holds up under regulatory scrutiny without that calibration work plus your own per-decision audit review until trust is established.
- **Three authoritative corpus bundles ship; OSFI is fetched at run time.** Prebuilt IndexBundles for NIST AI RMF, SOX (PL 107-204), and the EU AI Act (Regulation 2024/1689) live under `corpora/` and are usable immediately. OSFI E-23 (2027) is not redistributed due to Crown copyright reproduction terms; the integration suite fetches it from osfi-bsif.gc.ca on first run and SHA-256-verifies against a pinned hash. ISO/IEC 42001 and additional regulations land as their licensing and pinning workflows mature. Deploying organizations wanting a regulation the framework does not ship can provision their own authorised PDF and feed it through the same harness; see `docs/corpus-manifest.md`.
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
