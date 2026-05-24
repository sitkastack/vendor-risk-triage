# Synthetic Data Specification

This document specifies the synthetic dataset the reference implementation uses for testing, demonstration, and the eval set Phase 3 (Build & Eval) will build on. It is the sixth and final Phase 1 artifact. Every synthetic record conforms to the input contract in 02-input-contract.md, exercises the record shape in 03-output-contract.md, and respects the rules in the privacy and data handling spec, because synthetic data is what lets the rest of Phase 1 be tested without touching a real vendor or a real customer.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## Why synthetic data

The reference implementation cannot run on real vendor or customer data. The privacy and data handling spec excludes it, and a public project that shipped with real submissions would leak exactly the information a vendor risk process exists to protect. Synthetic data is the only corpus this work can use in the open.

Working against synthetic data lets the agent, the contracts, and the eval methodology develop against realistic scenarios with no privacy exposure. An engineer can run the agent end to end and exercise the contracts against documents that resemble real submissions, without a data processing agreement standing between the work and a test run.

The same corpus is the basis for the Phase 3 eval sets, so its quality sets a ceiling on what the system can be tested against. A corpus that omits a vendor pattern cannot reveal how the agent handles it, and gaps in the data become blind spots in the evaluation.

## What the synthetic dataset must contain

The dataset has to cover the input contract's full range, not a comfortable subset. Every value of vendor_classification appears: SaaS, infrastructure, model_provider, embedded_AI, and hybrid. So does every value of ai_usage_level, from none and productivity_only through operational_decisions and customer_facing up to regulated_decisions. A corpus of only SaaS vendors doing productivity-only AI tests one corner of the system and leaves the rest unmeasured.

Jurisdictions span at least Canada, the US, the EU, and the UK, the four the Phase 0 mapping leans on most, and ideally more for organizations deploying under additional regimes. Jurisdiction drives which frameworks apply, so a dataset thin on EU or Canadian vendors cannot exercise the EU AI Act or OSFI E-23 paths the classification logic depends on.

The records spread across all four risk tiers rather than clustering. A corpus that is all Tier 1 never tests an escalation, and one that is all Tier 4 never tests the routine approve path that most real intake actually follows. A spread weighted toward the middle tiers, with real examples at both ends, gives the system something to classify across its whole range.

Beyond the clean cases, the dataset carries the hard ones: borderline classifications that could defensibly land in either of two tiers, submissions missing optional fields, vendors whose disclosures conflict with each other, and malformed submissions that should fail validation. Every well-formed record conforms to the input contract in 02-input-contract.md, and the malformed ones are included because a contract is only as trustworthy as its behavior on input that breaks it.

## Realism requirements

Synthetic data has to look like real vendor documentation: plausible fictional vendor names, AI feature descriptions written the way a vendor would write them, and compliance attestations naming real frameworks with realistic types and dates. A reviewer should not be able to tell at a glance that a record was generated rather than submitted.

Vocabulary, structure, and detail should match what real vendors send. Real questionnaires hedge, omit, and over-claim, and real model cards range from thorough to thin. Data that is uniformly clean and complete trains the system on a world that does not exist and leaves it unprepared for the one that does.

Obviously synthetic data does not exercise the system the way real data would. Lorem ipsum, placeholder values, and repeated boilerplate let the agent pattern-match on the placeholder instead of reasoning about the content. This corpus is what the agent is developed against, so its quality compounds into everything built on top of it.

## Anti-patterns to avoid

No real personal information, in any field, even where the schema expects a person. A synthetic primary_contact is a fictional person with a fictional email, not a real name borrowed from a colleague or a public figure. The dataset is public, and a real email address in a synthetic record is a real leak.

No real company names, including public ones. Apple, Google, and their peers do not appear, even as examples, and the dataset uses fictional analogues instead. Naming a real vendor implies a real risk classification of it, which is both wrong and a statement this project has no business making.

No real proprietary documentation. The dataset is generated independently, not adapted from a real vendor's SOC 2 report or questionnaire, so nothing in it traces back to a document someone else owns. Each record must be plausibly attributable to no real entity.

