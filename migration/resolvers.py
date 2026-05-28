"""Tenant resolver builders for record migration.

The 1.2.0 -> 1.3.0 migration hop must assign a tenant_id to records
that predate tenancy. ``migrate_record`` accepts a ``tenant_resolver``
callable for this; this module provides the two standard resolvers
(decision D4: an operator supplies one explicitly, the engine never
defaults silently):

- ``fixed_tenant_resolver(tenant_id)``: assigns the same tenant_id to
  every record. The whole-batch case, when an operator knows all the
  records being migrated belong to one client. Corresponds to the CLI
  ``--tenant-id`` flag.
- ``mapping_tenant_resolver(mapping, key_field)``: assigns a tenant_id
  per record by looking up a key field (default ``decision_id``) in a
  mapping. The mixed-batch case, when a single file holds records for
  several clients. Corresponds to the CLI ``--tenant-map`` flag.

An optional ``registry`` constrains either resolver to known tenant
ids: a resolved tenant_id absent from the registry raises, so a typo
or a stale mapping fails loudly rather than minting an unknown tenant.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from migration.engine import TenantResolutionError, TenantResolver


__all__ = [
    "fixed_tenant_resolver",
    "mapping_tenant_resolver",
    "load_tenant_map",
]


def _check_registry(tenant_id: str, registry: Optional[object]) -> None:
    """Raise if a registry is supplied and does not know this tenant_id.

    The sentinel ``__default__`` is always permitted (a registry of
    real tenants is not expected to contain it). ``registry`` is duck-
    typed on ``has(tenant_id)`` so a TenantRegistry plugs in without a
    hard import dependency from this module.
    """
    if registry is None:
        return
    from agent.output_models import DEFAULT_TENANT_ID
    if tenant_id == DEFAULT_TENANT_ID:
        return
    if not registry.has(tenant_id):
        raise TenantResolutionError(
            f"resolved tenant_id {tenant_id!r} is not in the supplied "
            f"tenant registry. Known tenants: "
            f"{registry.tenant_ids() if hasattr(registry, 'tenant_ids') else '<unknown>'}."
        )


def fixed_tenant_resolver(
    tenant_id: str,
    registry: Optional[object] = None,
) -> TenantResolver:
    """Build a resolver that assigns the same tenant_id to every record.

    Args:
        tenant_id: The tenant_id to assign. Validated against the slug-
            or-sentinel rule by the engine; if a registry is supplied,
            also checked for membership here.
        registry: Optional TenantRegistry to constrain the tenant_id to
            known tenants.

    Returns:
        A resolver callable suitable for ``migrate_record``.
    """
    _check_registry(tenant_id, registry)

    def _resolve(_record: dict) -> str:
        return tenant_id

    return _resolve


def mapping_tenant_resolver(
    mapping: dict[str, str],
    key_field: str = "decision_id",
    registry: Optional[object] = None,
) -> TenantResolver:
    """Build a resolver that assigns tenant_id per record via a mapping.

    Args:
        mapping: Maps a record's key-field value to a tenant_id.
        key_field: The record field whose value keys the mapping.
            Defaults to ``decision_id``.
        registry: Optional TenantRegistry to constrain resolved
            tenant_ids to known tenants.

    Returns:
        A resolver callable. Raises TenantResolutionError when a record
        has no value for the key field, or the mapping has no entry for
        that value.
    """
    def _resolve(record: dict) -> str:
        key = record.get(key_field)
        if key is None:
            raise TenantResolutionError(
                f"record has no {key_field!r} field to resolve a tenant "
                f"from the mapping."
            )
        if key not in mapping:
            raise TenantResolutionError(
                f"no tenant mapping entry for {key_field}={key!r}. "
                f"Add an entry to the tenant map or correct the record."
            )
        tenant_id = mapping[key]
        _check_registry(tenant_id, registry)
        return tenant_id

    return _resolve


def load_tenant_map(path: Path | str) -> dict[str, str]:
    """Load a tenant map JSON file: {key_value: tenant_id, ...}.

    The file is a flat JSON object mapping a record key (by default the
    decision_id) to a tenant_id. Raises TenantResolutionError on a
    missing file, invalid JSON, or a non-object / non-string-valued
    structure.
    """
    path = Path(path)
    if not path.exists():
        raise TenantResolutionError(f"tenant map file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TenantResolutionError(
            f"tenant map file {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise TenantResolutionError(
            f"tenant map file {path} must be a JSON object mapping "
            f"record keys to tenant ids."
        )
    for key, value in data.items():
        if not isinstance(value, str):
            raise TenantResolutionError(
                f"tenant map entry {key!r} has a non-string tenant_id "
                f"{value!r}."
            )
    return data
