# Customization Guide

This document walks through customizing the framework for a specific deploying organization. It is written for a consultant or implementation engineer running a deployment engagement; the customer's internal engineer can read it too, but the prose addresses the person making the customization decisions.

The framework ships defaults that fit a Canadian fintech facing OSFI E-23. Every other deployment context needs adjustments. This document names which adjustments matter, what intake information drives each one, and where in the codebase the adjustment lands.

## How to use this document

Read it once end-to-end before starting your first engagement. On subsequent engagements, work through Section 1 (intake) with the customer in week 1, then make Section 2 (decisions) and Section 3 (extension points) your week-2 implementation reference.

Section 4 (worked example) is a fully-walked-through hypothetical engagement; treat it as an answer key when your own customer's decisions feel ambiguous. Section 5 (anti-patterns) is the list of customizations to refuse.

The framework's value depends on the customizations being deliberate. A blanket "use defaults" deployment will produce technically valid output that does not match the deploying organization's actual review workflow. The default is a starting point, not a destination.

## 1. Intake checklist

Six questions, asked in order, in the first customer engagement meeting. Each answer drives one or more configuration decisions in Section 2.

### 1.1 Jurisdiction and regulatory framework mix

Ask: "What jurisdictions does your organization operate in? What regulatory frameworks govern your AI vendor risk decisions?"

Expected answers:

- **Canadian deposit-taking institution**: OSFI E-23 is primary. Likely also PIPEDA, PCMLTFA (AML), and any provincial securities regulator. Recent OSFI Cyber Security Self-Assessment guidance applies.
- **US deposit-taking institution**: SR 11-7 for model risk, OCC bulletins, plus state regulators. SOX/ICFR for public companies.
- **US insurer**: NAIC Model AI Bulletin, state insurance department guidance, plus SOX if publicly traded.
- **EU financial services**: EU AI Act (especially Annex III high-risk categories for creditworthiness, insurance pricing, fraud detection). DORA for operational resilience. GDPR for any PII flow.
- **Global SaaS company with AI features**: SOC 2 for trust services, EU AI Act for EU customer-facing features, NIST AI RMF as the voluntary framework most likely to be requested by enterprise buyers.
- **Multi-jurisdictional**: name the primary regulator (the one a regulator-facing decision must defend to), then the secondaries.

What you are listening for: the customer's existing language for "which framework applies." If they say "OSFI" without elaboration, they mean E-23 today and they expect you to know that. If they say "we're SOC 2 Type II so we should be fine," they are conflating a security attestation with a regulatory framework, and you have a longer education conversation ahead.

Output: a list of frameworks the agent should treat as authoritative context, mapped to corpora the deployment must source.

### 1.2 Existing risk taxonomy

Ask: "Do you have an existing risk-tier taxonomy for vendors? If yes, how many tiers, what do they correspond to, and who approves at each tier?"

Most regulated organizations have something. The shape varies:

- **3-tier**: low / medium / high. Common in smaller organizations or those just maturing AI governance.
- **4-tier**: matches the framework's default. Tier 1 productivity, Tier 2 operational, Tier 3 elevated, Tier 4 regulated.
- **5-tier or 6-tier**: typically older risk frameworks adapted from operational risk or third-party risk programs. Often map "tier 5" to "prohibited" or "executive committee only."
- **Severity bands rather than tiers**: green / yellow / orange / red, or low / moderate / high / critical. Same concept, different vocabulary.
- **No taxonomy yet**: the customer is in early AI governance maturity and wants the framework to establish one. Use the default and educate them on the rationale.

What you are listening for: whether to remap the framework's four tiers to the customer's existing taxonomy, or whether to introduce the framework's taxonomy as their new internal standard. This is a customer-relationship decision as much as a technical one. Most established organizations will not adopt a new taxonomy mid-cycle; you adapt to theirs. Greenfield organizations welcome the framework's taxonomy as a starting baseline.

Output: a tier mapping table (framework tier ↔ customer tier) if remapping, or a confirmation that the customer is adopting the framework's default taxonomy.

### 1.3 Approval authority structure

Ask: "Who has authority to approve a vendor at each tier? Who must escalate? Who has authority to reject?"

This is the customer's RACI matrix for vendor risk decisions. The framework's `accountable_owner` field maps to a role name. You need the customer's role names.

Expected variations:

