# Phase 2: Architecture Decisions

Architecture Decision Records (ADRs) for the Vendor Risk Triage gate. Each ADR documents one significant design choice: what was decided, what was considered, why, and when it should be revisited.

## Reading this

ADRs are not vendor prescriptions. They document the choices made for this reference implementation, including the reasoning. Forks of the framework adapt the form (the ADR structure) rather than necessarily adopting the same answers. Where a decision is genuinely context-dependent, the ADR says so.

A pattern repeats across this document: each ADR separates the architectural decision (the durable semantics) from the deployment choice (the configurable specifics). Institutions adopt the architecture without inheriting the specific deployment.

## Format

Each ADR follows the same structure:

- Status: Accepted, Superseded, or Deprecated
- Date: Decision date
- Context: What problem prompted the decision
- Options considered: Alternatives evaluated, with brief notes on each
- Decision: What was chosen and why
- Consequences: Tradeoffs and downstream implications
- Reconsider when: Conditions that would justify revisiting
- Framework coverage: Mapping to NIST AI RMF, EU AI Act, OSFI E-23, and SOX ICFR

A new ADR is added when a significant design choice is made. ADRs are not edited after acceptance. If a decision changes, a new ADR is created and the prior ADR's status changes to Superseded with a reference to the replacement.

## Decisions in this document

- ADR-001: Provider-Agnostic LLM Interface with LiteLLM-Compatible Design
- ADR-002: Data Processing Region Strategy
- ADR-003: Agent Versioning via Git Commit SHA
- ADR-004: Schema Validation via the jsonschema Python Library
- ADR-005: Storage Architecture on Postgres with Role-Based Append-Only Constraints
- ADR-006: Schema Evolution and Migration Policy
- ADR-007: PydanticAI as the Agent Framework
- ADR-008: Stateless Reference Library Pattern
- ADR-009: Caller-Provided I/O at the Agent Boundary
- ADR-010: Document Hash Verification Before LLM Invocation
- ADR-011: BM25 Lexical Retrieval as the Primary Strategy
- ADR-012: Reciprocal Rank Fusion for Hybrid Retrieval
- ADR-013: Embedder Protocol for Vendor-Agnostic Semantic Retrieval
- ADR-014: Deterministic-First Evaluation Discipline
- ADR-015: Single-Criterion-Per-Call for LLM Judge
- ADR-016: Cross-Model Judging Recommended Not Enforced
- ADR-017: Equal-Width Binning for Calibration Reliability
- ADR-018: Per-Example Error Isolation in Eval Runners

Decisions not yet made, with reasoning, appear in the "Deferred decisions" section at the end of this document.

---

## ADR-001: Provider-Agnostic LLM Interface with LiteLLM-Compatible Design

**Status:** Accepted
**Date:** 2026-05-24

### Context

The Vendor Risk Triage agent depends on a third-party LLM provider for the classification work. Three interlocking decisions follow from that dependency.

First, single-provider commitment creates lock-in. Switching providers later requires touching every call site, every prompt, every tool definition. The output contract (docs/phase-1/03-output-contract.md) requires agent_version on every record, but does not constrain which provider produced the inference. The contract permits flexibility; the architecture has to enable it.

Second, regulated mid-market customers have heterogeneous provider preferences. Some are bound by existing enterprise agreements (Azure OpenAI, AWS Bedrock). Some have data residency requirements that only certain providers satisfy in specific regions. Some have safety or capability preferences that lean one way or another. A reference implementation that hard-codes Claude excludes those institutions from forking the framework directly.

Third, the reference implementation has its own vendor risk posture to maintain. Adding a third-party multi-provider library introduces a dependency whose own update cadence, vulnerability surface, and licensing must be governed. For the reference implementation specifically, fewer third-party AI library dependencies means a tighter audit story for the framework itself. Institutions operationalizing the framework may make a different tradeoff.

### Options considered

- **Hard-code Anthropic Claude.** Simplest implementation. Tight coupling to provider-specific APIs, prompts, and tool schemas. Adapting to a second provider requires substantial rework.
- **Hand-rolled internal interface with Claude as reference adapter.** Define a narrow internal interface for the operations the agent performs. Implement Claude as the reference adapter. Future adapters for other providers conform to the same interface. No third-party multi-provider library dependency.
- **LiteLLM or equivalent third-party multi-provider library.** Outsources the abstraction. Supports many providers out of the box, including retries, rate limiting, and fallbacks. Adds an external dependency that must be evaluated for safety, reliability, and vendor risk.

### Decision

Hand-rolled internal interface for the reference implementation, designed to be LiteLLM-compatible. Claude as the reference adapter.

The interface narrows to the operations the agent performs: structured classification with input conforming to docs/phase-1/02-input-contract.md, returning output conforming to docs/phase-1/03-output-contract.md. The interface intentionally does not expose provider-specific features at the call-site level. Provider-specific capabilities live inside adapters and surface through configuration.

The interface is designed to be LiteLLM-compatible: method signatures, parameter naming, and structured-output handling mirror LiteLLM's interface so that institutions operationalizing the framework can swap LiteLLM in for the hand-rolled abstraction with minimal call-site changes. The reference implementation does not depend on LiteLLM, but the interface design does not preclude its adoption.

Claude is the default adapter for the reference implementation. The choice is practical: existing familiarity with the API, zero data retention available for enterprise customers, and established integration patterns. A formal comparative evaluation across providers has not been conducted. Institutions forking the framework may select a different default by implementing the adapter for their preferred provider.

The reference implementation's choice to avoid LiteLLM is specific to the POC stage of the framework. The framework's own vendor risk story is cleaner with zero third-party AI library dependencies. Institutions bringing the framework in-house often have different requirements: they need broader provider coverage, built-in retry and rate-limit handling, and a smaller set of adapters to maintain. For those institutions, LiteLLM (or equivalent) is a reasonable choice, and the LiteLLM-compatible interface design keeps that path open.

### Verification of LiteLLM compatibility

The LiteLLM-compatibility property is a forward commitment, not a tested property at the time of this ADR. During Phase 3 (Build & Eval) the property will be verified by writing a parallel implementation of representative call sites against LiteLLM and confirming output equivalence for identical inputs. Any divergence becomes either an adapter bug or a documented interface gap, not a silent breakage of the compatibility claim. The verification harness lives in the test suite alongside the regular agent tests.

### Consequences

- Initial implementation cost: the hand-rolled interface and the Claude adapter must both be built rather than just direct calls.
- Zero third-party AI library dependencies in the reference implementation. The framework's own vendor risk posture is tight.
- Institutions operationalizing the framework can swap in LiteLLM or another multi-provider library when their requirements warrant. The swap is bounded work because the interface was designed compatible from the start.
- Adding a second native provider to the reference implementation is a defined unit of work: implement the adapter, validate against the threat model in docs/phase-2/03-threat-model.md, document the adapter's specific consequences. The work is bounded.
- Provider-specific safety behavior, output reliability, and prompt injection resistance vary across providers. The interface does not normalize these; each adapter must document them. A consumer cannot assume identical behavior across adapters.
- Provider outages affect only the configured adapter. Multi-adapter failover is not part of the reference but is a viable institutional extension.

### Reconsider when

This decision should be revisited if:

- LiteLLM or an equivalent becomes the de facto standard with audit-grade governance, and the reference implementation's vendor risk story benefits more from adoption than from independence.
- The reference implementation needs capabilities (multimodal inputs, agentic tool use beyond classification, fine-tuning) that materially diverge from a narrow classification interface.
- Provider behavior on the threat model becomes uniform enough that abstraction overhead exceeds value.

### Framework coverage

- **NIST AI RMF**: Govern function. Vendor lock-in mitigation and documented multi-provider architecture support organizational accountability for AI supplier risk.
- **EU AI Act**: Articles 25-29. The deployer obligation is independent of which provider is used; the architecture preserves the deployer's ability to switch providers without re-establishing compliance posture from scratch.
- **OSFI E-23**: Third-party model oversight. Multi-vendor resilience is part of operational risk management for federally regulated institutions.
- **SOX ICFR**: Third-party vendor management. Provider concentration risk for AI systems supporting financial reporting is mitigated through architectural flexibility.

---

## ADR-002: Data Processing Region Strategy

**Status:** Accepted
**Date:** 2026-05-24

### Context

Vendor risk triage processes documents that may contain personal information, vendor-confidential material, and references to the deploying organization's customer relationships. The region in which that data is processed by the LLM provider is a regulatory and contractual matter, not just an operational one.

Different deploying organizations face different residency obligations. A federally-regulated Canadian institution under OSFI may have contractual commitments to process data in Canada. An EU-based institution under GDPR may require EEA processing. A US institution may be indifferent or constrained by its own customer contracts.

The reference implementation's default cannot satisfy every customer. The architecture must accommodate multiple processing regions per provider, and must document which provider-region combinations are operationally available with explicit caveats around modern routing behaviors that complicate the apparent picture.

### Options considered

- **Default to US-East processing only.** Simplest. Excludes deploying institutions with non-US residency requirements.
- **Region as a per-deployment configuration choice.** Each deployment configures the region appropriate to its residency requirements. The reference implementation documents what's available; institutions select.
- **Provider-region matrix maintained in repository documentation.** Document which providers offer which regions and their caveats, so institutions can match provider choice to residency requirement.

### Decision

Region is a per-deployment configuration choice. The reference implementation runs against the direct Anthropic API in US-East as the default, because the reference institution does not currently have residency requirements that demand otherwise.

