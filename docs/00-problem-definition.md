# Problem Definition

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## The decision being supported

The system supports a single decision: given a vendor's documentation and a known business context, what risk tier does the vendor's AI usage fall into, and what should happen next? The next step is one of four dispositions: approve, conditional approve with named mitigations, escalate to senior human review, or reject. All four are human decisions; the system produces a recommendation and a written rationale, not a final answer.

A payments company is evaluating a support tool that just added AI summarization. The feature reads support tickets that contain full cardholder data, including primary account numbers and CVV codes, pulling those tickets into PCI scope, then sends them to a third-party model provider. The system reviews the vendor's documentation, questionnaire responses, and data processing terms, and returns a tier (high, because PII leaves the environment and retention terms are unclear) with a disposition (conditional approve: keep the feature off until the vendor confirms zero retention and signs a data processing addendum). A marketing analytics tool whose AI only summarizes the company's own published blog posts gets a low tier and a clean approve.

## Who this is for

Primary user: the compliance or risk professional who runs vendor intake daily. The system gives them a fast, defensible first pass that turns a stack of vendor documents into a tier and a recommended action, with the reasoning written down so they are not starting cold on every vendor. Procurement is a secondary consumer of the output, not a primary user; their concerns about cost and speed sit alongside but do not drive the risk classification.

Secondary user: the VP or Director of Compliance who owns the program. They need visibility into the triage queue, a clear view of why each vendor landed where it did, and the ability to override a recommendation and have that override recorded.

Tertiary stakeholder: the auditor or regulator reviewing decisions after the fact. They need to reconstruct what the system saw, what it recommended, who decided, and why, months or years later.

## The business context

A mid-market regulated company (fintech, PE-backed services, professional services, regulated SaaS) typically runs 50 to 500 SaaS vendors. Each one is a possible entry point for risk, and the list grows faster than the compliance team does.

The recent change is that more of those vendors ship AI features, often quietly. A tool bought two years ago for ticketing or expense management now trains on your data, generates outputs that feed decisions, pushes PII through a large language model, or embeds an agent that acts inside your workflow. A vendor you already approved can change risk profile in a single product release.

Regulators have moved. The EU AI Act sets binding obligations across multiple risk tiers, with the most stringent requirements on Annex III high-risk uses. Canada's OSFI Guideline E-23 takes effect May 1, 2027 for all federally regulated financial institutions and pulls third-party AI models into model risk management. NIST AI RMF offers a voluntary structure for AI risk that increasingly shows up in vendor contracts and audit expectations. Sectoral frameworks (NAIC for insurers, SR 11-7 for US banks, FCA and FINRA for relevant capital markets) add their own obligations. Most mid-market companies still have no AI-specific process for vendor intake. Existing security questionnaires rarely surface AI risk dimensions like training-data usage, model provenance, or post-procurement feature changes, so the risk gets handled ad hoc, skipped, or assumed to be covered when it is not.

## The cost of getting this wrong

The quiet failures cost the most. A vendor overstates its AI capabilities in a questionnaire, your team approves on that basis, and the gap becomes a due diligence failure with your name on it. Or a vendor you tiered as low risk ships an AI feature six months after procurement, with no trigger for re-review, and an unknown becomes a production issue with no governance behind it. None of this is dramatic. It's slow, and it's exactly what looks obvious in hindsight during an audit.

The data failures are the most legible to regulators. If a vendor's AI trains on your customer data without proper disclosure, you carry contractual exposure and potential violations of applicable privacy law (PIPEDA, provincial private-sector legislation, GDPR, or sectoral equivalents), and you may not find out until the vendor's own breach or audit surfaces it. The disclosure failure is theirs. The regulated relationship with your customers is yours.

The decision failures are the most damaging operationally. If a vendor's AI shapes customer-affecting outcomes you never authorized, and the outputs are biased, wrong, or unexplainable, the operational and reputational damage lands on you.

"The vendor's model did it" is not a defense regulators accept.

The same holds when a vendor's AI fails its own audit while you rely on it: their finding becomes yours.

## Why this work is being published openly

I'm publishing this as the first reference implementation in sitkastack because the problem is close to universal, the timing is concrete, and the building blocks generalize. Nearly every mid-market regulated company has a vendor list filling with AI features and no defined way to assess them. The regulatory forcing functions above are live or dated within eighteen months, with OSFI E-23 carrying a hard 2027 deadline. Structured triage with documented reasoning, audit logging, human-in-the-loop review, and turning unstructured documents into structured decisions are the patterns most AI governance problems need, so a working example here helps well beyond vendor intake.

## Limitations of this document

This is a v0.1 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage. It will change as the implementation phases ship and as practitioners with deeper experience in vendor risk, model validation, or regulatory examination point out what I have missed. Your regulatory context, sector, and internal controls will require adaptation. Treat it as a starting point you adjust, not a finished product you adopt unchanged. Production deployment requires institution-specific validation, including independent review where OSFI E-23, SR 11-7, or equivalent governance frameworks apply. Detailed exclusions, including what the system does not decide and who owns each excluded decision instead, live in 02-out-of-scope.md.

## Status

This document is part of Phase 0 (Discovery & Risk Classification) of the sitkastack Framework, in progress as of May 20, 2026. The full roadmap lives at sitkastack.com/roadmap.