- **Centralized**: a single Vendor Risk Manager or Vendor Management Office approves up to Tier 2; CRO or designated officer escalates Tier 3; an Executive Risk Committee or board owns Tier 4.
- **Decentralized by line of business**: each line of business has a designated risk approver; central risk function only weighs in at Tier 3 and above.
- **Two-stage**: every classification gets a primary reviewer (often a junior analyst) and a secondary signoff at the tier-specified authority.
- **Time-bound delegations**: the CRO may delegate Tier 3 authority to a deputy for a fixed window; the framework's output should still name the CRO as accountable, with the delegate operating under delegated authority documented separately.

What you are listening for: how the deploying organization wants escalations to read in the audit pack. "Senior Vendor Risk Manager" is generic and works. "Director, Operational Risk Management - Canadian Banking" is specific and matches their RACI; use it.

Output: a mapping from tier to accountable_owner role name (used to populate the `accountable_owner` field on escalations and rejects).

### 1.4 Review cadence policy

Ask: "How often do you re-review vendor decisions by default? Are there shorter cadences for higher tiers or higher-risk vendor categories?"

The framework defaults are not policy; they are placeholders. The customer's policy answer drives the `review_interval_days` field on every triage record.

Expected answers:

- **Annual baseline**: 365 days for Tier 1 and Tier 2, 180 days for Tier 3, 90 days for Tier 4 or any vendor with active mitigations.
- **Quarterly for elevated tiers**: 90 days for Tier 3 and 4, semi-annual for Tier 2, annual for Tier 1.
- **Event-driven only**: no fixed cadence; re-review triggered by attestation expiry, vendor incident, regulatory change, or material vendor service change. Set `review_interval_days` to null and document the event-driven policy elsewhere.
- **Aligned to vendor SOC 2 attestation cycle**: re-review window matches the customer's vendor's SOC 2 reissuance date. Set per-vendor.

What you are listening for: a real policy answer, not "whatever you recommend." If the customer does not have a policy, that is itself the engagement-finding: the framework needs a cadence to populate the field, and the customer needs a policy. Start with annual for Tier 1/2 and quarterly for Tier 3/4 as a defensible default, and document that you are establishing this with the customer rather than inheriting an existing policy.

Output: a tier-keyed dict of default review intervals, plus any vendor-category overrides.

### 1.5 Documentation corpus

Ask: "Which regulatory documents do you want the agent to retrieve from? Do you have authoritative copies, or do you need us to source them?"

This is the practical corpus question. The framework's `retrieval/` package needs chunked text from each regulation the agent should treat as authoritative. The default corpus manifest ships paths and licensing notes for OSFI E-23, NIST AI RMF, EU AI Act, ISO 42001, and SOX. Anything outside that list is a per-engagement addition.

Expected outcomes:

- **Standard mix, customer has copies**: customer provides PDFs, you build the IndexBundle locally, deploy it with the framework. Fastest path.
- **Standard mix, customer needs you to source**: you build the IndexBundle from the public sources (or, for licensed corpora like ISO 42001, the customer purchases the license; you operate under their license).
- **Custom regulator**: customer is in a jurisdiction the framework does not ship for (e.g., MAS Singapore, APRA Australia, FINMA Switzerland). You build a new corpus entry from their authoritative source.
- **Industry-specific framework**: customer has a sectoral framework not in the default mix (e.g., HIPAA for healthcare, PCI DSS for payments, FERPA for education). Same pattern as custom regulator.
- **Internal policy as corpus**: customer has internal AI governance policy documents they want the agent to cite alongside external regulation. Possible; you add them to the corpus with `corpus_name="customer-internal-policy"`.

What you are listening for: licensing. ISO standards cannot be redistributed; ensure the customer holds the license before you ingest. Government documents are usually fine. Industry-association documents (like PCI DSS) sometimes are not. When in doubt, do not include in any artifact the customer's auditor might inspect.

Output: a corpus manifest entry per regulatory framework the customer wants in scope, plus authoritative file paths or sourcing assignments.

### 1.6 LLM provider

Ask: "Which LLM provider does your security organization allow? Are there data-residency or vendor-neutrality requirements?"

The framework is vendor-agnostic via PydanticAI. The default `TriageAgentConfig()` uses whatever the PydanticAI default model is at install time. In practice every customer has constraints.

Expected variations:

