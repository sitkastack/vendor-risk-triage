# Data model

The Vendor Risk Triage agent's data model is published as a JSON Schema
contract (`schemas/output-contract-{version}.schema.json`) and enforced
at runtime by Pydantic models (`agent/output_models.py`). The contract
is the source of truth; the Pydantic models conform to it and reject
anything the schema would reject (plus several additional defenses).

This document is the visual anchor for `docs/phase-1/03-output-contract.md`
(per-field specification) and `docs/determinism-attestation.md` (the
contract introduced in 1.0.5).

## TriageRecord and nested types

```mermaid
classDiagram
    class TriageRecord {
        +string decision_id
        +datetime decision_timestamp
        +string input_submission_id
        +string input_schema_version
        +string agent_version
        +RiskTier risk_tier
        +Disposition recommended_disposition
        +string classification_rationale
        +list~EvidenceCitation~ evidence_cited
        +ConfidenceSignal confidence_signal
        +string output_schema_version
        +string? tenant_id
        +list~string~? required_mitigations
        +string? accountable_owner
        +string? supersedes
        +datetime? revoked_at
        +string? revocation_reason
        +int? review_interval_days
        +list~FrameworkTag~? regulatory_framework_tags
        +string? correlation_id
        +CostEstimate? cost_estimate
        +DeterminismAttestation? determinism_attestation
        +string? extension_schema_version
    }

    class EvidenceCitation {
        +string input_field_reference
        +string reasoning
    }

    class ConfidenceSignal {
        +float score
        +ConfidenceBand interpretation
        -enforce_band_matches_score()
    }

    class CostEstimate {
        +int input_tokens
        +int output_tokens
        +string model_id
        +float estimated_cost_usd
        +string price_table_version
    }

    class DeterminismAttestation {
        +float? effective_temperature
        +bool contract_honored
        +Provider? provider
        +string? effective_model_id
        +FallbackRecord? fallback
        +string? sampling_profile_hash
        +string? system_prompt_hash
        +string? corpus_bundle_hash
        +string? contract_version
        +string? migrated_from
    }

    class FallbackRecord {
        +bool fired
        +FallbackReason reason
        +string primary_model_id
        +string effective_model_id
        +string primary_provider
        +string effective_provider
        +string trigger_event
    }

    class RiskTier {
        <<enum>>
        tier_1_low
        tier_2_moderate
        tier_3_elevated
        tier_4_high
    }

    class Disposition {
        <<enum>>
        approve
        conditional_approve
        escalate_senior_review
        reject
    }

    class ConfidenceBand {
        <<enum>>
        low
        moderate
        high
    }

    class Provider {
        <<enum>>
        anthropic
        openai
        google-gla
        google-vertex
        test
        unknown
    }

    class FallbackReason {
        <<enum>>
        transient_retry
        hard_refusal
        circuit_open
        operator_pinned
        cross_provider
    }

    TriageRecord "1" *-- "1..*" EvidenceCitation : evidence_cited
    TriageRecord "1" *-- "1" ConfidenceSignal : confidence_signal
    TriageRecord "1" *-- "0..1" CostEstimate : cost_estimate
    TriageRecord "1" *-- "0..1" DeterminismAttestation : determinism_attestation
    TriageRecord ..> RiskTier : risk_tier
    TriageRecord ..> Disposition : recommended_disposition
    ConfidenceSignal ..> ConfidenceBand : interpretation
    DeterminismAttestation "1" *-- "0..1" FallbackRecord : fallback
    DeterminismAttestation ..> Provider : provider
    FallbackRecord ..> FallbackReason : reason
```

## Newly REQUIRED fields by contract version

The output contract evolved 1.0.0 -> 1.1.0 -> 1.2.0 -> 1.3.0 -> 1.4.0.
Earlier records remain valid against their version-of-record schema via
the dispatcher in `schemas/validate.py`. The diagram below shows only
the fields that became NEWLY REQUIRED at each version hop. The full
field inventory at 1.0.0 baseline is broader; see the class diagram
above and the per-field specification at
`docs/phase-1/03-output-contract.md` for the complete list.

