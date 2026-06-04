"""Up-migrate triage records across output-contract versions.

The framework's output contract has evolved 1.0.0 -> 1.1.0 -> 1.2.0 ->
1.3.0. A record produced under an older version can be migrated forward
to a newer one. This package is the engine that does it.

The version chain splits into two kinds of hop:

- **Additive-optional hops (1.0.0 -> 1.1.0 -> 1.2.0).** Each of these
  added only optional fields. A record produced under the older
  version is already structurally valid under the newer one; migrating
  is a version restamp (bump ``output_schema_version``). No data is
  invented.
- **The breaking hop (1.2.0 -> 1.3.0).** 1.3.0 added a *required*
  ``tenant_id`` field. A pre-1.3.0 record has no tenant identity, so
  this hop must source one. The engine does not guess: the caller
  supplies a tenant resolver, and migration fails loudly if it cannot
  produce a valid tenant_id. This mirrors the framework's stance that
  a record must never be silently mis-attributed (see the migration
  guide and the SS2 default-tenant discussion): at migration time
  there is always an operator in the loop who can answer "whose
  records are these," so the engine makes them answer rather than
  defaulting.

Migration is idempotent at the target: migrating a record that already
declares the target version is a no-op (it is returned unchanged after
validation). Downward migration is refused: the engine only moves
records forward, never strips fields to fit an older contract.

The engine validates its output against the target schema (via the
framework's own dispatch) before returning, so a migrated record is
guaranteed to conform to the contract it now claims.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from agent.output_models import (
    DEFAULT_TENANT_ID,
    _TENANT_ID_SLUG_PATTERN,
    _version_tuple,
)
from schemas.validate import _OUTPUT_SCHEMA_FILES, validate_output


__all__ = [
    "MigrationError",
    "TenantResolutionError",
    "migrate_record",
    "KNOWN_VERSIONS",
    "TenantResolver",
]


# The known output-contract versions, in ascending order. Sourced from
# the validator dispatch so this stays in lockstep with what the
# framework can actually validate against.
KNOWN_VERSIONS: tuple[str, ...] = tuple(
    sorted(_OUTPUT_SCHEMA_FILES.keys(), key=_version_tuple)
)

# The version at which tenant_id became required.
_TENANCY_VERSION: tuple[int, int, int] = (1, 3, 0)
# The version at which determinism_attestation became required.
_DETERMINISM_VERSION: tuple[int, int, int] = (1, 4, 0)


def _migrated_attestation(source_version: str) -> dict:
    """Build the determinism attestation for a record migrated from a
    pre-1.0.5 contract.

    Records produced under contracts 1.0.0-1.3.0 predate the determinism
    contract entirely. They cannot be retroactively attested: no
    measurement of the producing agent's temperature, system prompt,
    corpus bundle, or fallback path exists. The migrated record's
    attestation faithfully records this: ``migrated_from`` carries the
    discriminator value, ``contract_honored`` is ``False``, every other
    field is ``null``, and ``contract_version`` is ``None`` (no contract
    was in force at production time).

    Operators distinguish "migrated, contract not in force" from "fresh,
    contract violation at production" by inspecting ``migrated_from``:
    when set, the violation predates the contract and cannot be
    reattested.
    """
    return {
        "effective_temperature": None,
        "contract_honored": False,
        "provider": None,
        "effective_model_id": None,
        "fallback": None,
        "sampling_profile_hash": None,
        "system_prompt_hash": None,
        "corpus_bundle_hash": None,
        "contract_version": None,
        "migrated_from": source_version,
    }


# A tenant resolver maps a record (the pre-migration dict) to a
# tenant_id string. It is called only for the 1.2.0 -> 1.3.0 hop, and
# only for records that do not already carry a tenant_id. Raising
# TenantResolutionError signals the resolver could not produce a tenant
# for this record (e.g. a per-record map with no entry for it).
TenantResolver = Callable[[dict], str]


class MigrationError(ValueError):
    """Raised when a record cannot be migrated (bad version, downward, etc.)."""


class TenantResolutionError(MigrationError):
    """Raised when the 1.2.0 -> 1.3.0 hop cannot source a valid tenant_id."""


_SLUG_RE = re.compile(_TENANT_ID_SLUG_PATTERN)


def _validate_tenant_id(tenant_id: str, record_decision_id: str) -> str:
    """Validate a resolved tenant_id against the slug-or-sentinel rule."""
    if tenant_id == DEFAULT_TENANT_ID:
        return tenant_id
    if not isinstance(tenant_id, str) or not _SLUG_RE.match(tenant_id):
        raise TenantResolutionError(
            f"resolved tenant_id {tenant_id!r} for record "
            f"{record_decision_id!r} is not a valid slug (lowercase "
            f"alphanumerics and hyphens, starting and ending with an "
            f"alphanumeric) or the sentinel {DEFAULT_TENANT_ID!r}."
        )
    return tenant_id


def migrate_record(
    record: dict,
    target_version: str,
    tenant_resolver: Optional[TenantResolver] = None,
) -> dict:
    """Up-migrate a single record dict to ``target_version``.

    Args:
        record: The record to migrate, as a plain dict. Must carry an
            ``output_schema_version``; if absent, 1.0.0 is assumed
            (the contract's pre-versioning default, matching the
            validator's behavior).
        target_version: The version to migrate to. Must be a known
            version.
        tenant_resolver: Callable producing a tenant_id for a record
            that crosses the 1.2.0 -> 1.3.0 boundary without one.
            Required only when that hop is in range for a record
            lacking tenant_id; a MigrationError is raised if it is
            needed and not supplied.

    Returns:
        A new dict (the input is not mutated) declaring
        ``target_version`` and conforming to the target schema.

    Raises:
        MigrationError: unknown source/target version, downward
            migration, or output that fails the target schema.
        TenantResolutionError: the tenancy hop needs a tenant_id and
            the resolver could not produce a valid one.
    """
    if target_version not in _OUTPUT_SCHEMA_FILES:
        raise MigrationError(
            f"unknown target version {target_version!r}. Known "
            f"versions: {list(KNOWN_VERSIONS)}."
        )

    source_version = record.get("output_schema_version", "1.0.0")
    if source_version not in _OUTPUT_SCHEMA_FILES:
        raise MigrationError(
            f"record declares unknown source version "
            f"{source_version!r}. Known versions: {list(KNOWN_VERSIONS)}."
        )

    source_tuple = _version_tuple(source_version)
    target_tuple = _version_tuple(target_version)

    if target_tuple < source_tuple:
        raise MigrationError(
            f"refusing downward migration: record is {source_version}, "
            f"target is {target_version}. The engine only migrates "
            f"records forward."
        )

    # Idempotent no-op at the target: validate and return a copy.
    if target_tuple == source_tuple:
        migrated = dict(record)
        _validate_or_raise(migrated, target_version)
        return migrated

    # Work on a copy; never mutate the caller's dict.
    migrated = dict(record)
    decision_id = str(migrated.get("decision_id", "<unknown>"))

    # First structural hop: tenancy. If migration crosses from below
    # 1.3.0 to 1.3.0-or-above and the record has no tenant_id, source
    # one.
    crosses_tenancy = (
        source_tuple < _TENANCY_VERSION <= target_tuple
    )
    if crosses_tenancy and migrated.get("tenant_id") is None:
        if tenant_resolver is None:
            raise MigrationError(
                f"record {decision_id!r} (version {source_version}) "
                f"crosses the 1.3.0 tenancy boundary and has no "
                f"tenant_id, but no tenant_resolver was supplied. "
                f"Migration to {target_version} requires a tenant "
                f"source."
            )
        resolved = tenant_resolver(migrated)
        migrated["tenant_id"] = _validate_tenant_id(resolved, decision_id)

    # Second structural hop: determinism contract. If migration crosses
    # from below 1.4.0 to 1.4.0-or-above and the record has no
    # determinism_attestation, stamp the "migrated_from" attestation:
    # contract_honored=False, every data field null, migrated_from set
    # to the source version. Records produced under contracts
    # 1.0.0-1.3.0 predate the contract; they cannot be retroactively
    # attested.
    crosses_determinism = (
        source_tuple < _DETERMINISM_VERSION <= target_tuple
    )
    if crosses_determinism and migrated.get("determinism_attestation") is None:
        migrated["determinism_attestation"] = _migrated_attestation(
            source_version
        )

    # All hops (additive, tenancy, determinism) finish with a version
    # restamp.
    migrated["output_schema_version"] = target_version

    _validate_or_raise(migrated, target_version)
    return migrated


def _validate_or_raise(record: dict, target_version: str) -> None:
    """Validate a migrated record against the target schema dispatch."""
    ok, errors = validate_output(record)
    if not ok:
        raise MigrationError(
            f"migrated record does not conform to the {target_version} "
            f"output contract: {errors}"
        )