- **Anthropic Claude approved**: easiest path. Use the default config with explicit model identifier (e.g., `model="claude-sonnet-4"` or whatever is current). Document the model identifier in the agent_version string.
- **OpenAI approved**: pass an OpenAI model via PydanticAI's OpenAI integration. Test the framework's prompts against the chosen model; the SYSTEM_PROMPT is engineered against Claude and may need adjustment for other providers.
- **Azure OpenAI required**: customer has an enterprise Azure OpenAI deployment for compliance reasons. PydanticAI supports Azure OpenAI. Endpoint and deployment identifier go in `TriageAgentConfig`.
- **Self-hosted required**: customer runs an open-weight model in their own infrastructure. PydanticAI supports OpenAI-compatible endpoints; point the config at their inference server. Be honest about the quality tradeoff; smaller open-weight models will produce lower-quality classification rationales than Claude or GPT-4 class.
- **Multiple providers for redundancy**: customer wants fallback. Phase 6 sub-system "model fallback" addresses this; for now, document the constraint and deploy the primary provider.

What you are listening for: whether the customer wants their data to leave their network. If yes, only self-hosted or Azure-with-no-training-use is viable. If no, the choice is functional.

Output: a `TriageAgentConfig` with the model identifier, endpoint (if non-default), and any provider-specific options recorded.

## 2. Configuration decision tree

For each Section 1 answer, the corresponding framework configuration follows. This section names where the configuration lives.

### 2.1 Jurisdiction → regulatory_framework_tags and corpus

The agent's output records `regulatory_framework_tags` per decision. The schema enumerates `OSFI_E_23`, `NIST_AI_RMF`, `EU_AI_Act_Annex_III`, `NAIC`, `SR_11_7`. Anything else uses the `custom:` pattern documented in `schemas/output-contract-1.0.0.schema.json`:

```
custom:<org>:<framework_id>
```

Lowercase, hyphenated identifiers. Example: `custom:mas-singapore:guidelines-on-risk-management-tech-2021`.

For each framework in the customer's mix, build a corpus entry following `docs/corpus-manifest.md` and add the SHA-256 pin to `tests/integration/corpora_cache.py` if you intend to add integration tests. For deployment, you can skip the cache helper and load the bundle directly via `IndexBundle.load(path)`.

### 2.2 Risk taxonomy → SYSTEM_PROMPT customization

The framework's risk taxonomy lives in `SYSTEM_PROMPT` inside `agent/agent.py`. If the customer is adopting the framework's default four-tier taxonomy, no change.

If the customer is remapping to their own taxonomy:

1. Copy the framework's `SYSTEM_PROMPT` to a customer-specific variant (e.g., `agent/prompts/customer-acme.py`).
2. Edit the tier definitions to match the customer's vocabulary.
3. Bump `SYSTEM_PROMPT_HASH` (recomputed automatically from the new prompt bytes).
4. Bump `FRAMEWORK_VERSION` to a customer-suffixed variant (e.g., `0.6.0+acme.1`) so audit trails distinguish the customized deployment from upstream.

The `agent_version` string baked into every TriageRecord captures both the FRAMEWORK_VERSION and the SYSTEM_PROMPT_HASH. An auditor reviewing a customer's decisions can recover exactly which prompt produced them.

If the customer wants to keep the framework's four tiers but rename them (e.g., "Green/Yellow/Orange/Red" instead of "Tier 1-4"), that is a presentation customization, not an agent customization. Override the tier labels in the audit pack render layer rather than touching the prompt.

### 2.3 Approval authority → accountable_owner defaults

The agent does not assign `accountable_owner` for `approve` and `conditional_approve` dispositions; the schema only requires it for `escalate_senior_review`. The agent fills it in based on the SYSTEM_PROMPT's instructions and the submission context.

Customer-specific accountable_owner naming goes in the SYSTEM_PROMPT customization. Add a section like:

```
When the recommended disposition is escalate_senior_review, the accountable_owner
field must use one of the following role names from <Customer Name>'s RACI matrix:
- "Director, Operational Risk - Canadian Banking" (for Tier 3 banking-line decisions)
- "Director, Operational Risk - Wealth Management" (for Tier 3 wealth decisions)
- "Chief Risk Officer" (for Tier 4 decisions)
```

Be explicit and use the customer's actual role names. Generic strings ("Senior Vendor Risk Manager") work in default deployments but fail to land in customer audit packs.

### 2.4 Review cadence → review_interval_days defaults

Same customization point as the SYSTEM_PROMPT. Add a section like:

