# Multi-tenancy guide

This document explains the framework's per-tenant configuration model: what it is for, what is and is not configurable per tenant, the configuration format, and how the tenancy work is sequenced across sub-systems.

Tenancy exists for the consultancy deployment model. A single framework operator runs vendor risk triage on behalf of several client organizations, and each client needs isolated configuration: its own model routing, its own applicable regulations, its own metadata. The framework operator is one entity; the tenants are the clients it serves.

A deployment that serves a single organization does not need tenancy at all. That organization is, in effect, the only tenant, and the framework's default (no tenant registry) is exactly right for it. Tenancy is opt-in machinery for the multi-client case.

## What this sub-system provides (0.10.0)

As of 0.10.0, the `tenancy` package provides the configuration foundation: a way to describe each tenant and look them up. It does not yet wire tenant configuration into the agent, and it does not yet stamp records with a tenant identity. Those are the next sub-system. This staging is deliberate: the configuration model is stable and useful on its own, and the record-schema change it leads to is the framework's first breaking change, which deserves its own focused sub-system.

### TenantConfig

A `TenantConfig` is a frozen dataclass describing one tenant:

```python
from tenancy import TenantConfig
from resilience import CircuitBreakerConfig

config = TenantConfig(
    tenant_id="acme-bank",
    display_name="Acme Bank",
    model="anthropic:claude-sonnet-4-5",
    fallback_models=("openai:gpt-5.4",),
    circuit_breaker=CircuitBreakerConfig(failure_rate_threshold=0.5),
    regulation_set=("osfi-e23",),
    metadata={"jurisdiction": "CA", "sector": "banking"},
)
```

- `tenant_id` is a stable slug (lowercase alphanumerics and hyphens, 1-64 characters, starting and ending with an alphanumeric). It is constrained to a safe character set because it will be used as a map key, an audit-record field, and a metric label.
- `display_name` is the human-readable tenant name.
- `model`, `fallback_models`, and `circuit_breaker` are the per-tenant model routing settings. They reuse the same types the agent already accepts (the `circuit_breaker` is a `resilience.CircuitBreakerConfig`, not a redefinition). A tenant serving a cost-sensitive client might route through a cheaper model; a tenant with strict availability needs might configure fallbacks.
- `regulation_set` is the regulations applicable to this tenant. It is validated against the framework's live corpus registry, so a tenant cannot be configured for a regulation the framework has no corpus for. A Canadian bank tenant typically lists `osfi-e23`; a US-listed issuer lists `sox-pl-107-204`; an EU SaaS vendor lists `eu-ai-act`. The set may be empty for a tenant doing tier classification without regulation-grounded retrieval.
- `metadata` is a free-form dict the framework carries but does not interpret: client tier, account owner, contract reference, jurisdiction notes.

Construction validates everything in `__post_init__`: a malformed `tenant_id`, an empty `display_name`, an unknown or duplicated regulation all raise `TenantConfigError` immediately rather than producing a subtly-wrong tenant that fails later.

### TenantRegistry

A `TenantRegistry` holds the set of tenant configs for a deployment and provides lookup:

```python
from tenancy import TenantRegistry

# Programmatic
registry = TenantRegistry([config_a, config_b])
registry.register(config_c)

# From a JSON file
registry = TenantRegistry.from_json_file("tenants.json")

acme = registry.get("acme-bank")        # raises KeyError if unknown
registry.has("acme-bank")               # True
registry.tenant_ids()                   # sorted list of ids
```

`get` raises `KeyError` on an unknown tenant rather than returning `None`. In a multi-tenant deployment, asking for a tenant that is not registered is a configuration or programming error that should fail loudly: a silent `None` flowing downstream would eventually produce an un-attributed record, which is exactly the failure a multi-tenant audit posture cannot tolerate.

Registering two configs with the same `tenant_id` raises `TenantRegistryError`. A deployment must not have two configurations claiming the same tenant identity.

