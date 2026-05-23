# Extending the Framework

This guide describes how to extend the Phase 1 contracts and specs for institution-specific needs without breaking the audit boundary the reference establishes. Where the specs say a real deployment extends the reference, this is where the how lives.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## Why extension matters

The reference implementation is calibrated for a mid-market regulated company triaging conventional SaaS, infrastructure, and model-provider vendors. It fits the common case, not every case.

Real deployments meet vendor categories the reference does not name, internal control frameworks the schema does not carry, and board reporting requirements the output record does not capture. Those gaps are expected.

Extension is the expected path, not an edge case. The question is never whether to extend the contracts but how to do it without losing what makes the reference defensible: the closed schema, the immutable record, and the version metadata that lets an auditor reconstruct any decision.

## Extending the Input Contract

Add institution-specific fields by extending the schema rather than editing the reference in place. The recommended pattern is a schema that references the reference's base node (#/$defs/base) in an allOf, adds properties alongside it, and seals the result with unevaluatedProperties set to false, so the institution's schema stays separable from the upstream one and stays closed.

Required fields in the reference stay required in the extension; an extension adds to the floor, it does not lower it. Optional fields can be promoted to required where the institution's risk appetite calls for it.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/vendor-risk-triage/input-contract-extended/1.0.0.json",
  "allOf": [
    {"$ref": "https://sitkastack.com/schemas/vendor-risk-triage/input-contract/1.0.0.json#/$defs/base"},
    {
      "properties": {
        "internal_control_id": {
          "type": "string",
          "description": "Institution-specific internal control identifier."
        }
      },
      "required": ["internal_control_id"]
    }
  ],
  "unevaluatedProperties": false
}
```

## Extending the Output Contract

The output contract extends the same way. Add fields for institutional governance, such as decision approver IDs, GRC workflow references, and board reporting flags, layered on through the same schema reference pattern.

The required field set stays required. An extended record still carries the tier, the disposition, the rationale, the evidence, the confidence signal, and the version metadata, because those are what make a record reconstructable. Institutional fields sit alongside that floor, not in place of it.

For framework tagging, use the regulatory_framework_tags custom pattern rather than editing the enum. A code of the form custom:<institution>:<framework> validates against the contract as written, so an institution can tag with its own or a sector-specific framework without forking the schema.

```json
{
  "regulatory_framework_tags": [
    "OSFI_E_23",
    "EU_AI_Act_Annex_III",
    "custom:acme-bank:internal-control-aml-2024"
  ]
}
```

## Maintaining the audit boundary

Extensions inherit the closed-schema property from the reference. The reference keeps its field set in a reusable base and seals the top level with unevaluatedProperties set to false, so nothing it does not name slips through. An extension references that base and seals its own top level the same way. An extension that forgets to seal reintroduces the silent-inference gap the reference closed.

Extensions inherit the immutability requirement from the output contract. A record produced under an extended schema is still immutable, with corrections made through supersedes rather than edits in place. Institutional fields do not buy an exception to that rule.

The extended schema's version travels with every record it produces, alongside the reference version it builds on. An audit answer cites both, so a reviewer can reconstruct a decision against the exact pair of schemas that shaped it.

Nested objects in the reference schemas, including primary_contact, documentation_artifacts items, evidence_cited items, and others, keep additionalProperties set to false, so they cannot be extended through the same allOf and unevaluatedProperties pattern that works at the top level. Extending a nested object requires forking the nested schema in the extension and overriding the parent's property reference, which is more invasive than top-level extension and is not the recommended path for v0.1. Institutions that encounter the need typically benefit from adding a sibling field at the top level instead, where the extension pattern is supported directly.

## Extending the Privacy & Data Handling spec

The privacy spec is methodology, and institutions extend it through their own data classification categories, retention periods, and incident response procedures. Where the reference describes how to minimize, retain, and purge, the institution fills in the categories its data falls into and the periods its regulators require.

The reference establishes the methodology; the institution establishes the compliance, mapping the methodology onto the regimes that actually apply to it.

## Extending the Synthetic Data Spec

Extending the synthetic dataset means generating records that conform to the extended schemas, not only the reference ones. When the input contract gains a required field, the corpus has to carry it or it stops being a faithful test of what the system now accepts.

The coverage requirements carry over. The spread across vendor types, AI usage levels, jurisdictions, and risk tiers applies to extensions too, scaled to the institution's actual vendor population. The validation rule holds: every well-formed synthetic record validates against the extended input contract before it enters the corpus.

## Versioning extensions

Extension schemas follow the same semver discipline as the reference. Major versions break compatibility, minor versions add optional fields, and patches fix descriptions or constraints. The extension version history is the institution's audit trail, governed by the same review process as code.

## Limitations of this guide

This is a v0.1 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as institutions extend these contracts and report what the patterns missed.

This guide describes patterns, not a complete extension framework. A real extension needs its own design and review: the patterns here keep an extension from breaking the audit boundary, but they do not design the institution's schema for it.

This is practitioner methodology, not legal advice. Any production extension carries the same legal and privacy review burden as the reference it builds on, and the boundaries in 01-out-of-scope.md apply to extensions too.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, in progress as of May 21, 2026. Roadmap: sitkastack.com/roadmap.
