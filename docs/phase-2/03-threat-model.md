# Phase 2: Threat Model

STRIDE-based threat analysis, AI-specific threat coverage, and privacy threat coverage for the Vendor Risk Triage gate. Threats target the components named in docs/phase-2/01-system-architecture.md and the boundary crossings named in docs/phase-2/02-trust-boundaries.md. Mitigations reference controls already established in 01, 02, and docs/phase-2/04-architecture-decisions.md.

## Reading this

This document specifies the threat surface a regulated mid-market operator running the gate is realistically going to face and be asked about. It is not an exhaustive security review. Nation-state actors, advanced persistent threats targeting compiler toolchains, and similar high-end threat classes are out of scope. The threat model covers threats relevant to the framework's target customer.

Forks of the framework adapt the threat list to their specific deployment context. Institutions running the gate at higher risk tiers (large bank, critical infrastructure) extend the model with their additional threats. Institutions in lower-stakes contexts may de-prioritize threats that are not material to their use case. The patterns documented here are intended as a defensible reference, not a prescriptive standard.

## Methodology

The threat model uses STRIDE as the general security threat taxonomy and adds AI-specific and privacy categories. STRIDE categories cover the six general computer security threats: Spoofing (claiming a false identity), Tampering (modifying data in transit or at rest), Repudiation (denying an action occurred), Information Disclosure (data reaching unauthorized parties), Denial of Service (preventing legitimate use), and Elevation of Privilege (gaining unauthorized capabilities).

STRIDE alone is insufficient for AI systems. AI threats include attacks that target the model's behavior rather than the surrounding infrastructure: prompt injection, model probing, hallucination relied upon as fact, confidence-score manipulation, discriminatory bias, fairness drift, and classification drift through provider model updates. These threats are documented in a separate AI-specific category to make their AI-system origin explicit.

Privacy threats sit alongside security and AI threats but have a different mitigation profile (institutional privacy office workflows rather than purely technical controls). Documenting them in the threat model makes the privacy obligations and their interaction with the gate's architecture explicit.

Each threat has:
- A threat identifier and name
- A description of the attack
- A target (the specific component from 01-system-architecture.md or boundary crossing from 02-trust-boundaries.md that the attack reaches)
- An impact (what happens if the attack succeeds)
- A mitigation (controls that reduce the threat, referencing established controls where they exist)
- A detection approach (how the threat would be observed if it materializes in production)

Each mitigation is testable. Phase 5 (Deploy and Monitor) specifies the test procedures and audit assertions for each mitigation; this document identifies what is to be tested. The threat structure supports audit assertions in three ways: the target identifies the component or crossing under test; the mitigation identifies the control whose effectiveness is being verified; the detection identifies the indicator that operational monitoring should produce.

Threats are not assigned numerical severity scores. A reference framework cannot accurately score severity without institutional context (which decisions are highest-stakes, what regulatory exposure applies, what the cost of failure is). Qualitative impact statements are provided; institutions adopting the framework apply their own severity scoring in their context.

Residual risks (threats where mitigation is partial and the institution accepts what remains) are documented in a dedicated section at the end.

## STRIDE analysis

### Spoofing

**T-S1: Submitter identity spoofing**

An attacker submits a triage request or revocation request as if they were a legitimate reviewer or authorized automated system, gaining the gate's processing of a fabricated submission.

Target: Crossing 1 (Submitter to Intake Transport).
Impact: A fabricated triage record enters the audit trail with the appearance of legitimacy, potentially supporting a fraudulent vendor approval or improperly revoking a valid record.
Mitigation: Authentication at the API gateway (per 01, 02). The institution's authentication mechanism (API keys, OAuth, SAML, etc., per 02's institutional configuration) is the primary control. Audit logging at the intake transport records who submitted what, supporting post-incident investigation.
Detection: Detection through authentication failure rate anomalies at the API gateway and audit log analysis for repeated submissions from a single authenticated identity producing structurally similar but inconsistent content.

**T-S2: Auditor identity spoofing**

An attacker queries the Audit Query API while pretending to be an authorized auditor, examiner, or program owner.

Target: Crossing 3 (Audit Query API to Auditor).
Impact: Triage records, failed submissions, and revocations are disclosed to an unauthorized party. The Audit Query API is read-only, so the attacker cannot write, but disclosure alone is harmful for sensitive vendor data.
Mitigation: Authentication and authorization at the Audit Query API (per 01). Query audit log records which queries were served and to which authenticated identity, supporting detection of pattern abuse.
Detection: Detection through the Audit Query API's query log analysis. Anomalous query volumes from a given authenticated identity, queries outside typical access patterns, or queries from identities not associated with active auditor roles.

**T-S3: LLM provider endpoint spoofing**

An attacker presents a forged LLM provider endpoint (DNS poisoning, certificate compromise, proxy interception) to the LLM Provider Adapter, returning fabricated responses.

