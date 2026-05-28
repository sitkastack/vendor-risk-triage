# Changelog

All notable changes to this framework are documented here.

This file is generated from the hand-curated version history in
`_version.py` by `scripts/extract_changelog.py`. Do not edit it by
hand; edit the `FRAMEWORK_VERSION` docstring in `_version.py` and
regenerate. The format follows [Keep a Changelog](https://keepachangelog.com/),
and the framework adheres to [Semantic Versioning](https://semver.org/)
(pre-1.0: breaking changes may ride in minor bumps).


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