```mermaid
flowchart TB
    classDef contract fill:#f0f9ff,stroke:#0369a1,stroke-width:2px
    classDef field fill:#fef3c7,stroke:#b45309,stroke-width:1px
    classDef breaking fill:#fee2e2,stroke:#b91c1c,stroke-width:2px

    V100[output-contract 1.0.0<br/>Phase 1 baseline]:::contract
    V110[output-contract 1.1.0<br/>+ correlation_id]:::contract
    V120[output-contract 1.2.0<br/>+ cost_estimate]:::contract
    V130[output-contract 1.3.0<br/>+ tenant_id REQUIRED]:::breaking
    V140[output-contract 1.4.0<br/>+ determinism_attestation REQUIRED]:::contract

    F_core_req[REQUIRED in 1.0.0<br/>decision_id<br/>decision_timestamp<br/>input_submission_id<br/>input_schema_version<br/>agent_version<br/>risk_tier<br/>recommended_disposition<br/>classification_rationale<br/>evidence_cited<br/>confidence_signal<br/>output_schema_version]:::field
    F_core_opt[OPTIONAL in 1.0.0<br/>required_mitigations<br/>accountable_owner<br/>supersedes<br/>revoked_at + revocation_reason pair<br/>review_interval_days<br/>regulatory_framework_tags<br/>extension_schema_version]:::field
    F_correlation[correlation_id<br/>added 1.1.0, optional]:::field
    F_cost[cost_estimate<br/>added 1.2.0, optional]:::field
    F_tenant[tenant_id<br/>added 1.3.0, REQUIRED<br/>slug or sentinel]:::breaking
    F_attest[determinism_attestation<br/>added 1.4.0, REQUIRED<br/>all nested keys present, nulls allowed]:::field

    V100 --> V110
    V110 --> V120
    V120 --> V130
    V130 --> V140

    V100 -.->|carries| F_core_req
    V100 -.->|carries| F_core_opt
    V110 -.->|adds| F_correlation
    V120 -.->|adds| F_cost
    V130 -.->|requires| F_tenant
    V140 -.->|requires| F_attest
```

## Four populations of records

After 1.0.5 ships, four populations of records coexist (the three
populations in the contract docstring decompose to four for operator
dispatch: fresh records split into contract-honored and
contract-exited). Operators distinguish them by inspecting
`(output_schema_version, migrated_from, contract_honored)` and route on
the resulting four-bin discriminator. The dispatch order is:

1. Check `output_schema_version` first: pre-1.4.0 records have no attestation.
2. Then check `migrated_from` truthiness: any non-null value identifies a migrated record (sourced from 1.0.0, 1.1.0, 1.2.0, or 1.3.0).
3. Then check `contract_honored`: separates fresh records into honored vs exited.

```mermaid
flowchart LR
    classDef pre fill:#e5e7eb,stroke:#4b5563
    classDef migrated fill:#fed7aa,stroke:#c2410c
    classDef fresh_honored fill:#bbf7d0,stroke:#15803d
    classDef fresh_exited fill:#fecaca,stroke:#b91c1c

    PRE[Pre-1.0.5 records<br/>output_schema_version 1.0.0 - 1.3.0<br/>determinism_attestation absent<br/>cannot be retroactively attested]:::pre

    MIG[Migrated-forward records<br/>output_schema_version 1.4.0<br/>migrated_from in 1.0.0, 1.1.0, 1.2.0, 1.3.0<br/>contract_honored false<br/>data fields null]:::migrated

    FRESH_OK[Fresh contract-honored<br/>output_schema_version 1.4.0<br/>migrated_from null<br/>contract_honored true<br/>full attestation populated]:::fresh_honored

    FRESH_OUT[Fresh contract-exited<br/>output_schema_version 1.4.0<br/>migrated_from null<br/>contract_honored false<br/>identifies exit condition]:::fresh_exited

    OP{Operator dispatch:<br/>output_schema_version<br/>migrated_from<br/>contract_honored}

    PRE --> OP
    MIG --> OP
    FRESH_OK --> OP
    FRESH_OUT --> OP

    OP -->|"version less than 1.4.0"| BIN1[pre_contract bin]
    OP -->|"migrated_from not null"| BIN2[migrated bin]
    OP -->|"migrated_from null AND honored true"| BIN3[contract_honored bin]
    OP -->|"migrated_from null AND honored false"| BIN4[contract_exited bin]
```