Consistency holds across records. If two synthetic records reference the same fictional company, its name, jurisdiction, and disclosed AI use match between them. A fictional vendor that is a SaaS company in one record and a hardware maker in another turns the inconsistency, not the agent's reasoning, into what the test measures.

## Generation methodology

Synthetic data is produced through a documented pipeline, not assembled by hand in an undocumented way. The pipeline can be LLM generation with human review, structured templates filled programmatically, or a combination, but whichever it is, it is written down. How the corpus was made is part of what makes it trustworthy.

Every record carries metadata marking it synthetic, so it can never be mistaken for a real one if the dataset is ever loaded alongside production data. The marker travels with the record the way the schema version does.

The pipeline is itself auditable, documented well enough that someone can see how a given record came to exist and rerun the process to produce more. Phase 3 adds eval-specific requirements such as graded labels and held-out splits; this spec defines the base corpus those eval sets draw from.

### A reference pipeline

The spec stays neutral on which generation approach to use, but a workable reference pipeline looks much the same across institutions. Naming its stages helps an engineer or a PM scope the work before committing to any tool. The institution's choice is the technology inside each stage, not the stages themselves.

1. **Scenario design.** The institution decides which vendor patterns the corpus must cover: which classifications, which AI usage levels, which jurisdictions, which risk tiers, and which edge cases. The coverage requirements named earlier in this spec drive this stage. The output is a scenario inventory the rest of the pipeline generates against.

2. **Record generation.** For each scenario, the pipeline produces one or more candidate records. The mechanism is the institution's choice: an LLM with a structured prompt that references the input contract, programmatic templates with parameterized fields, or a hybrid where structure comes from templates and free-text fields come from a model.

3. **Validation.** Every candidate record passes through the input contract's schema validator before it enters the corpus. Records that fail are either corrected and re-validated, or routed to the explicitly invalid portion of the corpus when the intent was to generate a malformed test case. A candidate that fails for the wrong reason is thrown out.

4. **Realism review.** Records that validate are reviewed for plausibility against what a real vendor would actually submit. In this reference pipeline the reviewer is a human, often the engineer who built the pipeline. Records that read as obviously synthetic, repeat boilerplate, or violate the anti-patterns named earlier in this spec go back for regeneration.

5. **Metadata and storage.** Approved records carry metadata identifying them as synthetic, naming the pipeline version that produced them, and recording when the scenario they cover entered the inventory. The corpus is stored alongside the schemas it validates against and versioned in the same repository, so any past corpus is reconstructable.

The pipeline as described assumes manual realism review; later phases automate parts of it. The choices inside each stage, which model, which templates, which reviewer, are the institution's. What this spec requires is that the stages exist, that each is documented, and that the corpus carries metadata showing how each record came to exist.

## Validation against the contracts

Every well-formed synthetic record validates against the input contract in 02-input-contract.md. Generation is finished not when a record looks right but when it passes the same validator that gates real intake. Records that fail are flagged and either corrected or, where they are meant to be malformed test cases, moved into the explicitly invalid portion of the corpus.

Generating the corpus is itself a stress test for the contract. When a realistic vendor scenario cannot be expressed as a conforming record, a schema gap has surfaced as a generation problem, and it is cheaper to find here than in production.

## Versioning and lifecycle

The synthetic dataset is versioned alongside the schemas it conforms to. A major change to the input contract triggers a dataset update, because records generated against an old schema may no longer validate against a new one. The dataset version and the schema version move in step.

Old synthetic data is preserved rather than discarded, so a decision made against an earlier corpus can be re-run and compared, which is what regression testing needs. The dataset grows over time, with Phase 3 adding eval-specific records on top of this base rather than replacing it.

## Limitations of this spec

This is a v0.3 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as the dataset itself ships and as engineers point out gaps in the coverage it asks for.

This document specifies the requirements for the synthetic dataset; it is not the dataset. The corpus is a separate Phase 1 deliverable that ships with subsequent commits, and meeting these requirements in practice is harder than stating them here.

This is practitioner methodology, not a turnkey corpus. A deploying organization will have synthetic data needs that extend this baseline, shaped by its own vendor categories and the regimes it operates under. The requirements here are the floor, not the whole of what a real deployment needs.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, complete as of May 23, 2026. Roadmap: sitkastack.com/roadmap.
