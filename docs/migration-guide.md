# Migration guide

This document explains how to migrate triage records from an older output-contract version to a newer one, using the `migration` package and the `vrt migrate` CLI subcommand.

## When you need migration

The framework's output contract has versions: 1.0.0, 1.1.0, 1.2.0, and 1.3.0. A record carries the version it was produced under in its `output_schema_version` field, and it stays valid against that version's contract forever (the framework keeps every published schema and validates each record against its own declared version). So you do not need to migrate records just because a new contract version exists. Migration is for when a consumer specifically needs records at a newer version, most commonly:

- A downstream system that only understands the latest contract and needs old records brought forward.
- A reporting or analytics layer that wants every record at one uniform version.
- Adopting tenancy: bringing pre-1.3.0 records into the tenant-attributed world so every record has a `tenant_id`.

If none of those apply, leave records at the version they were produced under. They remain valid.

## What migration does

The version chain has two kinds of step:

- **Additive hops (1.0.0 to 1.1.0 to 1.2.0).** Each of these added only optional fields (`correlation_id` in 1.1.0, `cost_estimate` in 1.2.0). A record produced under the older version is already a structurally valid newer-version record; migrating just updates the `output_schema_version` stamp. No data is invented.
- **The tenancy hop (1.2.0 to 1.3.0).** 1.3.0 added a required `tenant_id`. A pre-1.3.0 record has no tenant identity, so this step must assign one. This is the only step that does more than restamp.

Migration is idempotent at the target (migrating a record that already declares the target version returns it unchanged after validation) and refuses to migrate downward (it only moves records forward). Every migrated record is validated against the target contract before it is returned, so a successful migration always produces a conforming record.

## The tenant-assignment decision

The 1.2.0 to 1.3.0 hop must source a `tenant_id` for records that never had one. The framework does not guess or silently default. You supply the tenant explicitly, in one of two ways:

- **One tenant for the whole batch.** When every record in the file belongs to one client, name that client once. CLI: `--tenant-id acme-bank`. Programmatic: `fixed_tenant_resolver("acme-bank")`.
- **A tenant per record.** When a single file holds records for several clients, supply a mapping from each record's `decision_id` to its tenant. CLI: `--tenant-map tenants-by-id.json`. Programmatic: `mapping_tenant_resolver(mapping)`.

The reasoning behind requiring an explicit choice: migration is a deliberate, operator-initiated batch action. There is always a human in the loop who can answer "whose records are these." Defaulting a missing tenant to a placeholder would silently relabel real clients' historical records as unconfigured and lose their provenance, which is exactly the kind of un-attributed record a multi-tenant audit posture cannot tolerate. Demanding the operator name the tenant costs almost nothing and prevents that harm. (This is the inverse of the triage-time stance, where a single-org deployment running without a tenant does get the `__default__` sentinel plus a warning, because refusing every single-org triage would be too costly. At migration time the calculus favors the explicit choice.)

The sentinel `__default__` is still reachable, but only by asking for it explicitly: `--tenant-id __default__`. Use that only when you genuinely know the records belong to an unconfigured single-organization deployment.

### Constraining to known tenants

Pass `--tenants tenants.json` (a tenant registry file, the same format the `tenancy` package loads) to constrain resolved tenant ids to known tenants. A tenant id that is not in the registry is rejected, so a typo in a `--tenant-id` flag or a stale entry in a `--tenant-map` fails loudly instead of minting a record attributed to a tenant that does not exist. The sentinel `__default__` is always permitted regardless of the registry.

## CLI usage

```
# Migrate one record to the latest contract, single client
vrt migrate record.json --to 1.3.0 --tenant-id acme-bank

# Migrate a JSONL batch where records belong to different clients
vrt migrate records.jsonl --to 1.3.0 --tenant-map tenants-by-id.json

# Constrain resolved tenant ids to a known registry
vrt migrate records.jsonl --to 1.3.0 --tenant-id acme-bank --tenants tenants.json

# An additive-only hop needs no tenant source
vrt migrate old-record.json --to 1.2.0

# Write to a file instead of stdout
vrt migrate records.jsonl --to 1.3.0 --tenant-id acme-bank --output migrated.jsonl
```

### Input shapes

`vrt migrate` auto-detects the input shape:

- A file that parses as a single JSON object is treated as one record. Output is a single pretty-printed JSON object.
- A file that parses as a JSON array of objects, or a JSONL file (one JSON object per line, with `#` comment lines and blank lines skipped), is treated as a batch. Output is JSONL, one record per line.

### Exit codes

- `0`: all records migrated and validated successfully.
- `1`: a record failed to migrate or validate (malformed JSON, downward migration, an unresolved tenant, or output that fails the target contract). In a batch, the failing record is reported with its `decision_id`.
- `2`: setup error (input file not found, both `--tenant-id` and `--tenant-map` supplied, unknown target version, an unwritable output path, a missing or invalid registry/map file).

## Programmatic usage

```python
from migration import migrate_record, fixed_tenant_resolver, mapping_tenant_resolver

# Additive hop: no tenant needed
migrated = migrate_record(old_record, "1.2.0")

# Tenancy hop: whole-batch tenant
migrated = migrate_record(record, "1.3.0", fixed_tenant_resolver("acme-bank"))

# Tenancy hop: per-record mapping, constrained to a registry
from tenancy import TenantRegistry
registry = TenantRegistry.from_json_file("tenants.json")
resolver = mapping_tenant_resolver({"d-001": "acme-bank"}, registry=registry)
migrated = migrate_record(record, "1.3.0", resolver)
```

`migrate_record` does not mutate its input; it returns a new dict. It raises `MigrationError` (or its subclass `TenantResolutionError`) on any failure, so wrap a batch loop in a try/except if you want to collect failures rather than stop at the first.

## A note on why this sub-system exists

Every schema change before 1.3.0 was additive-optional, so "migration" across those versions is only a version restamp, hardly worth an engine. The migration engine earns its complexity because of the 1.2.0 to 1.3.0 break: that is the first change where an old record cannot be made valid at the new version by a restamp alone, because it is missing a required field with no sensible automatic default. The engine exists to carry records across that break safely, with the tenant assignment made explicit and auditable rather than guessed. In other words, the migration tooling is the safety net for the framework's first breaking change: the two were designed together.