## Schema dispatch

`schemas.validate.validate_output` dispatches on the record's declared
`output_schema_version` so older records continue to validate against
their version-of-record schema. Every schema file is preserved in the
repo for the life of the project.

```mermaid
flowchart TB
    Input[Record dict] --> Read[Read output_schema_version]
    Read -->|"1.0.0"| S100[output-contract-1.0.0.schema.json<br/>Phase 1 baseline]
    Read -->|"1.1.0"| S110[output-contract-1.1.0.schema.json<br/>+ correlation_id]
    Read -->|"1.2.0"| S120[output-contract-1.2.0.schema.json<br/>+ cost_estimate]
    Read -->|"1.3.0"| S130[output-contract-1.3.0.schema.json<br/>+ tenant_id required]
    Read -->|"1.4.0"| S140[output-contract-1.4.0.schema.json<br/>+ determinism_attestation required]
    Read -->|unknown| Fail[Validation error<br/>unknown version]

    S100 --> Validate{JSON Schema 2020-12<br/>validation}
    S110 --> Validate
    S120 --> Validate
    S130 --> Validate
    S140 --> Validate

    Validate -->|valid| OK[ok=true, errors=empty]
    Validate -->|invalid| Errors[ok=false, structured errors]
```

## Pydantic enforcement

`agent.output_models.TriageRecord` is the runtime enforcement of the
JSON Schema contract. It carries:

- **Frozen models**: every model is `frozen=True` (tamper resistance).
- **Extra forbidden**: `extra="forbid"` on every model (no silent drift).
- **Cross-field validation**: a model-validator enforces the schema's
  `allOf` and `dependentRequired` rules so Pydantic and the JSON Schema
  reject the same instances for the same reasons.
- **Version-conditional enforcement**: declared `output_schema_version`
  gates conditional requirements (1.3.0+ requires `tenant_id`; 1.4.0+
  requires `determinism_attestation`).
- **Control character rejection**: free-text fields screen for log
  injection and ANSI escape sequences.
- **Datetime serialization**: RFC 3339 UTC with minimum fractional-second
  digits via a custom field serializer.
- **Attestation expansion on dump**: `model_dump` overrides
  `exclude_none` for the determinism attestation so every nested key
  is structurally present in serialized output (null means absent).

## Conditional requirements

```mermaid
flowchart LR
    DISP{recommended_disposition}
    DISP -->|conditional_approve| REQ_MIT[required_mitigations<br/>must be present]
    DISP -->|escalate_senior_review| REQ_OWNER[accountable_owner<br/>must be present]
    DISP -->|approve, reject| NONE[no conditional<br/>requirements]

    REV{revocation pair}
    REV -->|revoked_at present| REV1[revocation_reason<br/>must be present]
    REV -->|revocation_reason present| REV2[revoked_at<br/>must be present]
    REV -->|neither| REV3[both absent, valid]

    VER{output_schema_version}
    VER -->|"version greater or equal 1.3.0"| TEN[tenant_id required]
    VER -->|"version greater or equal 1.4.0"| ATT[determinism_attestation required]
```

## Cross-references

- Per-field specification: `docs/phase-1/03-output-contract.md`
- Determinism contract text: `docs/determinism-attestation.md`
- Schema files: `schemas/output-contract-{1.0.0, 1.1.0, 1.2.0, 1.3.0, 1.4.0}.schema.json`
- Pydantic models: `agent/output_models.py`
- Dispatcher: `schemas/validate.py`
- Migration engine: `migration/engine.py` (handles version hops including the 1.3.0 -> 1.4.0 attestation hop)
