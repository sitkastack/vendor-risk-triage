# Phase 2: Problem Definition

An auditor lands on your AI implementation. They want the architecture document. The threat model. The trust boundary documentation. The design decision records that show how this system was built. Can you produce them?

If those documents don't exist in advance, here's what happens instead. The architecture is reconstructed from code reading during examination. The threat model is backfilled after the first incident. The trust boundary is whatever the auditor can infer from a network diagram.

Phase 2 inverts the order. Architecture and threat model are written before implementation. The documents become the design record from the start.

## Reading this

This document and the four others in Phase 2 are written for operators implementing AI systems in regulated environments who need architecture and threat model documentation that holds up under audit. The artifacts are intended to be forked, adapted to a specific regulatory context, and committed to your repository alongside the implementation they document.

## What Phase 2 produces and why

**System architecture** (01-system-architecture.md)

Component-level decomposition of the Vendor Risk Triage gate. Most regulated AI implementations have an architecture that lives only in code. OSFI E-23 model risk requirements and SOC 2 Trust Services Criteria both expect institutions to have documented system architecture for AI systems in scope. This artifact produces that document before implementation begins, so the design record matches the code.

**Framework coverage:**
- **OSFI E-23**: model documentation requirements. Architecture documentation is part of the model documentation institutions maintain for federally regulated AI systems.
- **SOX ICFR**: IT general controls. When AI systems support financial reporting, architecture establishes the systems in ICFR scope.
- **EU AI Act**: Article 11 technical documentation for high-risk AI systems. The article explicitly requires architectural descriptions.
- **NIST AI RMF**: Govern function. System inventory and architectural context support organizational accountability requirements.

**Trust boundaries** (02-trust-boundaries.md)

Explicit documentation of what is inside the system's trust boundary and what is outside. AI systems with implicit trust boundaries create ambiguity for auditors and other reviewers trying to verify what the system does and where institutional accountability lies. Documenting boundaries explicitly removes that ambiguity.

**Framework coverage:**
- **OSFI E-23**: third-party model oversight. Trust boundaries identify where third-party AI components sit relative to internal controls.
- **SOX ICFR**: third-party vendor controls. Trust boundaries determine which vendors require SOC 1 or alternative attestations within ICFR scope.
- **EU AI Act**: Articles 25-29 (provider and deployer obligations). Trust boundaries delineate where provider obligations end and deployer obligations begin.
- **NIST AI RMF**: Govern function supply chain risk. Trust boundary documentation makes supply chain risk explicit and assessable.

**Threat model** (03-threat-model.md)

STRIDE-based analysis plus AI-specific threats. The STRIDE categories cover Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, and Elevation of Privilege. The AI-specific class adds prompt injection via untrusted documents, data exfiltration via prompt, model misuse and capability extraction, hallucination accepted without verification, and confidence-score manipulation.

Without a documented threat model, AI mitigations get bolted on retrospectively as incidents reveal each new threat class. The institution then cannot demonstrate it considered the threat surface before deployment. This artifact maps the threat surface before implementation.

**Framework coverage:**
- **NIST AI RMF**: Map function (system context and risk identification). The threat model is core to identifying risks across the AI system lifecycle.
- **EU AI Act**: Article 9 (risk management for high-risk AI systems). The article requires structured risk identification and analysis, which the threat model provides.
- **OSFI E-23**: model risk identification. The threat model contributes to overall model risk assessment for federally regulated AI systems.
- **SOX ICFR**: third-party risk assessment. AI threat surfaces in vendor documents are part of vendor risk assessment within ICFR scope.

**Architecture decisions** (04-architecture-decisions.md)

ADR-style records of design choices. When future maintainers ask why a choice was made (or when an institution is asked to explain its design rationale during examination), the ADRs are the record. They convert undocumented architectural assumptions into defensible decisions. The ADRs document choices made for this reference implementation; forks adapt the form, not necessarily the answer.

