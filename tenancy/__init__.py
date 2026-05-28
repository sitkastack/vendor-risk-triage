"""Multi-tenant configuration for the vendor risk triage framework.

This package supports the consultancy deployment model: one framework
operator running triage on behalf of several client organizations,
each with isolated configuration.

Public exports:

- ``TenantConfig``: per-tenant settings (model routing, regulation
  set, metadata). Frozen dataclass.
- ``TenantConfigError``: raised on invalid tenant config values.
- ``TenantRegistry``: holds tenant configs, lookup by tenant_id,
  loadable from JSON.
- ``TenantRegistryError``: raised on registry-level problems.
- ``VALID_REGULATION_IDS``: the canonical regulation identifiers a
  tenant may be configured for (sourced from the corpus registry).

SS1 (0.10.0) is the configuration foundation only: it does not touch
the agent or the record schema. The agent gaining tenant context and
records gaining a required tenant_id field is SS2 (the framework's
first breaking schema change, bumping the output contract to 1.3.0).
The SYSTEM_PROMPT stays uniform across all tenants by design, so that
every tenant's decisions trace to the identical version-pinned
reasoning.

See ``docs/multi-tenancy-guide.md``.
"""
from tenancy.config import (
    TenantConfig,
    TenantConfigError,
    VALID_REGULATION_IDS,
)
from tenancy.registry import TenantRegistry, TenantRegistryError


__all__ = [
    "TenantConfig",
    "TenantConfigError",
    "TenantRegistry",
    "TenantRegistryError",
    "VALID_REGULATION_IDS",
]