```
When setting review_interval_days, use:
- Tier 1: 365 days
- Tier 2: 365 days
- Tier 3: 180 days
- Tier 4: 90 days
unless the vendor's SOC 2 attestation expires sooner, in which case use the
attestation expiry minus 30 days.
```

The framework does not enforce these defaults at the code level; the agent applies them based on prompt instructions. If a customer needs hard enforcement (e.g., a regulator requires no review interval exceed 365 days), validate the field in a deploying-organization wrapper around the agent's output.

### 2.5 Corpus → IndexBundle build

Build one IndexBundle per regulation. Follow `scripts/build_corpus_bundles.py` for the pattern. The script ships configured for the framework's default mix; copy it to a customer-specific build script and add their corpora.

The customer's deployment uses `IndexBundle.load(...)` at process startup to materialize each bundle, then builds `BM25Index` and `VectorIndex` from the loaded chunks. Pass all loaded chunks (across all customer corpora) to a single `HybridIndex` so retrieval surfaces matches across the customer's full regulatory mix.

For customer internal policy documents, build an IndexBundle the same way; they are just another corpus by the framework's lights.

### 2.6 LLM provider → TriageAgentConfig

`TriageAgent(TriageAgentConfig(model="...", **provider_options))`. The provider_options shape depends on the PydanticAI integration:

- Anthropic Claude: `model="anthropic:claude-sonnet-4"` or current.
- OpenAI: `model="openai:gpt-4o"` or current.
- Azure OpenAI: `model=OpenAIModel(model_name="gpt-4o", base_url="https://yourtenant.openai.azure.com/...", api_key="...")` per PydanticAI docs.
- Self-hosted (OpenAI-compatible): same pattern as Azure with the customer's endpoint.

Test the agent's SYSTEM_PROMPT against the chosen model before deployment. The default prompt was engineered against Claude; classification quality on smaller open-weight models will be lower. If the customer's chosen model produces noticeably worse rationales, either negotiate up to a frontier-class model or adjust the prompt to compensate (more explicit instructions, more concrete examples).

## 3. Extension points (technical how-to)

Concrete code locations and patterns for the customizations above.

### 3.1 SYSTEM_PROMPT override

The default SYSTEM_PROMPT and SYSTEM_PROMPT_HASH live in `agent/agent.py` as module-level constants. To override:

```python
# customer_deployment/prompts.py
SYSTEM_PROMPT_FOR_ACME = """
You are a vendor risk triage agent. You classify vendor AI usage into a risk tier
and recommend a disposition...
[customer-specific tier definitions, accountable_owner roles, review cadences]
"""

# customer_deployment/agent_factory.py
from agent.agent import TriageAgent, TriageAgentConfig
from customer_deployment.prompts import SYSTEM_PROMPT_FOR_ACME

def build_acme_agent():
    config = TriageAgentConfig(
        model="anthropic:claude-sonnet-4",
        system_prompt=SYSTEM_PROMPT_FOR_ACME,
    )
    return TriageAgent(config)
```

The `TriageAgentConfig.system_prompt` field overrides the default. The framework recomputes `SYSTEM_PROMPT_HASH` automatically from whatever prompt is in use; the `agent_version` string flowing into every TriageRecord captures the customer-specific hash.

### 3.2 Custom regulatory_framework_tag

The output schema accepts the enumerated values plus a custom pattern:

```
^custom:[a-z0-9_-]{1,64}:[a-z0-9_-]{1,128}$
```

Use it for any framework outside the enumerated set. Examples:

- `custom:mas-singapore:guidelines-on-risk-management-tech-2021`
- `custom:apra-australia:cps-230-operational-risk-management`
- `custom:acme-internal:ai-governance-policy-v2`

No code change needed; the schema already permits the pattern. The agent prompts itself recognizes the custom tag if you instruct it to in the SYSTEM_PROMPT customization.

### 3.3 Submission schema extension

The input contract has a fixed shape. Customer-specific fields go via `extension_schema_version`:

1. Define a customer-specific JSON Schema file with the additional fields.
2. Reference the file's schema version in the submission's `extension_schema_version` field.
3. The framework's input validator accepts the extension version; downstream consumers can pull the extension schema and validate the additional fields.

Example use case: a customer's vendor intake captures `legal_entity_id` (their internal vendor master record key). Adding it to the base contract would couple the framework to one customer's vendor system. Adding it as an extension field keeps the base contract clean and lets the customer carry their internal identifier through the framework.