**Framework coverage:**
- **NIST AI RMF**: Govern function (accountability for decisions). ADRs document who decided what and why.
- **EU AI Act**: Article 17 quality management system documentation. ADRs are part of the QMS documentation requirements.
- **OSFI E-23**: model governance documentation. ADRs are part of the governance trail for model design decisions.
- **SOX ICFR**: supporting documentation environment. ADRs are not directly required by SOX ICFR, but they provide context for auditors evaluating whether AI-system controls operate as designed.

## What Phase 2 does not cover

The exclusions below are the ones a reader might wrongly expect from this phase. Items that naturally live in later phases (Build, Deploy, Sunset) are skipped here.

**Threat model is not a security audit.** Phase 2 documents the threat surface conceptually. Penetration testing, security control validation, and third-party security review sit downstream in Phase 5 (Deploy & Monitor).

**Architecture decisions are not vendor prescriptions.** The ADRs document choices made for the reference implementation. Forking the framework does not require forking the decisions. The ADR is the form of the decision record, not the answer.

**Trust boundary documentation is not a network security review.** Phase 2 trust boundaries are application-layer constructs mapped to control objectives. Network segmentation, firewall posture, and infrastructure security sit outside this scope.

**Threat coverage is STRIDE plus AI-specific. It is not exhaustive.** Nation-state actor modeling, physical security, supply chain attacks against compiler toolchains, and other advanced threat classes are out of scope. The threat model covers the threats a regulated mid-market operator is realistically going to face and be asked about.

**Architecture diagrams are conceptual, not implementation-level.** Mermaid diagrams show component relationships and data flow. They are not deployment topology diagrams, infrastructure-as-code, or sequence diagrams at the function-call level.

## When Phase 2 is done

These criteria apply to the reference implementation in this repository. Forks adapt the criteria to their own regulatory and architectural context.

Phase 2 is complete when:

- All four artifacts (system architecture, trust boundaries, threat model, architecture decisions) are committed to main.
- Each artifact has been cross-referenced against the Phase 0 risk classification, the Phase 0 out-of-scope boundaries, and the Phase 1 data contracts. Any contradictions identified have been resolved either by editing the contradicting document or by adding an explicit reconciliation note in the affected artifact.
- The architecture diagram in 01-system-architecture.md is rendered as Mermaid, not described in prose.
- The threat model in 03-threat-model.md acknowledges residual risk for at least three identified threats.
- Each artifact maps at least one specific control objective from NIST AI RMF, EU AI Act, OSFI E-23, and SOX ICFR. SOC 2 and ISO 42001 are included where the reference implementation context applies them.

## How Phase 2 connects to other phases

**Inputs from Phase 0 (Discovery & Risk Classification):**

- docs/phase-0/01-risk-classification.md: drives architectural choices including confidence thresholds, HITL requirements, and retention periods
- docs/phase-0/02-out-of-scope.md: defines what decisions the system explicitly does not make, which shapes the threat surface

**Inputs from Phase 1 (Data Contracts & Privacy):**

- docs/phase-1/02-input-contract.md: defines what gets validated at system boundaries, which informs the trust boundary documentation
- docs/phase-1/03-output-contract.md: defines what gets produced, which informs the data flow architecture
- docs/phase-1/04-privacy-and-data-handling.md: informs storage decisions and audit log requirements

**Outputs feeding Phase 3 (Build & Eval):**

- 04-architecture-decisions.md: constrains implementation choices
- 03-threat-model.md: defines what gets tested and red-teamed

**Outputs feeding Phase 4 (Governance Artifacts):**

- 02-trust-boundaries.md: informs what gets documented in model cards and vendor risk artifacts
- 04-architecture-decisions.md: defines the schema for governance artifact templates

## Status

Phase 2 (Architecture & Threat Model) of the sitkastack Framework, in progress as of May 23, 2026. This problem definition publishes ahead of the other four Phase 2 artifacts. The system architecture, trust boundaries, threat model, and architecture decisions documents are in active drafting. Roadmap: sitkastack.com/roadmap.

## Author

Robyn Toor. Fifteen years shipping programs in fintech and SaaS, including fintech operating roles where vendor risk decisions came across my desk.
