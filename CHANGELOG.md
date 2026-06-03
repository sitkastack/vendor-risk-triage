# Changelog

All notable changes to this framework are documented here.

This file is generated from the hand-curated version history in
`_version.py` by `scripts/extract_changelog.py`. Do not edit it by
hand; edit the `FRAMEWORK_VERSION` docstring in `_version.py` and
regenerate. The format follows [Keep a Changelog](https://keepachangelog.com/),
and the framework adheres to [Semantic Versioning](https://semver.org/)
(pre-1.0: breaking changes may ride in minor bumps).


## [1.0.4]

_CLI local-only corpus build skips hash verification). Completes the chain started by 1.0.2 (`--corpus` flag) and 1.0.3 (build accepts local-only names_

`build_bundle` now accepts a `verify` parameter that is forwarded to `fetch_corpus`. `vrt corpus build <name>` passes `verify=False` automatically when the named corpus is registered as local-only, and `verify=True` for committed corpora (preserving the existing pin-enforcement behavior). The rationale: local-only corpora like OSFI E-23 use placeholder (all-zeros) SHA-256 pins by design because the upstream endpoint serves byte-different content on every fetch (the Drupal print-PDF route embeds a per-fetch token), so pin-verification would always fail for them. The integration suite already used `verify=False` for OSFI; this patch brings the build path into alignment. Committed corpora are unaffected: their pins are real and continue to be enforced. Discovered as the third blocker in the same five-vendor newsletter run that produced 1.0.2 and 1.0.3. After 1.0.3 made `vrt corpus build osfi-e23` allowable, the build itself still failed at `fetch_corpus`'s pin check. 1.0.4 closes that gap. The local-only build note is also extended to surface the hash-verification skip so the operator knows what is happening. No schema change. No agent code change. No output-contract change. SYSTEM_PROMPT_HASH stays 69ef583c6dbe. Test count stays 1353 (the two pre-existing local-only/committed tests gained assertions on the `verify` flag pass-through; no new tests were needed). Coverage remains 100% across all twelve framework packages. cli/cmd_corpus.py at 62 statements 0 missing. scripts/build_corpus_bundles.py at 27% coverage (unchanged from baseline; the build script is not in the framework coverage gate per the existing convention). Patch bump: additive flag pass-through, no breaking surface change.

## [1.0.3]

(CLI corpus build allows local-only). Fixes `vrt corpus build <name>` to accept any registered corpus name, including those marked local-only (e.g. `osfi-e23`, which is registered but excluded from build-all because Crown copyright prevents redistribution of the source PDF). Building a local-only corpus by explicit name now succeeds and prints a one-line note that the resulting bundle is local-only and will not be committed. Building all (`vrt corpus build` with no name) still skips local-only corpora as before. The framework continues to refuse auto-redistribution of licensed material. The previous error message "unknown or non-committed regulation" conflated two distinct conditions (truly unknown name vs registered but local-only); the new message "unknown regulation 'X'. Registered names: ..." only fires when the name is not in `CORPUS_REGISTRY` at all. The local-only path takes precedence on a known local-only name and proceeds to build with the warning. Discovered during the same five-vendor newsletter run that surfaced the 1.0.2 `--corpus` flag gap: the new flag needed a bundle on disk, but `vrt corpus build osfi-e23` refused even though the OSFI PDF was cached and ready, because the build path intentionally allowlisted only committed corpora. The same newsletter run is the test case that revealed this is an operationally-important fix, not a theoretical one. No schema change. No agent code change. No output-contract change. No change to behavior when --corpus is omitted on triage. Test count 1351 -> 1353 (+2 new tests in `test_cli_dispatcher.py`: local-only-named-succeeds, and committed-named-no-local-only-note). One existing test updated for the new error wording. Coverage 100% across all packages including cmd_corpus.py (62 statements, 0 missing). Patch bump: additive CLI capability, no breaking surface change.

## [1.0.2]

(CLI corpus grounding). Adds `--corpus NAME` and `--top-k N` flags to `vrt triage`. When `--corpus` is set, the CLI loads the corresponding IndexBundle from `corpora/<NAME>/<NAME>.bundle.tgz`, derives a BM25 query from the submission's narrative fields (AI feature description, PII handling notes and categories, model providers, vendor classification, AI usage level), retrieves the top-K chunks, and passes them to `agent.triage` as `regulation_chunks` for citation in the produced TriageRecord. When `--corpus` is omitted, behavior is identical to 1.0.1 (JSON-prose-only triage, no regulation context). The flag closes the gap that the agent's Python API supported `regulation_chunks` since 0.6.0 but the CLI did not expose it. Discovered during a five-vendor public-triage newsletter run where a one-off Python script (`vrt-triage-with-corpus.py`) was used as a workaround; the patch graduates that workaround into the framework. New module-level helpers `_build_corpus_query` and `_load_and_retrieve` in `cli/cmd_triage.py`. New `_CorpusLoadError` exception surfaces tooling failures (corrupt bundle, missing retrieval modules) distinctly from data conditions (empty retrieval). Exit codes preserved: 0 success, 1 for runtime/data failure (now including empty retrieval), 2 for setup error (now including unknown corpus name and out-of-range `--top-k`). No schema change. No agent or output-contract change. Test count 1331 -> 1351 (+20 new tests in `test_cli_triage_corpus.py`). Coverage 100% across all packages including the new helpers. Patch bump: additive CLI flag, no breaking surface change.

## [1.0.1]

(documentation correction). Patch release fixing a writing error in the 1.0.0 History entry's CLI surface listing. The shipped 1.0.0 entry listed `vrt {triage, demo, migrate, report, eval}`, which was an invented surface introduced during release-notes drafting; the actual CLI surface, verified against `vrt --help`, is `vrt {triage, render, migrate, drift, corpus, version}`. Caught during pre-publication review of the GitHub release notes draft for v1.0.0, before any release was published. Corrects the 1.0.0 entry text on main and adds this 1.0.1 entry documenting the correction. Regenerates CHANGELOG.md. No framework code change. No behavior change. No test count change (still 1331 passed, 100% coverage across twelve packages). No drift. The v1.0.0 git tag (commit 7f9c073) still carries the original typo'd History entry text; git tags are immutable once pushed, so v1.0.0 forensic checkouts will always show the original. Main and v1.0.1 onward carry the corrected text. Patch bump: documentation correction only, no public API change.

## [1.0.0]

(framework production-ready). API and output-contract stability commitment from this release forward. 1.0.0 ships the same code as 0.14.0 plus the 843485d fixture hardening (anthropic_api_key skips cleanly on placeholder keys); no new features, no behavior changes beyond that fix. The 1.0.0 designation marks the milestone, not a code change. Build phases shipped across 0.x: framework foundations (discovery, data contracts, threat model, agent core), RAG and hybrid retrieval (BM25 + vector + RRF), eval suite (calibration, citation verification, LLM-as-judge), CLI and observability, resilience and cost tracking, multi-tenancy with required tenant_id, schema migration engine, end-to-end regression suite, real-corpus integration with pins for NIST AI RMF and SOX PL 107-204 and verify=False fetch for OSFI E-23 and EU AI Act, and the post-0.14.0 fixture hardening. Stable surfaces at 1.0.0: OUTPUT_SCHEMA_VERSION 1.3.0 (frozen; breaking schema changes from here on ride in major bumps and `vrt migrate` backfills), SYSTEM_PROMPT_HASH 69ef583c6dbe (stable since 0.5.0; uniform across tenants), tenant_id required with __default__ for single-org installs, CLI surface `vrt {triage, render, migrate, drift, corpus, version}`, 1331 tests with 100% coverage across twelve packages. Framework state: integration suite green against authoritative OSFI E-23 (2027) and EU AI Act PDFs; six prepare_release gates GO; no drift; no em-dashes. Major bump: stability commitment milestone, no behavior change vs 0.14.0 + 843485d.

## [0.14.0]

(post-build item 2: real-corpus integration). Tooling and pins for running the framework against the real regulation PDFs, and for harvesting demo/content artifacts from them. New `scripts/harvest_corpus_artifacts.py` runs the full pipeline (chunk -> BM25 retrieve -> triage -> render) on a regulation PDF and saves a rendered audit pack, a retrieval transcript, and the record JSON; it takes a registry corpus name (fetched from the cache) or an explicit `--pdf` path, and uses a deterministic model by default (`--real-llm` for the production model). New `scripts/print_corpus_hashes.py` fetches each corpus and prints its byte size + SHA-256, refusing to emit a hash for an empty or suspiciously small body (under 50 KB) so a blocked/empty response can never be mistaken for a pinnable artifact. Corpus registry pins: `nist-ai-rmf` and `sox-pl-107-204` are now pinned (verified by three byte-identical fetches; the integration test fetches and verifies them and runs end to end). `osfi-e23` URL fixed to the live Drupal print-PDF route (the direct gd-mrm path 404s) and fetched with a new `fetch_corpus(verify=False)` option: that route is non-deterministic (an embedded per-fetch token makes the bytes differ every fetch), so it has no stable content-hash to pin, but it fetches fine and the guideline text is stable. With verify=False the OSFI integration test and the harvest script run against the current bytes without a hash check, so the OSFI test runs (not skips) when the network is reachable. fetch_corpus now also rejects an empty or sub-1KB body outright, so a blocked/empty response can never be cached as a PDF. `eu-ai-act` left unpinned and not script-fetchable (EUR-Lex serves an empty body to scripted clients regardless of URL form, but DOES serve the real PDF to browsers). The EU integration fixture also uses verify=False so a manually-placed cached PDF is accepted without a hash check: drop the browser-downloaded PDF at `~/.cache/sitkastack-vrt/corpora/eu-ai-act/eu-ai-act-regulation-2024-1689-en.pdf` and the EU integration test runs against the real corpus. The harvest script's `--pdf` path remains available as the alternative. The integration-test README documents this status. Minor bump: additive tooling and corpus pins, no framework code or contract change.

## [0.13.0]

_Phase 7 close-out_

end-to-end regression suite and the code-complete milestone. New `tests/test_e2e.py` verifies that the framework's twelve packages compose into a working pipeline (not just that each works in isolation), with five scenario groups: the golden tenant-scoped pipeline (submission -> triage -> validate -> render, attribution carried end to end); the eval pipeline run on real agent output (citation verification, calibration, and the judge all accept a record the agent actually emitted, catching drift between what the agent produces and what the eval components expect); a migration round-trip (a pre-tenancy record migrated forward renders and validates identically to a natively-produced 1.3.0 record, and migration preserves the decision content); the multi-tenant attribution and audit invariant (two tenants produce correctly-attributed records sharing one identical SYSTEM_PROMPT_HASH); and a real-subprocess CLI chain (the installed `vrt` console script runs migrate and render through actual files, catching packaging and entry-point regressions in-process tests cannot). The suite passed clean on the first run: the framework composes with no integration seams. New `docs/end-to-end-example.md` walks the full pipeline with real shapes, doubling as demo and onboarding material. New `e2e_subprocess` pytest marker (registered, runs by default; requires the package installed). With this, the framework is code-complete for the vendor risk triage build: every planned sub-system across Phases 0 through 7 is shipped, and the end-to-end pipeline is verified. Minor bump: additive test suite and docs, no code change to the framework itself.

## [0.12.0]

_sub-system 12, Phase 7 SS3_

schema migration engine and the `vrt migrate` CLI subcommand. New `migration` package up-migrates triage records across the output-contract version chain (1.0.0 -> 1.1.0 -> 1.2.0 -> 1.3.0). The additive hops are version restamps (an older record is already structurally valid under the newer additive-optional contract); the 1.2.0 -> 1.3.0 hop is the one real migration, assigning a tenant_id to records that predate tenancy. `migrate_record(record, target_version, tenant_resolver)` is the core; it is idempotent at the target, refuses downward migration, and validates its output against the target contract before returning. Two tenant resolvers are provided: `fixed_tenant_resolver` (assign one tenant to a whole batch) and `mapping_tenant_resolver` (assign per record by decision_id), both optionally constrained to a TenantRegistry so an unknown tenant id is rejected. The engine never defaults a tenant silently (decision D4): a record crossing the tenancy boundary without a tenant_id and without a resolver raises, because migration is an operator-initiated batch action where there is always a human who can answer whose records these are. The sentinel `__default__` is reachable only by passing it explicitly. New sixth CLI subcommand `vrt migrate` reads a single record or a JSONL/array batch, requires `--tenant-id` or `--tenant-map` (mutually exclusive) for the tenancy hop, accepts an optional `--tenants` registry, and writes to stdout or `--output`. This is the sub-system that makes the SS2 breaking change safe: it is how a deployment carries pre-1.3.0 records forward. Minor bump: new public package and CLI subcommand, no breaking change.

## [0.11.0]

_sub-system 11, Phase 7 SS2_

tenant-scoped agent and the framework's first breaking schema change. Output contract bumped 1.2.0 -> 1.3.0, adding a required `tenant_id` field: every record is now attributable to exactly one tenant. TriageAgentConfig gains a `tenant` field (a TenantConfig), and TriageAgent.for_tenant() constructs an agent from a tenant, sourcing model routing (model, fallback_models, circuit_breaker) and tenant identity from it (decision C1: one agent per tenant, explicit-config-over-tenant when both are given). An agent built without a tenant stamps the reserved sentinel tenant_id `__default__` and logs a WARNING (decision B2: single-org use stays frictionless, but an accidental missing tenant in a multi-tenant deployment leaves an auditable trail). Backward compatibility is preserved (decision A1): the 1.0.0, 1.1.0, and 1.2.0 schemas remain in the validator dispatch unchanged, so a record declaring a pre-1.3.0 version still validates without tenant_id; only records declaring 1.3.0 or later require it. The Pydantic TriageRecord model enforces this conditionally by declared output_schema_version, mirroring the JSON-schema dispatch. tenant_id added to the agent.constructed event. SYSTEM_PROMPT stays uniform across tenants (hash unchanged). This is a minor bump: pre-1.0 the framework rides schema additions in minor versions, and A1 means no archived record is retroactively invalidated. The migration engine that up-migrates pre-1.3.0 records (assigning a tenant) is SS3.

## [0.10.0]

_sub-system 10, Phase 7 SS1_

tenant configuration model. New `tenancy` package with `TenantConfig` (per-tenant model routing, fallback models, circuit breaker, applicable regulation set, and free-form metadata) and `TenantRegistry` (lookup by tenant_id, duplicate rejection, JSON file loading). Supports the consultancy deployment model: one operator running triage for several client organizations with isolated configuration. Regulation sets are validated against the live corpus registry so a tenant cannot be configured for a regulation the framework has no corpus for. The SYSTEM_PROMPT stays uniform across all tenants by design: a per-tenant prompt would fork SYSTEM_PROMPT_HASH and break the property that every tenant's decisions trace to the identical version-pinned reasoning. This sub-system is the configuration foundation only: no agent integration and no schema change. The agent gaining tenant context and records gaining a required tenant_id field (the framework's first breaking schema change, output contract 1.2.0 -> 1.3.0) is SS2. Minor bump: new public package, no breaking change, no schema change.

## [0.9.1]

_sub-system 9, Phase 6 SS5_

release engineering tooling. New `scripts/bump_version.py` atomically bumps `_version.FRAMEWORK_VERSION` and the `pyproject.toml` version together (major/minor/patch or explicit), refusing on a dirty git tree unless `--allow-dirty` is passed and rejecting downgrades. New `scripts/extract_changelog.py` projects this hand-curated History section into a standard repo-root `CHANGELOG.md` (Keep-a-Changelog format), with a `--check` mode that verifies the committed changelog matches the source so CI can catch a stale changelog. New `scripts/prepare_release.py` runs the automatable subset of the maintenance doc's release checklist (version sync, changelog current, full suite, coverage gate, drift, em-dash) and emits a go/no-go report plus the manual steps a maintainer must confirm by hand. New repo-root `CHANGELOG.md` (generated). Patch bump: tooling only, no schema change, no runtime behavior change, no public framework API change. The changelog is deliberately projected from the hand-written History rather than generated from commit messages: the hand-curated prose is higher-signal than any commit-derived changelog.

## [0.9.0]

_sub-system 8, Phase 6 SS4_

model fallback with circuit breaker. New `resilience` package with CircuitBreaker, CircuitBreakerConfig, CircuitState, ModelHealth, BreakerStateStore protocol, and InMemoryBreakerStateStore. TriageAgentConfig gains `fallback_models` (list of model identifiers tried in order when primary fails) and `circuit_breaker` (optional config enabling per-model failure tracking). When configured, the agent tries primary first, falls back through alternates on failure, and tracks each model's health: failures count toward an opening threshold (50% over 60s default), opened breakers skip the model until cooldown (30s default), half-open trials restore or re-open. Failure counting is permissive (any exception counts). State storage is pluggable via the BreakerStateStore protocol; default is in-memory. Four new observability events (llm.call.fallback_triggered, circuit_breaker.opened, circuit_breaker.half_opened, circuit_breaker.closed) and three new metrics (vrt_llm_fallback_total, vrt_circuit_state_changes_total, and the existing vrt_llm_* families gain fallback-model labels). Default behavior unchanged: empty fallback_models + None circuit_breaker means identical behavior to 0.8.1. No schema change; cost_estimate records the effective (fallback) model.

## [0.8.1]

_sub-system 7B, Phase 6 SS3-B_

cost budget gate. Adds `--cost-budget DOLLARS` and `--max-output-tokens N` flags to `vrt triage`. The flags must be specified together; the gate computes an upper-bound cost estimate (input tokens via a 4-chars-per-token heuristic + max output tokens at standard rates from the published price table) and refuses calls projected to exceed budget. Unknown models refuse rather than proceed without enforcement. New `pricing/estimation.py` module exposes `count_input_tokens_heuristic`, `estimate_upper_bound_cost`, `check_budget`, and the `BudgetCheck` dataclass for use by the CLI and by deployments wanting programmatic budget enforcement. Patch bump: additive CLI flag, no schema change, no TriageRecord change.

## [0.8.0]

_sub-system 7, Phase 6 SS3-A_

cost tracking infrastructure. New `pricing` package with `ModelPriceTable` covering all four major providers' lineups (33 models: Anthropic, OpenAI, Google, Mistral). TriageRecord gains optional `cost_estimate` nested field (input_tokens, output_tokens, model_id, estimated_cost_usd, price_table_version). Output contract bumped to 1.2.0 (additive minor). Agent captures token usage from PydanticAI result and computes dollar cost; when model is not in the price table (FunctionModel, TestModel, custom adapters), cost_estimate stays absent. New observability event `llm.call.cost_recorded` plus metrics `vrt_llm_cost_usd_total` (counter) and `vrt_llm_tokens_total` (histogram). Standard rates only; batch discounts, prompt caching, long-context surcharges not modeled.

## [0.7.0]

_sub-system 6, Phase 6 SS2_

observability package added. TriageRecord gains optional `correlation_id` field (output contract bumped to 1.1.0). TriageAgent gains optional `observability` config parameter for structured event logging, metrics, and tracing. Default is silent (NoopEventLogger, NoopMetrics, NoopTracer). New `[otel]` extra for the OpenTelemetry adapter. Twelve framework events and ten built-in metrics are part of the public surface; renames or removals require a major version bump.

## [0.6.0]

_sub-system 5, May 26, 2026_

agent accepts optional regulation context (retrieved chunks) and includes them in the LLM prompt under BEGIN_REGULATION_CONTEXT / END_REGULATION_CONTEXT delimiters. Material capability change.

## [0.5.0]

_sub-system 4 deferreds resolution_

closes Phase 4 follow-up tags. SYSTEM_PROMPT unchanged.

## [0.4.0]

introduces eval/judge LLM-as-judge harness and three pre-built rubrics.

## earlier

phase-numbered milestones.