Target: Crossing 2 (LLM Provider Adapter to LLM Provider).
Impact: The Classification Logic processes responses from an attacker rather than the legitimate provider. Triage records reflect the attacker's chosen classification rather than the provider's actual inference.
Mitigation: TLS certificate validation in the adapter (standard practice). Provider endpoint configuration as deployment infrastructure (institutional), with the institution's network monitoring catching anomalous endpoints. The Output Validator constrains responses to schema-conforming output, but an attacker constructing schema-valid responses bypasses the validator.
Detection: Detection through TLS certificate fingerprint monitoring at the LLM Provider Adapter and provider endpoint anomaly detection (response latency patterns, response content patterns that deviate from established provider baselines).

**Framework coverage for Spoofing:**
- **NIST AI RMF**: Govern function. Identity and authentication are part of the system's accountability posture.
- **EU AI Act**: Article 15 (accuracy and robustness). Spoofing defeats robustness; documented mitigations support the article's requirements.
- **OSFI E-23**: Model input governance. Authenticated submitters are part of model input integrity for federally regulated institutions.
- **SOX ICFR**: Control reliability. Authentication on inputs and queries is part of standard IT general controls within ICFR scope.

### Tampering

**T-T1: Submission tampering in transit**

An attacker intercepts and modifies a triage submission or revocation request between submitter and intake transport, altering the documentation content or revocation reason.

Target: Crossing 1 (Submitter to Intake Transport).
Impact: The gate processes content other than what the submitter intended, producing a triage record based on tampered evidence.
Mitigation: TLS at transport prevents in-transit tampering for properly configured connections. Authentication at the API gateway ensures the request is from a known sender. The schema validation at the Input Validator catches structural tampering but not semantic content changes within valid fields.
Detection: Detection through schema validation failure rate spikes. Tampered submissions typically produce structural anomalies before semantic ones; sustained spikes in validation errors from a given source warrant investigation.

**T-T2: Inference traffic tampering in transit**

An attacker intercepts and modifies the inference request to the LLM provider or the response from the provider, altering what the Classification Logic sees.

Target: Crossing 2 (LLM Provider Adapter to LLM Provider).
Impact: The Classification Logic processes a request or response that was not what either party intended. The triage record reflects the tampered content.
Mitigation: TLS at transport prevents in-transit tampering for properly configured connections (mTLS optional where institutionally configured). Provider contract terms address request integrity (per ADR-001). The two-layer untrust of provider responses (per 02) limits the impact of response tampering to whatever an attacker can express within the response schema.
Detection: Detection through response anomaly monitoring. Provider responses that systematically deviate from established statistical patterns (response length distribution, confidence score distribution, rationale structure) may indicate tampering.

**T-T3: Agent code or prompt tampering at the source**

An attacker compromises the codebase or the build pipeline, introducing modified prompts, modified classification logic, or modified validators that produce systematically biased outputs.

Target: Classification Logic, Input Validator, Output Validator (per 01).
Impact: The gate produces incorrect triage records over an extended period. The agent_version (git commit SHA per ADR-003) reflects the compromised code, so reproducibility against the same compromised code is possible but does not catch the compromise itself.
Mitigation: Standard source control hygiene (signed commits, mandatory code review, protected main branch). Build pipeline integrity (deterministic builds, signed artifacts). The git commit SHA in agent_version supports forensic reconstruction once the compromise is identified, but does not prevent it. This threat is largely deployment infrastructure and engineering practice, not architectural; the framework documents it as residual risk for institutions to manage.
Detection: Detection through standard source control and build pipeline monitoring. Unsigned commits to main branch, build pipeline anomalies, deployment of unexpected code versions. The agent_version captured in records supports post-hoc reconciliation against expected versions.

**Framework coverage for Tampering:**
- **NIST AI RMF**: Manage function (integrity controls) and Govern function (source code governance).
- **EU AI Act**: Article 15 (accuracy and robustness) and Article 17 (quality management system for high-risk AI).
- **OSFI E-23**: Model integrity. Source-controlled and tamper-evident model deployment is part of model governance.
- **SOX ICFR**: Change management. Source control and build pipeline integrity map to ICFR change management requirements.

### Repudiation

**T-R1: Reviewer denying override or revocation action**

A compliance reviewer who triggered an override or revocation later denies having done so, claiming the action was unauthorized or fraudulent.

Target: HTTP REST Intake (per 01), specifically the override and revocation paths.
Impact: An action recorded against a reviewer's identity is disputed, undermining the audit trail's evidentiary weight.
Mitigation: Authentication at the intake transport binds each submission to an authenticated identity. Audit logging records the authenticated identity, timestamp, and request content. The Revocations store records revoked_by (institutional addition beyond contract fields). The combination of authenticated request, server-side log, and storage marker creates non-repudiation evidence.
Detection: Detection is reactive. When a reviewer disputes an action, the audit log is consulted to confirm the authenticated identity, timestamp, and request content at the time of the action.

**T-R2: LLM provider repudiation of processing**

