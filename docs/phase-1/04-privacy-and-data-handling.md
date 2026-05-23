# Privacy & Data Handling

This document specifies how the vendor-risk-triage system handles data, as distinct from how it shapes data. The input and output contracts in 02-input-contract.md and 03-output-contract.md define what flows in and what is written out; this spec defines how that data is classified, minimized, retained, and eventually purged. Where 01-out-of-scope.md draws the line at legal interpretation, this document stays on the methodology side of that line.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## What this spec covers

The contracts define data shape. This spec defines data handling. A field can be perfectly specified in the input contract and still be mishandled in practice if nothing says how long it is kept, what is stripped before it is stored, or where it is allowed to live. The contracts answer what the data is; this spec answers what happens to it.

Privacy obligations attach the moment data enters the system, which is why this spec sits in Phase 1 alongside the contracts rather than waiting for a later production phase. Minimization, retention, and residency are far cheaper to design into the data path than to retrofit onto one already built, and an examiner reads a retrofit as exactly that. Building the handling rules at the same time as the contracts keeps the two consistent, so the contract that names a field and the rule that governs its lifetime are written together.

This spec covers methodology, not jurisdiction-specific legal interpretation. It describes how data is classified, minimized, and retained in a way compatible with the obligations a regulated company operates under, but it does not interpret PIPEDA, GDPR, or a sectoral regime for a particular institution or arrangement. 01-out-of-scope.md names that boundary, and the legal interpretation behind it is owned by qualified counsel for the deploying organization.

## Data classification at intake

Data is classified into three categories as it enters the system. Vendor-organizational data identifies the vendor and its relationship: name, jurisdiction, classification, the structural facts the contract makes explicit. Vendor-disclosed claims are the vendor's own statements about how it uses AI, what data it processes, and what it attests to. Incidental PII is any personal data that appears inside submitted documentation without being a field the contract asked for.

The first two categories are straightforward because the contract names them. Vendor-organizational data and vendor-disclosed claims arrive in defined fields, typed and bounded, and the system knows exactly what it is holding. The privacy weight of these categories is low: a vendor's name and its self-assessment are not personal data, and the contact the contract does capture is a business contact processed for a business purpose.

Incidental PII is the hard category. It does not arrive in a labeled field; it hides inside a security questionnaire that names the engineer who filled it out, a support contact embedded in a sample record, a screenshot pasted into a document. The agent's job at intake is to detect incidental PII before it reaches the classification logic and either redact it in place or reject the submission with a request to redact and resubmit. The contract's closed shape helps, because anything outside the named fields is already suspect, but detection inside free text and attachments is a genuine problem this spec names rather than waves away.

### Detection approaches

The contract's closed shape limits the surface area for incidental PII, but it does not remove it: free-text fields and document attachments still carry personal data the schema never asked for. Detecting that data is a real engineering choice, and the institution selects among several categories of approach, each with a different balance of coverage, cost, and operational burden.

1. **Pattern-based scanning.** Regex matching for structured PII such as email addresses, phone numbers, government identifiers, and payment card numbers. It has high recall on those structured patterns and is cheap to run at the edge. It is blind to unstructured PII such as a personal name embedded in prose.

2. **Named entity recognition.** Library-based or model-based classification of text spans by entity type, using tools such as spaCy, Microsoft Presidio, or transformer-based NER models. It covers more than regex, including names, places, and personal identifiers. Its accuracy is sensitive to model quality and to how well the model's language coverage matches the institution's data.

3. **LLM-based classification.** Routing free-text fields through an LLM with a redaction prompt before retention. It offers the highest contextual accuracy and the lowest false-positive rate of the options here. It also introduces latency, cost, and a second AI dependency the institution must itself govern.

4. **Commercial data loss prevention tools.** Offerings such as Microsoft Purview, AWS Comprehend PII, Google Cloud DLP, and BigID. They bring mature detection libraries and an established compliance posture. They also carry vendor lock-in and integration overhead.

5. **Hybrid combinations.** Most production systems combine the above: regex for structured patterns at the edge, NER or LLM-based detection for free-text fields, and commercial DLP for compliance-bound categories. The right mix depends on data sensitivity, false-positive tolerance, infrastructure constraints, and budget.

