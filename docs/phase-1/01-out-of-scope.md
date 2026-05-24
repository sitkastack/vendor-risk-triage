# Out-of-Scope

This document is the companion to 00-problem-definition.md. That document fixes what Phase 1 produces. This one draws the line around what those artifacts do not cover.

## Why this document exists

Most data contracts ship without an explicit out-of-scope statement. The schema lists the fields the system expects, and everyone treats that list as the whole story: what is in the schema is in scope, and what is not in the schema is assumed irrelevant. The assumption holds right up until a real document arrives.

Then a vendor sends documentation with fields the schema never named. A security questionnaire includes a section on AI subprocessors the input contract did not anticipate. The contract said nothing about those fields, so what happens to them falls to whoever wrote the parsing code. The engineer silently drops them, or the system tries to parse them anyway, or the field slips into the unstructured "context" the agent reasons over and never gets formally tracked.

The failure mode is silent inference. The system processes data it never formally accepted, reaches a tier and a disposition shaped by inputs nobody intended it to read, and writes a record that does not reflect what actually happened. An auditor reconstructing the decision finds a record that references fields the contract does not define, and the gap between what was documented and what was processed becomes the finding.

What the contract does not name, the system processes anyway.

I treat this out-of-scope statement as part of the contract, not a disclaimer bolted onto it. Naming what the contracts do not cover is the only reliable way to keep undocumented data and unowned obligations from drifting onto the system by default.

What follows is the boundary, written down. Each exclusion names the artifact that does not cover the case, and the function or document that does instead.

## Data the contracts do not cover

1. **Real customer or production data.** The synthetic data spec defines the test corpus, and the contracts are designed against synthetic vendor documentation rather than real submissions. No real customer or production data flows through this reference implementation. Institutions deploying it in production apply their own real-data privacy controls, owned by their privacy and engineering functions, separate from anything specified here.

2. **Institution-specific schema extensions.** The input contract defines a generic schema for a mid-market regulated company. Real deployments will extend it for their own vendor categories, internal control framework, and questionnaire formats. Those extensions, and the decisions about what to add, are owned by the institution's engineering and compliance teams.

3. **Vendor-side data the agent never sees.** The contract describes what a vendor submits for review. It does not reach the vendor's internal training data, model weights, infrastructure, or operational logs. Those sit with the vendor and are pursued, where needed, through the security and vendor due diligence processes that run alongside triage.

4. **Data from channels other than submitted documentation.** Support tickets, sales conversations, live demos, and informal vendor disclosures fall outside the contract. The triage agent works from the documentation it is given, not from context that arrives through other channels. When relevant information comes from those sources, the vendor management function records it separately and feeds it into review by hand.

5. **Lineage upstream of intake or downstream of disposition.** The contract starts when documentation reaches the triage agent and ends when the record is written. How a vendor assembled its documentation before submission, and what the institution does with the triage record afterward, both fall outside it. The document management or GRC system owns the record once it leaves the agent.

## Privacy obligations the spec does not satisfy

1. **Legal interpretation of privacy obligations.** The privacy spec captures methodology: how data is minimized at intake, retained on a schedule, and purged on a defined trigger. It does not interpret PIPEDA, GDPR, or sectoral privacy law for a specific institution or a specific vendor arrangement. That interpretation is legal work, owned by qualified counsel for the deploying organization.

2. **Jurisdiction-specific enforcement and reporting.** The spec describes a framework, not the obligations that attach to a given region. Breach notification timelines, regulator reporting duties, and data subject rights vary by jurisdiction and shift with enforcement practice. Those obligations sit with the privacy officer and legal counsel for the deploying organization.

3. **Active monitoring of privacy regulations.** The spec reflects the regulatory landscape at the time of writing, and that landscape moves. Keeping it current with new requirements, whether the next EU AI Act delegated act, an updated AMF guideline, or a new state privacy law, is the deploying organization's responsibility, owned by its privacy and legal functions.

4. **Privacy training for the people using the system.** The spec documents the privacy approach embedded in the data contracts and handling rules. It does not train the compliance team, the privacy officer, or the engineers integrating the system on how to apply that approach. Training is a separate workstream, owned by the privacy or learning function.

## System behaviors not specified by the contracts

The contracts describe what flows in and out of the system. They do not describe what happens in between.

