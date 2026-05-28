"""Record migration across output-contract versions.

Up-migrates triage records from older output-contract versions to
newer ones. The additive hops (1.0.0 -> 1.1.0 -> 1.2.0) are version
restamps; the 1.2.0 -> 1.3.0 hop is the framework's one real
migration, assigning a tenant_id to records that predate tenancy.

Public exports:

- ``migrate_record``: up-migrate a single record dict to a target
  version, validating the result against the target contract.
- ``MigrationError`` / ``TenantResolutionError``: raised on migration
  failures.
- ``KNOWN_VERSIONS``: the output-contract versions, ascending.
- ``fixed_tenant_resolver`` / ``mapping_tenant_resolver``: build the
  tenant resolvers the 1.2.0 -> 1.3.0 hop needs (whole-batch and
  per-record).
- ``load_tenant_map``: load a per-record tenant map JSON file.

The ``vrt migrate`` CLI subcommand wraps this package. See
``docs/migration-guide.md``.
"""
from migration.engine import (
    KNOWN_VERSIONS,
    MigrationError,
    TenantResolutionError,
    TenantResolver,
    migrate_record,
)
from migration.resolvers import (
    fixed_tenant_resolver,
    load_tenant_map,
    mapping_tenant_resolver,
)


__all__ = [
    "migrate_record",
    "MigrationError",
    "TenantResolutionError",
    "TenantResolver",
    "KNOWN_VERSIONS",
    "fixed_tenant_resolver",
    "mapping_tenant_resolver",
    "load_tenant_map",
]