The spec does not pick among these approaches. It does require specific behaviors: detection runs at intake before the classification logic, every detection failure is logged, and incidental PII is either redacted in place before retention or surfaces as a rejection with a documented reason. The mechanism is the institution's choice; the behavior is not.

## Data minimization

The agent processes only what the contract requires. Data that arrives but is not part of a named field is discarded at intake, not parked in a staging area where it accumulates. Minimization starts before processing rather than after, so the smallest defensible set of data reaches the classification logic and the rest never enters the system's working memory.

Optional fields are processed when present because they sharpen the classification, but they are not retained beyond what the decision needs. A vendor that discloses its model providers and PII handling gives the agent more to reason over, and that reasoning is captured in the record. The raw optional input beyond what the record cites is not kept simply because it was sent.

Free-text fields carry the highest minimization risk, because prose is where incidental PII slips in. The classification_rationale and the evidence reasoning in the output contract are scrubbed for incidental PII before retention, so the durable record does not become the place a stray personal detail lives forever. A rationale should explain the decision in terms of the vendor's AI risk, not in terms of the name of whoever signed the questionnaire.

The governing principle is narrow. The agent retains what an auditor needs to reconstruct the decision and nothing more: the tier, the disposition, the reasoning, the evidence cited, and the versions that produced it. Anything that does not serve reconstruction is not retained, which keeps the retained footprint small enough to defend and small enough to purge cleanly when the time comes.

## Lawful basis for processing

The processing here is conducted by the deploying organization, not by sitkastack. This is a reference implementation, and when an institution runs it against its own vendor intake, the institution is the controller and the lawful basis for processing is the institution's to establish. Depending on its regulatory context, that basis may be legitimate interest, contractual necessity, or legal obligation, and more than one often applies across the data the system touches.

This spec does not interpret which basis applies, because that is legal work owned by the deploying organization. What it does instead is keep the data handling compatible with all of the common bases: there is no surprise processing, no use of data beyond the stated purpose of triaging vendor AI risk, and no secondary use an institution would have to disclose separately. A handling approach that stays inside the stated purpose is one a controller can map onto whichever lawful basis it relies on, rather than one that forces the basis to stretch.

## Retention schedule

Triage records are retained for the audit period the deploying organization's regulatory framework requires. For a federally regulated financial institution under OSFI E-23 that is commonly seven years, under SR 11-7 it is commonly five, and sectoral regimes vary. The spec does not pick the number, because the number is the institution's to set against its obligations, but it does require that the number be explicit and applied uniformly rather than left to whatever a storage default happens to be.

Input submissions are retained alongside the records they produced. The contracts make the submission the audit artifact, so a record without its submission is only half an answer: an examiner reconstructing a decision needs both what the agent decided and what it decided from. The two share a retention period and are purged together, so a record never outlives the evidence behind it and evidence is never kept past the record it supported.

Failed validations are retained for ninety days by default, and longer when the deploying organization needs to investigate a pattern of intake failures. A rejected submission is part of the audit trail, but it is not a decision and does not warrant the full audit-period retention a decision does. The ninety-day window is long enough to investigate an intake problem and short enough that turned-away data does not accumulate indefinitely.

Records tied to an active vendor relationship are retained through the life of the relationship plus the audit period that follows it, so a vendor still in use never has its triage history purged out from under it. Purge schedules are explicit and machine-enforced wherever the infrastructure allows, because a retention rule that depends on someone remembering to delete is a rule that quietly fails. The schedule is data the system acts on, not a policy in a document nobody runs.

## Data residency

Records and submissions stay in the deploying organization's primary jurisdiction unless a contractual obligation requires otherwise. The default is the conservative one, where data does not leave the jurisdiction it was collected in without a specific reason and a specific mechanism. Where a vendor relationship carries its own residency commitments those are honored, but they are the exception that has to be justified rather than the baseline.

Cross-border situations arise when a vendor is located outside the deploying organization's jurisdiction, and they are handled through the mechanisms a controller already relies on: standard contractual clauses, an adequacy decision, or an equivalent. This spec defines the residency requirement and records the regions involved through the contract's residency fields. Enforcing residency at the storage and network layer is infrastructure-dependent and out of scope here, owned by the deploying organization's engineering and privacy functions.