### Configuration file format

The registry loads from a JSON file with a top-level `tenants` array:

```json
{
  "tenants": [
    {
      "tenant_id": "acme-bank",
      "display_name": "Acme Bank",
      "model": "anthropic:claude-sonnet-4-5",
      "fallback_models": ["openai:gpt-5.4"],
      "circuit_breaker": {"failure_rate_threshold": 0.5},
      "regulation_set": ["osfi-e23"],
      "metadata": {"jurisdiction": "CA"}
    }
  ]
}
```

A runnable example with three tenants (a Canadian bank, a US issuer, an EU SaaS vendor) lives at `examples/tenancy/tenants.example.json`. Unknown keys in a tenant entry are rejected, so a typo in a config file fails loudly rather than being silently ignored.

## What is deliberately not per-tenant

### The system prompt

The `SYSTEM_PROMPT` is uniform across all tenants. This is a hard design stance, not a deferred feature. A per-tenant prompt would fork `SYSTEM_PROMPT_HASH` per tenant, and a stable hash across every tenant is what lets the operator tell an auditor: every client's decisions came from the identical, version-pinned reasoning. The moment prompts diverge per tenant, that claim collapses, and each tenant becomes its own audit surface with its own prompt-provenance story. For a framework whose entire positioning is audit-readiness, uniform reasoning across tenants is worth more than per-tenant prompt tuning.

If a tenant genuinely needs different reasoning (not just different configuration), that is not a tenancy feature; it is a different framework deployment with its own version pin.

### The output contract

Every tenant produces records against the same schema version. A later sub-system adds a `tenant_id` field so records are attributable, but the contract shape does not fork per tenant. One schema, all tenants.

### The classification logic

Tenants differ in configuration (which model, which regulations), not in how the framework reasons about risk. The tier classification logic, the disposition logic, and the evidence requirements are uniform.

## Roadmap: how tenancy is sequenced

Tenancy lands across three sub-systems:

1. **Tenant configuration model (0.10.0, this sub-system).** The `TenantConfig` and `TenantRegistry` described above. No agent integration, no schema change.
2. **Tenant-scoped agent and `tenant_id` on records (next).** The agent gains tenant context, constructing its model routing from the tenant's config, and every `TriageRecord` gains a required `tenant_id` field. This is the framework's first breaking schema change: the output contract goes from 1.2.0 to 1.3.0, and `tenant_id` is required (not optional), because an un-attributed record in a multi-tenant deployment is an audit failure. Pre-1.3.0 records, which have no `tenant_id`, will not validate against 1.3.0 without migration.
3. **Schema migration engine (after).** Tooling to up-migrate records across schema versions. This becomes substantive precisely because of the 1.2.0-to-1.3.0 break: migrating a pre-tenancy record forward requires assigning it a tenant identity, which is the framework's first non-trivial migration (every prior schema change was additive-optional and needed only a version restamp).

The required-versus-optional decision on `tenant_id` is the pivot. Making it required is the honest multi-client posture (no record is ever un-attributed) and it is what gives the migration engine real work to do. The alternative, an optional `tenant_id`, would keep tenancy additive and migration trivial, at the cost of permitting un-attributed records.

## Operational notes

- **Tenant isolation is configuration isolation, not process isolation.** The framework does not sandbox tenants from each other at the process or memory level; it gives each tenant its own configuration and (in a later sub-system) stamps each record with the tenant it belongs to. A deployment needing hard process isolation between tenants runs separate framework processes, one per tenant, each with a single-tenant registry.
- **The registry is loaded once and reused.** Construct the registry at deployment startup and hold it; it is not reloaded per request. A deployment that adds or changes tenants reloads the registry (or restarts) to pick up the change.
- **Regulation sets gate retrieval, not classification.** A tenant's `regulation_set` determines which regulatory corpora are in scope for retrieval-grounded reasoning. It does not change the tier or disposition logic; it changes which regulations the framework can cite as evidence.
