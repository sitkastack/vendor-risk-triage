# System architecture (v1.0.5)

The Vendor Risk Triage framework ships eleven runtime Python packages
(`agent`, `cli`, `eval`, `ingestion`, `migration`, `observability`,
`pricing`, `reporting`, `resilience`, `retrieval`, `tenancy`) plus a
`schemas/` directory of JSON Schema contract files, a `scripts/`
directory of maintenance and CI helpers, and a `detection/` Phase 5
skeleton not yet operational at v1.0.5. The framework is state-free at
the contract boundary: callers supply inputs, the framework returns
outputs. No HTTP, no database, no scheduled jobs; those concerns belong
to the deployment architecture (see
`docs/phase-2/01-system-architecture.md` for the institutional shape).

The framework is NOT process-stateless in the strict sense: the
default `resilience.InMemoryBreakerStateStore` carries cross-call
failure history inside each TriageAgent instance for circuit-breaker
decisions, and that state is lost on process restart. Deployments
wanting shared breaker state across workers inject a custom
`BreakerStateStore` (e.g. Redis or Postgres-backed) per
`resilience/circuit_breaker.py`. The Composition section below
enumerates breaker state as a concern the deployment can choose to
externalize.

This document is the visual anchor for the current (v1.0.5) framework
at the package level. The Phase 2 architecture diagram covers the
foundational design; this one covers how the framework's runtime
packages compose AND how the determinism contract (introduced 1.0.5,
output contract 1.4.0) flows through them.

## Package decomposition

```mermaid
flowchart TB
    classDef agent fill:#dbeafe,stroke:#1d4ed8,stroke-width:2px
    classDef contract fill:#dcfce7,stroke:#16a34a,stroke-width:2px
    classDef io fill:#fef3c7,stroke:#b45309,stroke-width:1px
    classDef ops fill:#fee2e2,stroke:#b91c1c,stroke-width:1px
    classDef eval fill:#f3e8ff,stroke:#7c3aed,stroke-width:1px
    classDef tool fill:#e0e7ff,stroke:#4338ca,stroke-width:1px
    classDef skeleton fill:#f5f5f5,stroke:#9ca3af,stroke-dasharray:5 5

    Caller([Institutional caller<br/>HTTP handler, batch job, CLI])
    TenancyConfig([TenantConfig<br/>caller-supplied per-tenant routing])

    CLI[cli/<br/>vrt triage render migrate drift corpus version]:::tool
    Scripts[scripts/<br/>build_corpus_bundles, check_drift,<br/>check_system_prompt_hash,<br/>measure_determinism_variance, prepare_release]:::tool

    subgraph Core[Core: agent + contract]
        Agent[agent/<br/>TriageAgent, SYSTEM_PROMPT,<br/>DeterminismAttestation builder]:::agent
        OutputModels[agent.output_models<br/>TriageRecord Pydantic<br/>DeterminismAttestation FallbackRecord]:::agent
        Schemas[schemas/<br/>output-contract-1.0.0 through 1.4.0<br/>JSON Schema 2020-12]:::contract
    end

    subgraph IO[I/O packages]
        Ingestion[ingestion/<br/>PDF parsing, Document type]:::io
        Retrieval[retrieval/<br/>BM25, Vector, Hybrid, Chunk type,<br/>corpus registry]:::io
        Tenancy[tenancy/<br/>TenantConfig, TenantRegistry,<br/>per-tenant model routing]:::io
    end

    subgraph Ops[Operational packages]
        Pricing[pricing/<br/>token to dollar price table]:::ops
        Resilience[resilience/<br/>CircuitBreaker, fallback policy,<br/>InMemoryBreakerStateStore default]:::ops
        Observability[observability/<br/>events, metrics, spans, attestation]:::ops
        Reporting[reporting/<br/>audit pack HTML, audit log envelope]:::ops
        Migration[migration/<br/>1.0.0 to 1.4.0 version hops]:::ops
    end

    subgraph Eval[Evaluation harness]
        EvalRunner[eval/<br/>runner, datasets, drift checker]:::eval
        EvalJudge[eval/judge<br/>LLM-as-judge]:::eval
        EvalCitations[eval/citations<br/>deterministic verification]:::eval
        EvalCalibration[eval/calibration<br/>Brier ECE MCE]:::eval
    end

    subgraph Skeletons[Phase 5 skeletons not active at v1.0.5]
        Detection[detection/<br/>signature rules for review triggers<br/>not installed; raises NotImplementedError]:::skeleton
    end

    Caller --> CLI
    Caller --> Agent
    TenancyConfig -.->|injected via TriageAgentConfig.tenant| Agent

    CLI --> Agent
    CLI --> Migration
    CLI --> Reporting
    CLI --> EvalRunner
    CLI --> Retrieval
    Scripts -.->|maintenance + CI gates| CLI

    Agent --> OutputModels
    Agent --> Pricing
    Agent --> Resilience
    Agent --> Observability
    Caller -.->|caller pre-parses| Ingestion
    Caller -.->|caller pre-retrieves chunks| Retrieval
    Agent -.->|imports Document type| Ingestion
    Agent -.->|imports Chunk type| Retrieval
    OutputModels -.->|conforms to| Schemas
    Migration -.->|validates against| Schemas
    Reporting --> OutputModels
    EvalRunner --> Agent
```