## Data subject rights

Vendor personnel whose contact information appears in a submission have data subject rights under PIPEDA, GDPR, and the sectoral frameworks that apply, and the system has to be built so those rights can be exercised. A business contact is still a data subject, and the fact that the data was collected for vendor risk rather than for marketing does not remove the obligation to honor an access or deletion request about it.

Access requests are handled through the deploying organization's existing privacy operations rather than through a separate path this system invents. The contracts make the relevant data findable, because a subject's contact information lives in named fields and the records referencing a given vendor are linkable, so a privacy team can locate what it holds about a person without reading every record by hand. The system's contribution is making the data locatable; the response process is the institution's.

Deletion requests for incidental PII are the harder case, because that data may sit inside a triage record that has independent audit value. The system handles this through the output contract's supersession and revocation machinery: a record carrying incidental PII is revoked or replaced with a redacted version that preserves the decision while removing the personal detail. The decision stays reconstructable, the personal data is gone, and the chain records that the change happened. The spec defines the data structures that make this possible; it does not implement the deletion workflow itself.

## Cross-border transfers

Many vendors operate across jurisdictions, so a single submission can contain data subject to more than one privacy regime at once. A vendor headquartered in one country, processing in another, with subprocessors in a third brings all three regimes into contact inside one record. The spec assumes the deploying organization already has the transfer mechanisms this requires, whether standard contractual clauses, binding corporate rules, or adequacy decisions.

The triage agent does not itself move data across borders. It reads submissions and writes records within the deploying organization's environment, and any cross-border movement happens through that organization's infrastructure under that organization's transfer mechanisms. The spec keeps the agent out of the transfer path deliberately, because an agent that quietly shipped data to a model provider in another jurisdiction would create exactly the cross-border exposure the institution's mechanisms exist to control.

## Breach handling

The spec defines what data exists and where it lives, which is the precondition for any incident response. A breach cannot be scoped without knowing what was held, in what fields, and under what retention, and the contracts plus this spec answer that before an incident rather than during one. Knowing the data inventory in advance turns a breach response from an archaeology project into a containment exercise.

Breach detection, containment, and notification are infrastructure and operational concerns owned by the deploying organization's security and privacy teams, not behaviors this reference implements. What the spec does ensure is that records are recoverable and audit trails stay intact even under partial compromise: the append-only, supersession-based record store means a decision history is not silently rewritten, and a tampered record is detectable rather than invisible, which is a property of how the store is built rather than something the response team adds after the fact.

## Audit considerations

Privacy compliance is auditable through this spec, the contracts, and the audit logs together. An examiner can reconstruct what data the agent processed, what was minimized at intake, what was retained, and for how long, because each of those is defined here and evidenced in the records and logs the system produces. The privacy posture is not a claim in a policy document, it is visible in what the system actually kept and discarded.

The spec is a public artifact, so a deploying organization demonstrates compliance by reference to the methodology plus its own implementation evidence. The methodology states the handling the system is designed for; the institution's logs, retention configuration, and purge records show that the design was actually applied. An auditor reads the two together, the published intent and the local proof that it was carried out.

## Limitations of this spec

This is a v0.1 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as the rest of Phase 1 settles and as privacy practitioners who have run data handling like this in production point out what I have missed.

This is methodology, not jurisdiction-specific compliance. It is built to be compatible with PIPEDA, GDPR, and common sectoral regimes, but compatibility is not the same as compliance with any one of them as applied to a particular institution. A real deployment requires legal and privacy review against the specific obligations that attach to it, and new privacy regulation requires the spec to be revisited rather than assumed still current.

This is practitioner methodology, not legal advice. The spec is the starting point a privacy team adapts, not the finished privacy program a regulated institution needs. Detailed boundaries on what this work does not cover live in 01-out-of-scope.md, and production deployment requires the legal, privacy, and security review those boundaries point to.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, in progress as of May 21, 2026. Roadmap: sitkastack.com/roadmap.
