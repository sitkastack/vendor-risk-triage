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


FRAMEWORK_VERSION: str = "0.7.0"
"""Semver of the framework's code.

Bumped on any behavior change. Pre-1.0, breaking changes ride in
minor bumps; the 1.0 release will signal API-stability commitments.

History:

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
