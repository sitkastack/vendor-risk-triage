"""Tests for the tenancy package (Phase 7 SS1).

Covers TenantConfig construction and validation, the from_dict
parser, TenantRegistry lookup/registration/duplicate-rejection, JSON
file loading, and the example tenant config file.

SS1 is the configuration foundation only: no agent integration, no
schema change. Those are tested in later sub-systems.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tenancy import (
    TenantConfig,
    TenantConfigError,
    TenantRegistry,
    TenantRegistryError,
    VALID_REGULATION_IDS,
)


_REPO_ROOT = Path(__file__).parent.parent
_EXAMPLE_TENANTS = _REPO_ROOT / "examples" / "tenancy" / "tenants.example.json"


# -- VALID_REGULATION_IDS ------------------------------------------------


def test_valid_regulation_ids_sourced_from_corpus_registry() -> None:
    """The valid regulation ids match the live corpus registry keys."""
    from retrieval.corpora import CORPUS_REGISTRY
    assert VALID_REGULATION_IDS == frozenset(CORPUS_REGISTRY.keys())


def test_valid_regulation_ids_includes_known_regulations() -> None:
    assert "osfi-e23" in VALID_REGULATION_IDS
    assert "sox-pl-107-204" in VALID_REGULATION_IDS
    assert "eu-ai-act" in VALID_REGULATION_IDS
    assert "nist-ai-rmf" in VALID_REGULATION_IDS


# -- TenantConfig construction -------------------------------------------


def test_minimal_tenant_config() -> None:
    t = TenantConfig(tenant_id="acme", display_name="Acme")
    assert t.tenant_id == "acme"
    assert t.display_name == "Acme"
    assert t.model is None
    assert t.fallback_models == ()
    assert t.circuit_breaker is None
    assert t.regulation_set == ()
    assert t.metadata == {}


def test_full_tenant_config() -> None:
    from resilience import CircuitBreakerConfig
    t = TenantConfig(
        tenant_id="acme-bank",
        display_name="Acme Bank",
        model="anthropic:claude-sonnet-4-5",
        fallback_models=("openai:gpt-5.4",),
        circuit_breaker=CircuitBreakerConfig(failure_rate_threshold=0.5),
        regulation_set=("osfi-e23",),
        metadata={"tier": "enterprise"},
    )
    assert t.model == "anthropic:claude-sonnet-4-5"
    assert t.fallback_models == ("openai:gpt-5.4",)
    assert t.circuit_breaker.failure_rate_threshold == 0.5
    assert t.regulation_set == ("osfi-e23",)
    assert t.metadata["tier"] == "enterprise"


def test_tenant_config_is_frozen() -> None:
    t = TenantConfig(tenant_id="acme", display_name="Acme")
    with pytest.raises(Exception):
        t.tenant_id = "other"  # type: ignore[misc]


# -- tenant_id validation ------------------------------------------------


def test_empty_tenant_id_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="", display_name="X")


def test_tenant_id_with_spaces_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="acme bank", display_name="X")


def test_tenant_id_with_uppercase_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="AcmeBank", display_name="X")


def test_tenant_id_with_special_chars_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="acme_bank!", display_name="X")


def test_tenant_id_leading_hyphen_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="-acme", display_name="X")


def test_tenant_id_trailing_hyphen_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="acme-", display_name="X")


def test_tenant_id_with_internal_hyphens_accepted() -> None:
    t = TenantConfig(tenant_id="acme-bank-ca", display_name="X")
    assert t.tenant_id == "acme-bank-ca"


def test_tenant_id_single_char_accepted() -> None:
    t = TenantConfig(tenant_id="a", display_name="X")
    assert t.tenant_id == "a"


def test_tenant_id_too_long_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="a" * 65, display_name="X")


def test_tenant_id_max_length_accepted() -> None:
    t = TenantConfig(tenant_id="a" * 64, display_name="X")
    assert len(t.tenant_id) == 64


# -- display_name validation ---------------------------------------------


def test_empty_display_name_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="acme", display_name="")


def test_whitespace_display_name_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(tenant_id="acme", display_name="   ")


# -- regulation_set validation -------------------------------------------


def test_unknown_regulation_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(
            tenant_id="acme", display_name="X",
            regulation_set=("not-a-real-reg",),
        )


def test_duplicate_regulation_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig(
            tenant_id="acme", display_name="X",
            regulation_set=("osfi-e23", "osfi-e23"),
        )


def test_empty_regulation_set_accepted() -> None:
    """A tenant doing tier classification without retrieval is valid."""
    t = TenantConfig(tenant_id="acme", display_name="X", regulation_set=())
    assert t.regulation_set == ()


def test_multiple_regulations_accepted() -> None:
    t = TenantConfig(
        tenant_id="acme", display_name="X",
        regulation_set=("osfi-e23", "nist-ai-rmf"),
    )
    assert len(t.regulation_set) == 2


# -- from_dict -----------------------------------------------------------


def test_from_dict_minimal() -> None:
    t = TenantConfig.from_dict({"tenant_id": "acme", "display_name": "Acme"})
    assert t.tenant_id == "acme"


def test_from_dict_full() -> None:
    t = TenantConfig.from_dict({
        "tenant_id": "acme-bank",
        "display_name": "Acme Bank",
        "model": "anthropic:claude-sonnet-4-5",
        "fallback_models": ["openai:gpt-5.4"],
        "circuit_breaker": {"failure_rate_threshold": 0.6, "cooldown_seconds": 45},
        "regulation_set": ["osfi-e23"],
        "metadata": {"tier": "enterprise"},
    })
    assert t.fallback_models == ("openai:gpt-5.4",)
    assert t.circuit_breaker.failure_rate_threshold == 0.6
    assert t.circuit_breaker.cooldown_seconds == 45


def test_from_dict_not_a_dict_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_from_dict_unknown_key_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig.from_dict({
            "tenant_id": "acme", "display_name": "X", "typo": 1,
        })


def test_from_dict_missing_tenant_id_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig.from_dict({"display_name": "X"})


def test_from_dict_missing_display_name_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig.from_dict({"tenant_id": "acme"})


def test_from_dict_circuit_breaker_not_object_rejected() -> None:
    with pytest.raises(TenantConfigError):
        TenantConfig.from_dict({
            "tenant_id": "acme", "display_name": "X",
            "circuit_breaker": "not-an-object",
        })


def test_from_dict_invalid_circuit_breaker_rejected() -> None:
    """A circuit_breaker with an out-of-range value is rejected."""
    with pytest.raises(TenantConfigError):
        TenantConfig.from_dict({
            "tenant_id": "acme", "display_name": "X",
            "circuit_breaker": {"failure_rate_threshold": 5.0},
        })


# -- TenantRegistry ------------------------------------------------------


def test_empty_registry() -> None:
    reg = TenantRegistry()
    assert len(reg) == 0
    assert reg.tenant_ids() == []
    assert reg.all_tenants() == []


def test_registry_from_configs() -> None:
    configs = [
        TenantConfig(tenant_id="acme", display_name="Acme"),
        TenantConfig(tenant_id="globex", display_name="Globex"),
    ]
    reg = TenantRegistry(configs)
    assert len(reg) == 2


def test_registry_register_and_get() -> None:
    reg = TenantRegistry()
    reg.register(TenantConfig(tenant_id="acme", display_name="Acme"))
    assert reg.get("acme").display_name == "Acme"


def test_registry_duplicate_register_rejected() -> None:
    reg = TenantRegistry()
    reg.register(TenantConfig(tenant_id="acme", display_name="Acme"))
    with pytest.raises(TenantRegistryError):
        reg.register(TenantConfig(tenant_id="acme", display_name="Other"))


def test_registry_get_unknown_raises_keyerror() -> None:
    reg = TenantRegistry()
    with pytest.raises(KeyError):
        reg.get("nobody")


def test_registry_has() -> None:
    reg = TenantRegistry([TenantConfig(tenant_id="acme", display_name="Acme")])
    assert reg.has("acme") is True
    assert reg.has("nobody") is False


def test_registry_all_tenants_sorted() -> None:
    reg = TenantRegistry([
        TenantConfig(tenant_id="zebra", display_name="Z"),
        TenantConfig(tenant_id="acme", display_name="A"),
    ])
    ids = [t.tenant_id for t in reg.all_tenants()]
    assert ids == ["acme", "zebra"]


def test_registry_iter() -> None:
    reg = TenantRegistry([
        TenantConfig(tenant_id="acme", display_name="A"),
        TenantConfig(tenant_id="globex", display_name="G"),
    ])
    ids = [t.tenant_id for t in reg]
    assert ids == ["acme", "globex"]


# -- Registry from_dict / from_json_file ---------------------------------


def test_registry_from_dict() -> None:
    reg = TenantRegistry.from_dict({
        "tenants": [
            {"tenant_id": "acme", "display_name": "Acme"},
            {"tenant_id": "globex", "display_name": "Globex"},
        ],
    })
    assert len(reg) == 2


def test_registry_from_dict_not_object_rejected() -> None:
    with pytest.raises(TenantRegistryError):
        TenantRegistry.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_registry_from_dict_missing_tenants_key_rejected() -> None:
    with pytest.raises(TenantRegistryError):
        TenantRegistry.from_dict({"not_tenants": []})


def test_registry_from_dict_tenants_not_list_rejected() -> None:
    with pytest.raises(TenantRegistryError):
        TenantRegistry.from_dict({"tenants": "not-a-list"})


def test_registry_from_dict_bad_entry_reports_index() -> None:
    with pytest.raises(TenantRegistryError, match="index 1"):
        TenantRegistry.from_dict({
            "tenants": [
                {"tenant_id": "acme", "display_name": "Acme"},
                {"tenant_id": "BAD ID", "display_name": "X"},
            ],
        })


def test_registry_from_dict_duplicate_rejected() -> None:
    with pytest.raises(TenantRegistryError):
        TenantRegistry.from_dict({
            "tenants": [
                {"tenant_id": "acme", "display_name": "Acme"},
                {"tenant_id": "acme", "display_name": "Other"},
            ],
        })


def test_registry_from_json_file(tmp_path: Path) -> None:
    config_file = tmp_path / "tenants.json"
    config_file.write_text(json.dumps({
        "tenants": [{"tenant_id": "acme", "display_name": "Acme"}],
    }), encoding="utf-8")
    reg = TenantRegistry.from_json_file(config_file)
    assert reg.has("acme")


def test_registry_from_json_file_missing_rejected(tmp_path: Path) -> None:
    with pytest.raises(TenantRegistryError):
        TenantRegistry.from_json_file(tmp_path / "nope.json")


def test_registry_from_json_file_bad_json_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.json"
    config_file.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(TenantRegistryError):
        TenantRegistry.from_json_file(config_file)


def test_registry_from_json_file_accepts_string_path(tmp_path: Path) -> None:
    config_file = tmp_path / "tenants.json"
    config_file.write_text(json.dumps({
        "tenants": [{"tenant_id": "acme", "display_name": "Acme"}],
    }), encoding="utf-8")
    reg = TenantRegistry.from_json_file(str(config_file))
    assert reg.has("acme")


# -- The shipped example file --------------------------------------------


def test_example_tenants_file_loads() -> None:
    """The committed example tenant config file is valid."""
    reg = TenantRegistry.from_json_file(_EXAMPLE_TENANTS)
    assert len(reg) == 3
    assert reg.has("example-cdn-bank")
    assert reg.has("example-us-issuer")
    assert reg.has("example-eu-saas")


def test_example_tenants_regulations_valid() -> None:
    """Every regulation in the example file is a valid regulation id."""
    reg = TenantRegistry.from_json_file(_EXAMPLE_TENANTS)
    for tenant in reg:
        for regulation in tenant.regulation_set:
            assert regulation in VALID_REGULATION_IDS
