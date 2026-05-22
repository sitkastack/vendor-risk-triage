# Risk Classification

This document classifies the vendor-risk-triage system against the regulatory frameworks it has to answer to, and defines the internal taxonomy the system uses to tier the vendors it reviews. It sits between 00-problem-definition.md, which fixes the decision the system supports, and 02-out-of-scope.md, which draws the line around what it does not do. Problem Definition says what the system decides; this document says how that decision is graded.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## Why this document exists

Risk classification is where policy meets operations. A governance framework that lives only in a policy binder is operationally inert: it says AI risk must be managed without saying how a given vendor gets graded on a Tuesday. Classification is the step that turns a principle into a decision someone can make and stand behind.

The triage system runs on an internal taxonomy mapped to the external frameworks a regulated company answers to. This document defines those mappings in the open. The point is defensibility: when an examiner asks why a vendor landed in a given tier, the reasoning is written down here rather than reconstructed under pressure.

Without explicit mapping, a system's risk posture defaults to whatever the most aggressive interpreter says it is. Writing the mapping down sets the posture deliberately.

One boundary matters before the rest. This document classifies the triage system itself against regulatory frameworks. It does not classify the vendors being triaged or the AI those vendors ship. Each triaged vendor is a separate classification the deploying organization owns, a point I return to below.

## Regulatory frameworks this system maps to

The system maps its classification logic to four bodies of regulation, ordered here by how directly they bear on a mid-market regulated company deploying it.

**EU AI Act.** Mandatory for AI systems placed on the market or put into service in the EU, or whose outputs affect people in the EU, with obligations scaled across risk tiers and the heaviest weight on the Annex III high-risk categories.

**OSFI Guideline E-23.** Effective May 1, 2027, it extends Canada's model risk management to AI and ML systems and pulls third-party model risk under Guideline B-10 for all federally regulated financial institutions.

**NIST AI RMF.** A voluntary US structure whose four functions increasingly appear in vendor contracts and audit expectations even where no statute requires them.

**Sectoral frameworks.** The NAIC Model Bulletin on AI for insurers, SR 11-7 for US banks, and FCA and FINRA expectations where capital-markets activity is in play.

This document maps the system's classification logic to these frameworks. It does not certify any specific vendor's regulatory compliance; that sits with the vendor and, where relied upon, the deploying organization.

## EU AI Act classification analysis

The load-bearing question for the system's own classification is whether it is a high-risk AI system under the EU AI Act. Annex III enumerates eight high-risk categories; the system is tested against each below, not waved past as a group.

**1. Biometric identification and categorisation of natural persons.** Not in scope. The system processes text: vendor documentation, questionnaire responses, and contract terms. It performs no biometric capture, matching, or inference about natural persons.

**2. Management and operation of critical infrastructure.** Not in scope. The system supports an internal compliance workflow and has no role in the safety or operation of energy, water, transport, or comparable infrastructure.

**3. Education and vocational training.** Not in scope. The system plays no part in admissions, assessment, or any decision affecting access to education or training.

**4. Employment, workers management, and access to self-employment.** Not in scope. The users are compliance and risk professionals who operate the system as a tool; it does not evaluate them, and it takes no part in hiring, firing, promotion, or task allocation decisions about any worker.

**5. Access to and enjoyment of essential private and public services and benefits.** Not in scope for the triage system itself, with one nuance that matters. The system classifies a vendor relationship; it does not make the credit, insurance, or benefits decision that a vendor's AI might. If a deploying organization uses this system to triage a vendor whose AI affects customer-facing financial decisions such as credit scoring or insurance underwriting, that vendor's AI may itself fall under this category, and the deploying organization owns that separate Annex III classification. Triaging the relationship does not discharge it.

**6. Law enforcement.** Not in scope. The system has no law enforcement function and produces no output used in policing, investigation, or prosecution.

**7. Migration, asylum, and border control management.** Not in scope. The system plays no part in immigration, asylum, or border processes.

**8. Administration of justice and democratic processes.** Not in scope. The system informs no judicial decision and has no role in elections or democratic processes.

**Cumulative classification.** The vendor-risk-triage system is not a high-risk AI system under EU AI Act Annex III. It is a limited-risk system supporting an internal compliance workflow. It remains subject to the EU AI Act's general transparency obligations for AI systems, but not to the conformity assessment, registration, or post-market monitoring requirements that attach to Annex III systems. This classification holds only while the human-in-the-loop disposition flow defined in 00-problem-definition.md is preserved. A deploying organization that automates dispositions without human review must re-evaluate the system's classification under the EU AI Act.

This classification reflects the system in isolation. It does not classify the vendors being triaged or their AI systems. Each triaged vendor must be classified separately.

## NIST AI RMF mapping

The NIST AI RMF organizes AI risk work into four functions. The system touches all four but owns none outright; it operationalizes work that human governance still directs. This section receives lighter treatment than the EU AI Act and OSFI mappings because NIST AI RMF is voluntary; deploying organizations bound by it through contract or audit expectation will need to do more specific function-by-function mapping than what this reference provides.

