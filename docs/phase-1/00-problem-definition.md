# Problem Definition

Phase 1 of the vendor-risk-triage build defines the data. Phase 0 settled what the system decides and how that decision is graded against regulatory frameworks; this document settles what flows in, what comes out, and how privacy obligations are met at each step. It opens the six artifacts that make up Data Contracts & Privacy.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## What Phase 1 covers

Phase 0 fixed the decision the system supports and mapped it to the regulatory frameworks it has to answer to (docs/phase-0/00-problem-definition.md and docs/phase-0/01-risk-classification.md). Phase 1 fixes the material that produces the tier and disposition: the fields the triage agent reads, the record it writes, and the privacy rules that govern both.

A risk classification is operationally inert without explicit data definitions. You cannot run a triage agent on "vendor documentation." You have to know which fields are required, which formats are accepted, what gets logged, and what gets discarded. The Phase 0 taxonomy assumes clean inputs; Phase 1 specifies them.

Phase 1 produces six artifacts: this problem definition, an out-of-scope document, an input data contract, an output data contract, a privacy and data handling spec, and a synthetic data specification. The contracts are the machine-readable core, the privacy spec governs what they may retain, and the synthetic data spec defines the records used to test everything without real vendor or customer data.

## The decisions being supported

Phase 0 supported one decision: tier and disposition. Phase 1 adds two that sit upstream of it.

1. **Can a given vendor's documentation be processed by the triage agent?** This is a data validation question. The input contract defines the schema, the accepted formats, and the required fields. A vendor's SOC 2 report, security questionnaire, model card, and data processing terms arrive in inconsistent shapes. Documents that do not conform are rejected at intake with a stated reason or normalized through a documented transformation, not quietly coerced.

2. **What gets persisted from a triage decision, and for how long?** This is a data lifecycle question. The output contract defines the triage record: the tier, the disposition, the rationale, and the evidence the agent relied on. The privacy spec defines which PII is retained, which is minimized at intake, and which is purged on a schedule.

Both decisions sit upstream of the classification logic. Without explicit answers, the triage agent runs on whatever an engineer fed it during development, and those assumptions get re-litigated in every audit.

## Who this is for

The primary audience shifts toward the people who build and govern the data path:

- The engineer integrating the triage agent into a vendor intake workflow. They need the input and output schemas to be machine-readable and stable, so the integration survives the next differently shaped questionnaire.
- The privacy officer (DPO, CPO, or equivalent) reviewing data handling for PIPEDA, GDPR, or sectoral obligations. They need minimization and retention rules stated explicitly, not implied by the code.
- The auditor or examiner reconstructing what data was processed, when, and how it was handled. They need lineage that rebuilds from records rather than from anyone's memory.

The compliance and risk professionals primary in Phase 0, including the VP or Director of Compliance who owns the program, remain stakeholders but are not the primary readers of these specifications.

## Why explicit data contracts matter

Most AI implementations treat the data as whatever happened to be fed in during development. Six months later the input shape drifts, a field the agent depended on goes missing, and the system misbehaves quietly with nobody able to say why.

An explicit data contract is the schema written down in the open: which fields, which types, what is required, what is optional, what gets transformed. The contract is the boundary between what the system trusts as input and what it discards. An engineer reading it knows what to send. A reviewer reading it knows what the agent actually saw.

For regulated AI the contract is also the audit boundary. When an examiner asks what a vendor's documentation looked like at intake, the answer is the contract plus the validation log: this schema, these fields, this record rejected for that missing term. That is a reconstructable answer. "We think it was the standard questionnaire" is not.

## Why privacy is part of this phase, not later

Privacy obligations attach the moment data enters the system, so the data contracts and the privacy rules belong in the same phase. Treating privacy as a later production concern means building infrastructure that then has to be retrofitted. Minimization, retention, and residency are far cheaper to design in than to bolt on. PIPEDA and GDPR both reward upfront design and penalize the retrofit, in remediation cost and in what an examiner concludes about your governance.

## What this phase does not cover

Phase 1 draws its boundaries in a dedicated document, 01-out-of-scope.md, the same way Phase 0 did. Model validation, the agent's reasoning quality, downstream workflow integration, and the institution-specific schema extensions a real deployment requires are named there. This phase specifies the data and its handling, not the model behavior that consumes it.

## Why this work is being published openly

The data problem is the same in nearly every regulated AI system: undefined inputs, unstated retention, and privacy handled after the fact. The contract and privacy patterns generalize well past vendor intake to any AI system that ingests documents and writes decisions. Publishing them pressure-tests the methodology against real practitioner experience faster than refining it in private would. Like the other artifacts in this Framework, these ship under Apache 2.0 and improve through issues opened by practitioners who have done this work.

## Limitations of this document

This is a v0.3 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as the remaining Phase 1 artifacts ship and as engineers and privacy practitioners point out what I have missed.

The contracts described here reflect a generic triage agent. A real deployment will extend the schema for its own vendor categories, questionnaire formats, and internal control framework. The patterns for extending without breaking the audit boundary live in EXTENDING.md.

This is practitioner methodology, not legal advice. Detailed privacy considerations live in the privacy and data handling spec, and boundary clarifications live in 01-out-of-scope.md. Production deployment requires legal and privacy review alongside any framework like this, particularly where PIPEDA, GDPR, or sectoral retention rules apply.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, complete as of May 23, 2026. Roadmap: sitkastack.com/roadmap.
