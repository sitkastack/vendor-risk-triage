# Problem Definition

This document defines the one problem the vendor-risk-triage system is built to solve, and who depends on it. Read it before any code, because every later build decision traces back to the scope set here.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions. This document reflects what I wish vendor risk programs had looked like from the inside.

## The decision being supported

The system supports a single decision: given a vendor's documentation and a known business context, what risk tier does the vendor's AI usage fall into, and what should happen next? The next step is one of four dispositions: approve, conditional approve with named mitigations, escalate to senior human review, or reject. All four are human decisions; the system produces a recommendation and a written rationale, not a final answer.

Made concrete: a payments company is evaluating a support tool that just added AI summarization. The feature reads support tickets that contain cardholder names and partial account numbers, then sends them to a third-party model provider. The system reviews the vendor's documentation, questionnaire responses, and data processing terms, and returns a tier (high, because PII leaves the environment and retention terms are unclear) with a disposition (conditional approve: keep the feature off until the vendor confirms zero retention and signs a data processing addendum). For contrast, a marketing analytics tool whose AI only summarizes the company's own published blog posts gets a low tier and a clean approve. Same inputs, different outputs, each with a written rationale.

## Who this is for

Primary user: the compliance, risk, or procurement professional who runs vendor intake daily. They need a fast, defensible first pass that turns a stack of vendor documents into a tier and a recommended action, with the reasoning written down so they are not starting cold on every vendor.

Secondary user: the VP or Director of Compliance who owns the program. They need visibility into the triage queue, a clear view of why each vendor landed where it did, and the ability to override a recommendation and have that override recorded.

Tertiary stakeholder: the auditor or regulator reviewing decisions after the fact. They need to reconstruct what the system saw, what it recommended, who decided, and why, months or years later.

## The business context

A mid-market regulated company (fintech, PE-backed services, professional services, regulated SaaS) typically runs 50 to 500 SaaS vendors. Each one is a possible entry point for risk, and the list grows faster than the compliance team does.

The recent change is that more of those vendors ship AI features, often quietly. A tool bought two years ago for ticketing or expense management now trains on your data, generates outputs that feed decisions, pushes PII through a large language model, or embeds an agent that acts inside your workflow. A vendor you already approved can change risk profile in a single product release.

Regulators have moved. NIST AI RMF offers a voluntary structure for AI risk. The EU AI Act sets binding obligations across multiple risk tiers, with the most stringent requirements on Annex III high-risk uses. Canada's OSFI Guideline E-23 takes effect May 1, 2027 for all federally regulated financial institutions and pulls third-party AI models into model risk management. The NAIC Model Bulletin on AI extends similar expectations to insurers, and SR 11-7 has governed model risk in US banking for over a decade. Most mid-market companies still have no AI-specific process for vendor intake. Existing security questionnaires rarely surface AI risk dimensions like training-data usage, model provenance, or post-procurement feature changes, so the risk gets handled ad hoc, skipped, or assumed to be covered when it is not.

## The cost of getting this wrong

Start with data. If a vendor's AI trains on your customer data without proper disclosure, you carry contractual exposure and potential violations of applicable privacy law (PIPEDA, provincial private-sector legislation, GDPR, or sectoral equivalents), and you may not find out until the vendor's own breach or audit surfaces it. The disclosure failure is theirs. The regulated relationship with your customers is yours.

Then decisions. If a vendor's AI shapes customer-affecting outcomes you never authorized, and the outputs are biased, wrong, or unexplainable, the operational and reputational damage lands on you. "The vendor's model did it" is not a defense regulators accept. The same holds when a vendor's AI fails its own audit while you rely on it: their finding becomes yours.

The quiet failures cost the most. A vendor overstates its AI capabilities in a questionnaire, your team approves on that basis, and the gap becomes a due diligence failure with your name on it. Or a vendor you tiered as low risk ships an AI feature six months after procurement, with no trigger for re-review, and an unknown becomes a production issue with no governance behind it. None of this is dramatic. It's slow, and it's exactly what looks obvious in hindsight during an audit.

## What this system is not

This is a triage system. It is not a full vendor risk management program, and it is not a substitute for legal review or formal model risk validation. The detailed exclusions live in 02-out-of-scope.md. Read that before assuming the system covers a given case.

## Why this work is being published openly

I'm publishing this as the first reference implementation in sitkastack for three reasons. The problem is close to universal: nearly every mid-market regulated company has a vendor list filling with AI features and no defined way to assess them. The timing is concrete: the regulatory forcing functions above are live or dated within eighteen months, with OSFI E-23 carrying a hard 2027 deadline. And the building blocks generalize. Structured triage with documented reasoning, audit logging, human-in-the-loop review, and turning unstructured documents into structured decisions are the patterns most AI governance problems need, so a working example here helps well beyond vendor intake.

## Limitations of this document

This is a v0.1 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as the implementation phases ship and as people who do this for a living point out what I have missed. Your regulatory context, sector, and internal controls will require adaptation. Treat it as a starting point you adjust, not a finished product you adopt unchanged. Production deployment requires institution-specific validation, including independent review where OSFI E-23, SR 11-7, or equivalent governance frameworks apply.

## Status

Status: Phase 0 (Discovery & Risk Classification) in progress.

Roadmap: https://sitkastack.com/roadmap

Last updated: Wednesday, May 20, 2026