**Govern.** The system supports governance by producing durable, examinable records of every triage decision and its reasoning. It does not replace governance accountability; it gives that accountability something concrete to act on.

**Map.** The system maps vendor AI capabilities to internal risk categories. The Phase 0 documentation in this repository, including this file, defines that mapping.

**Measure.** The system produces measurable outputs: a risk tier, a recommended disposition, documented reasoning, and a confidence signal on the classification. Those artifacts ship with the system rather than being reconstructed after the fact.

**Manage.** The system enables risk management through human-in-the-loop review for elevated cases, logging of every triage decision, and a defined escalation path to senior human review.

## OSFI Guideline E-23 mapping

OSFI Guideline E-23 takes effect May 1, 2027 and applies to every federally regulated financial institution in Canada. It extends model risk management to AI and ML systems explicitly and pulls third-party model risk under Guideline B-10. For a Canadian FRFI, this is the framework that turns vendor AI triage from good practice into an examination expectation.

**Model inventory.** Triage records feed the institution's enterprise model inventory for third-party AI systems, giving each vendor model an entry rather than leaving it uncounted.

**Risk-based classification.** The system's tiers align with E-23's expectation that risk ratings reflect complexity, autonomy, data sensitivity, and customer impact.

**Third-party model oversight.** The system operationalizes B-10's requirements for assessing vendor AI risk at intake and on review.

**Lifecycle governance.** Triage records carry version metadata, supporting the lifecycle controls E-23 expects across a model's life.

**Documentation.** Structured triage outputs support board-level reporting and regulatory examination readiness.

The system is one component of E-23 compliance, not a complete solution. Full E-23 readiness requires governance artifacts out of scope here: an enterprise model risk management policy, model approval workflows, and independent validation procedures among them.

## NAIC Model Bulletin and SR 11-7

**NAIC Model Bulletin.** The Model Bulletin on the Use of Artificial Intelligence Systems by Insurers, adopted by the NAIC in late 2023 and since enacted as binding regulation in roughly 25 states, sets regulatory expectations for insurers using AI, including AI obtained from third parties. The system contributes to insurer compliance by documenting third-party AI risk assessments in a consistent, examinable format.

**SR 11-7.** The Federal Reserve's 2011 guidance on model risk management predates the current AI wave and is not AI-specific, but its requirements for model inventory, validation, and ongoing monitoring apply to AI-based vendor systems. The system produces artifacts consistent with SR 11-7 expectations for third-party model risk.

## Internal risk taxonomy

Underneath the regulatory mappings, the system runs on a four-tier taxonomy. Each tier carries a typical disposition, so a classification points at a next step, not just a label.

**Tier 1, low risk.** The vendor uses AI in roles that support no decision: internal productivity, summarization, search. No customer data flows to the vendor's AI, and standard contractual protections cover the relationship. Typical disposition: approve with standard documentation.

**Tier 2, moderate risk.** The vendor uses AI in operational decisions that shape internal workflows but not customer outcomes. Customer data may reach the vendor's AI under appropriate contractual constraints. Typical disposition: conditional approve with named mitigations and quarterly review.

**Tier 3, elevated risk.** The vendor uses AI in customer-affecting decisions, processes regulated PII through LLMs, or operates as an agentic system that takes actions in production environments without human confirmation on each action. Typical disposition: escalate to senior human review with documented risk acceptance and a named accountable owner.

**Tier 4, high risk.** The vendor uses AI in decisions under direct regulatory scrutiny: credit, underwriting, fraud detection, hiring, or any EU AI Act Annex III category. Typical disposition: senior management or risk committee approval, comprehensive contractual protections, and ongoing monitoring.

Tier assignment is a judgment, not a measurement. Two competent practitioners can place the same vendor in adjacent tiers and both defend the call, because the inputs are disclosures and context rather than hard numbers. The system's value is consistency within an organization, not objective truth: the same vendor, reviewed twice, lands in the same tier for the same reasons.

## Limitations of this document

This is a v0.1 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage. It will change as the implementation phases ship and as practitioners with deeper experience in regulatory examination, model validation, or vendor risk point out what I have missed.

The EU AI Act analysis reflects the system in isolation, and the boundary noted above applies: each triaged vendor must be separately classified by the deploying organization. The OSFI E-23 mapping is a starting point; actual E-23 compliance requires institution-specific implementation that is out of scope here. Risk taxonomies are inherently judgmental, and the four tiers above are calibrated for a generic mid-market regulated company. Real deployment will require recalibration.

This is practitioner methodology, not legal advice. Production deployment requires legal review and regulatory examination preparation alongside any framework like this. Detailed exclusions about what this system does not decide live in 02-out-of-scope.md.

## Status

Phase 0 (Discovery & Risk Classification) of the sitkastack Framework, in progress as of May 21, 2026. Roadmap: sitkastack.com/roadmap.
