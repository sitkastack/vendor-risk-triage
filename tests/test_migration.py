"""Tests for the migration engine and resolvers (Phase 7 SS3).

Covers up-migration across the output-contract version chain:

- Additive hops (1.0.0 -> 1.1.0 -> 1.2.0) are version restamps.
- The 1.2.0 -> 1.3.0 hop sources a tenant_id via a resolver
  (decision D4: explicit, never silently defaulted).
- Idempotent no-op at the target; downward migration refused.
- Resolvers: fixed (whole-batch), mapping (per-record), with an
  optional registry constraint and the explicit sentinel.
- Output is validated against the target contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from migration import (
    KNOWN_VERSIONS,
    MigrationError,
    TenantResolutionError,
    fixed_tenant_resolver,
    load_tenant_map,
    mapping_tenant_resolver,
    migrate_record,
)
from agent.output_models import DEFAULT_TENANT_ID
from tenancy import TenantConfig, TenantRegistry


def _record(version: str, decision_id: str = "d-001", with_tenant: bool = False) -> dict:
    rec = {
        "decision_id": decision_id,
        "decision_timestamp": "2026-05-28T12:00:00Z",
        "input_submission_id": "v-x",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.0+test+abc123def456",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "A rationale for the migration test.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "y."},
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
        "output_schema_version": version,
    }
    if with_tenant:
        rec["tenant_id"] = "acme-bank"
    return rec


# -- KNOWN_VERSIONS ------------------------------------------------------


def test_known_versions_ascending() -> None:
    assert KNOWN_VERSIONS == ("1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0")


# -- additive hops (restamp) ---------------------------------------------


@pytest.mark.parametrize("source,target", [
    ("1.0.0", "1.1.0"),
    ("1.0.0", "1.2.0"),
    ("1.1.0", "1.2.0"),
])
def test_additive_hop_restamps_without_tenant(source: str, target: str) -> None:
    """Additive hops need no tenant and just restamp the version."""
    result = migrate_record(_record(source), target)
    assert result["output_schema_version"] == target
    assert result.get("tenant_id") is None


def test_additive_hop_does_not_mutate_input() -> None:
    rec = _record("1.0.0")
    migrate_record(rec, "1.2.0")
    assert rec["output_schema_version"] == "1.0.0"


def test_missing_version_assumed_1_0_0() -> None:
    """A record without output_schema_version is treated as 1.0.0."""
    rec = _record("1.0.0")
    del rec["output_schema_version"]
    result = migrate_record(rec, "1.2.0")
    assert result["output_schema_version"] == "1.2.0"


# -- tenancy hop ---------------------------------------------------------


def test_tenancy_hop_without_resolver_raises() -> None:
    with pytest.raises(MigrationError, match="tenant"):
        migrate_record(_record("1.2.0"), "1.3.0")


def test_tenancy_hop_with_fixed_resolver() -> None:
    result = migrate_record(
        _record("1.2.0"), "1.3.0", fixed_tenant_resolver("acme-bank")
    )
    assert result["output_schema_version"] == "1.3.0"
    assert result["tenant_id"] == "acme-bank"


def test_tenancy_hop_from_1_0_0_through_to_1_3_0() -> None:
    """A 1.0.0 record migrates straight to 1.3.0 with a tenant."""
    result = migrate_record(
        _record("1.0.0"), "1.3.0", fixed_tenant_resolver("globex")
    )
    assert result["output_schema_version"] == "1.3.0"
    assert result["tenant_id"] == "globex"


def test_tenancy_hop_with_existing_tenant_id_keeps_it() -> None:
    """A record that already has a tenant_id keeps it (resolver not needed)."""
    result = migrate_record(_record("1.2.0", with_tenant=True), "1.3.0")
    assert result["tenant_id"] == "acme-bank"


def test_tenancy_hop_explicit_sentinel() -> None:
    result = migrate_record(
        _record("1.2.0"), "1.3.0", fixed_tenant_resolver(DEFAULT_TENANT_ID)
    )
    assert result["tenant_id"] == DEFAULT_TENANT_ID


def test_resolver_producing_bad_tenant_raises() -> None:
    with pytest.raises(TenantResolutionError):
        migrate_record(
            _record("1.2.0"), "1.3.0", fixed_tenant_resolver("Bad Tenant!")
        )


# -- idempotence + downward ----------------------------------------------


def test_idempotent_noop_at_target() -> None:
    rec = _record("1.3.0", with_tenant=True)
    result = migrate_record(rec, "1.3.0")
    assert result["output_schema_version"] == "1.3.0"
    assert result["tenant_id"] == "acme-bank"


def test_idempotent_noop_needs_no_resolver() -> None:
    """A 1.3.0 -> 1.3.0 no-op does not require a resolver."""
    rec = _record("1.3.0", with_tenant=True)
    result = migrate_record(rec, "1.3.0", tenant_resolver=None)
    assert result["tenant_id"] == "acme-bank"


def test_downward_migration_refused() -> None:
    rec = _record("1.3.0", with_tenant=True)
    with pytest.raises(MigrationError, match="downward"):
        migrate_record(rec, "1.2.0")


def test_unknown_target_raises() -> None:
    with pytest.raises(MigrationError, match="unknown target"):
        migrate_record(_record("1.0.0"), "9.9.9")


def test_unknown_source_raises() -> None:
    rec = _record("1.0.0")
    rec["output_schema_version"] = "8.8.8"
    with pytest.raises(MigrationError, match="unknown source"):
        migrate_record(rec, "1.3.0")


# -- determinism hop (1.3.0 -> 1.4.0) ------------------------------------


def test_determinism_hop_adds_attestation_with_migrated_from() -> None:
    """A 1.3.0 record migrated to 1.4.0 gains a 'migrated_from' attestation."""
    result = migrate_record(_record("1.3.0", with_tenant=True), "1.4.0")
    assert result["output_schema_version"] == "1.4.0"
    attestation = result["determinism_attestation"]
    assert attestation["migrated_from"] == "1.3.0"
    assert attestation["contract_honored"] is False
    # Every data field is null: the contract was not in force at
    # production time, so nothing can be retroactively measured.
    assert attestation["effective_temperature"] is None
    assert attestation["provider"] is None
    assert attestation["effective_model_id"] is None
    assert attestation["fallback"] is None
    assert attestation["sampling_profile_hash"] is None
    assert attestation["system_prompt_hash"] is None
    assert attestation["corpus_bundle_hash"] is None
    # contract_version is null because no contract was in force.
    assert attestation["contract_version"] is None


def test_determinism_hop_from_1_0_0_through_to_1_4_0() -> None:
    """A 1.0.0 record migrates straight to 1.4.0 with attestation + tenant."""
    result = migrate_record(
        _record("1.0.0"), "1.4.0", fixed_tenant_resolver("globex")
    )
    assert result["output_schema_version"] == "1.4.0"
    assert result["tenant_id"] == "globex"
    # The migrated_from records the SOURCE version, not 1.3.0
    # (the determinism boundary).
    assert result["determinism_attestation"]["migrated_from"] == "1.0.0"


def test_determinism_hop_preserves_existing_attestation_if_present() -> None:
    """A record that already carries an attestation keeps it."""
    rec = _record("1.4.0", with_tenant=True)
    rec["determinism_attestation"] = {
        "effective_temperature": 0.0,
        "contract_honored": True,
        "provider": "anthropic",
        "effective_model_id": "anthropic:claude-sonnet-4-5",
        "fallback": None,
        "sampling_profile_hash": "abcdef012345",
        "system_prompt_hash": "f" * 64,
        "corpus_bundle_hash": "0" * 64,
        "contract_version": "1.0.0",
        "migrated_from": None,
    }
    result = migrate_record(rec, "1.4.0")
    # Idempotent no-op preserves the attestation untouched.
    assert result["determinism_attestation"]["contract_honored"] is True
    assert result["determinism_attestation"]["migrated_from"] is None


def test_determinism_hop_validates_against_1_4_0() -> None:
    """The migrated attestation passes 1.4.0 schema validation."""
    from schemas.validate import validate_output
    result = migrate_record(
        _record("1.3.0", with_tenant=True), "1.4.0"
    )
    ok, errors = validate_output(result)
    assert ok, f"migrated 1.4.0 record should validate: {errors}"


# -- output validation ---------------------------------------------------


def test_migrated_output_validates_against_target() -> None:
    """The migrated record conforms to the target contract."""
    from schemas.validate import validate_output
    result = migrate_record(
        _record("1.0.0"), "1.3.0", fixed_tenant_resolver("acme-bank")
    )
    ok, errors = validate_output(result)
    assert ok, f"migrated record should validate: {errors}"


def test_migration_rejects_output_that_fails_target_schema() -> None:
    """A structurally invalid record fails validation at the target.

    The engine validates its output against the target contract before
    returning; a record that is a dict but does not conform (here, an
    invalid risk_tier) raises MigrationError rather than emitting a
    non-conforming record.
    """
    rec = _record("1.0.0")
    rec["risk_tier"] = "not_a_real_tier"
    with pytest.raises(MigrationError, match="does not conform"):
        migrate_record(rec, "1.2.0")


# -- fixed resolver ------------------------------------------------------


def test_fixed_resolver_assigns_same_tenant() -> None:
    resolver = fixed_tenant_resolver("acme-bank")
    assert resolver({"decision_id": "a"}) == "acme-bank"
    assert resolver({"decision_id": "b"}) == "acme-bank"


def test_fixed_resolver_registry_accepts_known() -> None:
    reg = TenantRegistry([TenantConfig(tenant_id="acme-bank", display_name="A")])
    resolver = fixed_tenant_resolver("acme-bank", registry=reg)
    assert resolver({}) == "acme-bank"


def test_fixed_resolver_registry_rejects_unknown() -> None:
    reg = TenantRegistry([TenantConfig(tenant_id="acme-bank", display_name="A")])
    with pytest.raises(TenantResolutionError, match="not in the supplied"):
        fixed_tenant_resolver("unknown-co", registry=reg)


def test_fixed_resolver_registry_allows_sentinel() -> None:
    reg = TenantRegistry([TenantConfig(tenant_id="acme-bank", display_name="A")])
    resolver = fixed_tenant_resolver(DEFAULT_TENANT_ID, registry=reg)
    assert resolver({}) == DEFAULT_TENANT_ID


# -- mapping resolver ----------------------------------------------------


def test_mapping_resolver_per_record() -> None:
    resolver = mapping_tenant_resolver({"d-001": "acme-bank", "d-002": "globex"})
    assert resolver({"decision_id": "d-001"}) == "acme-bank"
    assert resolver({"decision_id": "d-002"}) == "globex"


def test_mapping_resolver_missing_entry_raises() -> None:
    resolver = mapping_tenant_resolver({"d-001": "acme-bank"})
    with pytest.raises(TenantResolutionError, match="no tenant mapping entry"):
        resolver({"decision_id": "d-999"})


def test_mapping_resolver_missing_key_field_raises() -> None:
    resolver = mapping_tenant_resolver({"d-001": "acme-bank"})
    with pytest.raises(TenantResolutionError, match="no .* field"):
        resolver({})


def test_mapping_resolver_custom_key_field() -> None:
    resolver = mapping_tenant_resolver(
        {"v-1": "acme-bank"}, key_field="input_submission_id"
    )
    assert resolver({"input_submission_id": "v-1"}) == "acme-bank"


def test_mapping_resolver_registry_rejects_unknown() -> None:
    reg = TenantRegistry([TenantConfig(tenant_id="acme-bank", display_name="A")])
    resolver = mapping_tenant_resolver({"d-001": "unknown-co"}, registry=reg)
    with pytest.raises(TenantResolutionError, match="not in the supplied"):
        resolver({"decision_id": "d-001"})


# -- load_tenant_map -----------------------------------------------------


def test_load_tenant_map(tmp_path: Path) -> None:
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"d-001": "acme-bank"}), encoding="utf-8")
    assert load_tenant_map(p) == {"d-001": "acme-bank"}


def test_load_tenant_map_string_path(tmp_path: Path) -> None:
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"d-001": "acme-bank"}), encoding="utf-8")
    assert load_tenant_map(str(p)) == {"d-001": "acme-bank"}


def test_load_tenant_map_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(TenantResolutionError, match="not found"):
        load_tenant_map(tmp_path / "nope.json")


def test_load_tenant_map_bad_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(TenantResolutionError, match="not valid JSON"):
        load_tenant_map(p)


def test_load_tenant_map_not_object_raises(tmp_path: Path) -> None:
    p = tmp_path / "arr.json"
    p.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(TenantResolutionError, match="must be a JSON object"):
        load_tenant_map(p)


def test_load_tenant_map_non_string_value_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"d-001": 123}), encoding="utf-8")
    with pytest.raises(TenantResolutionError, match="non-string"):
        load_tenant_map(p)
