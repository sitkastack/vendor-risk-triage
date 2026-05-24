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

## Deferred decisions

The following decisions are real architectural questions the Vendor Risk Triage gate will eventually need to answer. They are deferred because the answer depends on work that has not yet happened, or because the decision is intentionally left to the deploying institution.

**Output validation mechanism (tool use vs JSON mode vs constrained generation).** ADR-001 commits to a provider-agnostic interface; each provider adapter chooses its own mechanism for producing output that conforms to docs/phase-1/03-output-contract.md. The reference Claude adapter's specific mechanism is decided when the agent build begins in Phase 3.

**Confidence score calibration and HITL routing thresholds.** Phase 1 specifies that confidence calibration is a Phase 3 (Build & Eval) concern. Specific HITL routing thresholds depend on calibrated confidence scores against a representative evaluation set. Both are deferred to Phase 3.

**Incidental PII detection mechanism.** The privacy spec (docs/phase-1/04-privacy-and-data-handling.md) names the available approaches (pattern matching, NER, LLM-based classification, commercial DLP, hybrid) and requires specific behaviors (detection at intake, every failure logged, redaction or rejection). The mechanism is the institution's choice.

**Specific retention period for the reference deployment.** The privacy spec requires retention to be explicit but leaves the period to the deploying institution. The reference deployment's specific number is set when the reference institution publishes its retention policy alongside the running system.

**Cross-region and multi-adapter failover.** The architecture does not include failover at the reference level. Institutional extensions may add it.

---

## Adding new ADRs (for forks)

When you fork this framework and make architectural decisions that diverge from the reference implementation, add an ADR documenting your decision. Use the format above. Maintain the framework coverage discipline: each ADR maps to at least NIST AI RMF, EU AI Act, OSFI E-23, and SOX ICFR where applicable to your context.

If your decision supersedes one of the ADRs in this document, mark the original as Superseded by your new ADR identifier and reference the new decision.

## Status

Phase 2 (Architecture & Threat Model) of the sitkastack Framework, in progress as of May 24, 2026. This architecture decisions document publishes alongside the Phase 2 problem definition. The system architecture, trust boundaries, and threat model documents are in active drafting.

## Author

Robyn Toor. Fifteen years shipping programs in fintech and SaaS, including fintech operating roles where vendor risk decisions came across my desk.
