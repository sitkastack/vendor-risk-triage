# Input Data Contract

This document specifies the input data contract: the schema a vendor's documentation must conform to before the triage agent will process it. It is the first of the four technical specifications in Phase 1, and it turns the data validation decision named in 00-problem-definition.md into something an engineer can validate against, inside the boundaries 01-out-of-scope.md draws. Where those two documents describe the data path in prose, this one defines it as a schema.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## What this contract specifies

The contract is a JSON Schema, and the schema is the contract. A submission that conforms to it is eligible for triage. A submission that does not is rejected at intake with a stated reason, or routed to a normalization step that transforms it into a conforming shape before the agent sees it. Nothing reaches the classification logic without passing this gate first. The gate is enforced programmatically: a validator runs at intake, and its pass-or-fail result, not a human's impression of whether a document looks complete, decides whether the submission proceeds.

This is the boundary between trusted input and discarded input, and the schema makes it explicit rather than leaving it to whatever the parsing code happened to tolerate. The fields the agent is allowed to read are the fields named here. The formats it accepts are the formats validated here. A reviewer who wants to know what the agent could possibly have seen at intake reads the schema, not the source code.

The contract also closes the silent-inference gap that 01-out-of-scope.md describes. The schema rejects fields it does not define, so a vendor document carrying an unanticipated section does not quietly become part of the context the agent reasons over. The unknown field surfaces at intake as a validation event, recorded and visible, instead of being absorbed without a trace.

## Design principles

Required fields are the minimum the agent must see to produce a defensible decision. The required set is deliberately small: who the vendor is, where it operates, how it uses AI, and what documentation backs the submission. These are the fields without which the agent cannot place a vendor in a tier and defend the placement.

Optional fields enable richer triage, and the system functions without them. Disclosed AI features, named model providers, and PII handling claims let the agent reason in more detail and raise its confidence. Their absence lowers confidence but never blocks a classification. A sparse but valid submission still produces a tier and a disposition.

Every field is typed, and the few that carry prose are length-bounded. There is no open notes field that becomes a dumping ground the agent silently reads. Where a description is genuinely needed, the schema caps its length and states what it is for, so even the free-text fields have edges.

