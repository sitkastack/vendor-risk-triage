# Output Data Contract

This document specifies the output data contract: the schema for the triage record the agent writes for every classification decision. It pairs with 02-input-contract.md, which defines what the agent reads; this one defines what it writes. Together they bound the agent on both sides, so the data entering a decision and the record leaving it are both defined rather than improvised.

Written by Robyn Toor. Fifteen years building enterprise systems in regulated financial services, including fintech operating roles where I lived the buyer side of vendor risk decisions.

## What this contract specifies

The contract is a JSON Schema for the triage record. Every classification the agent produces is written as a record that conforms to this schema, or the decision is treated as incomplete and not relied upon. There is no partial record that an integration quietly accepts: a decision either produces a conforming record or it has not finished.

The record is the agent's output in full. It carries the tier, the disposition, the reasoning behind both, the evidence the agent cited, and the metadata needed to reconstruct the decision later. What the input contract does for intake, this contract does for the result: it makes the boundary of a valid output explicit rather than leaving it to whatever the agent happened to emit. The metadata includes a reference back to the exact input submission and the input contract version that validated it, so the two contracts form a closed loop: the input contract defines what was accepted, this one defines what was decided, and the two are joined by reference rather than by assumption.

The record is also the primary audit artifact. When an examiner asks what the agent decided and why, the answer is the record: this tier, this disposition, this rationale, citing these input fields, at this confidence, under this agent version. A decision that cannot be expressed as a conforming record is a decision the system cannot defend, and the contract surfaces that failure at write time rather than at audit time. A decision the agent cannot justify in the required fields is one the system declines to record as complete, so the gap shows up to the engineer who can fix it, not to the examiner who cannot.

## Design principles

Every record reconstructs the decision. The required fields are chosen so a reader holding the record and the referenced input submission can rebuild what happened: the tier and disposition the agent reached, the reasoning it gave, and the evidence it relied on. A record that omits any of these is not a lighter record, it is an incomplete one.

Records are immutable. Once written, a record is not edited in place. A correction is a new record that supersedes the prior one through explicit linkage, and a revocation marks a record without erasing it. The history of a vendor's decisions is additive, so nothing that was once true of a record is quietly overwritten. An overwrite is indistinguishable from tampering after the fact, and a system that cannot rule out tampering cannot defend its records, so the contract rules it out by construction.

Records carry version metadata for both the schema and the agent. Each record names the output schema version that shaped it, the input schema version that validated its source, and the agent version that produced it. A decision is reproducible only against the exact versions that made it, and those versions live in the record rather than in deployment notes.

No silent fields. Everything the agent weighed is either in the record or explicitly outside it. The agent does not reach a tier on the strength of a consideration that never appears in evidence_cited. If something shaped the decision, the record names it.

