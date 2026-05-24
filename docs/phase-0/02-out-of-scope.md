# Out-of-Scope

This document is the companion to 00-problem-definition.md. That document fixes the single decision the system supports. This one draws the line around everything it leaves to someone else.

## Why this document exists

Most AI projects never write this document. The team is busy proving the thing works, the demo lands, and scope lives in people's heads or a Slack thread that scrolls away. Everyone in the room already knows what the system is not for, so no one records it.

The trouble starts when people who were not in that room start using the output. A risk analyst reads a clean triage record as sign-off. A sponsor sees "low risk" and assumes legal cleared the contract. The system claimed neither, but the failure mode has a name: capability assumption, where a tool inherits authority no one granted it. The vendor goes live, and months later someone is explaining to an auditor why a triage note was treated as a control.

An unstated boundary reads as coverage.

So I treat the out-of-scope document as the highest-leverage artifact in the build. It forces explicit ownership of every decision the system does not make, the only reliable way to keep those decisions from drifting to the system by default. Every Phase 0 here ships one before any code is written, because naming the boundary first is cheaper than discovering it in production.

What follows is the boundary, written down. Each exclusion names the decision the triage agent does not make, and the function or named person who owns that decision instead. Read these as load-bearing, not as a disclaimer.

## Decisions this system does not make

Problem Definition establishes that every disposition the system recommends is a human decision. These are the specific decisions that stay with people and functions other than the triage agent.

**1. Procurement decisions stay with procurement.** The system classifies AI risk and recommends a disposition, but the choice to bring a vendor in runs far wider than that risk. Procurement and the business sponsor own it.

**2. Legal liability stays with legal.** The system can flag exposure in a vendor's data handling, but contractual interpretation and fault allocation are in-house counsel's work, and they need to remain so even when the triage record makes the issues feel clear.

**3. Security validation is the InfoSec team's work.** The system reads a vendor's security claims; it does not test them through penetration tests, SOC 2 review, or control verification. A clean triage record is a statement about disclosed AI practices, not about whether the vendor's controls actually work.

**4. Financial risk belongs to procurement and finance.** The system scopes AI risk, not the vendor's balance sheet, business continuity, or concentration risk. A favorable AI risk tier says nothing about whether the vendor is financially sound enough to rely on.

**5. Exceptions belong to accountable humans.** When a vendor lands in a tier that would block or condition an engagement, the agent only documents the risk. An accountable risk owner with documented authority owns the exception, with the rationale recorded and the trade-off named.

**6. The system of record is somewhere else.** The agent records its reasoning but is not the system of record for the underlying questionnaires, reports, and contracts. The document management system or GRC platform retains that evidence; the triage record references it rather than replacing it.

**7. Termination is a vendor management decision, not a triage signal.** The agent can flag risks serious enough to end a relationship, but it does not trigger offboarding. The contractual obligations, transition planning, and continuity consequences of termination belong to vendor management with input from the business sponsor.

## Populations this system does not cover

**1. Vendors not using AI.** The triage agent activates only when a vendor discloses or is found to use AI that touches the organization's data or decisions. Standard third-party risk processes, owned by the existing vendor management or TPRM program, apply otherwise.

**2. Internally-developed AI systems.** This system covers third-party AI only; in-house models raise builder-side questions a buyer's lens does not fit. A separate governance process, owned by the teams that build and operate them, covers internal builds.

**3. Foundation model providers being used directly.** Consuming a foundation model directly through an API or platform agreement is a platform decision with broad downstream reach, not a single vendor intake. Senior engineering or technology leadership owns that review, typically with input from security, legal, and the relevant business sponsor.

**4. Open-source AI components without commercial vendor backing.** The agent assumes a commercial counterparty to question and hold accountable; open-source AI shifts the questions toward provenance, maintenance, and license terms. The engineering and security functions that maintain those components own that adoption. FRFIs and other regulated organizations retain governance obligations for open-source AI in their environment; this system does not satisfy those obligations.