The LLM provider denies having processed a particular request, or denies the response that was received, complicating reconstruction of how a decision was reached.

Target: Crossing 2 (LLM Provider Adapter to LLM Provider).
Impact: Triage records that reference the provider's inference cannot be independently corroborated by the provider. Audit reconstruction depends on the gate's records alone.
Mitigation: Provider contract terms include processing logs accessible to the institution (per ADR-001 provider selection criteria). The agent_version (git SHA) captures what code made the request. The triage record captures the request structure and the response content as part of the rationale field. The combination supports reconstruction from the gate's own records, reducing dependence on provider acknowledgment.
Detection: Detection through provider log reconciliation. Periodic comparison of the gate's claimed provider calls against the provider's billing or usage logs identifies discrepancies.

**Framework coverage for Repudiation:**
- **NIST AI RMF**: Govern function. Non-repudiation supports accountability.
- **EU AI Act**: Article 12 (record-keeping) and Article 17 (quality management). Non-repudiable records support both.
- **OSFI E-23**: Model audit trail. Reproducibility against authenticated actions supports the audit trail integrity expectation.
- **SOX ICFR**: Evidence integrity. Non-repudiable actions are part of evidence reliability.

### Information Disclosure

**T-I1: Excessive disclosure to LLM provider**

The gate sends more content to the LLM provider than is necessary for classification, including PII or vendor-confidential material that the submission did not require for triage.

Target: Crossing 2 (LLM Provider Adapter to LLM Provider).
Impact: Information that should have stayed within the gate's boundary is processed by the provider. Even with zero data retention (per ADR-001), the in-flight exposure is real and may violate institutional data minimization commitments.
Mitigation: The Phase 1 privacy spec requires minimization at intake. PII detection at the Normalization-to-Input-Validator stage removes incidental PII. The input contract restricts what fields the gate processes; documentation_artifacts content is not parsed (per 01). The institution's data classification policy informs what is acceptable to send to the provider.
Detection: Detection through the PII detection step's incident logs. Spikes in incidental PII reaching the validator stage indicate either submission-side PII bleed-through or detection-side gaps.

**T-I2: System prompt extraction via responses**

A submitter crafts content designed to elicit the LLM's system prompt or other internal state in the response, then captures it from the returned triage record's rationale field.

Target: Classification Logic, LLM Provider Adapter (per 01).
Impact: The institution's proprietary classification prompts are disclosed. While the prompts may not be highly sensitive, their disclosure aids attackers in crafting subsequent prompt injection attacks (T-AI1).
Mitigation: The Output Validator constrains the rationale field to schema-conforming content (per ADR-004). Specific guardrails against system prompt leakage in responses are deferred to Phase 3 implementation (prompt engineering and structured output enforcement). This threat has partial mitigation; residual risk is documented below.
Detection: Detection through response content analysis. Triage records containing rationale content that matches system prompt patterns or refers to operational instructions indicate possible prompt leakage.

**T-I3: Cross-vendor information leakage via prior records**

A submission references prior_triage_record_id for a different vendor (legitimately or fraudulently), and the response includes information from that prior record.

Target: Classification Logic, Audit Query API (per 01).
Impact: One vendor's information is disclosed in another vendor's triage context.
Mitigation: The Classification Logic does not use prior_triage_record_id to fetch other-vendor records; the field is for supersession within the same vendor's history. The Audit Query API's authorization controls (institutional configuration) restrict cross-vendor access. The check is enforced at query time, not at inference time, so a compromised query API path could disclose; the broader mitigation is the read-only API surface limiting the impact.
Detection: Detection through cross-record content matching. Triage records that reference other vendors' identifiers, names, or specific content in their rationale fields suggest cross-vendor leakage.

**Framework coverage for Information Disclosure:**
- **NIST AI RMF**: Map and Govern functions. Data classification and supply chain disclosure controls.
- **EU AI Act**: Article 10 (data and data governance) and GDPR overlay.
- **OSFI E-23**: Data confidentiality and third-party data handling.
- **SOX ICFR**: Confidentiality of records supporting financial reporting.

### Denial of Service

**T-D1: Resource exhaustion via oversized or volume submissions**

An attacker submits very large or very many submissions, exhausting the gate's processing capacity or LLM provider rate limits, denying service to legitimate submitters.

Target: HTTP REST Intake, LLM Provider Adapter (per 01).
Impact: Legitimate triage submissions are delayed or rejected. Vendor onboarding throughput drops.
Mitigation: Rate limiting at the API gateway (institutional infrastructure). Schema validation rejects oversized submissions through input contract constraints (per ADR-004). LLM provider rate limits cap downstream impact. Idempotency at intake (per 01) prevents simple duplicate-flood attacks from creating amplified load.
Detection: Detection through API gateway metrics. Request rate spikes, submission size distribution shifts, and latency anomalies are leading indicators of resource exhaustion attacks.

**T-D2: LLM provider outage cascading to gate**

