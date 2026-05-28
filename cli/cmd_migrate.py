"""``vrt migrate`` subcommand: up-migrate records to a newer output contract.

Usage::

    # Migrate a single record to the latest contract, whole-batch tenant
    vrt migrate record.json --to 1.3.0 --tenant-id acme-bank

    # Migrate a JSONL batch where records belong to different tenants
    vrt migrate records.jsonl --to 1.3.0 --tenant-map tenants-by-id.json

    # Constrain resolved tenant ids to a known registry
    vrt migrate records.jsonl --to 1.3.0 --tenant-id acme-bank \\
        --tenants tenants.json

    # Write migrated output to a file (default: stdout)
    vrt migrate records.jsonl --to 1.3.0 --tenant-id acme-bank \\
        --output migrated.jsonl

Input is auto-detected: a file whose first non-empty content parses as
a single JSON object is treated as one record; a file with one JSON
object per line is treated as a JSONL batch.

The 1.2.0 -> 1.3.0 hop requires a tenant source. Exactly one of
``--tenant-id`` (assign one tenant to every migrated record) or
``--tenant-map`` (assign per record by decision_id) must be supplied
when any record crosses that boundary without an existing tenant_id.
The engine never defaults a tenant silently; the sentinel is reachable
only by passing ``--tenant-id __default__`` explicitly.

Exit codes:

- ``0``: all records migrated and validated successfully
- ``1``: a record failed to migrate or validate (bad JSON, downward
  migration, unresolved tenant, output fails the target contract)
- ``2``: setup error (input file not found, bad flag combination,
  output unwritable)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


__all__ = ["add_arguments", "run"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``migrate`` arguments."""
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "Path to a record JSON file (single object) or a JSONL "
            "batch (one record per line)."
        ),
    )
    parser.add_argument(
        "--to",
        type=str,
        required=True,
        help="Target output-contract version, e.g. 1.3.0.",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help=(
            "Assign this tenant_id to every migrated record that crosses "
            "the 1.3.0 tenancy boundary without one. Mutually exclusive "
            "with --tenant-map. Pass '__default__' to explicitly use the "
            "sentinel."
        ),
    )
    parser.add_argument(
        "--tenant-map",
        type=Path,
        default=None,
        help=(
            "Path to a JSON object mapping decision_id to tenant_id, "
            "assigning a tenant per record. Mutually exclusive with "
            "--tenant-id."
        ),
    )
    parser.add_argument(
        "--tenants",
        type=Path,
        default=None,
        help=(
            "Optional path to a tenant registry JSON file. When "
            "supplied, resolved tenant ids are checked against it and a "
            "tenant id absent from the registry is rejected."
        ),
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Path to write migrated output. Default: print to stdout.",
    )


def _load_input_records(path: Path) -> tuple[list[dict], bool]:
    """Load records from a single-object or JSONL file.

    Returns (records, is_batch). Raises ValueError on malformed input.
    The detection: parse the whole file as JSON first; if that yields a
    single object, it is one record. Otherwise parse line-by-line as
    JSONL (skipping blank lines and comment lines starting with '#').
    """
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        raise ValueError("input file is empty.")

    # Try whole-file single JSON object first.
    try:
        whole = json.loads(stripped)
        if isinstance(whole, dict):
            return [whole], False
        if isinstance(whole, list):
            # A JSON array of records is accepted as a batch too.
            if not all(isinstance(r, dict) for r in whole):
                raise ValueError(
                    "JSON array input must contain only record objects."
                )
            return list(whole), True
        raise ValueError(
            "single-JSON input must be an object or array of objects."
        )
    except json.JSONDecodeError:
        pass  # Fall through to JSONL parsing.

    # JSONL: one object per line.
    records: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {lineno} is not valid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"line {lineno} is not a JSON object.")
        records.append(obj)
    if not records:
        raise ValueError("no records found in input.")
    return records, True


def run(args: argparse.Namespace) -> int:
    """Migrate records to the target output-contract version."""
    from migration import (
        KNOWN_VERSIONS,
        MigrationError,
        fixed_tenant_resolver,
        load_tenant_map,
        mapping_tenant_resolver,
        migrate_record,
    )

    # Validate target version up front.
    if args.to not in KNOWN_VERSIONS:
        print(
            f"ERROR: unknown target version {args.to!r}. Known "
            f"versions: {list(KNOWN_VERSIONS)}.",
            file=sys.stderr,
        )
        return 2

    # Mutually-exclusive tenant source.
    if args.tenant_id is not None and args.tenant_map is not None:
        print(
            "ERROR: --tenant-id and --tenant-map are mutually exclusive. "
            "Pass exactly one.",
            file=sys.stderr,
        )
        return 2

    # Input file present.
    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2

    # Optional registry.
    registry: Optional[object] = None
    if args.tenants is not None:
        if not args.tenants.exists():
            print(
                f"ERROR: tenants registry file not found: {args.tenants}",
                file=sys.stderr,
            )
            return 2
        from tenancy import TenantRegistry, TenantRegistryError
        try:
            registry = TenantRegistry.from_json_file(args.tenants)
        except TenantRegistryError as exc:
            print(f"ERROR: invalid tenants registry: {exc}", file=sys.stderr)
            return 2

    # Build the tenant resolver from the chosen source (may be None: if
    # no record crosses the tenancy boundary without a tenant_id, the
    # engine never calls it, and a missing resolver is only an error at
    # the point a record actually needs one).
    resolver = None
    if args.tenant_id is not None:
        try:
            resolver = fixed_tenant_resolver(args.tenant_id, registry=registry)
        except MigrationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    elif args.tenant_map is not None:
        if not args.tenant_map.exists():
            print(
                f"ERROR: tenant map file not found: {args.tenant_map}",
                file=sys.stderr,
            )
            return 2
        try:
            mapping = load_tenant_map(args.tenant_map)
        except MigrationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        resolver = mapping_tenant_resolver(mapping, registry=registry)

    # Load input.
    try:
        records, is_batch = _load_input_records(args.input)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Migrate each record.
    migrated: list[dict] = []
    for index, record in enumerate(records):
        try:
            result = migrate_record(record, args.to, tenant_resolver=resolver)
        except MigrationError as exc:
            label = (
                f"record {index} ({record.get('decision_id', '<no id>')})"
                if is_batch else "record"
            )
            print(f"ERROR: {label} failed to migrate: {exc}", file=sys.stderr)
            return 1
        migrated.append(result)

    # Emit output: JSONL for a batch, a single pretty object otherwise.
    if is_batch:
        out_text = "\n".join(json.dumps(r) for r in migrated) + "\n"
    else:
        out_text = json.dumps(migrated[0], indent=2) + "\n"

    if args.output is not None:
        try:
            args.output.write_text(out_text, encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: could not write output: {exc}", file=sys.stderr)
            return 2
        print(
            f"Migrated {len(migrated)} record(s) to {args.to} -> "
            f"{args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out_text)

    return 0