**5. Embedded AI in physical devices or IoT.** Hardware-embedded AI raises safety, supply chain, and physical security questions beyond document-based triage, and the agent does not evaluate firmware or device integrity. The teams responsible for device safety and supply chain security own it.

## Time periods and scope boundaries

**1. The triage decision reflects vendor state at the time of review.** The system evaluates the documentation in front of it on the day it runs; last quarter's clean triage is not evidence about this one. The third-party risk function (vendor management, TPRM, or equivalent) owns ongoing monitoring and periodic re-triage.

**2. Historical vendor decisions are not retroactively re-evaluated.** Standing up this system does not reopen vendors approved before it existed; the agent runs forward from adoption. Legacy vendor remediation is a separate, scoped effort owned by vendor management and risk.

**3. The system does not predict future vendor behavior.** A classification describes current and disclosed practices, not a forecast of what a vendor will do next. The business sponsor and vendor management own that watch through ongoing oversight.

**4. Mid-engagement vendor changes are not auto-detected.** Once a vendor is in use, the agent does not watch for new AI features, changed terms, or quiet model swaps. The business sponsor or vendor management monitors those changes and can request a re-triage.

## Integration points this system does not have

**1. No direct integration with vendor systems.** The agent reads documentation and disclosures; it does not connect to vendor APIs or run a vendor's AI live. The InfoSec team owns any live testing.

**2. No automated procurement system changes.** The agent produces records as artifacts; nothing reaches procurement systems, contract management, or vendor master data without a human moving it there. Procurement and vendor management own the systems of record.

**3. No automated alerts to vendors.** The triage process is internal: the system does not email vendors, request clarifications, or notify them of an outcome. The procurement or vendor management team owns all vendor-facing communication.

**4. No integration with the customer-facing application stack.** This system supports vendor intake decisions, not runtime decisions inside customer-facing applications. The product and engineering teams own those runtime decisions.

The exclusions above describe what the system does not do. The exclusions below describe what the system's outputs do not guarantee, which is a different category of out-of-scope and the one most likely to be misread under audit.

## Levels of assurance this system does not provide

**1. The triage record is not a regulatory attestation.** The output is internal documentation built to hold up when an auditor asks how a decision was made, not a regulatory filing or public statement. The compliance function that signs and submits owns any attestation.

**2. The risk classification is not a substitute for vendor SLAs or contractual protections.** A favorable tier does not reduce the need for service levels, data protection clauses, and audit rights that bind a vendor. Legal owns contractual protections at every risk tier.

**3. The system does not certify the regulatory compliance of the vendor.** It assesses risk to the organization; it does not declare the vendor compliant with any law or standard. A vendor's compliance rests on its own attestations, which compliance and legal confirm.

**4. The system does not replace independent model validation.** Where frameworks such as OSFI E-23 or SR 11-7 require independent model validation, a triage record does not satisfy that requirement. Qualified internal or external reviewers, separate from the triage process, own that validation.

## When this list should be revisited

New regulatory requirements, new vendor patterns, and lessons from operating the process push items in and out of scope. A quarterly revisit is reasonable for most mid-market organizations. Specific events should also trigger an off-cycle revisit: a new regulatory framework takes effect (OSFI E-23 in May 2027 is the most concrete near-term example); a vendor pattern emerges that does not fit existing categories, such as cross-system AI agents or vendor-of-vendor AI exposure; or an audit finding surfaces a boundary issue this list did not anticipate.

The list also contracts as the system grows. When a later phase adds a capability the system genuinely supports, the matching exclusion comes off and the change gets recorded in the same commit history as the new capability.

## Limitations of this document

This list reflects the v0.3 reference implementation. Real deployments will carry their own context-specific exclusions, shaped by sector, regulators, and internal structure that this document cannot anticipate.

The most useful feedback comes from practitioners who have seen the failure modes I haven't. If an exclusion belongs here and isn't, open a GitHub issue.

## Status

Phase 0 (Discovery & Risk Classification) of the sitkastack Framework, complete as of May 23, 2026. Roadmap: sitkastack.com/roadmap.