The provider-region matrix below is accurate as of the decision date (May 24, 2026). Cloud-provider region availability for specific models changes frequently as providers add new regions, deprecate older deployments, and adjust which models are available in cross-region inference profiles. Institutions adopting this framework must independently verify the current availability and routing behavior of their selected provider-region combination before deployment, and should treat the matrix below as a starting point for that verification, not as authoritative current state.

The provider-agnostic interface defined in ADR-001 enables a different deployment to select different region configurations:

- Direct Anthropic API: US (East) or EU regions
- AWS Bedrock with Claude: AWS Canada Central, AWS US regions, AWS EU regions. Subject to cross-region inference caveats (see warning below)
- Azure OpenAI: Canada East, Canada Central, US regions, EU regions
- Google Vertex AI: Montreal region (northamerica-northeast1), US regions, EU regions
- Cohere on Bedrock or direct API: Canadian-headquartered provider, available in multiple regions including Bedrock Canada Central

Each provider adapter (per ADR-001) documents its supported regions and the configuration mechanism. The reference deployment publishes which adapter and region it runs in deployment metadata visible alongside the audit trail.

### Cross-region inference caveat

AWS Bedrock supports cross-region inference profiles alongside native single-region deployments. Cross-region inference routes requests received in a source region (for example, ca-central-1) to model deployments in other regions (US-East, EU regions, etc.) for actual processing.

A Bedrock request submitted in Canada Central using a cross-region inference profile may be processed in the United States or Europe. For data residency purposes, this is not equivalent to native Canadian processing.

Institutions requiring data to remain in Canada must verify all of the following before deployment:

1. The specific Claude model has a native ca-central-1 deployment (not just cross-region inference availability from that region)
2. The deployment configuration uses on-demand or provisioned throughput in the target region rather than cross-region inference profiles
3. The inference profile ID does not include geo scopes (US, EU, Global, APAC) that would route data out of region

Similar caveats apply to other cloud providers. Azure OpenAI and Google Vertex AI have their own routing behaviors that institutions verify at the inference path level, not just the API endpoint level. The deployment configuration documentation must explicitly confirm residency at the inference path, with evidence in the audit trail.

### Consequences

- The deploying institution is responsible for confirming the configured region (and inference path) satisfies its specific residency obligations. The architecture enables the choice; it does not verify legal sufficiency.
- A region change within a single provider, when correctly configured, is a deployment-configuration change rather than a code change.
- A provider change to reach a different region (for example, Anthropic direct to AWS Bedrock Canada Central with native deployment) requires the relevant adapter to be implemented. The interface decision in ADR-001 makes this bounded work.
- Cross-region inference profiles are convenient for performance and availability but introduce residency risk that the institution must explicitly evaluate.
- Cross-region failover is not part of the reference implementation. A region outage requires manual cutover or institutional automation built on top.

### Reconsider when

This decision should be revisited if:

- Anthropic adds a Canadian data residency option to its direct API, simplifying the architecture for Canadian institutions without requiring Bedrock.
- A specific deploying institution's regulator issues guidance that the per-deployment configuration approach is insufficient and requires a more prescriptive design.
- Cross-region resilience becomes a reference implementation requirement rather than an institutional extension.

### Framework coverage

- **NIST AI RMF**: Manage function. Documented region selection is part of operational deployment risk management.
- **EU AI Act**: Article 10 (data and data governance) and the GDPR overlay that governs personal-data processing locations.
- **OSFI E-23**: Data residency is part of the third-party arrangement documentation a federally-regulated institution maintains.
- **SOX ICFR**: Records supporting financial reporting controls inherit the residency requirements of the financial reporting environment.

---

## ADR-003: Agent Versioning via Git Commit SHA

**Status:** Accepted
**Date:** 2026-05-24

### Context

The output contract (docs/phase-1/03-output-contract.md) requires every triage record to carry an agent_version field. The contract specifies the field is an identifier of the triage agent that produced the decision, retrievable so the decision can be reproduced against the exact agent that made it.

The contract leaves the form of the identifier to Phase 2. The form chosen must satisfy two properties: it must uniquely identify the exact code that produced a record, and it must be retrievable from the source repository at any future date.

### Options considered

- **Semver release tag (for example, v0.1.0).** Human-readable. Granular only to release boundaries; multiple records produced between releases all bear the same version, which obscures pre-release changes.
- **Git commit SHA (for example, 9e244f5cabd2...).** Uniquely identifies the exact code state. Not human-readable, but the version control system makes it traceable.
- **Combination (for example, v0.1.0+9e244f5).** Human-readable release context plus exact code identification.

### Decision

The agent_version field is the full 40-character git commit SHA of the code that produced the record, captured at the time of inference.

The full SHA, not the short form, is used because short SHAs can collide as the repository grows. The contract field has a 128-character maximum, so the full SHA fits with room for an optional dirty-tree marker if needed for development records.

For deployed builds, the commit SHA is captured at build time and embedded in the agent's runtime environment. Every record produced by that build inherits the embedded SHA. The mechanism is documented in the build pipeline (Phase 3).

Institutions may publish a tag-to-SHA mapping alongside the audit trail for human readability. The mapping is supplementary; the SHA in the record remains the authoritative version identifier.

### Consequences

- Every record traces to an exact code state, reproducible by checking out the SHA.
- A consumer reading a record cannot tell from agent_version alone which release tag it came from. The mapping from SHA to release tag (if any) is recoverable from the version control history or from an institution-published tag-to-SHA index.
- Locally-built agents (developer workstations, ad-hoc builds) produce records bearing development SHAs. This is intentional; a record from a non-release build is identifiable as such.
- Records produced from a working tree with uncommitted changes would carry the parent commit's SHA with no indication of dirty state. To prevent this, the build pipeline rejects dirty trees from producing production records, and development builds append a dirty-tree marker to the SHA.

### Reconsider when

This decision should be revisited if:

- The repository moves off git (unlikely).
- A specific regulator requires a human-readable version on the record itself rather than indirectly through SHA-to-tag mapping.
- Build reproducibility requirements exceed what commit SHA alone can guarantee, requiring a richer reproducibility identifier.

### Framework coverage

- **NIST AI RMF**: Manage function (incident response and decision reproducibility).
- **EU AI Act**: Article 12 (record-keeping). The commit SHA supports the reproducibility requirement for high-risk AI system records.
- **OSFI E-23**: Model audit trail. Reproducibility of the agent that produced a decision is foundational to model governance.
- **SOX ICFR**: Evidence reproducibility for controls that operated through the agent.

---

## ADR-004: Schema Validation via the jsonschema Python Library

**Status:** Accepted
**Date:** 2026-05-24

### Context

The input and output contracts (docs/phase-1/02-input-contract.md and docs/phase-1/03-output-contract.md) are defined in JSON Schema 2020-12 with unevaluatedProperties set to false at the top level and additionalProperties set to false on nested objects. The closure properties matter: a submission carrying fields the schema does not name must be rejected, not silently accepted with the extra data ignored.

Phase 2 must choose a validator library that implements 2020-12 correctly, including the closure properties. Not all Python JSON Schema libraries implement the full 2020-12 specification.

### Options considered

- **jsonschema (python-jsonschema/jsonschema).** The canonical Python implementation. Full 2020-12 support including unevaluatedProperties. Mature, well-maintained, widely-used in the Python ecosystem.
- **fastjsonschema.** Compiled-to-Python validator, significantly faster than jsonschema. Support for 2020-12 features including unevaluatedProperties has historically lagged the canonical jsonschema library. Institutions considering fastjsonschema verify current 2020-12 feature support against their specific schema constructs before adoption.
- **pydantic.** Popular for data validation but uses its own schema model. JSON Schema 2020-12 features like unevaluatedProperties do not map cleanly to Pydantic's model-driven validation. Adopting Pydantic would require re-modeling the contracts away from JSON Schema, breaking the publication of the contracts as standard JSON Schema artifacts.

### Decision

Use the jsonschema library for validation against the published contracts in the Python reference implementation. The Python ecosystem's canonical JSON Schema implementation, with full 2020-12 support, is the appropriate choice for a contract-driven architecture where the contract itself is the published artifact.

Validation runs at two points:

- Intake: every submission is validated against the input contract before any classification work begins. A submission that fails validation is rejected with a structured error naming each failing field.
- Output write: every triage record is validated against the output contract before it is written to storage. A record that fails validation is treated as an incomplete decision and is not relied upon, per the output contract.

The validator is instantiated with the schema version specified in the submission's schema_version field (for input) or the current output schema version (for output records).

Forks of the framework in other language ecosystems select their own validator that implements 2020-12 with full closure-property support. Equivalents exist in JavaScript or TypeScript (ajv), Go (gojsonschema or jsonschema), Rust (jsonschema), and Java (everit-json-schema, networknt). The architectural decision is the validation behavior; the library is the deployment choice within each ecosystem.

### Consequences

- Performance overhead of jsonschema validation is acceptable for the workload (single-submission classification, not high-throughput streaming inference).
- The library's 2020-12 support is current; tracking library updates is part of the dependency management workflow.
- The closure properties (unevaluatedProperties false and additionalProperties false) are enforced as the contracts specify. A field outside the schema fails validation, surfacing the unexpected data as a validation event rather than absorbing it silently.
- The Python ecosystem choice commits the Python reference implementation to a specific library. Forks in other ecosystems make their own equivalent choice; the architectural property (full 2020-12 with closure) is the constraint, not the specific library.

### Reconsider when

This decision should be revisited if:

- Performance becomes a bottleneck (high-throughput classification, real-time inference). At that point fastjsonschema or a compiled validator may be revisited, with attention to whether closure properties are fully supported in the version being considered.
- The contracts move away from JSON Schema 2020-12 (unlikely without a major version bump on the contracts themselves).
- A specific institutional fork prefers a different validator for compatibility with its existing data validation infrastructure.