The contract is closed, not open. The top-level object enforces closure through unevaluatedProperties set to false, which rejects any field not named in the schema (or in an institution's extension that builds on it), and every nested object sets additionalProperties to false. A submission carrying a field the schema does not name fails validation rather than passing with the extra data ignored. This is the schema-level enforcement of the boundary 01-out-of-scope.md draws: what the contract does not name, the system does not quietly accept. The use of unevaluatedProperties at the top level instead of additionalProperties is deliberate: it preserves closure for standalone use while allowing institutions to extend the contract through the patterns in EXTENDING.md, without losing the closure property either side depends on.

Versioning is explicit. The schema carries its own version, that version travels with every record produced under it, and changes are tracked in commit history and governed like code. The contract as it stood on any past date is reconstructable rather than remembered.

## The schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://sitkastack.com/schemas/vendor-risk-triage/input-contract/1.0.0.json",
  "title": "Vendor Risk Triage Input Contract",
  "description": "Schema a vendor documentation submission must conform to before the triage agent will process it. Submissions that validate are eligible for triage; submissions that fail are rejected at intake or routed to normalization.",
  "$ref": "#/$defs/base",
  "unevaluatedProperties": false,
  "$defs": {
    "base": {
      "type": "object",
      "required": [
        "vendor_id",
        "vendor_name",
        "jurisdiction",
        "primary_contact",
        "vendor_classification",
        "ai_usage_level",
        "documentation_artifacts",
        "submission_timestamp",
        "schema_version"
      ],
      "properties": {
        "vendor_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "description": "Stable unique identifier for the vendor, assigned by the deploying organization. Attributes the triage record and links re-reviews of the same vendor over time."
        },
        "vendor_name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 256,
          "description": "Legal or commonly used name of the vendor, as it should appear in the triage record and any board or examiner reporting."
        },
        "jurisdiction": {
          "type": "string",
          "pattern": "^([A-Z]{2}(-[A-Z0-9]{1,3})?|EU|EEA|UK|GLOBAL)$",
          "description": "Primary jurisdiction governing the vendor relationship, as an ISO 3166-1 alpha-2 country code, an ISO 3166-2 region code, or one of EU, EEA, UK, GLOBAL. Determines which regulatory frameworks the triage applies."
        },
        "primary_contact": {
          "type": "object",
          "additionalProperties": false,
          "required": ["name", "email"],
          "description": "Person accountable for the submission on the deploying organization's side, used for follow-up on validation failures and re-review.",
          "properties": {
            "name": {
              "type": "string",
              "minLength": 1,
              "maxLength": 256,
              "description": "Full name of the accountable contact."
            },
            "email": {
              "type": "string",
              "format": "email",
              "description": "Working email address for the accountable contact."
            }
          }
        },
        "vendor_classification": {
          "type": "string",
          "enum": ["SaaS", "infrastructure", "model_provider", "embedded_AI", "hybrid"],
          "description": "Category of the vendor relationship. With ai_usage_level, anchors the initial risk tier."
        },
        "ai_usage_level": {
          "type": "string",
          "enum": ["none", "productivity_only", "operational_decisions", "customer_facing", "regulated_decisions"],
          "description": "Highest level at which the vendor's AI participates in decisions, ordered from no AI use to AI in decisions under direct regulatory scrutiny. The primary driver of the risk tier defined in docs/phase-0/01-risk-classification.md."
        },
        "documentation_artifacts": {
          "type": "array",
          "minItems": 1,
          "description": "References to the documentation backing the submission. At least one artifact is required so every classification is tied to evidence.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["artifact_type", "reference"],
            "properties": {
              "artifact_type": {
                "type": "string",
                "enum": ["soc2_report", "security_questionnaire", "model_card", "data_processing_agreement", "privacy_policy", "architecture_document", "other"],
                "description": "Kind of documentation the reference points to."
              },
              "reference": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1024,
                "description": "Locator for the artifact in the deploying organization's document store, such as a URI or content-addressed identifier. The contract records the reference; it does not parse the artifact."
              },
              "content_hash": {
                "type": "string",
                "pattern": "^sha256:[a-f0-9]{64}$",
                "description": "Optional SHA-256 hash of the artifact, as sha256:<hex>, so the record can prove which exact document was submitted."
              }
            }
          }
        },
        "submission_timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "ISO 8601 datetime at which the submission entered intake. Establishes when the agent saw this state of the vendor's documentation."
        },
        "schema_version": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$",
          "description": "Semver version of this input contract the submission targets. Travels with the resulting triage record so the contract that produced a decision is always recoverable."
        },
        "ai_features_disclosed": {
          "type": "array",
          "description": "Specific AI features the vendor discloses. Optional; presence raises classification confidence, absence lowers it without blocking a decision.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["feature_name", "description"],
            "properties": {
              "feature_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": "Short name of the disclosed feature."
              },
              "description": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "Bounded prose description of what the feature does and where it sits in the vendor's product."
              },
              "decision_role": {
                "type": "string",
                "enum": ["none", "supporting", "operational", "customer_facing", "regulated"],
                "description": "Role the feature plays in decisions, mirroring ai_usage_level at the level of an individual feature."
              },
              "autonomy": {
                "type": "string",
                "enum": ["human_initiated", "human_confirmed", "autonomous"],
                "description": "Degree of autonomy the feature exercises: actions a human triggers, actions a human confirms, or actions the feature takes on its own."
              }
            }
          }
        },
        "model_providers": {
          "type": "array",
          "description": "Named third-party model providers the vendor relies on, if disclosed.",
          "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256
          }
        },
        "training_data_sources": {
          "type": "array",
          "description": "Categories or sources of training data the vendor discloses. Recorded as the vendor's representation, not a verified fact.",
          "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512
          }
        },
        "pii_processing_claims": {
          "type": "object",
          "additionalProperties": false,
          "description": "Vendor's claims about the personal information its AI processes. Informs the privacy considerations in the privacy and data handling spec.",
          "properties": {
            "processes_pii": {
              "type": "boolean",
              "description": "Whether the vendor states its AI processes personal information at all."
            },
            "categories": {
              "type": "array",
              "description": "Categories of personal information processed, such as contact data, financial identifiers, or special-category data.",
              "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256
              }
            },
            "handling_notes": {
              "type": "string",
              "maxLength": 2000,
              "description": "Bounded prose notes on how the vendor states it handles the personal information it processes."
            }
          }
        },
        "data_residency": {
          "type": "object",
          "additionalProperties": false,
          "description": "Where the vendor stores and processes data, and under what conditions.",
          "properties": {
            "regions": {
              "type": "array",
              "description": "Regions in which data is stored or processed, as country or region codes.",
              "items": {
                "type": "string",
                "pattern": "^([A-Z]{2}(-[A-Z0-9]{1,3})?|EU|EEA|UK|GLOBAL)$"
              }
            },
            "conditions": {
              "type": "string",
              "maxLength": 2000,
              "description": "Bounded prose describing residency conditions, such as contractual data-localization commitments or cross-border transfer mechanisms."
            }
          }
        },
        "compliance_attestations": {
          "type": "array",
          "description": "Attestations the vendor holds against named frameworks.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["framework", "attestation_type"],
            "properties": {
              "framework": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": "Framework the attestation is against, such as SOC 2, ISO 27001, or ISO 42001."
              },
              "attestation_type": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": "Type of attestation, such as a Type II report, a certification, or a self-attestation."
              },
              "date": {
                "type": "string",
                "format": "date",
                "description": "Date the attestation was issued, as an ISO 8601 date."
              },
              "validity_period": {
                "type": "string",
                "maxLength": 128,
                "description": "Bounded statement of how long the attestation is valid, such as an ISO 8601 duration or an explicit expiry date."
              }
            }
          }
        },
        "ai_act_self_classification": {
          "type": "string",
          "enum": ["prohibited", "high_risk", "limited_risk", "minimal_risk", "not_applicable", "not_assessed"],
          "description": "Vendor's own EU AI Act risk classification of its system. Recorded as the vendor's assessment; the deploying organization performs its own classification per docs/phase-0/01-risk-classification.md."
        },
        "prior_triage_record_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "description": "Identifier of a previous triage record for this vendor, present when the submission is a re-review. Links the new decision to the one it supersedes."
        },
        "vendor_disclosed_subprocessors": {
          "type": "array",
          "description": "Subprocessors the vendor discloses, including any that provide AI capabilities.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["name"],
            "properties": {
              "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": "Name of the subprocessor."
              },
              "role": {
                "type": "string",
                "maxLength": 512,
                "description": "Bounded description of what the subprocessor does in the vendor's service."
              },
              "location": {
                "type": "string",
                "pattern": "^([A-Z]{2}(-[A-Z0-9]{1,3})?|EU|EEA|UK|GLOBAL)$",
                "description": "Primary location of the subprocessor, as a country or region code."
              },
              "processes_customer_data": {
                "type": "boolean",
                "description": "Whether the subprocessor processes the deploying organization's customer data."
              }
            }
          }
        }
      }
    }
  }
}
```

## Required vs. optional: the rationale

The required fields are the floor for a defensible classification. vendor_classification and ai_usage_level most directly drive the tier; jurisdiction determines which regulatory frameworks apply; vendor_id and primary_contact make the record attributable and re-findable; documentation_artifacts ties the decision to the evidence it rested on; submission_timestamp and schema_version make it reconstructable. Remove any of these and the agent is guessing at something it should have been told.

Optional fields refine rather than gate. A submission that includes ai_features_disclosed and pii_processing_claims gives the agent specific material to reason over and earns a higher-confidence classification. A submission without them is still classified, at correspondingly lower confidence, with the absence recorded in the output. The system degrades in confidence, not in function. The output contract records which optional fields were absent, so a later reader sees not just the confidence level but the specific gaps that produced it.

The contract never silently fills a gap. A document missing a required field is rejected at intake with a structured reason, not coerced into a default the agent then treats as fact. A document missing only optional fields is classified as it stands. The distinction matters in an audit: a rejection is a recorded event with a cause, while a silent default is an assumption nobody can later prove or disprove.

## Validation rules

Validation happens at intake, before any classification work begins. A submission is checked against the schema, and one that fails is rejected with a structured error naming each field that failed and why: a missing required field, a value outside an enum, a malformed timestamp. The error is specific enough that the submitter can correct the problem without guessing at what the contract wanted. The error is structured rather than a free-text message: it names the offending field by its path in the submission, the rule that failed, and the value that failed it. A submission that breaks three rules produces three entries, not one vague refusal, so failures can be logged, counted, and reported on like any other event.

Every validation failure is logged. A corrected resubmission is treated as a new triage decision with its own record, and the failed submission is retained as part of the audit trail rather than overwritten. An examiner can therefore see not only the decision that was reached but the submissions turned away before it, which is often where the more interesting questions live.

## Format considerations

The contract is defined in JSON, and a structured submission that already conforms is validated directly against it. Most real vendor documentation does not arrive in that shape.

Semi-structured submissions, such as CSV exports or completed questionnaire forms, are routed through a normalization step that maps them onto the schema before validation. The normalization is documented and deterministic, so the transformation from raw form to contract-conforming JSON is itself reconstructable rather than a black box.

Document attachments such as PDF and DOCX files are referenced through documentation_artifacts, not parsed by the agent. They exist for the human reviewer. The contract records that they were part of the submission without treating their unstructured contents as fields the agent reads, which keeps the agent classifying from structured data and leaves the documents to support the human in the loop.

## Schema versioning

Schema versions follow semver. A major version breaks compatibility, typically by adding or retyping a required field. A minor version adds optional fields and stays backward compatible. A patch corrects an error in a description or a constraint without changing the data shape.

Every triage record carries the schema_version that produced it. A decision made under 1.2.0 stays valid under 1.3.0 unless a 1.3.0 change is explicitly marked retroactive, which is rare and called out when it happens. Schema changes move through the same pull-request review as code: a version bump, a changelog entry, and explicit sign-off before merge. The version history is the contract's own audit trail.

## Audit considerations

The contract is the audit boundary for intake. When an examiner asks what the agent saw, the answer is the schema version plus the validated submission: these fields, these values, this artifact set, validated at this timestamp. That is a reconstructable answer rather than a recollection, and it holds because the schema that defined "valid" at the time is itself recorded.

Failed validations belong to that trail too, not discarded as noise. The schema and its version history are public artifacts in this repository, so an auditor can reconstruct what the contract required at any past date and check a given record against the version that produced it. Nothing about what the agent accepted at intake depends on anyone's memory.

Where a submission includes the optional content_hash on its artifacts, the record can go past naming the documents the agent relied on and prove which exact bytes they were. An auditor comparing the stored hash against the document in the management system can confirm the artifact has not changed since intake, closing the gap between what the record says was reviewed and what was actually reviewed.

## Limitations of this contract

This is a v0.3 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as the remaining Phase 1 specifications ship and as engineers point out what I have missed.

The field set is generic. It is built for a mid-market regulated company triaging conventional SaaS, infrastructure, and model-provider vendors, and it will not cover every category a real deployment meets. Embedded-AI hardware, vendor-of-vendor exposure, and category-specific disclosures will need fields this schema does not carry. A real deployment extends the schema; the reference is a structure to build on, not a finished intake format to adopt. The patterns for extending it without breaking the audit boundary are described in EXTENDING.md.

This is practitioner methodology, not legal advice. The contract specifies the shape of the data, not its regulatory adequacy. Whether a given field set satisfies a given obligation is a question for the privacy and legal review that the privacy spec and 01-out-of-scope.md both defer to, and production deployment requires that review alongside any framework like this.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, complete as of May 23, 2026. Roadmap: sitkastack.com/roadmap.
