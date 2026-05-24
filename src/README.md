# Source

The agent implementation will live here, starting in Phase 3 (Build and Eval). Expected layout: a small Python package with the triage agent, prompt templates, and any orchestration glue, plus a CLI entry point for running a triage against a vendor dossier.

The agent implementation follows the architectural commitments documented in Phase 2 architecture decisions:

- ADR-001: Provider-agnostic LLM interface with LiteLLM-compatible design
- ADR-002: Data processing region strategy with cross-region inference caveats
- ADR-003: Agent versioning via Git commit SHA, captured in every triage record
- ADR-004: Schema validation via the jsonschema Python library (already in use in schemas/validate.py)
- ADR-005: Storage architecture on Postgres with role-based append-only constraints
- ADR-006: Schema evolution and migration policy

Phases 0, 1, and 2 are documentation phases (problem definition, data contracts, architecture and threat model), so this folder is empty by design through the end of Phase 2. Phase 3 implements the reference application against the architecture documented in docs/phase-2/.