### Framework coverage

- **NIST AI RMF**: Measure function (validation reliability and contract enforcement).
- **EU AI Act**: Article 15 (accuracy and robustness). Schema enforcement is part of the robustness posture for high-risk AI systems processing structured inputs.
- **OSFI E-23**: Model input governance. Strict input validation supports the model integrity expectations for federally regulated institutions.
- **SOX ICFR**: Control reliability. Inputs to controls that produce financial-reporting-relevant decisions are validated before processing.

---

## ADR-005: Storage Architecture on Postgres with Role-Based Append-Only Constraints

**Status:** Accepted
**Date:** 2026-05-24

### Context

The output contract (docs/phase-1/03-output-contract.md) requires records to be immutable once written, with supersession handled through explicit linkage rather than in-place edits. The privacy spec (docs/phase-1/04-privacy-and-data-handling.md) requires retention to be enforced and purge to be machine-executable.

Phase 2 must select a storage technology that supports these semantics. The choice must work for the reference implementation and serve as a sensible default for institutional forks, including forks with different operational preferences (managed service vs self-hosted, different cloud providers, different existing database investments).

The architectural decision and the deployment choice are separable. The architectural decision is the storage semantics. The deployment choice is the specific Postgres-compatible host that implements those semantics.

### Options considered

- **Postgres with role-based permissions.** Mature relational database with role-based access, row-level security, and broad managed and self-hosted deployment options. Append-only semantics enforced through database role permissions (the application role lacks UPDATE and DELETE on the records table). Familiar to most developers; standard in the regulated mid-market stack.
- **Event store database (EventStoreDB, Kafka).** Native append-only semantics. Higher operational complexity; less familiar to most operators; introduces a category of system the deploying institution may not already run.
- **Object storage with write-once semantics (S3 with Object Lock, Cloudflare R2).** Strong immutability guarantees. Operational complexity for the query patterns the triage workflow requires (lookup by decision_id, vendor_id, supersession chain traversal).
- **Document database (DynamoDB, MongoDB).** Append-only achievable through application-level enforcement. Less natural fit for the relational query patterns the contracts imply.

### Decision

Use Postgres as the storage technology, with append-only semantics enforced through database role permissions, not application-layer policy.

The records table grants the application role INSERT only. No UPDATE, no DELETE. Supersession is implemented as a new record with the supersedes field referencing the prior decision_id, per the output contract. Revocation is implemented as a separate revocations table that joins to records by decision_id; the original record is never modified.

Retention enforcement is implemented through scheduled jobs that delete records past the configured retention period. A dedicated retention-enforcement role has DELETE permission scoped through row-level security policies that gate eligibility by decision_timestamp plus the configured retention period. The application role itself never has DELETE on records.

Deployment choice is institutional. The reference implementation is validated on Supabase Postgres only. The architectural decision (Postgres + role-based append-only) is independent of the specific host, so institutions may deploy on other Postgres-compatible services. The following are compatible deployment options that the framework's architectural constraints support, though only the Supabase deployment has been validated against the reference implementation:

- Self-hosted Postgres on the institution's own infrastructure
- AWS RDS for PostgreSQL
- Google Cloud SQL for PostgreSQL
- Azure Database for PostgreSQL
- Other managed Postgres services (Neon, Crunchy Bridge, Aiven, etc.)

Institutions adopting a non-Supabase deployment verify the role-based append-only configuration works in their chosen environment and document any deviations. The architectural decision (Postgres + role-based append-only) is fixed; the host is configurable.

### Reference implementation pattern

The pattern is implemented through Postgres role permissions and row-level security. The illustrative shape:

```sql
-- Application role: INSERT only on records
GRANT INSERT ON triage_records TO app_role;
-- No UPDATE, no DELETE granted to app_role

-- Retention role: DELETE only on records past retention period
GRANT DELETE ON triage_records TO retention_role;
CREATE POLICY retention_eligible ON triage_records
  FOR DELETE TO retention_role
  USING (decision_timestamp < now() - interval '<institutional_retention_period>');
```

The specific institutional retention period is configuration, not part of this architectural decision. Other Postgres-compatible deployments (AWS RDS, Cloud SQL, Azure Database, self-hosted) use equivalent role grants and row-level security configuration. The pattern's verifiability matters more than the specific syntax: a reviewer can inspect role permissions and confirm the application role lacks UPDATE and DELETE on the records table.

### Consequences

- The choice ties the reference implementation to Postgres. Forks running on a different database substrate need a different storage adapter. The Postgres semantics travel; the database-specific implementation does not.
- Append-only enforcement at the database role level is auditable: a reviewer can verify the application role's permissions and confirm that UPDATE and DELETE are not granted on records.
- Deployment flexibility means institutions are not forced to adopt Supabase or any specific managed service. The architectural decision is independent of operational preferences.
- Supabase's managed offering carries vendor concentration risk only for institutions that select it. Self-hosted and other managed Postgres options are first-class alternatives.
- Retention enforcement through scheduled deletion is verifiable through retention job logs. The privacy spec requires retention to be machine-executable, and this design satisfies that.
- Read patterns the contracts imply (lookup by decision_id, supersession chain traversal, vendor history queries) are natural in Postgres with appropriate indexes.

### Reconsider when

This decision should be revisited if:

- The reference implementation scales beyond what a Postgres instance can comfortably handle (unlikely within the target customer scope; relational databases scale further than most assume).
- Regulatory guidance specific to immutable AI audit records requires write-once storage at the reference level rather than as an institutional layer.
- Institutional forks consistently report friction with the Postgres choice, suggesting a different default would be more useful.

### Framework coverage

- **NIST AI RMF**: Manage function (operational deployment risk management; documented storage architecture for AI decision records).
- **EU AI Act**: Article 12 (record-keeping; the storage architecture supports the immutability and retention obligations).
- **OSFI E-23**: Model audit trail. Append-only storage with role-enforced immutability supports the audit trail expectations for federally regulated institutions.
- **SOX ICFR**: Evidence preservation. Immutable storage of decision records supports the evidence integrity controls for financial reporting environments.

---

## ADR-006: Schema Evolution and Migration Policy

**Status:** Accepted
**Date:** 2026-05-24

### Context

The input and output contracts (docs/phase-1/02-input-contract.md and docs/phase-1/03-output-contract.md) are versioned with semver, and every record carries the schema version that produced it. Phase 1 specifies that a decision made under 1.2.0 stays valid under 1.3.0 unless a 1.3.0 change is explicitly marked retroactive, which is rare and called out when it happens.

Phase 2 must specify the operational policy for how records produced under earlier schema versions are handled when the schema evolves: are they re-validated against the new schema, migrated forward, or left untouched?

### Options considered

- **Re-validate all records on every schema bump.** Maintains a single "valid records" invariant but risks invalidating historical records that were valid when written.
- **Migrate records forward on schema bump.** Each schema bump includes a migration that rewrites existing records. Preserves a single schema version in storage but loses the historical record of what shape the data actually was when produced.
- **Records stay validated against their original schema version; new records use the current version.** Preserves the audit trail of what was actually written and when. Storage holds multiple schema versions simultaneously; readers select the right version when reading.

### Decision

Records stay validated against the schema version they were written under. New records use the current schema version. No retroactive re-validation or migration by default.

A record produced under schema 1.0.0 remains valid against 1.0.0 even after 1.1.0 ships. The record's output_schema_version field names the schema it conforms to; readers validating the record use the named version, not the current version.

This preserves three properties:

- Auditability: a reviewer can reconstruct what the record's contract was at the time it was written, not just what the current contract is.
- Reproducibility: a record produced by a past agent against a past schema can be re-validated against that exact schema, confirming the record was valid at write time.
- Honest history: the storage layer reflects what the system actually wrote, not a retroactively-normalized view.

Retroactive changes (situations where a 1.x bump must apply to records written under earlier versions) are the exception, not the rule. When they are necessary, they are called out explicitly in the schema changelog, the migration is implemented as code reviewed alongside the schema change, and the migration's effect on existing records is documented in the record metadata through an optional field naming the retroactive migration that touched the record.

Major version bumps (semver breaking changes) follow a different rule: existing records in the old major version are not migrated forward. The two majors coexist in storage until the old-version records age out under the retention policy.

### Institutional flexibility

The default policy serves audit trail integrity. Institutions whose context calls for a different approach may layer additional behavior on top of the framework's default:

- Institutions where the default works (most cases): use the framework as-is. Records carry their schema version; readers dispatch on schema version when reading.
- Institutions with stable, infrequent schema changes: the multi-version overhead is minimal because few versions are in flight simultaneously.
- Institutions where a regulator requires all historical records to conform to the current contract: implement migration-forward as an additional layer on top of the framework's default.

### Forward direction: institutional migration-forward

Migration-forward as an institutional layer is a forward direction, not implemented in the reference framework. The "retroactive-migration field" referenced earlier in this ADR does not yet exist on the output contract; it is a design proposal that would be added to docs/phase-1/03-output-contract.md in a future schema bump if and when migration-forward becomes a supported pattern.

Institutions implementing migration-forward before the framework formalizes the pattern should:

- Design their own metadata field for tracking retroactive migrations applied to records
- Preserve the original record alongside the migrated version, with the supersession field linking the two
- Document the migration approach in their own internal architecture decisions
- Treat the migration as an extension of the framework, not an adoption of an existing framework feature

The reference framework may add formal support for migration-forward in a future phase if institutional demand justifies it.