## Submission to record (the triage path)

The default flow callers exercise. Includes the determinism attestation
builder added in 1.0.5.

```mermaid
sequenceDiagram
    autonumber
    participant Caller
    participant Agent as TriageAgent
    participant LLM as PydanticAI Model
    participant Resilience as CircuitBreaker
    participant AttBuilder as Attestation builder
    participant Obs as Observability
    participant Pricing
    participant Record as TriageRecord

    Note over Caller: caller pre-parses PDFs via ingestion.PDFReader and retrieves chunks via retrieval.Retriever before invoking triage
    Caller->>Agent: triage submission, documents, chunks
    Note over Agent: tenant_id and routing cached from TriageAgentConfig.tenant at construction. Stamped on every record.
    Note over Agent: in-process _verify_documents_against_submission checks content_hash matches submission claim
    Note over Agent: temperature pinned at 0.0 in model_settings
    loop over N candidates primary first then ordered fallbacks
        Agent->>Resilience: should_attempt for this model
        alt breaker open
            Resilience-->>Agent: skip and record reason circuit_open
        else breaker closed
            Agent->>LLM: run_sync with BEGIN/END delimited prompt
            alt success
                LLM-->>Agent: classification
                Agent->>Resilience: record_success and break loop
            else error
                LLM-->>Agent: exception
                Agent->>Resilience: record_failure and continue loop with next candidate
                Note over Agent: first non-primary success records FallbackRecord with reason in transient_retry hard_refusal circuit_open operator_pinned or cross_provider
            end
        end
    end
    Agent->>Pricing: compute cost from token usage
    Pricing-->>Agent: CostEstimate or None
    Agent->>Obs: emit llm.call.cost_recorded
    Agent->>AttBuilder: build attestation with chunks and fallback_info
    AttBuilder-->>Agent: DeterminismAttestation
    Note over AttBuilder: contract_honored true iff temperature zero AND default prompt AND known provider AND no fallback fired. Corpus integrity anchored separately by corpus_bundle_hash field.
    Agent->>Obs: emit validation.started
    Agent->>Record: construct TriageRecord with attestation and cost
    Agent->>Obs: emit validation.completed then triage.completed with contract posture
    Agent-->>Caller: TriageRecord
```

## Determinism contract flow

The determinism contract introduced in 1.0.5 cuts across the framework.
Every record carries an attestation; the configuration that produced
it determines whether `contract_honored` is true or false.

```mermaid
flowchart TB
    classDef input fill:#fef3c7,stroke:#b45309
    classDef gate fill:#dbeafe,stroke:#1d4ed8
    classDef pass fill:#bbf7d0,stroke:#15803d
    classDef fail fill:#fecaca,stroke:#b91c1c

    Config[TriageAgentConfig<br/>model, temperature,<br/>system_prompt, fallback_models]:::input
    PromptText[SYSTEM_PROMPT bytes]:::input
    Chunks[regulation_chunks at call time]:::input

    Init[TriageAgent init]:::gate
    TempGate{temperature == 0.0?}:::gate
    PromptHash[Compute SYSTEM_PROMPT_HASH_FULL<br/>SHA-256 of loaded bytes]:::gate
    ProviderParse[Parse provider, effective_model_id<br/>from config.model]:::gate
    ProfileHash[Compute sampling_profile_hash<br/>SHA-256 of provider, model, temperature]:::gate
    CorpusHash[Compute corpus_bundle_hash<br/>SHA-256 of canonical chunks JSON]:::gate

    Construct{construct or refuse?}:::gate

    Refuse[TriageAgentError<br/>no agent, no record]:::fail
    LegacyWarn[DeprecationWarning<br/>contract_honored false]:::fail

    Call[triage call: iterate N candidates]:::gate
    FallbackCheck{fallback fired?<br/>reason in transient_retry,<br/>hard_refusal, circuit_open,<br/>operator_pinned, cross_provider}:::gate

    AttBuild[Build DeterminismAttestation]:::gate
    HonorCheck{all conditions met?}:::gate
    Honored[contract_honored true<br/>fresh attestation]:::pass
    Exited[contract_honored false<br/>exit condition identifiable<br/>FallbackRecord populated if fallback fired]:::fail

    Record[TriageRecord with<br/>determinism_attestation]:::pass

    Config --> Init
    PromptText --> PromptHash
    Init --> TempGate
    TempGate -->|0.0| ProviderParse
    TempGate -->|non-zero, no legacy flag| Refuse
    TempGate -->|non-zero, legacy flag| LegacyWarn
    LegacyWarn --> ProviderParse
    PromptHash --> ProviderParse
    ProviderParse --> ProfileHash
    ProfileHash --> Construct
    Construct --> Call

    Chunks --> CorpusHash
    Call --> FallbackCheck
    FallbackCheck -->|no fallback fired| AttBuild
    FallbackCheck -->|fallback fired| AttBuild
    CorpusHash --> AttBuild

    AttBuild --> HonorCheck
    HonorCheck -->|"temperature_zero AND default_prompt<br/>AND known_provider AND no_fallback_fired"| Honored
    HonorCheck -->|"any false"| Exited
    Honored --> Record
    Exited --> Record
```

