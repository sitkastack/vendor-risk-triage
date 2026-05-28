"""Per-tenant configuration for multi-tenant deployments.

A deployment that serves multiple client organizations (the
consultancy model: one framework operator running triage on behalf of
several regulated clients) needs per-tenant configuration. Each tenant
has its own model routing, its own applicable regulation set, and its
own metadata, while sharing the framework's uniform SYSTEM_PROMPT and
output contract.

What is per-tenant (this module):

- ``model`` / ``fallback_models`` / ``circuit_breaker``: a tenant
  serving a cost-sensitive client may route through a cheaper model;
  a tenant with strict latency needs may configure different
  fallbacks. These reuse the same types the agent already accepts.
- ``regulation_set``: which regulations apply to this client. A
  Canadian bank tenant cares about OSFI E-23; a US-listed issuer
  cares about SOX. Validated against the framework's canonical
  corpus registry so a tenant cannot be configured for a regulation
  the framework has no corpus for.
- ``metadata``: a free-form dict for deployment-specific attributes
  (client tier, account owner, contract reference) that the framework
  carries but does not interpret.

What is deliberately NOT per-tenant:

- **SYSTEM_PROMPT.** The system prompt is uniform across all tenants.
  A per-tenant prompt would fork SYSTEM_PROMPT_HASH per tenant and
  destroy the auditability property that every tenant's decisions
  came from the identical, version-pinned reasoning. This is a
  hard design stance, not a deferred feature.
- **The output schema / contract.** Every tenant produces records
  against the same schema version. Tenancy adds a tenant_id field
  (in a later sub-system) but does not fork the contract shape.
- **The classification logic.** Tenants differ in configuration, not
  in how the framework reasons.

This module (SS1) is the configuration foundation only. It does not
touch the agent or the record schema; the agent gaining tenant
context and records gaining a tenant_id field is a separate
sub-system.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from retrieval.corpora import CORPUS_REGISTRY


__all__ = [
    "TenantConfig",
    "TenantConfigError",
    "VALID_REGULATION_IDS",
]


# The canonical regulation identifiers a tenant may be configured for.
# Sourced from the live corpus registry so tenancy never drifts from
# what the framework can actually retrieve. ISO 42001 is intentionally
# absent: it is licensed and not redistributable, so it is not in the
# fetchable corpus registry (see docs/corpus-manifest.md). A deployment
# with an ISO 42001 license supplies that corpus out of band; tenant
# regulation_set validation covers only the framework-distributable
# corpora.
VALID_REGULATION_IDS: frozenset[str] = frozenset(CORPUS_REGISTRY.keys())


# Tenant IDs are slug-like: lowercase alphanumerics and hyphens, must
# start and end with an alphanumeric. This keeps them safe as map keys,
# file path components, metric label values, and audit-record fields.
_TENANT_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_TENANT_ID_MAX_LEN = 64


class TenantConfigError(ValueError):
    """Raised when a TenantConfig is constructed with invalid values."""


@dataclass(frozen=True)
class TenantConfig:
    """Configuration for a single tenant (client organization).

    Attributes:
        tenant_id: Stable slug identifying the tenant (lowercase
            alphanumerics and hyphens, 1-64 chars, e.g. 'acme-bank').
            Used as a map key, audit-record field, and metric label,
            so it is constrained to a safe character set.
        display_name: Human-readable name for the tenant.
        model: PydanticAI model identifier for this tenant's primary
            model. Defaults to None, meaning "use the framework
            default" (resolved by the agent in a later sub-system).
        fallback_models: Ordered fallback model identifiers for this
            tenant. Defaults to empty (no fallback).
        circuit_breaker: Optional per-tenant CircuitBreakerConfig.
            Defaults to None (no breaker). Reuses the resilience
            package's type rather than redefining it.
        regulation_set: Regulation identifiers applicable to this
            tenant. Must be a subset of VALID_REGULATION_IDS. May be
            empty (a tenant doing tier classification without
            regulation-grounded retrieval).
        metadata: Free-form deployment attributes the framework
            carries but does not interpret.
    """

    tenant_id: str
    display_name: str
    model: Optional[str] = None
    fallback_models: tuple[str, ...] = ()
    circuit_breaker: Optional[Any] = None  # Optional["CircuitBreakerConfig"]
    regulation_set: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # tenant_id format.
        if not isinstance(self.tenant_id, str) or not self.tenant_id:
            raise TenantConfigError("tenant_id must be a non-empty string.")
        if len(self.tenant_id) > _TENANT_ID_MAX_LEN:
            raise TenantConfigError(
                f"tenant_id {self.tenant_id!r} exceeds "
                f"{_TENANT_ID_MAX_LEN} characters."
            )
        if not _TENANT_ID_RE.match(self.tenant_id):
            raise TenantConfigError(
                f"tenant_id {self.tenant_id!r} is not a valid slug: use "
                f"lowercase alphanumerics and hyphens, starting and "
                f"ending with an alphanumeric (e.g. 'acme-bank')."
            )

        # display_name non-empty.
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise TenantConfigError(
                f"display_name for tenant {self.tenant_id!r} must be a "
                f"non-empty string."
            )

        # regulation_set members must be known and unique.
        seen: set[str] = set()
        for reg in self.regulation_set:
            if reg not in VALID_REGULATION_IDS:
                raise TenantConfigError(
                    f"tenant {self.tenant_id!r} references unknown "
                    f"regulation {reg!r}. Valid regulation ids: "
                    f"{sorted(VALID_REGULATION_IDS)}."
                )
            if reg in seen:
                raise TenantConfigError(
                    f"tenant {self.tenant_id!r} lists regulation {reg!r} "
                    f"more than once."
                )
            seen.add(reg)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantConfig":
        """Build a TenantConfig from a plain dict (e.g. parsed JSON).

        Recognizes an optional nested ``circuit_breaker`` object and
        constructs a CircuitBreakerConfig from it. Tuples are accepted
        as lists in the input and normalized.

        Raises TenantConfigError on unknown keys or malformed values so
        a typo in a tenant config file fails loudly rather than being
        silently ignored.
        """
        if not isinstance(data, dict):
            raise TenantConfigError(
                f"tenant config entry must be an object, got "
                f"{type(data).__name__}."
            )

        recognized = {
            "tenant_id", "display_name", "model", "fallback_models",
            "circuit_breaker", "regulation_set", "metadata",
        }
        unknown = set(data.keys()) - recognized
        if unknown:
            raise TenantConfigError(
                f"unknown tenant config keys: {sorted(unknown)}. "
                f"Recognized keys: {sorted(recognized)}."
            )

        if "tenant_id" not in data:
            raise TenantConfigError("tenant config entry missing 'tenant_id'.")
        if "display_name" not in data:
            raise TenantConfigError(
                f"tenant {data.get('tenant_id')!r} missing 'display_name'."
            )

        circuit_breaker = None
        cb_data = data.get("circuit_breaker")
        if cb_data is not None:
            if not isinstance(cb_data, dict):
                raise TenantConfigError(
                    f"tenant {data['tenant_id']!r} circuit_breaker must be "
                    f"an object."
                )
            from resilience import CircuitBreakerConfig
            try:
                circuit_breaker = CircuitBreakerConfig(**cb_data)
            except (TypeError, ValueError) as exc:
                raise TenantConfigError(
                    f"tenant {data['tenant_id']!r} circuit_breaker is "
                    f"invalid: {exc}"
                ) from exc

        fallback = data.get("fallback_models", ())
        regulation = data.get("regulation_set", ())
        return cls(
            tenant_id=data["tenant_id"],
            display_name=data["display_name"],
            model=data.get("model"),
            fallback_models=tuple(fallback),
            circuit_breaker=circuit_breaker,
            regulation_set=tuple(regulation),
            metadata=dict(data.get("metadata", {})),
        )