### Consequences

- Storage holds multiple schema versions simultaneously. Readers dispatch on schema version when reading.
- Migrations exist only for the rare retroactive case in the default policy. Most schema bumps require no migration work.
- The schema-version-aware reader is a small piece of complexity that lives in every consumer. The complexity is bounded by the number of schema versions in flight, which is bounded by the retention period.
- Major version bumps create a parallel-versions period that gradually resolves as old-major records age out. During the parallel period, the reader handles both major versions explicitly.
- Institutional migration-forward implementations carry additional storage cost (original record plus migrated version kept together). The institution chooses whether the audit-trail-completeness or the storage-economy tradeoff serves its context.

### Reconsider when

This decision should be revisited if:

- A specific regulator requires that all historical records conform to the current contract (would force migration-forward as the framework default).
- The number of schema versions in flight exceeds what consumers can reasonably dispatch on (suggests the contract design needs revision rather than the migration policy).
- The schema becomes stable enough that the multi-version overhead is no longer justified.

### Framework coverage

- **NIST AI RMF**: Manage function (record lineage and version management).
- **EU AI Act**: Article 12 (record-keeping; the contract version travels with the record, preserving the documentation chain).
- **OSFI E-23**: Model documentation versioning. The audit trail of what contract was in force when a decision was made supports model governance.
- **SOX ICFR**: Evidence integrity. Historical records reflect their original validation context, not a retroactively normalized one.

---

## ADR-007: PydanticAI as the Agent Framework

**Status:** Accepted
**Date:** 2026-05-25

### Context

ADR-001 commits to a provider-agnostic LLM interface designed LiteLLM-compatible. ADR-001 also notes that the reference Claude adapter's specific mechanism for producing schema-conforming output is decided when the agent build begins. Phase 3 sub-system 2 made that decision: the agent uses PydanticAI as its framework.

The decision had to balance three properties:

- **Provider-agnosticism.** ADR-001 commits to the abstraction. The chosen framework must support multiple providers without requiring rewrites at the call site.
- **Structured output enforcement.** The output contract (docs/phase-1/03-output-contract.md) is JSON Schema 2020-12 with closure properties. The framework must produce conforming output reliably, not as a best-effort hint to the LLM.
- **Audit-trail compatibility.** Every record carries agent_version. The framework must be inspectable enough that the version captures both the framework's own behavior and the prompt's behavior.

### Options considered

- **Direct provider SDK (anthropic-sdk-python, openai-python).** Native to each provider, no abstraction layer. ADR-001's provider-agnostic commitment requires the institution to build its own abstraction over the SDKs, or accept lock-in.
- **LangChain.** Popular abstraction layer. Higher complexity surface, heavier dependency, history of frequent breaking changes. Audit story for the framework's own dependency is weaker.
- **PydanticAI.** Type-safe agent framework built on Pydantic. Supports multiple providers (Anthropic, OpenAI, Google, Mistral, Cohere, local models). Output is constrained by a Pydantic model the framework enforces, with retry logic when the LLM produces malformed output. Smaller dependency surface than LangChain. Stable interface (1.0 release in 2025).

### Decision

Adopt PydanticAI as the agent framework for the reference implementation. The agent (agent/agent.py) wraps a PydanticAI Agent configured with an internal _TriageClassification output type. The LLM is required to produce JSON conforming to the type; PydanticAI handles retries on malformed output (up to a configurable retry count, default 2).

Provider-agnosticism is preserved: PydanticAI's Model abstraction supports swapping providers without changing the agent code. The reference implementation uses Anthropic Claude by default; deploying organizations select any PydanticAI-supported provider through configuration.

The agent_version field (per ADR-003) captures both the framework's FRAMEWORK_VERSION constant (currently 0.6.0, bumped on material behavior changes) and a SYSTEM_PROMPT_HASH computed at module load from the system prompt text. Any change to the prompt produces a different hash, surfacing the change in the audit trail without manual versioning discipline.

The LiteLLM-compatibility commitment in ADR-001 is preserved as a forward direction. Institutions operationalizing the framework may swap PydanticAI for LiteLLM at the adapter layer if their requirements warrant; the agent code is small enough that the swap is bounded work.

### Consequences

- The reference implementation has a PydanticAI dependency (pydantic-ai-slim[anthropic]>=1.0,<2 in pyproject.toml). The dependency is well-maintained, version-pinned, and tracked in the audit log.
- Provider swap is configuration, not code, for any provider PydanticAI supports.
- Structured output is enforced by the framework with retry, not by a separate validator step. The agent module is more compact and the failure modes (UnexpectedModelBehavior after retries) surface explicitly.
- The deployment-architecture Output Validator described in 01-system-architecture.md is realized by PydanticAI's Pydantic-enforced output, not by a separate JSON Schema validation step. The architecture's intent (validated output before storage) is preserved; the mechanism is different.
- Tests use PydanticAI's TestModel and FunctionModel to make agent tests deterministic and credential-free.

### Reconsider when

- PydanticAI introduces breaking changes the framework cannot easily absorb.
- A specific deploying institution requires a provider PydanticAI does not support, and adding the provider upstream is not viable.
- LiteLLM (or an equivalent) becomes the de facto standard with audit-grade governance, and the reference's vendor risk story benefits more from adoption.

### Framework coverage

- **NIST AI RMF**: Govern function. Framework choice is part of the system's vendor risk posture; documenting it supports accountability.
- **EU AI Act**: Article 15 (accuracy and robustness). Structured output enforcement supports robustness; framework choice affects how robustly the constraint is enforced.
- **OSFI E-23**: Model documentation requirements. The framework underlying the model is part of the model's documentation.
- **SOX ICFR**: Third-party software dependency in the controls environment. PydanticAI is a third-party dependency the institution governs as part of its software supply chain.

---

## ADR-008: Stateless Reference Library Pattern

**Status:** Accepted
**Date:** 2026-05-25

### Context

01-system-architecture.md (this document's companion in Phase 2) describes a deployment architecture with HTTP REST intake, Postgres-backed storage, an Audit Query API, and a Retention Enforcement job. That architecture is correct as the institutional deployment pattern: it is what a regulated mid-market institution running the gate at production scale ultimately deploys.

The reference implementation in this repository, however, is not the deployment. It is the library that goes inside the deployment. The library is what gets imported into the institution's chosen transport, storage, and operational substrate.

The choice between "reference is the deployment" and "reference is the library" has consequences for adoption, testing, audit, and forks.

### Options considered

- **Reference is the deployment.** The repository ships a runnable HTTP service with Postgres bindings, ready to deploy. Maximum demo value, minimum integration value. Institutions running on different transport (RPC, message bus, batch) or storage (SQLite, DynamoDB, object storage) face significant rework. The reference becomes a competitor to the institution's stack rather than a component of it.
- **Reference is the library.** The repository ships a Python library that classifies submissions, ingests documents, retrieves regulation context, and evaluates output. The library carries no HTTP, no Postgres, no audit log writer. Institutional code wires the library into the institution's chosen transport and storage. The reference becomes a building block.
- **Reference is both.** Maintain a library plus a reference deployment that uses it. Highest maintenance burden; risks the deployment diverging from the library as the framework evolves.

### Decision

The reference implementation is the library. The repository ships seven Python packages (agent/, ingestion/, retrieval/, eval/, eval/attacks/, eval/citations/, eval/calibration/, eval/judge/) that perform classification, parsing, retrieval, and evaluation. No HTTP server, no database, no audit log writer. The library is stateless: callers supply submissions, documents, and chunks; the library returns TriageRecords and evaluation results.

The deployment architecture described in 01-system-architecture.md remains the recommended institutional deployment pattern. Institutions wire the library into their chosen transport (HTTP, RPC, message bus), storage (Postgres or equivalent per ADR-005), and operational substrate (audit log, retention, observability). The library does not constrain the wiring; the deployment architecture documents the recommended shape.

A reference deployment using this library is a separate workstream (planned for Phase 5/6) and is intentionally not part of this repository. Keeping deployment separate from library lets the library evolve faster, keeps the dependency footprint smaller, and avoids the reference becoming a competitor to the institution's stack.

### Consequences

- The repository's dependency footprint is small: pydantic, pydantic-ai-slim, pypdf, jsonschema, rank-bm25, optionally sentence-transformers. No web framework, no database client, no observability vendor.
- Adoption cost for the institution is the wiring work. The library is small enough that wiring is straightforward; the deployment architecture document gives the target shape.
- Audit log writing, retention enforcement, and the audit query API are institutional concerns. The library does not produce an audit log; it produces TriageRecords that the institution persists and indexes in the institution's chosen audit substrate.
- The library is testable without HTTP servers or databases. The full test suite (568 tests at FRAMEWORK_VERSION 0.6.0) runs in seconds against in-memory fixtures.
- Forks of the framework can adopt the library wholesale or selectively (just the agent, just the retrieval layer, just the eval harness) without inheriting deployment commitments.
- The framework's audit story is cleaner: the library's behavior is fully specified by its types and tests; the deployment's behavior is the institution's responsibility, documented separately.

### Reconsider when

- A specific deploying institution requires a runnable reference deployment to evaluate the framework and the institution does not have the engineering capacity to wire the library themselves.
- The framework's adoption stalls because the wiring work is consistently the blocker.
- A specific regulator requires the framework itself to demonstrate end-to-end operational behavior, not just the library.

### Framework coverage

- **NIST AI RMF**: Govern function. The deployment vs library distinction is part of accountability for what the framework does and what the institution does.
- **EU AI Act**: Article 16 (obligations of providers of high-risk AI systems). The framework provides AI system components; the institution deploying them assembles the system. The distinction matters for provider/deployer obligations.
- **OSFI E-23**: Third-party model oversight. The library is the third-party component; the deployment is the institution's. The boundary is operational, not just semantic.
- **SOX ICFR**: IT general controls. Library and deployment have different control responsibilities. The institution's ITGC scope covers the deployment; the library's controls cover the library.

---

## ADR-009: Caller-Provided I/O at the Agent Boundary

**Status:** Accepted
**Date:** 2026-05-25

### Context

The agent (agent/agent.py) takes three optional inputs in addition to the submission: documents (pre-extracted PDF text), regulation_chunks (retrieved regulation context), and decision_id (caller-supplied for retry chains).

A design choice exists at the agent boundary: does the agent fetch documents and retrieve chunks itself, or does the caller supply them already-fetched?

Self-fetching simplifies the caller's code. Caller-supplied I/O simplifies the agent's code and makes testing dramatically easier.

### Options considered

- **Agent fetches documents and retrieves chunks.** Caller supplies a submission and connection strings or URLs; the agent parses documents from the references and runs retrieval against the configured corpus. Caller code is shorter. Agent has its own I/O surface (network, file system), its own error handling, its own retry logic. Testing requires mocking I/O at multiple levels.
- **Caller fetches and supplies pre-extracted content.** Caller invokes ingestion/PDFReader and retrieval/Retriever themselves; the agent receives Document and Chunk instances ready to render into the LLM prompt. Caller code is longer but more explicit. Agent has no I/O surface; testing uses in-memory fixtures.

### Decision

Caller-provided I/O. The agent's triage() method takes documents and regulation_chunks as already-constructed lists; the agent does no fetching, no parsing, no retrieval. Callers compose with ingestion/PDFReader (to construct Documents from PDFs) and retrieval/Retriever (to construct Chunks from a queried index) before invoking triage().

Three properties this preserves:

- **No I/O at the agent boundary.** The agent is a pure function over its inputs: same submission + same documents + same chunks + same model = same output. Testability is dramatic; the full agent test suite runs in seconds without network or file system access.
- **Composability with alternative providers.** A caller wanting to swap pypdf for a different parser, BM25 for a different retrieval strategy, or the local file system for an object store does so without touching the agent. The Embedder Protocol (per Phase 4 sub-system 5) is the same pattern at the embedding layer.
- **Audit clarity.** What the agent saw is exactly what the caller passed. There is no hidden I/O the auditor has to reconstruct.

### Consequences

- The caller is responsible for wiring document parsing and retrieval. The ingestion/ and retrieval/ packages make this small (a few lines for each), but it is real wiring.
- The agent cannot fail because of I/O errors; those failures surface earlier, at the caller's parsing or retrieval step. Better error localization for the institution's logs.
- The bait-and-switch defense (per ADR-010) is enforced at the agent boundary: the agent verifies a supplied Document's content_hash against the submission's claim before any LLM call. If the agent fetched documents, the defense would have to live in the fetch path; pushing it to the boundary makes the verification explicit and unavoidable.
- Tests construct Document and Chunk fixtures in-memory. No PDFs are read during the test suite; no network is touched.
- Wrapping the library in a thin HTTP service is the institution's task. The wrapper handles the fetch-and-supply pattern; the library does the work.

### Reconsider when

- A specific deploying institution requires a self-fetching agent because their wrapper layer is constrained.
- The library's adoption stalls because the I/O wiring is consistently the blocker (in which case ADR-008's reconsider conditions also apply).

