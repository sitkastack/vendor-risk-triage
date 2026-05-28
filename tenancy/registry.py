"""Registry of tenant configurations.

A ``TenantRegistry`` holds the set of ``TenantConfig`` objects for a
deployment and provides lookup by tenant_id. It can be built
programmatically (register configs one at a time) or loaded from a
JSON file describing all tenants at once.

The registry is the single place the rest of the framework asks "what
is the configuration for tenant X." A later sub-system wires the agent
to consult the registry; SS1 provides the registry itself.

JSON file format::

    {
      "tenants": [
        {
          "tenant_id": "acme-bank",
          "display_name": "Acme Bank",
          "model": "anthropic:claude-sonnet-4-5",
          "fallback_models": ["openai:gpt-5.4"],
          "regulation_set": ["osfi-e23"],
          "circuit_breaker": {"failure_rate_threshold": 0.5},
          "metadata": {"account_owner": "rt", "tier": "enterprise"}
        }
      ]
    }

Duplicate tenant_ids in a single load are rejected: a deployment must
not have two configurations claiming the same tenant identity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

from tenancy.config import TenantConfig, TenantConfigError


__all__ = ["TenantRegistry", "TenantRegistryError"]


class TenantRegistryError(ValueError):
    """Raised on registry-level problems (duplicate ids, bad file)."""


class TenantRegistry:
    """Holds tenant configurations and provides lookup by tenant_id."""

    def __init__(self, configs: Iterable[TenantConfig] | None = None) -> None:
        self._tenants: dict[str, TenantConfig] = {}
        if configs is not None:
            for config in configs:
                self.register(config)

    def register(self, config: TenantConfig) -> None:
        """Add a tenant config. Rejects a duplicate tenant_id."""
        if config.tenant_id in self._tenants:
            raise TenantRegistryError(
                f"duplicate tenant_id {config.tenant_id!r}: a tenant with "
                f"that id is already registered."
            )
        self._tenants[config.tenant_id] = config

    def get(self, tenant_id: str) -> TenantConfig:
        """Return the config for a tenant_id, or raise KeyError.

        Raising (rather than returning None) is deliberate: in a
        multi-tenant deployment, asking for an unregistered tenant is a
        programming or configuration error that should fail loudly, not
        silently produce a None that flows downstream into an
        un-attributed record.
        """
        if tenant_id not in self._tenants:
            raise KeyError(
                f"no tenant registered with id {tenant_id!r}. "
                f"Registered tenants: {sorted(self._tenants.keys())}."
            )
        return self._tenants[tenant_id]

    def has(self, tenant_id: str) -> bool:
        """Return True if a tenant with this id is registered."""
        return tenant_id in self._tenants

    def all_tenants(self) -> list[TenantConfig]:
        """Return all registered configs, ordered by tenant_id."""
        return [self._tenants[k] for k in sorted(self._tenants.keys())]

    def tenant_ids(self) -> list[str]:
        """Return the registered tenant ids, sorted."""
        return sorted(self._tenants.keys())

    def __len__(self) -> int:
        return len(self._tenants)

    def __iter__(self) -> Iterator[TenantConfig]:
        return iter(self.all_tenants())

    @classmethod
    def from_dict(cls, data: dict) -> "TenantRegistry":
        """Build a registry from a parsed config dict.

        Expects a top-level ``tenants`` key whose value is a list of
        tenant config objects (see module docstring for the format).
        """
        if not isinstance(data, dict):
            raise TenantRegistryError(
                f"tenant config must be an object with a 'tenants' key, "
                f"got {type(data).__name__}."
            )
        if "tenants" not in data:
            raise TenantRegistryError(
                "tenant config must have a top-level 'tenants' key."
            )
        tenants_raw = data["tenants"]
        if not isinstance(tenants_raw, list):
            raise TenantRegistryError(
                f"'tenants' must be a list, got {type(tenants_raw).__name__}."
            )

        registry = cls()
        for index, entry in enumerate(tenants_raw):
            try:
                config = TenantConfig.from_dict(entry)
            except TenantConfigError as exc:
                raise TenantRegistryError(
                    f"tenant config at index {index} is invalid: {exc}"
                ) from exc
            registry.register(config)
        return registry

    @classmethod
    def from_json_file(cls, path: Path | str) -> "TenantRegistry":
        """Load a registry from a JSON file."""
        path = Path(path)
        if not path.exists():
            raise TenantRegistryError(f"tenant config file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TenantRegistryError(
                f"tenant config file {path} is not valid JSON: {exc}"
            ) from exc
        return cls.from_dict(data)