The LLM provider experiences an outage or performance degradation, blocking all classification work at the gate.

Target: Crossing 2 (LLM Provider Adapter to LLM Provider).
Impact: The gate cannot complete triage submissions during the outage. Vendor onboarding stops.
Mitigation: The provider-agnostic interface (per ADR-001) supports adding fallback adapters as an institutional extension; the reference implementation does not include automatic failover. Provider SLAs (per ADR-001 provider contract) bound outage duration. Submission backpressure is handled by the synchronous HTTP REST default (per 01); long outages produce timeouts that submitters can retry once the provider recovers. This threat has partial mitigation; residual risk is documented below.
Detection: Detection through provider call latency and success rate monitoring. Sustained degradation patterns at the LLM Provider Adapter indicate provider-side issues regardless of provider acknowledgment.

**Framework coverage for Denial of Service:**
- **NIST AI RMF**: Manage function. Operational resilience controls.
- **EU AI Act**: Article 15 (accuracy and robustness). Operational availability is part of robustness.
- **OSFI E-23**: Operational risk management.
- **SOX ICFR**: Availability of controls supporting financial reporting.

### Elevation of Privilege

**T-E1: Read-to-write privilege escalation via Audit Query API**

An attacker exploits a vulnerability in the Audit Query API (injection, deserialization, authorization bypass) to gain write access to underlying storage.

Target: Audit Query API, Triage Records / Failed Submissions / Revocations stores (per 01).
Impact: An attacker could fabricate, modify, or delete records, undermining the integrity of the audit trail.
Mitigation: The Audit Query API is read-only at the architectural level (per 01); no UPDATE or DELETE methods exist. The database role used by the Audit Query API has no write permissions on records (per ADR-005). Even a successful API-level compromise cannot escalate to writes because the database role lacks the required permissions. This is defense-in-depth: code-level read-only enforcement plus database role-level read-only enforcement.
Detection: Detection through database role privilege audits. Regular review of role permissions confirms UPDATE and DELETE remain ungranted to the audit role. Database audit logs of permission changes capture attempts to grant them.

**T-E2: Application role privilege escalation**

An attacker compromises the gate's application code or runtime, and uses the application role's database connection to attempt UPDATE or DELETE on records.

Target: Triage Records, Failed Submissions, Revocations stores (per 01, ADR-005).
Impact: If successful, records could be modified or deleted, undermining the append-only invariant.
Mitigation: The application role has INSERT only (per ADR-005); UPDATE and DELETE are not granted. The database enforces this regardless of what the application code attempts. The compromise is contained: the attacker is limited to inserting new records, which appear as additional history rather than modifications to existing records. Subsequent audit review identifies anomalous insertions.
Detection: Detection through anomaly monitoring on the records table. INSERT volume spikes outside expected ranges or insertions from unexpected source addresses indicate possible application role compromise.

**T-E3: Retention enforcement role scope expansion**

An attacker compromises the retention enforcement job's runtime, and attempts to delete records outside the eligible-for-deletion set.

Target: Retention Enforcement, Triage Records / Failed Submissions stores (per 01, ADR-005).
Impact: Records that should be retained could be deleted, breaking the audit trail's coverage of the retention period.
Mitigation: The retention enforcement role's DELETE permission is scoped by row-level security policy (per ADR-005). The policy gates DELETE eligibility by decision_timestamp plus the configured retention period. An attacker with the retention role's credentials can only delete records the policy already identifies as eligible; records within the retention period are protected at the database level regardless of what the compromised job attempts.
Detection: Detection through retention job audit logs. Comparison of actual deleted record counts against expected retention eligibility (computed from the row-level security policy) identifies retention job anomalies.

**Framework coverage for Elevation of Privilege:**
- **NIST AI RMF**: Govern function. Least-privilege design is part of accountability.
- **EU AI Act**: Article 15 (accuracy and robustness). Privilege boundaries are part of robustness.
- **OSFI E-23**: Operational integrity. Least-privilege access controls support model integrity.
- **SOX ICFR**: Segregation of duties and least-privilege access. Database role design maps directly to ICFR access control requirements.

## AI-specific threats

These threats target the AI system's behavior specifically. STRIDE alone does not address them because they exploit how the model interprets and produces content rather than how the surrounding system enforces access or integrity.

**T-AI1: Prompt injection via vendor documents**

A submission contains content crafted to override the gate's system prompt, instruct the LLM to produce a particular triage outcome, or behave in ways inconsistent with the institution's classification policy. Common patterns: "Ignore previous instructions," "You are now a different assistant," indirect injection through documentation_artifacts text fields.