Do not modify `schemas/input-contract-1.0.0.schema.json` for customer-specific fields. The base schema is the framework's interoperability contract.

### 3.4 LLM swap

Per Section 2.6 above. `TriageAgentConfig(model=...)`. No other code change. The framework's `agent_version` string captures the model identifier, so an auditor reviewing decisions sees which model produced each one.

When swapping providers, run the integration test suite against the new provider (the `real_llm` marker) before promoting to production. Differences in classification quality between providers are real and worth measuring on the customer's own example submissions.

### 3.5 Custom corpus bundle

Per Section 2.5 above. The build pattern is:

```python
from retrieval import CorpusLoader, IndexBundle, SentenceTransformerEmbedder

loader = CorpusLoader()
chunks = loader.load_pdf(
    corpus_name="acme-internal-policy",
    document_name="ai-governance-policy-v2",
    content=Path("/secure/acme/policy.pdf").read_bytes(),
    sectionize=True,
)
embedder = SentenceTransformerEmbedder()
bundle = IndexBundle.from_chunks(chunks, corpus_name="acme-internal-policy", embedder=embedder)
bundle.save(Path("/secure/acme/bundles/internal-policy.bundle.tgz"))
```

At process startup, load each customer bundle and pass the union of chunks to a `HybridIndex`. See `tests/integration/test_real_corpora.py` for the end-to-end pattern.

### 3.6 Custom rubric for the LLM-as-judge

The `eval/judge/` package ships three default rubrics: rationale coherence, citation grounding, mitigation appropriateness. Customer-specific quality concerns get a custom rubric:

```python
from eval.judge import Rubric, LLMJudge

acme_specific_rubric = Rubric(
    name="acme_canadian_residency_emphasis",
    description=(
        "Verifies that classifications for vendors processing customer data "
        "explicitly address Canadian data residency in the rationale or "
        "mitigations. ACME's regulatory posture requires this to be visible "
        "in the triage record."
    ),
    criteria=[
        "The classification rationale or required_mitigations mentions data "
        "residency, cross-border data flow, or Canadian-specific localization.",
        "If the vendor's data_residency field includes any non-CA region, "
        "the rationale acknowledges the cross-border flow.",
    ],
    scoring="Score 1.0 if both criteria are satisfied. Score 0.0 otherwise.",
)
```

Run the custom rubric against the customer's expected decision set as part of pre-deployment validation. A customer-specific rubric is the right place to encode customer-specific quality expectations that the default rubrics do not capture.

## 4. Worked example: hypothetical mid-market US insurer

This section walks through a customization end-to-end. The example is hypothetical; real customers will have their own quirks. The point is to show the full sequence of intake → decision → implementation in one place.

**Customer profile**: a 5,000-employee US property and casualty insurer, publicly traded, deploying AI capabilities for claims-decisioning support and customer-service automation. Risk function reports to the CFO; AI governance is a new cross-functional group that includes the CISO, the Chief Actuary, and the General Counsel.

### 4.1 Intake answers

**Jurisdiction and frameworks**: US federal and state. Public company, so SOX in scope. Insurance regulator is the state department of insurance in each state of operation; the NAIC Model AI Bulletin is the dominant industry guidance. EU AI Act not in scope (no EU operations). NIST AI RMF requested by their largest reinsurance partner, who wants their primary insurer to align.

→ Framework mix: NAIC, SOX/ICFR, NIST AI RMF. SR 11-7 not in scope (not a bank), but the customer's actuarial team uses SR 11-7-style validation discipline so cite SR 11-7 when model risk-management language is needed.

**Existing risk taxonomy**: a 5-tier taxonomy adapted from the customer's third-party risk management program. Tiers are labeled "Minimal", "Low", "Moderate", "Significant", "Critical". Approval thresholds are the customer's existing TPRM thresholds.

→ Decision: remap the framework's 4-tier output to the customer's 5-tier taxonomy. Map: Tier 1 → Minimal, Tier 2 → Low or Moderate (depending on PII flow), Tier 3 → Moderate or Significant (depending on autonomy), Tier 4 → Significant or Critical. Document the mapping table in the customer-specific SYSTEM_PROMPT. The "Critical" tier in their taxonomy corresponds to "reject" in the framework's disposition vocabulary (regardless of underlying tier).

**Approval authority**: Minimal and Low approved by line-of-business risk officer. Moderate approved by Director, Operational Risk. Significant escalated to VP, Enterprise Risk. Critical escalated to the AI Governance Committee.