The contract is closed, not open. The top-level object enforces closure through unevaluatedProperties set to false, which rejects any field not named in the schema (or in an institution's extension that builds on it), and every nested object sets additionalProperties to false. A record carrying a field the schema does not name fails validation rather than passing with the extra data ignored. The use of unevaluatedProperties at the top level instead of additionalProperties is deliberate: it preserves closure for standalone use while allowing institutions to extend the contract through the patterns in EXTENDING.md, without losing the closure property either side depends on.

## The schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://sitkastack.com/schemas/vendor-risk-triage/output-contract/1.0.0.json",
  "title": "Vendor Risk Triage Output Contract",
  "description": "Schema for the triage record the agent writes for every classification decision. A record that does not conform is treated as an incomplete decision and is not relied upon.",
  "$ref": "#/$defs/base",
  "unevaluatedProperties": false,
  "$defs": {
    "base": {
      "type": "object",
      "required": [
        "decision_id",
        "decision_timestamp",
        "input_submission_id",
        "input_schema_version",
        "agent_version",
        "risk_tier",
        "recommended_disposition",
        "classification_rationale",
        "evidence_cited",
        "confidence_signal",
        "output_schema_version"
      ],
      "properties": {
        "decision_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "description": "Unique identifier for this triage decision, stable for the life of the record and referenced by any record that supersedes it."
        },
        "decision_timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "ISO 8601 datetime at which the agent wrote this record. Fixes when the decision was made."
        },
        "input_submission_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "description": "Identifier of the validated input submission this decision was made from. Assigned by the intake system upon successful validation against the input contract, linking the record to the exact data the agent read."
        },
        "input_schema_version": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$",
          "description": "Semver version of the input contract that validated the source submission, recorded so the intake rules in force at decision time are recoverable."
        },
        "agent_version": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "description": "Identifier of the triage agent that produced the decision, such as a release tag or build hash, so the decision can be reproduced against the exact agent that made it."
        },
        "risk_tier": {
          "type": "string",
          "enum": ["tier_1_low", "tier_2_moderate", "tier_3_elevated", "tier_4_high"],
          "description": "Risk tier assigned to the vendor, per the taxonomy in docs/phase-0/01-risk-classification.md."
        },
        "recommended_disposition": {
          "type": "string",
          "enum": ["approve", "conditional_approve", "escalate_senior_review", "reject"],
          "description": "Disposition the agent recommends. A recommendation for a human decision, not a final action."
        },
        "classification_rationale": {
          "type": "string",
          "minLength": 1,
          "maxLength": 8000,
          "description": "The agent's reasoning for the tier and disposition, in bounded prose. The narrative an examiner reads to understand why the decision was reached."
        },
        "evidence_cited": {
          "type": "array",
          "minItems": 1,
          "description": "The specific input fields the agent relied on and what it drew from each. At least one citation is required so no decision rests on unstated grounds.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["input_field_reference", "reasoning"],
            "properties": {
              "input_field_reference": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
                "description": "Reference to a field in the input submission, such as a field name or JSON pointer, that the agent relied on."
              },
              "reasoning": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "Bounded prose explaining what the agent drew from that field and how it bore on the tier or disposition."
              }
            }
          }
        },
        "confidence_signal": {
          "type": "object",
          "additionalProperties": false,
          "required": ["score", "interpretation"],
          "description": "The agent's confidence in the classification. The contract records it; calibration is a Phase 3 concern.",
          "properties": {
            "score": {
              "type": "number",
              "minimum": 0,
              "maximum": 1,
              "description": "Confidence score from 0 to 1 as reported by the agent."
            },
            "interpretation": {
              "type": "string",
              "enum": ["low", "moderate", "high"],
              "description": "Banded interpretation of the score, recorded so a reader is not left to interpret a bare number."
            }
          }
        },
        "output_schema_version": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$",
          "description": "Semver version of this output contract (the reference) the record conforms to. Travels with the record so the reference shape that produced it is always recoverable. When the record was produced under an institutional extension, the extension's version is captured separately in extension_schema_version."
        },
        "extension_schema_version": {
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$",
          "description": "Semver version of the institution's extension schema when the record was produced under an extension of this contract rather than the reference directly. Captures the extension version alongside output_schema_version so an audit can reconstruct the full schema chain. Absent when the record was produced under the reference schema directly."
        },
        "required_mitigations": {
          "type": "array",
          "minItems": 1,
          "description": "Mitigations attached to a conditional approval, such as keeping a feature disabled or requiring a contractual term. Required when recommended_disposition is conditional_approve.",
          "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1000
          }
        },
        "accountable_owner": {
          "type": "string",
          "minLength": 1,
          "maxLength": 256,
          "description": "Name or role of the human accountable for an escalated decision. Required when recommended_disposition is escalate_senior_review."
        },
        "supersedes": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "description": "decision_id of the prior record this record replaces, present when this record is a correction."
        },
        "revoked_at": {
          "type": "string",
          "format": "date-time",
          "description": "ISO 8601 datetime at which this decision was revoked, if it has been. Paired with revocation_reason."
        },
        "revocation_reason": {
          "type": "string",
          "minLength": 1,
          "maxLength": 2000,
          "description": "Bounded prose explaining why the decision was revoked. Paired with revoked_at."
        },
        "review_interval_days": {
          "type": "integer",
          "minimum": 1,
          "description": "Recommended number of days until the vendor is re-triaged, when a recurring review cadence applies."
        },
        "regulatory_framework_tags": {
          "type": "array",
          "uniqueItems": true,
          "description": "Frameworks the decision is explicitly relevant to, for filtering and regulator-facing reporting. Supports standard framework codes and institution-specific custom codes via the pattern custom:<institution>:<framework>.",
          "items": {
            "type": "string",
            "oneOf": [
              {
                "enum": ["EU_AI_Act_Annex_III", "OSFI_E_23", "NIST_AI_RMF", "NAIC", "SR_11_7"]
              },
              {
                "pattern": "^custom:[a-z0-9_-]{1,64}:[a-z0-9_-]{1,128}$"
              }
            ]
          }
        }
      },
      "dependentRequired": {
        "revoked_at": ["revocation_reason"],
        "revocation_reason": ["revoked_at"]
      },
      "allOf": [
        {
          "if": {
            "required": ["recommended_disposition"],
            "properties": {"recommended_disposition": {"const": "conditional_approve"}}
          },
          "then": {"required": ["required_mitigations"]}
        },
        {
          "if": {
            "required": ["recommended_disposition"],
            "properties": {"recommended_disposition": {"const": "escalate_senior_review"}}
          },
          "then": {"required": ["accountable_owner"]}
        }
      ]
    }
  }
}
```

## Required vs. optional: the rationale

The required fields make every record reconstructable. decision_id and decision_timestamp identify and place the decision; input_submission_id and input_schema_version tie it to the exact input that produced it; agent_version names what produced it; risk_tier and recommended_disposition are the decision itself; classification_rationale and evidence_cited are why; confidence_signal qualifies how strongly; output_schema_version fixes the shape. Strip any of these and an audit answer has a hole in it that nobody can fill after the fact.

Optional fields capture context that depends on the disposition or on later events. A conditional approval needs its required_mitigations; an escalation needs an accountable_owner; a superseded or revoked record needs the linkage and the reason that explain its status; a recurring review needs its interval; a regulator-facing decision benefits from framework tags. These are optional in the general case but conditionally required when the disposition or status triggers them, and the schema enforces that rather than trusting the caller: required_mitigations is required when the disposition is conditional_approve, accountable_owner is required when the disposition is escalate_senior_review, and revoked_at and revocation_reason are required together or not at all. Enforcing these in the schema rather than in application code is deliberate. A rule that lives only in a code path can be skipped when the path changes, while a rule in the contract travels with the record to every place it is validated. The schema is the one gate every record passes through, so it is where a conditional approval is guaranteed never to land without its mitigations, and an escalation never without its accountable owner. The extension_schema_version field is present only when the record was produced under an institutional extension of this contract; absent on records produced under the reference directly. Its presence and value travel into the audit trail so a reviewer can identify which extension version shaped the record.

## Immutability and supersession

Records are immutable once written, and the immutability is enforced through tooling rather than left to convention. The store that holds triage records appends and supersedes; it does not update in place. A reader can trust that a record reflects exactly what the agent wrote at decision_timestamp because nothing in the system has the ability to alter it afterward.

A correction creates a new record with supersedes set to the prior decision_id, so the two are linked and the newer one is understood to replace the older. A revocation is different: it marks the existing record with revoked_at and revocation_reason but leaves it in place, because a revoked decision is still part of the history an examiner may need to see. The full chain is preserved, and the current state of a vendor is the most recent live record in that chain, the one neither superseded nor revoked. Determining that current record is a query over the chain, not a flag someone remembers to set, so two readers asking what a vendor's standing is today get the same answer from the data.

## Confidence signal

The contract defines the confidence_signal field, a score and its banded interpretation, but it does not define how the score is computed. Calibration, whether a score of 0.8 means what it should against ground truth, is a Phase 3 (Build & Eval) concern, handled where the agent's behavior is measured. The banded interpretation travels alongside the raw score so downstream routing and reporting do not each have to agree on a numeric cutoff the contract never set: a record marked low reads as low for every consumer. The contract records the confidence the agent reported; whether that confidence is well-calibrated is a separate question this contract does not answer.

## Audit considerations

The record is the primary audit artifact, and it is built to answer the examiner's question without recourse to anyone's memory. Four things reconstruct any past decision: the input submission, the input schema version that validated it, the output record, and the agent version that produced it. With those, a reviewer can rebuild what the agent saw, what rules its input had to satisfy, what it decided and why, and what produced the decision.

Decision lineage is queryable from the records themselves. The supersedes links form a chain back through every correction, and revoked_at marks the points where a decision was withdrawn. An examiner asking how the current view of a vendor came to be can follow that chain rather than interview the team, because the lineage is data rather than institutional knowledge. How long those records are kept, and what is minimized within them, is governed by the privacy and data handling spec rather than by this contract; the output contract fixes the shape of a record, not its lifetime.

## Limitations of this contract

This is a v0.1 reference, not production-grade audit defense. It reflects my own work without external peer review at this stage, and it will change as the remaining Phase 1 specifications ship and as engineers point out what I have missed.

The field set is generic. It records a tier, a disposition, and the reasoning behind them for a mid-market regulated company, and it will not capture every field a particular institution's governance or board reporting requires. Decision approvers, internal control identifiers, and links into a GRC workflow are the kind of fields a real deployment adds. A real deployment extends the contract; the reference is a structure to extend, not a finished record format to adopt. Extension patterns are described in EXTENDING.md.

The contract also assumes the human-in-the-loop disposition flow established in docs/phase-0/00-problem-definition.md. A deployment that automates dispositions without human review changes the regulatory posture established in docs/phase-0/01-risk-classification.md and requires re-evaluation.

This is practitioner methodology, not legal advice. The contract specifies the shape of the record, not whether that record satisfies a given regulator's evidentiary expectations. Whether a record is sufficient for a particular examination is a question for the legal and compliance review that 01-out-of-scope.md defers to, and production deployment requires that review alongside any framework like this.

## Status

Phase 1 (Data Contracts & Privacy) of the sitkastack Framework, in progress as of May 21, 2026. Roadmap: sitkastack.com/roadmap.