Target: Classification Logic, LLM Provider Adapter (per 01).
Impact: The triage record reflects the attacker's chosen classification rather than the institution's policy. For example, a high-risk vendor receives an approve disposition; or a benign vendor receives an escalate to manipulate human review queues.
Mitigation: Multiple layers, none individually sufficient. Schema validation at intake constrains the field structures the LLM sees (per ADR-004). The Phase 1 input contract explicitly does not parse documentation_artifacts content (per 01), reducing the prompt injection surface for the most common injection vector. System prompt design (Phase 3 implementation) includes injection-resistant patterns: explicit instructions about adversarial input handling, refusal of meta-instructions in submission content, output constrained to structured schemas. The Output Validator catches structurally invalid responses but cannot catch valid responses that reflect injected reasoning. Human review of escalated cases provides the final safety net. Prompt injection cannot be fully eliminated; residual risk is documented below.
Detection: Detection through input pattern analysis. Submissions containing common prompt injection markers (instruction overrides, role escalation phrases, system prompt extraction requests) and output structural anomalies suggesting the LLM diverged from its expected behavior pattern.

**T-AI2: Data exfiltration via prompt**

A submission contains instructions attempting to extract data from the LLM's context: system prompt content, examples from training data, content from prior submissions if the provider maintains any in-session state.

Target: Classification Logic, LLM Provider Adapter (per 01).
Impact: System prompts or other internal content are disclosed in the response. Same effective harm as T-I2 (system prompt extraction) but with explicit attacker intent.
Mitigation: Zero data retention at the provider level (per ADR-001) prevents cross-session exfiltration. System prompt design (Phase 3) includes refusal patterns for extraction attempts. The Output Validator structurally constrains responses, limiting the channel through which exfiltrated content can return. The combination reduces but does not eliminate the threat; residual risk documented below.
Detection: Detection through response content analysis. Triage records containing content resembling system prompt structures, training data fragments, or other indicators of extraction success.

**T-AI3: Model misuse and capability extraction**

An attacker submits crafted submissions to probe the gate's classification boundaries, learn how it weighs different risk dimensions, and build a model of its behavior that supports subsequent attacks or vendor positioning.

Target: Classification Logic, LLM Provider Adapter (per 01).
Impact: Attacker learns enough about classification logic to craft borderline submissions that game outcomes. The reference implementation's classification logic is public (the framework is open-source), reducing the value of this attack against the framework itself; the institution-specific prompts and policies remain protected.
Mitigation: The framework's openness paradoxically helps: when classification logic is publicly known, attackers cannot gain advantage by reverse-engineering it. The institution-specific prompts (which encode the institution's specific risk policies) are private; protecting those is part of code and configuration management. Rate limiting at intake bounds the rate of probing. The Audit Query API does not expose other vendors' triage logic.
Detection: Detection through volume and pattern analysis. High submission rates from the same source with subtle systematic variations consistent with probing behavior; unusual diversity in submission content from a single source.

**T-AI4: Hallucination accepted without verification**

The LLM fabricates plausible-sounding content (regulatory citations, vendor capabilities, risk dimensions) that the Classification Logic includes in the triage record without independent verification. A human reviewer relying on the record makes a decision based on fabricated facts.

Target: Classification Logic, Output Validator (per 01); the triage record itself.
Impact: A triage record contains fabricated facts. Human reviewer trusts the record and acts on the fabrication. Regulatory citation in the record points to non-existent provisions.
Mitigation: Confidence-gated HITL routing (per 01 deferred to Phase 3) escalates lower-confidence decisions to human review. The output contract requires rationale to be specific and reviewable; vague or formulaic rationales are caught at output validation or human review. Institution-specific evaluation in Phase 3 (Build and Eval) tests for hallucination patterns and tunes prompts to reduce them. Hallucination cannot be fully eliminated in current LLMs; residual risk documented below.
Detection: Detection is reactive (reviewer flags fabrication) and proactive (sampling audits, automated fact-checking against known facts for regulatory citation patterns, periodic evaluation against held-out test sets to measure hallucination rates).

**T-AI5: Confidence-score manipulation**

A submission is crafted to influence the LLM's confidence score such that the triage record bypasses HITL routing thresholds, either keeping a high-risk case from human review or escalating a low-risk case to consume reviewer capacity.

Target: Classification Logic, confidence-gated routing (deferred to Phase 3 per 01).
Impact: HITL routing is bypassed when it should engage, or engaged when it should not. The institution's review queue is mistargeted.
Mitigation: Confidence calibration is a Phase 3 concern (per 01 deferred). Calibration testing on a representative evaluation set establishes that confidence scores correlate with correctness; calibration drift detection in production catches when the relationship weakens. Threshold tuning is institutional configuration; institutions periodically review whether thresholds still serve their risk posture. The institution's program owner retains visibility into the routing distribution through the Audit Query API; sudden distribution shifts are observable.
Detection: Detection through confidence score distribution monitoring. Sudden shifts in the distribution of confidence scores across submissions, or anomalous correlations between confidence and submission characteristics (such as consistently high confidence on borderline cases), indicate manipulation.

**T-AI6: Discriminatory output bias**

The LLM systematically produces different classifications for vendors with characteristics correlated with protected categories (small business size, geographic distribution, ownership demographics, language patterns indicating non-English-native preparation, etc.), even when objective risk dimensions are equivalent.