Note: `corpus_bundle_hash` is recorded on every attestation as an
audit anchor, but the contract_honored boolean does NOT include a
bundle-equality check against a deployment-specified expected hash.
Operators wanting end-to-end corpus pinning compare
`corpus_bundle_hash` against their own committed expected value
out-of-band. See `docs/determinism-attestation.md` for the contract
text.

## Migration paths

```mermaid
flowchart LR
    classDef restamp fill:#e5e7eb,stroke:#4b5563
    classDef tenancy fill:#fef3c7,stroke:#b45309
    classDef determinism fill:#dcfce7,stroke:#16a34a

    V100[1.0.0 record]:::restamp
    V110[1.1.0 record]:::restamp
    V120[1.2.0 record]:::restamp
    V130[1.3.0 record<br/>tenant_id present]:::tenancy
    V140[1.4.0 record<br/>tenant_id + attestation]:::determinism

    V100 -->|restamp version<br/>no field added| V110
    V110 -->|restamp version<br/>no field added| V120
    V120 -->|tenant_resolver REQUIRED if no tenant_id present<br/>adds tenant_id| V130
    V130 -->|stamps migrated_from attestation<br/>contract_honored false, data null| V140

    V100 -.->|"vrt migrate --to 1.4.0<br/>tenant_resolver if no tenant_id"| V140
    V110 -.->|"vrt migrate --to 1.4.0<br/>tenant_resolver if no tenant_id"| V140
    V120 -.->|"vrt migrate --to 1.4.0<br/>tenant_resolver if no tenant_id"| V140
    V130 -.->|"vrt migrate --to 1.4.0"| V140
```

## CLI surface

```mermaid
flowchart TB
    classDef cmd fill:#e0e7ff,stroke:#4338ca
    classDef package fill:#fef3c7,stroke:#b45309

    User[Operator] --> VRT[vrt CLI<br/>cli/dispatcher.py]

    VRT --> TRI[vrt triage<br/>cli/cmd_triage.py]:::cmd
    VRT --> REN[vrt render<br/>cli/cmd_render.py]:::cmd
    VRT --> MIG[vrt migrate<br/>cli/cmd_migrate.py]:::cmd
    VRT --> DRI[vrt drift<br/>cli/cmd_drift.py]:::cmd
    VRT --> COR[vrt corpus<br/>cli/cmd_corpus.py]:::cmd
    VRT --> VER[vrt version<br/>cli/cmd_version.py]:::cmd

    TRI -->|submission + corpus| Agent[agent/<br/>TriageAgent]:::package
    TRI -.->|TriageRecord JSON| User

    REN -->|record + submission| Reporting[reporting/<br/>render_audit_pack]:::package
    REN -.->|HTML audit pack| User

    MIG -->|record + target_version<br/>+ tenant_resolver| Migration[migration/<br/>migrate_record]:::package
    MIG -.->|migrated record| User

    DRI -->|current vs baseline| EvalDrift[eval/drift<br/>checker, contract_honored signal]:::package
    DRI -.->|DriftReport| User

    COR -->|build, list| RetrievalCorpora[retrieval/corpora<br/>CORPUS_REGISTRY]:::package
    COR -.->|bundle path or list| User

    VER -.->|FRAMEWORK_VERSION,<br/>SYSTEM_PROMPT_HASH,<br/>pyproject_sync| User
```

## CI gates

The framework's CI enforces the contract on every push.