### Framework coverage

- **NIST AI RMF**: Govern function (transparency about what the agent does and does not do).
- **EU AI Act**: Article 13 (transparency and provision of information to deployers). The agent's I/O boundary is a transparency property; documenting it supports the article's requirements.
- **OSFI E-23**: Model governance (model boundaries explicit, not implicit).
- **SOX ICFR**: Control reliability (the agent's behavior is fully determined by its inputs, which is auditable).

---

## ADR-010: Document Hash Verification Before LLM Invocation

**Status:** Accepted
**Date:** 2026-05-25

### Context

Documentation artifacts in the input contract (per docs/phase-1/02-input-contract.md) can carry an optional content_hash field naming the SHA-256 of the document the submitter claims to have attached. The hash is part of the submission identity for idempotency purposes (per 01-system-architecture.md).

T-AI4 in the threat model identifies hallucination as a residual risk. A related but distinct threat is bait-and-switch: a submitter claims one document via content_hash, but the actual document parsed at inference time is different. The discrepancy is invisible to the LLM, which sees only the parsed text. The result is a triage record that purports to be based on the claimed document but is actually based on attacker-substituted content.

### Options considered

- **Trust the submitter's claimed hash.** Skip verification. Simplest, but defeats the integrity purpose of the hash field.
- **Verify on read at audit time.** Persist the hash with the record; verify when the auditor queries. Pushes detection to audit rather than prevention at decision time.
- **Verify at the agent boundary, before any LLM call.** Compute the actual document's hash, compare against the submission's claim, raise if they differ. Cost is one SHA-256 per document.

### Decision

Verify at the agent boundary before any LLM call. The agent's triage() method, when documents are supplied, calls _verify_documents_against_submission() which compares each Document's computed content_hash against the matching entry in the submission's documentation_artifacts. A mismatch raises TriageInputError, surfacing the integrity failure before any classification work begins.

The verification covers two failure modes:
- Source reference matches, but content_hash differs: bait-and-switch. Reject.
- Source reference matches no submission entry: phantom document. Reject.

The error includes specific reference paths for the auditor to investigate.

### Consequences

- One SHA-256 computation per supplied document at the agent boundary. The cost is negligible compared to the LLM call.
- Bait-and-switch attacks are caught before the LLM is invoked, not after. The audit trail shows the rejection event with specific references; the LLM cost is zero for the attack.
- The agent's caller is responsible for actually computing the content_hash on the Document instance it constructs. The ingestion/ package's PDFReader does this automatically; callers using a different parser must compute the hash themselves.
- The defense applies only when the submission carries content_hash claims. Submissions omitting content_hash bypass the verification; this is consistent with the input contract's optional treatment of content_hash and the 01-system-architecture.md note about best-effort idempotency in the absence of claims.
- The verification is tested explicitly in tests/test_agent_core.py with both passing (matching hashes) and failing (mismatched hashes) cases. Phase 4 sub-system 1's attack dataset includes an "attack-bait-switch-1" entry with expected_to_raise=TriageInputError that exercises the defense in the eval harness.

### Reconsider when

- The submitter cannot reasonably compute content_hash for their submission (e.g., document is fetched at submission time and the hash is computed downstream). In that case, content_hash should be omitted rather than fabricated.
- A specific provider or transport introduces hash mutation between submission and agent invocation (e.g., document re-encoding by a proxy). The verification logic accommodates this by accepting hash absence; mutations should not silently change a claimed hash.

### Framework coverage

- **NIST AI RMF**: Manage function (integrity controls on inputs to the AI system).
- **EU AI Act**: Article 15 (accuracy and robustness). Input integrity is a robustness property.
- **OSFI E-23**: Model input governance. Verified input integrity supports model accountability for the inputs used in classification.
- **SOX ICFR**: Control input integrity. When AI supports financial reporting, inputs to the AI are inputs to a control; verified integrity is required.

---

## ADR-011: BM25 Lexical Retrieval as the Primary Strategy

**Status:** Accepted
**Date:** 2026-05-25

### Context

Phase 3 sub-system 5 added regulation context retrieval. The agent's triage() method accepts regulation_chunks as an optional input; the chunks are retrieved by the caller from a regulation corpus (OSFI E-23, ISO 42001, NIST AI RMF, EU AI Act, SOX/ICFR) and supplied to the agent.

The retrieval strategy choice has consequences for vendor risk posture, audit defensibility, determinism, and operational footprint.

### Options considered

- **Vector embeddings as the primary retrieval.** Dense semantic retrieval via a learned embedding model. Captures semantic similarity well; misses exact-phrase and acronym matches. Requires an embedding model dependency (sentence-transformers, OpenAI text-embedding, Voyage, Cohere). Non-deterministic across model updates: re-embedding the same chunk after a model version bump produces a different vector.
- **BM25 lexical retrieval as the primary strategy.** Token-overlap-based ranking via rank-bm25 (pure Python, no model dependency). Captures exact-phrase and regulation-specific acronyms (CC6.1, E-23, Annex III). Deterministic: same corpus + same query = same ranking, indefinitely. Auditor can inspect tokenization and ranking logic.
- **Hybrid lexical + vector from the start.** Both signals combined. Stronger retrieval, but commits to the vector dependency at the primary level. Audit story is more complex.

### Decision

BM25 lexical retrieval is the primary strategy. Phase 3 sub-system 5 ships BM25Index, Retriever, and CorpusLoader; these are the framework's documented retrieval surface. Vector and hybrid retrieval ship in Phase 4 sub-system 5 as complementary signals available via opt-in.

Three properties drive the primary choice:

- **Vendor-agnostic.** rank-bm25 is pure Python with one dependency (numpy). No model file, no model provider, no inference cost. The institution's vendor risk posture for retrieval is minimal.
- **Deterministic.** Same corpus, same query, same ranking. Indefinitely. Regulation chunks an agent cited in a decision today rank identically when re-queried in a 5-year audit review, assuming the corpus has not changed.
- **Auditable.** The tokenizer is a 4-line regex (a single function in retrieval/index.py). The BM25 formula is documented. A reviewer can predict which chunks rank for a given query without running the system.

Vector retrieval addresses BM25's gaps (semantic similarity, vocabulary mismatch) as a Phase 4 addition (per Phase 4 sub-system 5 in retrieval/vector_index.py and retrieval/hybrid_index.py). The Embedder Protocol is vendor-agnostic at the embedding layer; HashEmbedder ships as the no-dependency default, SentenceTransformerEmbedder ships as the opt-in [vector] extra. Institutional deployments may select any Embedder Protocol implementation, including provider-backed ones (Voyage, OpenAI, Cohere). The hybrid index combines BM25 and vector rankings via Reciprocal Rank Fusion (k=60).

### Consequences

- The framework's default retrieval has minimal vendor risk and small dependency footprint.
- BM25's gaps are real: a query for "AI governance" does not match a chunk discussing "AI management systems" by token overlap. Hybrid retrieval addresses this when the deploying institution installs the [vector] extra.
- BM25's IDF math degenerates on very small corpora (N<3 documents). Documented in retrieval/README.md. Real regulation corpora are well into the hundreds of chunks where IDF is well-behaved.
- The deterministic property is foundational to the audit story. Citation grounding (per Phase 4 sub-system 2) checks chunk_id references against the supplied chunk list; deterministic retrieval means the same chunks reach the agent and the verifier.
- Adding a different lexical retrieval (e.g., SPLADE) is a future option; the Retriever abstracts the index type. The framework's commitment is to a primary deterministic, vendor-agnostic strategy, not specifically to BM25 forever.

### Reconsider when

- Hybrid retrieval becomes the default for a majority of deploying institutions, and the dependency on sentence-transformers (or equivalent) becomes acceptable as a baseline.
- A specific regulator requires semantic retrieval as the primary strategy for AI risk classification.
- BM25's gaps on specific corpora become consistently problematic.

### Framework coverage

- **NIST AI RMF**: Govern function (vendor risk for retrieval components). The default minimizes vendor risk.
- **EU AI Act**: Article 12 (record-keeping). Deterministic retrieval supports the reconstructability of decisions over time.
- **OSFI E-23**: Model governance. Deterministic retrieval supports the model's auditability and reproducibility expectations.
- **SOX ICFR**: Reproducibility of control outputs. Deterministic retrieval supports reproducibility of AI-driven decisions in the ICFR scope.

---

## ADR-014: Deterministic-First Evaluation Discipline

**Status:** Accepted
**Date:** 2026-05-25

### Context

Phase 4 added evaluation depth beyond the tier-and-disposition accuracy measured in Phase 3 (eval/runner.py). The new sub-systems address questions that go beyond label match:

- Does the agent resist prompt injection? (Phase 4 sub-system 1, eval/attacks/)
- Do citations in the agent's reasoning actually resolve? (Phase 4 sub-system 2, eval/citations/)
- Is the agent's confidence calibrated? (Phase 4 sub-system 3, eval/calibration/)
- Does the agent's reasoning hold up to semantic review? (Phase 4 sub-system 4, eval/judge/)

Two of these (citations, calibration) admit deterministic answers via reference resolution and arithmetic. One (attacks) admits a deterministic answer via assertion grading. One (judge) requires an LLM to grade semantic quality.

The order in which the framework adopts these signals matters. Adopting an LLM-based signal first introduces non-determinism into the eval story; adopting deterministic signals first establishes a stable baseline that the LLM signal complements rather than replaces.

### Options considered

- **LLM-as-judge first.** Highest semantic depth, addresses the auditor's hardest questions. Non-deterministic: same record judged twice produces different scores. The framework's eval story becomes "LLM grades LLM"; the audit story is harder.
- **Deterministic-first, then LLM-as-judge as complement.** Citation verification, calibration, and attack-resistance establish deterministic baselines. LLM-as-judge adds the semantic dimension as a documented non-deterministic signal layered on top.
- **All four signals at once.** No prioritization. Higher risk that one signal's non-determinism contaminates the audit story for the others.

### Decision

Deterministic signals first, LLM-as-judge as complement. Phase 4 sub-system 1 (attacks) ships a deterministic assertion-grading harness (the agent's response either falls in the assertion's allowed range or it does not; no LLM grades). Phase 4 sub-system 2 (citations) ships fully-deterministic verification with JSONPath-lite path resolution and Jaccard token-overlap grounding. Phase 4 sub-system 3 (calibration) ships fully-deterministic Brier, ECE, and MCE arithmetic. Phase 4 sub-system 4 (LLM-as-judge) ships as the explicit non-deterministic complement, with three pre-built rubrics, audit-trail metadata (judge_model_version, run_timestamp), and edge-case short-circuits that prefer the deterministic answer when one exists.

Implications for audit:

- The first three eval signals are reproducible. Same dataset, same agent, same code = identical metrics. Auditors can replay.
- The fourth signal is documented non-deterministic. Audit guidance is to run it multiple times for critical examples and report the score distribution.
- Cross-model judging is recommended (per ADR-016) but not enforced; deploying institutions decide their judge model policy.
- The non-deterministic signal's edge-case handlers route to deterministic answers when possible (e.g., MITIGATION_APPROPRIATENESS returns score=1.0 for non-conditional-approve dispositions without calling the LLM). This minimizes LLM-induced variance on cases where the answer is mechanically determined.

### Consequences

- The framework's eval story has a stable deterministic core. An auditor reviewing Phase 4 sub-system 1 through 3 results gets reproducible metrics; the Phase 4 sub-system 4 results are explicitly framed as a non-deterministic complement.
- The cost ordering aligns: deterministic checks are essentially free, LLM-as-judge has per-call cost. Running citations and calibration over an entire dataset is cheap; running LLM-as-judge requires budget.
- The audit cycle benefits: the deterministic signals are run on every commit (in CI); the LLM signal is run on dataset milestones or on demand.
- The framework's stance on non-determinism is consistent across components: it is acknowledged where it exists (the triage agent itself is non-deterministic, the judge is non-deterministic) and surfaced via audit-trail metadata, not hidden.

### Reconsider when

- A deployment context exists where deterministic-first ordering is not appropriate (e.g., a research environment where the LLM-grader produces ground-truth labels).
- Confidence intervals on LLM-grader scores become reliable enough that the non-deterministic signal can be treated as if deterministic (with documented confidence bounds). This is roughly a Phase 5 question.

### Framework coverage

- **NIST AI RMF**: Measure function (consistent measurement methodology). Deterministic-first measurement is more consistently applicable than non-deterministic-first.
- **EU AI Act**: Article 15 (accuracy and robustness) and Article 17 (quality management). Reproducible evaluation metrics support both.
- **OSFI E-23**: Model validation. Deterministic evaluation signals support model validation expectations.
- **SOX ICFR**: Control effectiveness measurement. Reproducible measurements support the audit trail for control effectiveness.

---

## ADR-012: Reciprocal Rank Fusion for Hybrid Retrieval

**Status:** Accepted
**Date:** 2026-05-26

### Context

Phase 4 sub-system 5 added vector retrieval (per ADR-013) and hybrid retrieval that combines vector and BM25 (per ADR-011). The hybrid combination step required a method for merging two ranked lists into one.

BM25 scores and cosine similarities live in incomparable numeric ranges. Naive weighted-sum combinations are fragile: small changes in the corpus or the embedder shift the score distributions, and tuned weights stop working. The combination method needs to be robust to score-scale differences.

### Options considered

- **Weighted score combination.** alpha * normalized_bm25 + (1-alpha) * normalized_cosine. Requires score normalization (min-max, z-score, percentile) and a tuned alpha. Both moving parts; both fragile.
- **Reciprocal Rank Fusion (RRF).** Combine ranks not scores: score(d) = sum over indexes of 1 / (k + rank_in_index(d)). The constant k=60 is the standard value from Cormack, Clarke, and Buettcher (2009). Order-preserving: a document ranked first in both indexes scores highest; one ranked first in one index but absent from the other still scores meaningfully.
- **Learning-to-rank.** Train a ranker on labeled query-document pairs. Highest-quality option, requires labeled training data the framework does not have.

### Decision

Reciprocal Rank Fusion (RRF) with k=60. The HybridIndex (retrieval/hybrid_index.py) pulls top-fanout (default 50) results from each underlying index, computes RRF over the union of returned chunk_ids, and returns the top-k by RRF score. Documents not appearing in a given index's top-fanout contribute 0 from that index.

The RRF constant k=60 is held to the standard value from Cormack, Clarke, and Buettcher (2009). Configurability is exposed for institutions that want to tune (lower k emphasizes top positions more strongly; higher k de-emphasizes the difference between near-top ranks), but the default is the standard value.

The fanout=50 default balances recall against latency. Larger fanout improves recall at the cost of pulling more results per query; smaller fanout may miss chunks that one index ranks low.

### Consequences

- The hybrid score is not a similarity. RRF scores are bounded by 2 / (k+1) ≈ 0.0328 for top-ranked items; they are useful for ordering but should not be interpreted as probabilities or similarities. Documented in retrieval/README.md.
- No score normalization required. The two underlying indexes can have wildly different score distributions; RRF is robust.
- No alpha to tune. Institutions adopting hybrid retrieval get the Cormack-paper standard immediately; tuning is opt-in, not required.
- Tests exercise the RRF math directly (tests/test_vector_hybrid.py::test_rrf_formula_explicit) to ensure the formula remains correct as the implementation evolves.

### Reconsider when

- Labeled query-document pairs become available and learning-to-rank becomes feasible.
- A specific deployment context produces consistently poor results with RRF and a tuned weighted-sum performs measurably better.

### Framework coverage

- **NIST AI RMF**: Measure function. Reproducible retrieval-quality measurement is supported by deterministic combination.
- **EU AI Act**: Article 15 (accuracy and robustness). Robust ranking combination supports robustness.
- **OSFI E-23**: Model design rationale. Documented combination method supports model governance.
- **SOX ICFR**: Documented control logic. The retrieval ranking is an input to control output; documented logic supports reproducibility.

---

## ADR-013: Embedder Protocol for Vendor-Agnostic Semantic Retrieval

**Status:** Accepted
**Date:** 2026-05-26

### Context

Phase 4 sub-system 5 added dense semantic retrieval as a complement to BM25 (per ADR-011). The dense retrieval requires an embedding function that maps text to fixed-dimension vectors. Several providers offer this (sentence-transformers, OpenAI text-embedding, Voyage, Cohere, Anthropic, local models).

Hard-coding any one provider would defeat the framework's vendor-agnostic posture. A pluggable abstraction was required.

### Options considered

- **Hard-code sentence-transformers.** Simplest. Locks the framework to sentence-transformers' update cadence, model availability, and licensing.
- **Hard-code one cloud provider's embedding API (OpenAI, Voyage).** Simplest cloud path. Locks the framework to one provider and one billing relationship; defeats the vendor-agnostic posture.
- **Embedder Protocol abstraction.** Define a structural typing protocol (Python's typing.Protocol) that any embedding implementation can satisfy. Ship one or more default implementations.

### Decision

Embedder Protocol abstraction. retrieval/embeddings.py defines the Embedder protocol with two methods: `dimension` (property, returns the fixed output dimension) and `embed(texts: list[str]) -> np.ndarray` (returns L2-normalized vectors, shape (len(texts), dimension)).

Two default implementations ship:

- HashEmbedder: deterministic hash-based pseudo-embeddings. No external dependencies. Tokenizes input, maps tokens to dimension indices via a hash function, L2-normalizes. Does NOT capture semantic similarity (chunks with disjoint vocabularies have near-zero similarity). Used in tests and as a fallback when sentence-transformers is not installed.
- SentenceTransformerEmbedder: wraps the sentence-transformers library with lazy import. Default model `all-MiniLM-L6-v2` (384-dim, ~80MB). Installed via the opt-in `[vector]` extra.

Adding a provider-backed Embedder (Voyage, OpenAI, Cohere, Anthropic) requires only implementing the Protocol. No framework changes. The Protocol's contract specifies that all embeddings are L2-normalized so cosine similarity in VectorIndex becomes a dot product.

### Consequences

- HashEmbedder makes the dense-retrieval code path testable without external dependencies. Tests run in seconds without downloading models.
- SentenceTransformerEmbedder is opt-in. Users who do not want vector retrieval do not pay the install cost (model files are 50-500MB depending on the model).
- Provider-backed Embedders (Voyage, OpenAI, Cohere) are not bundled. The framework ships the Protocol; institutions wire up their preferred provider. The `[deferred-phase-5]` items in retrieval/README.md track the suggestion to ship a small number of provider-backed implementations.
- L2-normalization is required by the contract. The Protocol's `embed()` docstring states this explicitly. VectorIndex relies on L2-normalization to make cosine similarity a dot product; an implementation that returns non-normalized vectors will produce incorrect rankings.

### Reconsider when

- A specific embedding provider becomes dominant enough that hard-coding it becomes acceptable.
- The Protocol's contract proves insufficient for advanced embedding patterns (e.g., per-text-pair scoring, query-vs-document asymmetric embedders).

### Framework coverage

- **NIST AI RMF**: Govern function. Vendor-agnostic abstraction at the embedding layer is part of the framework's vendor risk posture.
- **EU AI Act**: Article 13 (transparency). The Protocol documents what the framework expects of an embedder; deploying organizations know what they are wiring up.
- **OSFI E-23**: Third-party model oversight. The embedding model is a third-party model in the deployment; the Protocol surfaces the dependency for oversight.
- **SOX ICFR**: Third-party dependency governance. The framework provides the abstraction; the institution governs its specific embedding choice.

---

## ADR-015: Single-Criterion-Per-Call for LLM Judge

**Status:** Accepted
**Date:** 2026-05-26

### Context

Phase 4 sub-system 4 ships the LLM-as-judge harness (eval/judge/). The judge grades a TriageRecord against a Rubric (a single evaluation criterion: rationale coherence, citation grounding, mitigation appropriateness, or a custom one).

A design choice exists: should one LLM call evaluate one rubric, or should a single call bundle multiple criteria?

### Options considered

- **Single-criterion-per-call.** Each judge call grades exactly one Rubric. Three rubrics across 100 records = 300 calls.
- **Multi-criterion bundling.** Each judge call grades multiple Rubrics in one prompt. Three rubrics across 100 records = 100 calls. One-third the cost.
- **Adaptive bundling.** Bundle when correlated, separate when not. Requires per-rubric correlation analysis.

### Decision

Single-criterion-per-call. Each invocation of LLMJudge.judge() grades exactly one Rubric against one TriageRecord. The LLM produces JSON with exactly two fields: `score` (float in [0, 1]) and `rationale` (string).

Three properties this preserves:

- **Cleaner per-criterion scores.** Bundled grading risks the LLM's score on rubric A being influenced by its score on rubric B (anchoring, ordering effects, criterion bleed). Single-criterion calls isolate the signal.
- **Easier debugging.** When a rubric's scores look wrong, the prompt is one rubric, not three. Investigation is targeted.
- **Easier metric attribution.** The aggregate metrics (JudgeAggregateMetrics) report per-rubric mean, min, max, stdev cleanly. Bundling would force per-call scores to be split out, with associated potential for parsing errors.

Multi-criterion bundling is tagged `[deferred-phase-4-followup]` in eval/judge/README.md. Institutions running large evaluation datasets where per-record cost matters more than per-criterion isolation may layer their own bundling logic on top.

### Consequences

- The framework's judge cost is per-rubric-per-record. 3 rubrics × 100 records = 300 LLM calls. Documented explicitly in eval/judge/README.md.
- Per-rubric scores are isolated; no criterion-bleed concerns.
- Future bundling is additive: the Rubric model and the LLMJudge.judge() signature do not preclude a bundled-grading variant landing later.

### Reconsider when

- LLM provider pricing makes per-rubric-per-record cost unworkable for typical evaluation dataset sizes.
- Empirical evidence shows bundling does not affect per-criterion scores meaningfully on the framework's specific rubrics.

### Framework coverage

- **NIST AI RMF**: Measure function. Isolated per-criterion measurement supports reliability of the measurement.
- **EU AI Act**: Article 17 (quality management). Documented measurement methodology supports the QMS.
- **OSFI E-23**: Model validation. Per-criterion measurement supports model validation discipline.
- **SOX ICFR**: Measurement reliability for AI-driven controls.

---

## ADR-016: Cross-Model Judging Recommended Not Enforced

**Status:** Accepted
**Date:** 2026-05-26

### Context

Phase 4 sub-system 4 ships the LLM-as-judge harness. The judge is itself an LLM, so the framework faces a self-judging question: if the triage agent runs on Claude and the judge also runs on Claude, the judge's evaluation of the agent has correlated errors. The two models share priors; the judge may approve of reasoning patterns the agent generates because both share the same training distribution.

Cross-model judging (triage agent on one model, judge on a different model) mitigates the self-judging correlation. The framework's stance on this needs to be documented: is cross-model judging required, recommended, or just permitted?

This ADR closes a forward reference originally placed in ADR-014, which had mentioned that cross-model judging would be documented in a subsequent ADR. ADR-014 has been updated to reference this ADR-016 directly.

### Options considered

- **Enforce cross-model judging.** The LLMJudge raises if its configured model matches the triage agent's model. Maximum audit-independence; restricts deploying organizations to multi-provider relationships.
- **Recommend cross-model judging without enforcement.** Documented in eval/judge/README.md as the recommended setup; the LLMJudge does not check. Institutions with single-provider constraints can run same-model judging with the documented caveat.
- **Silent on the topic.** Leave it to the deploying organization with no framework guidance. Weakest audit story.

### Decision

Recommend cross-model judging without enforcement. eval/judge/README.md documents:

- Cross-model judging is the recommended setup for audit-grade evaluation.
- Same-model judging is permitted but produces correlated errors; the audit story is weaker. Cheaper mitigation: same model with substantially different system prompt and temperature.
- The deploying organization's judge model policy is institutional configuration.

The LLMJudge constructor accepts any PydanticAI Model. The judge_model_version is captured into every JudgeResult; auditors can verify the judge model is distinct from the triage model in the audit trail.

The framework does not enforce because:

- Some deploying organizations have single-provider relationships (one LLM contract). Forcing them to add a second provider creates adoption friction without obvious benefit when the deploying organization knows the limitation.
- The deploying organization's risk posture is its own. The framework provides the guidance; the institution decides.
- Enforcement would require the framework to know which models "count as different." Cross-vendor (Claude vs GPT) is clearly different; same-vendor different-model (Claude Sonnet vs Claude Opus) is debatable; same-model different-temperature is not different at all. Codifying this judgment in the framework is fragile.

### Consequences

- Audit-grade deployments use cross-model judging. The framework's documented best practice supports the audit story.
- Single-provider deployments can still run the judge; the trade-off is explicit.
- judge_model_version metadata supports post-hoc audit verification regardless of policy.

### Reconsider when

- A specific regulator requires cross-model judging for AI-evaluation results in scope (would force enforcement).
- Cross-vendor judging becomes substantially cheaper such that single-provider deployments are no longer common.

### Framework coverage

- **NIST AI RMF**: Govern function. Independence of judging is part of audit integrity.
- **EU AI Act**: Article 17 (quality management). Documented evaluation methodology including independence considerations.
- **OSFI E-23**: Model validation. Independence in model validation is a discipline expectation.
- **SOX ICFR**: Independent evaluation. Cross-model judging supports independence in control effectiveness measurement.

---

## ADR-017: Equal-Width Binning for Calibration Reliability

**Status:** Accepted
**Date:** 2026-05-26

### Context

Phase 4 sub-system 3 ships calibration measurement (eval/calibration/). The reliability calculation requires partitioning predicted confidences in [0, 1] into bins and computing per-bin empirical accuracy. The binning choice has consequences for Expected Calibration Error (ECE) and Maximum Calibration Error (MCE) interpretation.

### Options considered

- **Equal-width bins.** Partition [0, 1] into M equal-width intervals (10 intervals of width 0.1 by default). Simple, interpretable; bins with low confidence range can have few or zero observations.
- **Equal-frequency bins.** Partition observations into M groups of equal sample size (quantile bins). Each bin has roughly the same observation count, improving statistical reliability of per-bin metrics; bin widths vary, making the reliability diagram harder to interpret.
- **Adaptive binning.** Choose binning per-dataset to optimize some criterion. Defensible for research; less defensible for audit (the binning depends on the data).

### Decision

Equal-width bins with M=10 as the default. eval/calibration/CalibrationScorer.compute_calibration() partitions confidence scores in [0, 1] into 10 intervals of width 0.1. The reliability diagram shows mean confidence vs empirical accuracy per bin.

Three properties this supports:

- **Interpretability.** A reviewer reading the reliability diagram sees fixed bin widths matching natural confidence intervals. "The 0.8-0.9 bin has 85% empirical accuracy" is directly readable.
- **Stability across datasets.** The same bins apply across datasets and across time. Calibration drift detection (a Phase 5 deliverable) compares apples to apples.
- **Audit defensibility.** Equal-width is the standard textbook choice (Niculescu-Mizil & Caruana 2005, Guo et al. 2017). Auditors familiar with calibration literature recognize it.

Equal-frequency binning is tagged `[deferred-phase-4-followup]` in eval/calibration/README.md. Institutions with severely imbalanced confidence distributions may want quantile bins; the framework will support it as a flag, not the default.

The bin count M is configurable (the CalibrationScorer constructor accepts a `bin_count` parameter). 10 is the default; 5-15 is the practical range. Below 5 the metric is too coarse; above 15 the per-bin observation count drops.

### Consequences

- ECE and MCE values are interpretable against the standard textbook formulation.
- Bins at the extremes (0-0.1, 0.9-1.0) may have few observations when the agent rarely produces extreme confidences. Reported in the per-bin observation count alongside metrics so reviewers can identify low-N bins.
- The framework's calibration story is comparable to other AI evaluation literature.

### Reconsider when

- Empirical evidence shows equal-frequency produces materially better drift detection for the framework's specific confidence distributions.
- A specific regulator standardizes on a different binning method.

### Framework coverage

- **NIST AI RMF**: Measure function. Standardized calibration measurement supports reliability of the measurement.
- **EU AI Act**: Article 15 (accuracy). Calibration is part of the accuracy posture.
- **OSFI E-23**: Model validation. Calibration measurement supports validation expectations.
- **SOX ICFR**: Measurement reliability. Standardized binning supports reproducibility of calibration claims across audits.

---

## ADR-018: Per-Example Error Isolation in Eval Runners

**Status:** Accepted
**Date:** 2026-05-26

### Context

The eval harnesses (eval/runner.py for graded examples, eval/attacks/runner.py for prompt-injection attacks) process datasets of N examples. When an exception is raised on example K, the harness must decide whether to abort the entire run or isolate the failure and continue.

This is a small decision but it has consequences for the audit story and for the framework's usability on imperfect datasets.

### Options considered

- **Abort on first error.** One malformed example causes the whole run to fail with that example's exception. Strict but unusable on real-world datasets where one corrupt entry should not invalidate the rest of the evaluation.
- **Per-example error isolation.** Each example runs in a try/except; an exception on example K is captured as an EvalError record and the run continues. The final report distinguishes successful examples (with metrics) from errored examples (with the exception type and message).
- **Silent skip.** Errored examples are silently dropped; the report shows N-1 successful examples with no indication that one was dropped. Worst audit story; the run looks complete but is not.

### Decision

Per-example error isolation. eval/runner.py's TriageEvalRunner.run() catches exceptions per example and records them as EvalError instances in the report. The aggregate metrics (TierAccuracy, DispositionAccuracy, JointAccuracy) compute against successful examples only; the error count is reported separately.

Two properties this preserves:

- **Run-level completeness.** A 1000-example dataset with 3 malformed entries produces a report on 997 examples plus a documented 3-example error set. The auditor sees both.
- **Per-example error visibility.** Errors are not silent. The error record names the example_id, the exception type, and a truncated traceback for debugging. A dataset with widespread errors is visible at a glance.

The attack runner (eval/attacks/runner.py) applies the same pattern: each attack is graded individually; an unexpected exception on attack K is captured as a `harness_error` outcome distinct from the pass/fail outcomes.

### Consequences

- The framework is usable on imperfect datasets. Real-world graded datasets sometimes contain malformed entries; one corrupt row does not invalidate the entire run.
- The audit story is improved: error events are first-class in the report. An auditor reviewing eval results sees not just metrics but also the data quality of the run.
- Tests exercise the isolation explicitly (test_runner.py::test_error_isolation_does_not_abort_run) to ensure the pattern remains in place as the runners evolve.
- A run with mostly errors (a misconfigured dataset, for example) still completes; the metrics are computed over the tiny successful subset and the error count makes the misconfiguration obvious.

### Reconsider when

- Specific deployment context requires fail-fast behavior (a CI pipeline that wants any error to fail the build). The institution can layer their own assertion that error_count == 0 after the run.
- A specific error pattern indicates a fundamental harness bug rather than a data issue; isolating it just delays diagnosis. Distinguishing harness bugs from data bugs is a Phase 5 concern.

### Framework coverage

- **NIST AI RMF**: Measure function. Robust measurement methodology supports reliability.
- **EU AI Act**: Article 17 (quality management). Robust evaluation harness supports the QMS.
- **OSFI E-23**: Model validation. Resilient validation infrastructure supports validation discipline.
- **SOX ICFR**: Measurement infrastructure. Robust measurement supports reliability of control evaluation.

---

## Deferred decisions

The following decisions are real architectural questions the Vendor Risk Triage gate will eventually need to answer. They are deferred because the answer depends on work that has not yet happened, or because the decision is intentionally left to the deploying institution.

**Output validation mechanism (resolved by ADR-007).** Originally listed as deferred to Phase 3. Phase 3 sub-system 2 adopted PydanticAI, which enforces structured output via the Pydantic-typed _TriageClassification output model. The mechanism is documented in ADR-007.

**Confidence score calibration (partially resolved by Phase 4 sub-system 3).** Phase 4 sub-system 3 (eval/calibration/) ships the calibration measurement: Brier, ECE, MCE, reliability bins, and three correctness dimensions (tier, disposition, both). The mechanism is in place. HITL routing thresholds remain institutional configuration; the framework provides the calibration data, deploying organizations select thresholds appropriate to their risk posture.

**Incidental PII detection mechanism.** The privacy spec (docs/phase-1/04-privacy-and-data-handling.md) names the available approaches (pattern matching, NER, LLM-based classification, commercial DLP, hybrid) and requires specific behaviors (detection at intake, every failure logged, redaction or rejection). The mechanism remains the institution's choice. The reference library does not include PII detection; the institution's deployment wires PII detection into the intake transport before invoking the library.

**Specific retention period for the reference deployment.** The privacy spec requires retention to be explicit but leaves the period to the deploying institution. Per ADR-008, the reference library does not persist records; retention is the institution's storage layer's concern.

**Cross-region and multi-adapter failover.** The architecture does not include failover at the reference level. Institutional extensions may add it. PydanticAI's Model abstraction (per ADR-007) supports the swap.

**Audit-log shipping format.** Originally implied in Phase 4's "Governance Artifacts" framing; deferred to Phase 5 (Operational Hardening). The library produces TriageRecords conforming to the output contract; the audit-log shipping format describes how a collection of records, dataset hashes, eval reports, and corpus content_hashes are bundled for regulator handoff.

**Multi-tenant corpora.** Different deploying organizations index different regulation selections. Deferred to Phase 5. The framework's Embedder Protocol and Retriever abstraction support multi-tenant patterns; the bundling and access-control layer is Phase 5 work.

---

## Adding new ADRs (for forks)

When you fork this framework and make architectural decisions that diverge from the reference implementation, add an ADR documenting your decision. Use the format above. Maintain the framework coverage discipline: each ADR maps to at least NIST AI RMF, EU AI Act, OSFI E-23, and SOX ICFR where applicable to your context.

If your decision supersedes one of the ADRs in this document, mark the original as Superseded by your new ADR identifier and reference the new decision.

## Status

Phase 2 (Architecture & Threat Model) of the sitkastack Framework, complete as of May 24, 2026. Updated May 26, 2026 to add ADR-007 through ADR-018 documenting all Phase 3 and Phase 4 architectural decisions. All five Phase 2 artifacts (problem definition, system architecture, trust boundaries, threat model, and architecture decisions) are published.

## Author

Robyn Toor. Fifteen years shipping programs in fintech and SaaS, including fintech operating roles where vendor risk decisions came across my desk.