Target: Classification Logic, LLM Provider Adapter (per 01).
Impact: Vendors are systematically disadvantaged based on characteristics that should not affect risk classification. The institution may face discrimination complaints, regulator inquiries, or contract challenges from affected vendors.
Mitigation: Phase 3 evaluation includes bias testing against vendor categories of concern. The reference framework provides bias evaluation suites for the institution to adapt to their context. The institution's vendor diversity policy and procurement governance provide upstream controls. Output rationale review by human reviewers catches some bias patterns; the structured rationale field (per the output contract) supports systematic post-hoc review. Bias cannot be fully eliminated; residual risk documented below.
Detection: Detection through output distribution analysis across vendor categories. Periodic bias audits comparing classification rates, dispositions, and rationale patterns across vendor types of concern. Reviewer escalation when systematic patterns emerge.

**T-AI7: Fairness drift over vendor distribution**

The vendor population the gate processes changes over time (new vendor types, new geographies, new business models). The LLM's classification behavior on the new population may degrade relative to its behavior on the original population, producing systematically different outcomes for new vendor types.

Target: Classification Logic, LLM Provider Adapter (per 01).
Impact: Newly common vendor types receive systematically different treatment than the vendors the system was originally tuned for. Fairness is compromised across the shifting distribution.
Mitigation: Phase 3 evaluation includes representative sampling of the current vendor population, not just the original test set. Periodic re-evaluation when the institution's vendor mix shifts materially. The agent_version (git SHA per ADR-003) captures when prompt or code changes were made; comparison of pre-change and post-change classification rates supports drift detection.
Detection: Detection through periodic classification distribution analysis. Shifts in tier and disposition distributions over time, especially when correlated with shifts in vendor characteristic distributions, indicate fairness drift.

**T-AI8: Classification drift through provider model updates**

The LLM provider updates the underlying model (silent updates, version transitions, deprecations) and the gate's classification behavior changes without any code change at the institution. Triage records produced on date X against model version Y may differ systematically from records produced on date X+30 against model version Y'.