```mermaid
flowchart LR
    classDef gate fill:#dbeafe,stroke:#1d4ed8
    classDef fail fill:#fecaca,stroke:#b91c1c
    classDef pass fill:#bbf7d0,stroke:#15803d

    Push[Push or PR to main] --> Tests[pytest with coverage 95%]:::gate
    Push --> VerSync[check_version_sync<br/>pyproject vs _version.py]:::gate
    Push --> Changelog[extract_changelog --check<br/>CHANGELOG vs _version.py history]:::gate
    Push --> SchemaValid[All schemas validate as<br/>JSON Schema 2020-12]:::gate
    Push --> Drift[check_drift<br/>against demo-scenarios baseline]:::gate
    Push --> PromptHash[check_system_prompt_hash<br/>vs baselines/system_prompt_hash.txt]:::gate
    Push --> EmDash[grep for em-dashes<br/>in markdown]:::gate

    Tests --> Decision{all pass?}
    VerSync --> Decision
    Changelog --> Decision
    SchemaValid --> Decision
    Drift --> Decision
    PromptHash --> Decision
    EmDash --> Decision

    Decision -->|yes| Green[Build green<br/>release-ready]:::pass
    Decision -->|no| Red[Build red<br/>release blocked]:::fail
```

## Observability event taxonomy

The framework emits structured events at each stage of the triage call.
Sinks compose observability by filtering on event_name and attributes.

```mermaid
flowchart TB
    classDef event fill:#dbeafe,stroke:#1d4ed8
    classDef attr fill:#fef3c7,stroke:#b45309

    Triage[triage call] --> Started[triage.started]:::event
    Started --> CallStart[llm.call.started]:::event
    CallStart --> CallComplete[llm.call.completed<br/>or llm.call.fallback_triggered]:::event
    CallComplete --> CostRecorded[llm.call.cost_recorded<br/>token usage resolved to dollars]:::event
    CostRecorded --> Validation[validation.started]:::event
    Validation --> ValidationDone[validation.completed<br/>TriageRecord constructed with attestation and cost]:::event
    ValidationDone --> Completed[triage.completed]:::event

    Completed --> Attrs[Attributes carried:<br/>decision_id<br/>tier disposition<br/>confidence_score<br/>contract_honored<br/>effective_temperature<br/>effective_model_id<br/>fallback_fired]:::attr

    CallComplete --> BreakerEvents[circuit_breaker.opened<br/>circuit_breaker.half_opened<br/>circuit_breaker.closed]:::event
```

## Composition with the deployment architecture

The framework's eleven runtime packages compose into the deployment
shape specified in `docs/phase-2/01-system-architecture.md`. The
relationship:

- The **framework library** (this repo) handles classification,
  validation, retrieval type plumbing, cost accounting, fallback,
  observability event emission, audit pack rendering, audit log
  envelope construction, and migration.
- The **deployment architecture** (institutional shape) handles HTTP
  transport, normalization, PII detection, Postgres storage, audit
  query API, retention enforcement, and the trust boundary controls.

Per ADR-008, the framework intentionally carries no HTTP, no database,
no scheduled jobs. A deploying institution wires the framework into
the deployment architecture.

Statefulness the deployment must consider:

- **Circuit-breaker state.** The default `InMemoryBreakerStateStore`
  in `resilience/` carries per-model failure history inside each
  TriageAgent instance lifetime. On process restart, the breaker
  forgets which providers were unhealthy and retries them
  immediately. Deployments running long-lived workers benefit from
  injecting a shared store (Redis, Postgres) so breaker decisions
  span workers and survive restarts.
- **Caller-side parsing and retrieval state.** The agent does NOT
  parse PDFs or run retrieval itself. Callers exercise
  `ingestion.PDFReader` and `retrieval.Retriever` upstream and pass
  pre-built `Document` and `Chunk` instances. Caching, document
  storage, and corpus warm-up belong to the caller's deployment.
- **Tenancy.** A `TenantConfig` is bound to a single TriageAgent
  instance at construction. A multi-tenant deployment instantiates
  one agent per tenant (or pools agents per tenant); the framework
  does not multiplex tenants on one agent instance.

## Cross-references

- Phase 2 system architecture (foundational): `docs/phase-2/01-system-architecture.md`
- Trust boundaries: `docs/phase-2/02-trust-boundaries.md`
- Threat model: `docs/phase-2/03-threat-model.md`
- Architecture decisions: `docs/phase-2/04-architecture-decisions.md`
- Data model: `docs/data-model.md`
- Determinism contract: `docs/determinism-attestation.md`
- Tenancy guide: `docs/multi-tenancy-guide.md`
- Migration guide: `docs/migration-guide.md`
- Fallback guide: `docs/model-fallback-guide.md`
- Observability guide: `docs/observability-guide.md`
- Audit log shipping: `docs/audit-log-shipping.md`
- Cost tracking: `docs/cost-tracking-guide.md`
- Customization: `docs/customization-guide.md`
- Maintenance workflow: `docs/maintenance-workflow.md`
