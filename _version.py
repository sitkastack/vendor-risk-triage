"""Single source of truth for the framework's version string.

This module exists solely to hold ``FRAMEWORK_VERSION`` so that
multiple packages (``agent``, ``reporting``, and future consumers)
can read it without creating import-layering issues between
packages.

Why a separate top-level module instead of putting the constant in
``agent/agent.py`` and importing from there:

- ``reporting/`` already depends on ``agent.output_models`` for the
  ``TriageRecord`` type. Adding a second dependency on
  ``agent.agent`` for a version constant tightens the coupling
  unnecessarily: a future refactor of ``agent.agent`` (or its
  removal in favor of a new agent implementation) would force
  ``reporting`` to chase the move. A standalone version module is
  refactor-proof.
- ``pyproject.toml`` separately declares the package version. Keeping
  the runtime constant and the build-system version in lockstep is
  enforced by the CI script ``scripts/check_version_sync.py``; both
  read this module's ``FRAMEWORK_VERSION`` as the canonical answer.

Maintenance procedure: edit this file. Run ``python -m pytest`` to
verify the framework still works under the new version string. Run
``python scripts/check_version_sync.py`` to confirm ``pyproject.toml``
matches. Commit both files together.

See ``docs/maintenance-workflow.md`` section 1 for the full release
procedure.
"""
from __future__ import annotations


__all__ = ["FRAMEWORK_VERSION"]


FRAMEWORK_VERSION: str = "0.9.1"
"""Semver of the framework's code.

Bumped on any behavior change. Pre-1.0, breaking changes ride in
minor bumps; the 1.0 release will signal API-stability commitments.

History:

- 0.9.1 (sub-system 9, Phase 6 SS5): release engineering tooling.
  New ``scripts/bump_version.py`` atomically bumps
  ``_version.FRAMEWORK_VERSION`` and the ``pyproject.toml`` version
  together (major/minor/patch or explicit), refusing on a dirty git
  tree unless ``--allow-dirty`` is passed and rejecting downgrades.
  New ``scripts/extract_changelog.py`` projects this hand-curated
  History section into a standard repo-root ``CHANGELOG.md`` (Keep-a-
  Changelog format), with a ``--check`` mode that verifies the
  committed changelog matches the source so CI can catch a stale
  changelog. New ``scripts/prepare_release.py`` runs the automatable
  subset of the maintenance doc's release checklist (version sync,
  changelog current, full suite, coverage gate, drift, em-dash) and
  emits a go/no-go report plus the manual steps a maintainer must
  confirm by hand. New repo-root ``CHANGELOG.md`` (generated). Patch
  bump: tooling only, no schema change, no runtime behavior change,
  no public framework API change. The changelog is deliberately
  projected from the hand-written History rather than generated from
  commit messages: the hand-curated prose is higher-signal than any
  commit-derived changelog.
- 0.9.0 (sub-system 8, Phase 6 SS4): model fallback with circuit
  breaker. New ``resilience`` package with CircuitBreaker,
  CircuitBreakerConfig, CircuitState, ModelHealth, BreakerStateStore
  protocol, and InMemoryBreakerStateStore. TriageAgentConfig gains
  ``fallback_models`` (list of model identifiers tried in order when
  primary fails) and ``circuit_breaker`` (optional config enabling
  per-model failure tracking). When configured, the agent tries
  primary first, falls back through alternates on failure, and
  tracks each model's health: failures count toward an opening
  threshold (50% over 60s default), opened breakers skip the model
  until cooldown (30s default), half-open trials restore or re-open.
  Failure counting is permissive (any exception counts). State
  storage is pluggable via the BreakerStateStore protocol; default
  is in-memory. Four new observability events
  (llm.call.fallback_triggered, circuit_breaker.opened,
  circuit_breaker.half_opened, circuit_breaker.closed) and three new
  metrics (vrt_llm_fallback_total, vrt_circuit_state_changes_total,
  and the existing vrt_llm_* families gain fallback-model labels).
  Default behavior unchanged: empty fallback_models + None
  circuit_breaker means identical behavior to 0.8.1. No schema
  change; cost_estimate records the effective (fallback) model.
- 0.8.1 (sub-system 7B, Phase 6 SS3-B): cost budget gate. Adds
  ``--cost-budget DOLLARS`` and ``--max-output-tokens N`` flags to
  ``vrt triage``. The flags must be specified together; the gate
  computes an upper-bound cost estimate (input tokens via a 4-
  chars-per-token heuristic + max output tokens at standard rates
  from the published price table) and refuses calls projected to
  exceed budget. Unknown models refuse rather than proceed without
  enforcement. New ``pricing/estimation.py`` module exposes
  ``count_input_tokens_heuristic``, ``estimate_upper_bound_cost``,
  ``check_budget``, and the ``BudgetCheck`` dataclass for use by
  the CLI and by deployments wanting programmatic budget
  enforcement. Patch bump: additive CLI flag, no schema change, no
  TriageRecord change.
- 0.8.0 (sub-system 7, Phase 6 SS3-A): cost tracking infrastructure.
  New ``pricing`` package with ``ModelPriceTable`` covering all four
  major providers' lineups (33 models: Anthropic, OpenAI, Google,
  Mistral). TriageRecord gains optional ``cost_estimate`` nested
  field (input_tokens, output_tokens, model_id, estimated_cost_usd,
  price_table_version). Output contract bumped to 1.2.0 (additive
  minor). Agent captures token usage from PydanticAI result and
  computes dollar cost; when model is not in the price table
  (FunctionModel, TestModel, custom adapters), cost_estimate stays
  absent. New observability event ``llm.call.cost_recorded`` plus
  metrics ``vrt_llm_cost_usd_total`` (counter) and
  ``vrt_llm_tokens_total`` (histogram). Standard rates only; batch
  discounts, prompt caching, long-context surcharges not modeled.
- 0.7.0 (sub-system 6, Phase 6 SS2): observability package added.
  TriageRecord gains optional ``correlation_id`` field (output
  contract bumped to 1.1.0). TriageAgent gains optional
  ``observability`` config parameter for structured event logging,
  metrics, and tracing. Default is silent (NoopEventLogger,
  NoopMetrics, NoopTracer). New ``[otel]`` extra for the OpenTelemetry
  adapter. Twelve framework events and ten built-in metrics are part
  of the public surface; renames or removals require a major version
  bump.
- 0.6.0 (sub-system 5, May 26, 2026): agent accepts optional
  regulation context (retrieved chunks) and includes them in the LLM
  prompt under BEGIN_REGULATION_CONTEXT / END_REGULATION_CONTEXT
  delimiters. Material capability change.
- 0.5.0 (sub-system 4 deferreds resolution): closes Phase 4 follow-up
  tags. SYSTEM_PROMPT unchanged.
- 0.4.0: introduces eval/judge LLM-as-judge harness and three
  pre-built rubrics.
- earlier: phase-numbered milestones.
"""