Target: Classification Logic, LLM Provider Adapter, LLM Provider (per 01, Crossing 2 per 02).
Impact: Classification consistency degrades across the provider's model lifecycle. Vendors triaged in different periods may receive different classifications for equivalent inputs. Audit reconstruction is complicated because the upstream model version may not be discoverable post-hoc.
Mitigation: ADR-001 selects providers based partly on model versioning transparency. Provider contract terms specify model version pinning where available (Anthropic's API supports model version specification per ADR-001). The agent_version captures the deployed code SHA but not the upstream model; institutions configure provider model version explicitly to capture it. Phase 3 evaluation re-runs the suite when the provider announces material changes. Records may carry a deployment_metadata field (institutional addition beyond the contract) recording the provider model version at time of inference.
Detection: Detection through provider change notifications (institutional subscription to provider release notes), periodic re-evaluation against held-out test sets (classification rates that drift on stable inputs indicate upstream changes), and statistical monitoring of confidence distributions and rationale patterns over time.

**Framework coverage for AI-specific threats:**
- **NIST AI RMF**: Manage function (AI risk monitoring), Measure function (AI behavior measurement), and Map function (bias and fairness identification). AI-specific threats require AI-specific measurement.
- **EU AI Act**: Article 9 (risk management for high-risk AI systems), Article 10 (data governance with fairness implications), and Article 15 (accuracy and robustness). All three encompass AI-specific threat management.
- **OSFI E-23**: Model risk management. AI-specific threats are model risk; identification and mitigation are part of E-23 expectations.
- **SOX ICFR**: When AI supports financial reporting, AI-specific threats affect the reliability of controls operating through the AI; mitigation is part of ICFR control design.

## Privacy threats

These threats target the privacy obligations of the institution operating the gate. They sit alongside the security threats (STRIDE) and AI-specific threats above, but their mitigation profile is institutional process (privacy office workflows) rather than purely technical. The Phase 1 privacy spec (docs/phase-1/04-privacy-and-data-handling.md) establishes the privacy obligations and data handling rules; this section makes explicit the threats those obligations create when interacting with the gate's architecture.

**T-P1: Data subject access request conflict with audit trail retention**

A vendor or vendor representative submits a data subject access request (under GDPR Article 15, PIPEDA, or equivalent privacy law) for personal information processed by the gate. The audit trail retention requirements (multi-year per institutional retention policy) and the data subject's request for disclosure interact in ways the architecture must support.

Target: Triage Records store, Failed Submissions store (per 01).
Impact: Without explicit handling, the institution faces a regulatory conflict: either deny the access request (privacy law violation) or modify records in a way that breaks the audit trail's immutability.
Mitigation: The append-only storage (per ADR-005) supports the access request without modifying records: the data subject can receive a copy of what was processed without the records being changed. The institution's privacy office manages the response, drawing on the Audit Query API to extract relevant records for disclosure. The architecture does not require modification of records for compliance.
Detection: Detection through standard privacy office workflow. Access requests are received and routed; the institution tracks request volume and response time as part of privacy compliance metrics.

**T-P2: Right to erasure conflict with append-only storage**

A vendor exercises a right to erasure (GDPR Article 17, equivalent in other jurisdictions) requesting that their data be deleted. Append-only storage with multi-year retention does not delete records on demand.

Target: Triage Records store, Failed Submissions store, Revocations store (per 01).
Impact: Without explicit handling, the institution faces a conflict between privacy law (erasure obligation) and regulatory retention (audit trail requirement). The institution must either violate one or document why the other is exempt.
Mitigation: GDPR Article 17 includes exemptions for records required for legal compliance (Article 17(3)(b)). Regulated AI audit trail retention typically qualifies. The institution's privacy office and compliance function document the exemption and respond to erasure requests with a structured denial citing the legal obligation. The append-only storage supports this response by not making erasure technically straightforward; the policy decision is made deliberately rather than by deletion default.
Detection: Detection through standard privacy office workflow. Erasure request volume and outcome (granted or denied with documented exemption) is tracked as part of privacy compliance reporting.

**T-P3: Cross-border transfer threat at Crossing 2**

The LLM provider processes inference requests in regions outside the institution's primary jurisdiction. Personal information or vendor-confidential data crosses borders during processing. The cross-border transfer mechanism (GDPR Chapter V, equivalent in other jurisdictions) governs the legality of the transfer.

Target: Crossing 2 (LLM Provider Adapter to LLM Provider, per 02).
Impact: Cross-border transfers without proper legal mechanism create privacy law violations. EU data crossing to US processing requires adequacy decisions or standard contractual clauses; similar mechanisms apply in other jurisdictions.
Mitigation: ADR-002 specifies the region strategy with cross-region inference caveats. The institution's privacy office establishes the legal mechanism (standard contractual clauses with the provider, transfer impact assessment, etc.). The region configuration per ADR-002 supports the institution's chosen mechanism by allowing region selection consistent with the legal mechanism. The Phase 1 privacy spec governs what data is permitted to cross.
Detection: Detection through region configuration audit (periodic verification that the deployed configuration matches the legal mechanism) and provider audit of actual processing region (institutions verify processing region for AWS Bedrock and similar at the inference path level, per ADR-002).

**Framework coverage for Privacy threats:**
- **NIST AI RMF**: Govern function (privacy as part of accountability) and Map function (privacy risk identification).
- **EU AI Act**: Article 10 (data and data governance) and GDPR overlay through Recital 28 (the Act does not affect GDPR application).
- **OSFI E-23**: Privacy obligations of federally regulated institutions extend to AI system data handling.
- **SOX ICFR**: Privacy of records supporting financial reporting is part of confidentiality controls.

## Residual risks

The following threats have partial mitigation in the reference architecture. Institutions adopting the framework accept the residual risk explicitly or layer additional controls.

**Prompt injection (T-AI1).** Cannot be fully eliminated with current LLM technology. The reference architecture reduces the surface (no document parsing, structured output enforcement, system prompt design) but does not close it. Residual risk: a sufficiently sophisticated injection produces an attacker-chosen classification. Institutional mitigation: HITL review of escalated cases (and ideally a sample of approved cases) provides the final safety net. Institutions with higher exposure may require human review of all high-risk vendor decisions.

**Hallucination (T-AI4).** Cannot be fully eliminated with current LLM technology. The reference architecture reduces incidence through prompt engineering, confidence-gated routing, and output validation, but does not eliminate it. Residual risk: a triage record contains fabricated content that survives validation. Institutional mitigation: reviewer training to recognize hallucination patterns, sampling-based audit of approved records, regulator engagement when hallucination in a regulatory citation is identified.

**System prompt extraction (T-I2 and T-AI2).** The Output Validator constrains responses structurally but cannot fully prevent prompt content from leaking through valid response patterns. Residual risk: institutional prompts are disclosed. Institutional mitigation: prompts that do not contain content harmful to disclose (no embedded secrets, no embedded credentials), and treating prompt leakage as a normal risk of public AI deployment rather than as a confidentiality failure.

**LLM provider outage (T-D2).** The reference implementation does not include automatic provider failover. Residual risk: extended provider outage stops classification work. Institutional mitigation: provider contract SLAs, manual fallback to alternative adapters using the LiteLLM-compatible interface (per ADR-001), or temporary process changes during outages.

**Provider concentration (architectural).** The LLM provider is a single point of dependence even with the provider-agnostic interface. Residual risk: provider business or technical changes affect the entire gate's reliability. Institutional mitigation: vendor risk monitoring of the LLM provider, periodic re-evaluation of the provider choice, multi-adapter readiness as an institutional extension.

**Provider model updates (T-AI8).** Cannot be fully mitigated. Provider model version pinning is supported by some providers (Anthropic) but may be partial; silent updates within a pinned version remain possible. Residual risk: classification behavior shifts that may not be discoverable without active monitoring. Institutional mitigation: subscription to provider release notes, periodic re-evaluation against stable test sets, deployment_metadata capture of upstream model version at time of inference.

**Bias and fairness (T-AI6 and T-AI7).** Cannot be fully eliminated with current LLM technology. The reference architecture supports detection and correction through bias evaluation suites and distribution monitoring, but cannot prevent bias from arising in model outputs. Residual risk: vendor classification reflects biases that affect specific vendor categories. Institutional mitigation: documented bias evaluation procedures, reviewer training on bias patterns, vendor escalation paths when bias is identified, board-level oversight of vendor classification fairness over time.

## Risk management formality and forward references

This threat model articulates threats and detection approaches in prose with mitigations per threat. Practitioners trained in formal risk management disciplines (CRISC, AAIR) will note that the model does not yet ship:

- A tabular threat-to-control matrix at the per-control level
- A formal risk register integrating these threats with the institution's broader risk inventory
- Named key risk indicators (KRIs) for ongoing monitoring
- Per-threat risk owners and risk acceptance documentation

These artifacts are scoped to Phase 4 (Governance Artifacts), where they integrate with the institution's broader governance discipline and the ISO/IEC 42001 Annex A controls documented in docs/governance/README.md. The threat model in Phase 2 provides the substantive analysis that Phase 4 formalizes; the formality follows the substance rather than preceding it.

The detection skeletons in detection/ provide the executable interface that Phase 5 implements against. Risk register integration, KRI definition, and risk owner assignment are governance concerns Phase 4 addresses; the threat-and-detection substance lives here.

## What this threat model does not cover

The exclusions below are the ones a reader might wrongly expect from this document.

**Security audit and penetration testing.** This document specifies the threat surface conceptually. Penetration testing, vulnerability scanning, and third-party security review sit downstream in Phase 5 (Deploy and Monitor). The threat model identifies threats; the security audit confirms mitigations are operationally effective.

**Nation-state and advanced persistent threat modeling.** The threat coverage is appropriate for regulated mid-market operators. Institutions facing nation-state actors (critical infrastructure, large banks under specific advisories) extend the model with additional threat classes.

**Physical security threats.** Physical access to data centers, hardware tampering, and similar physical-layer threats are infrastructure concerns owned by the institution's facilities and infrastructure security functions.

**Compiler toolchain and dependency supply chain attacks.** Threats targeting the build pipeline beyond standard source control hygiene (deterministic builds, signed artifacts, dependency pinning) are out of scope for this reference framework. T-T3 acknowledges the threat at a high level; deeper supply chain threat modeling is institutional.

**Social engineering against reviewers.** Phishing, pretexting, and similar social attacks against compliance reviewers and program owners are personnel security concerns rather than system architecture concerns.

**Regulatory enforcement risk.** This document is not a regulatory risk assessment. The threat model maps to regulatory frameworks (NIST AI RMF, EU AI Act, OSFI E-23, SOX ICFR) but does not assess the institution's enforcement risk under each.

**CMMC and DoD-specific frameworks.** The reference framework targets regulated financial services and adjacent mid-market sectors. Department of Defense Cybersecurity Maturity Model Certification (CMMC) practices, Controlled Unclassified Information (CUI) handling, and System Security Plan (SSP) requirements are out of scope. Institutions deploying the framework in defense industrial base contexts extend the threat model with the relevant CMMC practices.

## Framework coverage

- **NIST AI RMF**: Map function (system context and risk identification) and Manage function (risk treatment and monitoring). The threat model is core to identifying risks across the AI system lifecycle.
- **EU AI Act**: Article 9 (risk management for high-risk AI systems). Structured risk identification and analysis are explicitly required; the threat model provides them.
- **OSFI E-23**: Model risk identification. The threat model contributes to overall model risk assessment for federally regulated AI systems.
- **SOX ICFR**: Third-party and IT general control risk assessment. AI threat surfaces in vendor decisions affect the reliability of controls within ICFR scope.

## Forward references

This threat model is built on by:

- Phase 3 (Build and Eval): Mitigations referenced as "deferred to Phase 3" are implemented and tested in Phase 3. Confidence calibration, prompt engineering for injection resistance, bias evaluation suites, and output guardrails are Phase 3 deliverables.
- Phase 5 (Deploy and Monitor): Operational threat monitoring, penetration testing, and security audit confirm mitigations work in production. Threat model assumptions are validated against operational reality. Detection mechanisms identified in this document are operationalized in Phase 5.

## Status

Phase 2 (Architecture and Threat Model) of the sitkastack Framework, complete as of May 24, 2026. All five Phase 2 artifacts (problem definition, system architecture, trust boundaries, threat model, and architecture decisions) are published.

## Author

Robyn Toor. Fifteen years shipping programs in fintech and SaaS, including fintech operating roles where vendor risk decisions came across my desk.