→ accountable_owner mapping in the SYSTEM_PROMPT:
- Tier 1 / Minimal: "Line of Business Risk Officer"
- Tier 2 / Low: "Line of Business Risk Officer"
- Tier 2 / Moderate: "Director, Operational Risk"
- Tier 3 / Significant: "VP, Enterprise Risk"
- Tier 4 / Critical: "AI Governance Committee"

**Review cadence**: annual default. Significant and Critical revisited at 90 days. Vendors with active mitigations re-reviewed when the next mitigation deadline approaches.

→ review_interval_days:
- Tier 1: 365 days
- Tier 2: 365 days
- Tier 3: 90 days
- Tier 4: 90 days
Overrides for active mitigations handled by the customer's vendor management system; the framework records the default and the customer's system tracks actual.

**Corpus**: customer has NAIC Model AI Bulletin and SR 11-7 in their existing policy library. NIST AI RMF is public. SOX statute is public. Customer has internal AI governance policy v1.2 they want cited where applicable.

→ Corpus bundles to build:
- `naic-ai-bulletin` (from customer's library)
- `sr-11-7` (from customer's library; also publicly available)
- `nist-ai-rmf` (public; use the framework's existing build script)
- `sox-pl-107-204` (public; use the framework's existing build script)
- `acme-internal-ai-governance-v1-2` (from customer)

**LLM provider**: customer's security org has approved Azure OpenAI with their tenant's data-processing addendum (no training use, US data residency). They have not approved Anthropic.

→ TriageAgentConfig with Azure OpenAI endpoint:
```python
TriageAgentConfig(
    model=OpenAIModel(
        model_name="gpt-4o",
        base_url="https://acme-tenant.openai.azure.com/openai/deployments/gpt-4o-prod",
        api_key="...",
    ),
)
```

### 4.2 Configuration produced

A single customer-deployment repo, structured as:

```
acme-vrt-deployment/
├── pyproject.toml                  # declares dependency on sitkastack-vrt
├── acme/
│   ├── prompts.py                  # customer-specific SYSTEM_PROMPT
│   ├── agent_factory.py            # build_acme_agent() returns a configured TriageAgent
│   ├── corpus_loader.py            # loads the five bundles, builds HybridIndex
│   └── rubrics.py                  # acme_canadian_residency_emphasis and similar
├── corpora/
│   ├── naic-ai-bulletin.bundle.tgz
│   ├── sr-11-7.bundle.tgz
│   ├── nist-ai-rmf.bundle.tgz
│   ├── sox-pl-107-204.bundle.tgz
│   └── acme-internal-ai-governance-v1-2.bundle.tgz
└── schemas/
    └── acme-extension-1.0.0.schema.json    # customer-specific submission fields
```

The framework is unchanged. Everything customer-specific lives in the deployment repo.

### 4.3 Audit pack for a triage decision

The customer triages a vendor: a third-party claims-image-analysis service that reads photos of accident damage and produces structured estimates. The agent classifies as Significant (framework Tier 3) with disposition escalate_senior_review. accountable_owner: "VP, Enterprise Risk". review_interval_days: 90.

The audit pack renders with the customer's attribution footer (the framework default replaced):

```python
from reporting import save_audit_pack

save_audit_pack(
    record=triage_result,
    submission=vendor_submission,
    path="/acme/vendor-decisions/2026-q2/vendor-photolens-001.html",
    attribution_footer=(
        "Confidential. ACME Insurance Risk Management. "
        "Vendor risk classification per Enterprise Risk Policy 4.2. "
        "Decision ID and timestamp travel with this record."
    ),
)
```

The customer's risk committee opens the HTML in their browser. The rendered document shows:

- Banner: "Escalate to senior review: Tier 3 (elevated)" with the customer's vendor name
- Metadata strip with vendor ID, jurisdiction (US-NY for the underwriting line), classification (SaaS), AI usage level (operational_decisions), decision ID, decision timestamp, next review (90 days)
- Classification rationale referencing the cross-line operational use, the PII flow through the third-party vision model, and the AI's role as input to the human claims adjuster (with the adjuster as the final decisioner)
- Evidence table citing $.ai_usage_level, $.pii_processing_claims.categories, the model card disclosure of training data, and the data residency conditions
- Required mitigations naming five items including SOC 2 confirmation, the customer's internal Data Sharing Agreement v3, model accuracy monitoring, and quarterly bias review
- Accountable owner: "VP, Enterprise Risk"
- Confidence pill: 0.77 (moderate)
- Regulatory frameworks engaged: NAIC, NIST AI RMF, custom:acme-internal:ai-governance-policy-v2
- Audit trail showing decision_id, decision_timestamp, input_submission_id, agent_version capturing both the FRAMEWORK_VERSION and the customer-specific SYSTEM_PROMPT_HASH

The customer's attribution footer replaces the default sitkastack credit. The document reads as ACME's own.

## 5. Anti-patterns

Customizations to refuse, with reasons.

### 5.1 Modifying the base input contract or base output contract

The schemas in `schemas/` are the framework's interoperability contracts. Modifying them in a customer deployment breaks the framework's audit-traceability story: a TriageRecord produced under a modified schema cannot claim to conform to `1.0.0`, and any downstream tooling that expects 1.0.0 conformance (the audit pack renderer, the eval harness, future regulator-facing adapters) will silently produce wrong output.

Use `extension_schema_version` instead. The base schemas are stable across deployments.

### 5.2 Disabling evidence_cited requirements

The framework requires evidence_cited to be non-empty for every record. The output contract enforces this; the agent's prompt instructs it; the citation verifier audits it.

Customers occasionally ask to relax this for vendors with no documentation provided (the "we already know this vendor, just classify it" case). Refuse. A classification without cited evidence is not auditable. If the customer wants to fast-path certain vendors, that fast-path lives in their vendor-management workflow upstream of the framework, not in the framework itself.

### 5.3 Suppressing confidence_signal calibration

The framework records a confidence score on every decision and runs calibration metrics in the eval harness. Customers sometimes want to remove or hide confidence from the audit pack ("we don't want our reviewers to see the AI's uncertainty"). Refuse.

The confidence score is part of the audit signal. A reviewer's job is to apply more scrutiny when confidence is moderate or low. Suppressing the score makes the framework less audit-defensible, not more. If the customer's reviewers do not know how to interpret confidence, that is a training need, not a UI need.

### 5.4 Baking customer-specific logic into the agent module

The agent's job is to classify and produce a record. Customer-specific routing, escalation workflows, vendor-master integration, and notification logic all belong in the deploying organization's wrapper around the agent, not in the agent module.

If the customer wants "when disposition is escalate_senior_review, file a ticket in their ServiceNow instance," that ticket-filing is application logic that lives in their deployment, not in the framework. Keep the agent module deployable across customers; only the SYSTEM_PROMPT changes between deployments.

### 5.5 Sourcing licensed corpora without confirming the license

ISO 42001, certain industry standards, paywalled research, paid newsletters. Do not ingest these into a customer's corpus until the customer has confirmed they hold the license. The customer's deployment depends on the corpus being defensible if an auditor asks "where did this regulation text come from."

When in doubt, do not ingest. The framework operates with one less corpus rather than one corpus that creates downstream legal exposure.

### 5.6 Promising the framework eliminates human review

The framework recommends; humans decide. Every disposition value is a recommendation to a human reviewer. A customer that wants to deploy the framework as autonomous decisioning has misunderstood the framework's purpose, and you should not deploy it for them. The classification rationale, evidence citations, mitigations, and audit trail exist because they are the inputs to a human review, not because they are evidence of an AI-replaces-human pattern.

This is the most important anti-pattern to refuse cleanly. The framework's defensibility argument depends on the human being the decisioner. Any deployment that erodes this is a deployment the framework should not be in.

## Engagement deliverables checklist

At the end of a customization engagement, the customer should have:

- A deployment repo containing their customer-specific SYSTEM_PROMPT, agent factory, corpus bundles, extension schema (if any), and custom rubrics
- A signed-off mapping document recording the intake-question answers and the configuration that follows from each
- A successful pre-deployment test run against the customer's expected example submissions, with the custom rubrics passing
- A documented integration with the customer's vendor management workflow (intake, decisioning, re-review triggers)
- A first-pass calibration measurement on the customer's actual decisions (or a documented plan to collect calibration data once the framework is in production)
- A clear handoff document naming who owns SYSTEM_PROMPT updates, corpus refreshes, model version upgrades, and the eval-harness regression cadence

The handoff document is the artifact that determines whether the customization survives staff turnover. Write it as if the customer's risk team has full turnover six months after deployment, because eventually it will.