1. **The classification logic itself.** The contracts say which fields the triage agent reads and which it writes. They do not say how the agent moves from those fields to a tier. That logic lives in docs/phase-0/01-risk-classification.md and is refined in the model behavior work of later phases.

2. **Model quality, accuracy, and testing.** The contracts produce records; they do not guarantee the records are correct. Evaluation methodology, accuracy benchmarks, and failure analysis are Phase 3 (Build & Eval) work, owned there rather than by the contract.

3. **Confidence calibration.** The output contract includes a confidence signal field and defines its shape. It does not specify how that confidence is calculated, calibrated against ground truth, or tested for drift over time. Calibration is a model-quality concern, handled in Phase 3.

4. **The mechanism that produces dispositions.** The output contract carries the disposition. Whether that disposition comes from a rules engine, a fine-tuned model, an agent with tool use, or some combination is outside the contract's concern. The contract names the output, not the machinery that produces it.

## Operational concerns not addressed in Phase 1

The contracts and privacy spec are design artifacts. The operational concerns around them sit in later phases or in the deploying organization's existing infrastructure.

1. **Architecture and threat modeling.** How the triage agent is deployed, what services it depends on, what trust boundaries separate its components, and how it resists adversarial inputs are Phase 2 (Architecture & Threat Model) work. The contracts assume a deployment exists; they do not design it.

2. **Production monitoring and observability.** Logging against the data contract is one thing. Watching whether real inputs keep conforming to it, alerting when they drift, and dashboarding compliance metrics are Phase 5 (Deploy & Monitor) work, owned there.

3. **Access control and authentication.** Who can invoke the triage agent, who can read its outputs, and how identity is established sit with the institution's identity and access management infrastructure. The contracts assume authenticated access; they do not specify how authentication happens.

4. **Backup, disaster recovery, and continuity.** The privacy spec defines retention. It does not define how records are backed up, how they survive a regional outage, or what continuity obligations apply. Those sit with the institution's IT continuity function.

## Quality assurances the contracts do not provide

The contracts standardize how data enters and exits the system. They do not standardize the truth of the data itself.

1. **Vendor honesty.** The input contract accepts what the vendor submits at face value. If a vendor misrepresents its AI usage, omits a feature, or supplies outdated documentation, the contract has no mechanism to notice. Verification of vendor claims sits with the vendor management and security validation functions.

2. **Schema completeness.** The contract defines a schema sufficient for the reference triage agent, not an exhaustive map of every field a future use case might need. Real deployments will find gaps. Those gaps are closed by extending the schema through the institution's engineering and compliance teams, not by working around the contract.

3. **Field accuracy.** When the schema captures a field such as disclosed AI training data sources, it records what the vendor stated. It does not certify that the statement is correct, complete, or current. Accuracy is the vendor's representation, confirmed where it matters by the security and vendor management functions, not a guarantee the contract makes.

4. **Detection of deliberate misrepresentation.** A vendor that structures its disclosure to mislead, by omitting a relevant field, using vague language, or claiming an exemption that does not apply, is not caught by the contract on its own. Detecting intentional misrepresentation needs human review, third-party validation, or legal mechanisms that sit outside this reference, owned by the functions that run them.

## When this list should be revisited

New data sources, new regulatory requirements, and lessons from operating the contracts push items in and out of scope. A quarterly revisit is reasonable for most deploying organizations. Specific events should trigger an off-cycle revisit: a vendor pattern emerges that the schema cannot represent without ad hoc transformations; a new privacy regulation takes effect that changes minimization or retention obligations; or an audit finding surfaces a boundary the contracts did not anticipate. The list also contracts as later phases ship. When Phase 2 delivers the architecture and threat model, several exclusions here graduate to that phase rather than staying out of scope, and the change gets recorded in the same commit history as the new work.

## Limitations of this document

This list reflects the v0.3 reference implementation. Real deployments will carry context-specific exclusions, shaped by sector, regulators, and internal structure, that this document cannot anticipate.

The most useful feedback comes from engineers and privacy practitioners who have run contracts like these in production and seen failure modes I have not. If an exclusion belongs here and isn't, open a GitHub issue.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, complete as of May 23, 2026. Roadmap: sitkastack.com/roadmap.
