# End-to-end example

This walkthrough follows a single vendor submission through the entire framework: classification, the produced audit record, audit-pack rendering, and migration. It is the concrete picture of how the twelve packages compose into one pipeline.

The flow is:

```
submission JSON
   -> triage (tenant-scoped agent)
      -> TriageRecord (validated against output contract 1.3.0)
         -> audit pack HTML (the human-readable, auditor-facing artifact)
         -> migration (carry older records forward when needed)
```

Every stage is exercised end to end by `tests/test_e2e.py`; this document is the narrated version of those scenarios.

## 1. The input: a vendor submission

A submission is a JSON document conforming to the input contract. The framework ships five example submissions under `examples/submissions/`, one per risk archetype. Each describes a vendor's AI usage, data handling, jurisdiction, and the compliance attestations they have provided. The submission is the only input the agent reads; every conclusion the agent reaches must trace back to a field in it.

## 2. Classification: tenant-scoped triage

In a consultancy deployment, you build one agent per client and reuse it:

```python
from agent.agent import TriageAgent
from tenancy import TenantRegistry

registry = TenantRegistry.from_json_file("tenants.json")
agent = TriageAgent.for_tenant(registry.get("acme-bank"))

record = agent.triage(submission)
```

The agent classifies the vendor into a risk tier, recommends a disposition (approve, conditional approve, escalate, or reject), writes a rationale, cites the specific submission fields its reasoning rests on, and emits a confidence signal. The framework wraps that reasoning with the metadata an audit needs: a unique decision id, a timestamp, the agent version, the tenant id, and the output-contract version.

The agent's reasoning is the LLM's job; everything else is Python-controlled. In particular the system prompt is uniform across every tenant, so the agent version (which encodes the prompt hash) is identical regardless of which client the agent serves. That is the property an auditor relies on: every client's decisions came from the same version-pinned reasoning.

## 3. The output: a validated audit record

The produced record is a `TriageRecord` declaring output contract `1.3.0`. Its shape, for a moderate-risk conditional approval:

```json
{
  "decision_id": "d-c5aaabd3-...",
  "decision_timestamp": "2026-05-28T...Z",
  "input_submission_id": "...",
  "input_schema_version": "1.0.0",
  "agent_version": "vrt-agent-v0.12.0-...-prompt-69ef583c6dbe",
  "tenant_id": "acme-bank",
  "output_schema_version": "1.3.0",
  "risk_tier": "tier_2_moderate",
  "recommended_disposition": "conditional_approve",
  "classification_rationale": "The vendor processes limited PII ...",
  "evidence_cited": [
    {"input_field_reference": "$.ai_usage_level", "reasoning": "..."},
    {"input_field_reference": "$.data_residency", "reasoning": "..."}
  ],
  "confidence_signal": {"score": 0.78, "interpretation": "moderate"},
  "required_mitigations": ["Obtain a signed data-processing addendum ..."]
}
```

The record validates against the framework's output contract. Note the `tenant_id` (required as of 1.3.0, every record attributable to exactly one client) and the `agent_version` ending in the system-prompt hash (`69ef583c6dbe`, identical across all tenants).

The framework can also evaluate the record it just produced. The same record flows through:

- **Citation verification** (`eval.citations`): every `input_field_reference` is checked to resolve against a real path in the submission, and the rationale is scored for grounding in the cited evidence.
- **Calibration** (`eval.calibration`): across many records, confidence scores are checked against outcomes, surfacing over- or under-confidence.
- **LLM-as-judge** (`eval.judge`): a separate model grades the agent's reasoning on coherence, citation grounding, and mitigation appropriateness.

These are the framework's own quality controls running on its own output, which is what lets a deployment make claims about decision quality rather than just decision volume.

## 4. The deliverable: an audit pack

The record renders to a self-contained HTML audit pack, the artifact an auditor or procurement reviewer actually reads:

```python
from reporting import render_audit_pack

html = render_audit_pack(record, submission)
```

The pack presents the decision, the rationale, the cited evidence with the submission values it references, the required mitigations, and the full provenance footer (agent version, contract version, tenant). It is the human-readable face of the structured record.

From the command line:

```
vrt render record.json --submission submission.json --output audit-pack.html
```

## 5. Carrying older records forward: migration

When a deployment needs records at a newer contract version (for example, adopting tenancy and bringing pre-tenancy records into the attributed world), the migration engine carries them forward:

```
vrt migrate legacy-records.jsonl --to 1.3.0 --tenant-id acme-bank
```

Records produced under the additive versions (1.0.0 through 1.2.0) are restamped; records crossing the 1.2.0-to-1.3.0 boundary are assigned a tenant explicitly (never silently defaulted). A migrated record validates against the target contract and renders identically to a natively-produced one: migration changes only the version stamp and the assigned tenant, never the decision itself.

See `docs/migration-guide.md` for the full migration story.

## The whole pipeline, in one place

```python
from agent.agent import TriageAgent
from tenancy import TenantRegistry
from reporting import render_audit_pack

# Configure once, per client.
registry = TenantRegistry.from_json_file("tenants.json")
agent = TriageAgent.for_tenant(registry.get("acme-bank"))

# Classify a submission.
record = agent.triage(submission)            # -> TriageRecord (1.3.0, attributed)

# Render the auditor-facing artifact.
audit_pack_html = render_audit_pack(record, submission)

# Persist the record; render and migrate it later as needed.
```

Every step here is covered end to end by the regression suite, so the composition shown above is verified, not aspirational.
