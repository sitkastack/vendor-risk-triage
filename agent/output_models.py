"""Pydantic output models for the Vendor Risk Triage agent.

These models are the runtime enforcement of the Phase 1 data contract published at
``schemas/output-contract-1.0.0.schema.json``. The schema is the hand-curated
source of truth for the public contract; these models conform to it and reject
anything the schema would reject (and several additional defenses the schema
does not encode).

Conformance is verified in ``tests/test_output_models.py`` against the schema
file directly. If the schema changes and these models drift, those tests fail.

Field-level classification (Phase 1 / governance-as-code):

- ``classification_rationale`` may contain extracted phrasing from vendor
  documentation. Treat as Internal Confidential.
- ``evidence_cited[].reasoning`` may contain extracted phrasing or paraphrase
  of vendor documentation. Treat as Internal Confidential.
- ``required_mitigations[]`` describes operational controls expected of the
  vendor. Treat as Internal Confidential.

Audit posture (Phase 2 threat model, ``docs/phase-2/03-threat-model.md``):

- All models are frozen after construction. Tamper resistance.
- ``extra='forbid'`` on every model. No silent schema drift.
- Free-text fields reject control characters and ANSI terminal escape sequences.
- Cross-field requirements from the schema (conditional disposition rules and
  paired revocation fields) are enforced by a single model-level validator.

Deferred to later phases (consciously, with audit visibility, tagged for
git-grep retrieval):

- [deferred-phase-4] structured ``risk_owner`` field (AAIR)
- [deferred-phase-4] ``inherent_risk_tier`` vs ``residual_risk_tier`` (AAIR)
- [deferred-phase-4] ``model_card_ref`` for ISO 42001 A.6.2.4 (AAISM)
- [deferred-phase-4] ``governance_objectives`` for COBIT mapping (CGEIT)
- [deferred-phase-4] structured EU AI Act Article 13 transparency (AAIA)
- [deferred-phase-4] ``contains_pii`` flag (CDPSE)
- [deferred-phase-4] GDPR Article 17 / SOX retention reconciliation (CDPSE)
- [deferred-phase-4] Unicode bidirectional / homoglyph defenses (Security)
- [deferred-phase-5] ``signature_hash`` and ``signing_key_id`` (CISA)
- [deferred-phase-5] ``request_id`` / ``trace_id`` for SIEM correlation (CCOA)
- [deferred-phase-5] ``detection_events`` linkage to 27 detection functions (CCOA)
- [deferred-phase-5] ``framework_citations`` registry validation (AAIA)

Operational note: pydantic-core ships as a Rust binary wheel. FRFI environments
with binary restrictions may need to vendor the wheel.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


__all__ = [
    "TriageRecord",
    "EvidenceCitation",
    "ConfidenceSignal",
    "RiskTier",
    "Disposition",
    "ConfidenceBand",
    "FrameworkTag",
    "ProseString",
    "MitigationString",
]


# Module-level constants. Pattern strings reused across multiple Field declarations.

_SEMVER_PATTERN: str = r"^\d+\.\d+\.\d+$"
_CUSTOM_FRAMEWORK_PATTERN: str = r"^custom:[a-z0-9_-]{1,64}:[a-z0-9_-]{1,128}$"


# Shared validators. Regex-based for speed (the per-character Python loop these
# replace was a measurable hot path during test runs).

_CONTROL_CHAR_RE: re.Pattern[str] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)


def _reject_control_chars(value: str) -> str:
    """Reject control characters that could enable log injection or terminal escape sequences.

    Allows tab (\\t), newline (\\n), and carriage return (\\r). Rejects all other
    C0 control codes (codepoints below 0x20 except whitespace) plus DEL (0x7F).
    This is a defense against log poisoning and ANSI escape sequence injection
    in audit records.

    Args:
        value: The string to check.

    Returns:
        The original string if it contains no rejected control characters.

    Raises:
        ValueError: If the string contains a rejected control character.
    """
    match = _CONTROL_CHAR_RE.search(value)
    if match is None:
        return value
    bad_char = match.group(0)
    raise ValueError(
        f"contains control character (codepoint {ord(bad_char):#x}); "
        "control characters are rejected to prevent log injection"
    )


ProseString = Annotated[str, AfterValidator(_reject_control_chars)]
"""Multi-line text fields. Allows newlines, rejects other control characters."""

MitigationString = Annotated[
    str,
    Field(min_length=1, max_length=1000),
    AfterValidator(_reject_control_chars),
]
"""Required mitigation entry. Bounded length, control-char screened."""


# Type aliases for the constrained primitive enums.

RiskTier = Literal["tier_1_low", "tier_2_moderate", "tier_3_elevated", "tier_4_high"]
Disposition = Literal["approve", "conditional_approve", "escalate_senior_review", "reject"]
ConfidenceBand = Literal["low", "moderate", "high"]

# regulatory_framework_tags entries are either a known standard tag or a custom
# tag matching the institution-specific pattern. Pydantic walks the Union from
# left to right; the Literal arm wins for the known cases and the custom arm
# catches everything else (where the pattern enforces the format).

_StandardFrameworkTag = Literal[
    "EU_AI_Act_Annex_III", "OSFI_E_23", "NIST_AI_RMF", "NAIC", "SR_11_7"
]
_CustomFrameworkTag = Annotated[
    str, Field(pattern=_CUSTOM_FRAMEWORK_PATTERN)
]
FrameworkTag = Annotated[
    _StandardFrameworkTag | _CustomFrameworkTag,
    Field(union_mode="left_to_right"),
]


class EvidenceCitation(BaseModel):
    """One citation tying the agent's decision back to a specific input field.

    Every TriageRecord requires at least one citation; the schema enforces a
    minimum of one item in ``evidence_cited``. A decision that cites nothing
    rests on unstated grounds and is not auditable.

    Attributes:
        input_field_reference: A field name or JSON pointer (e.g. ``$.ai_usage_level``)
            identifying which input field the agent drew from.
        reasoning: Bounded prose explaining what the agent drew from that field
            and how it bore on the tier or disposition.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_field_reference: str = Field(min_length=1, max_length=512)
    reasoning: ProseString = Field(min_length=1, max_length=2000)


class ConfidenceSignal(BaseModel):
    """The agent's confidence in its own classification.

    The numeric ``score`` and the banded ``interpretation`` are recorded
    together so a reader is not left to interpret a bare number. Calibration
    of the score itself is a Phase 3 eval-harness concern.

    Attributes:
        score: Confidence from 0.0 to 1.0 as reported by the agent.
        interpretation: Banded interpretation of the score: ``low``,
            ``moderate``, or ``high``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    interpretation: ConfidenceBand


class TriageRecord(BaseModel):
    """The complete vendor risk triage record the agent writes for each decision.

    Conforms to the Phase 1 output contract at
    ``schemas/output-contract-1.0.0.schema.json`` (version 1.0.0). The schema
    requires certain fields conditionally on disposition; those requirements
    are enforced here by a single model-level validator that mirrors the
    schema's ``allOf`` and ``dependentRequired`` clauses.

    Audit invariants:

    - The record is frozen. The agent writes it once; nothing mutates it later.
    - ``extra='forbid'``. Unknown fields are rejected (no silent drift).
    - Free-text fields screen for control characters (log injection defense).
    - Cross-field consistency (disposition-conditioned requirements; paired
      revocation fields) is verified at construction.

    Canonical schema:

    The hand-curated ``schemas/output-contract-1.0.0.schema.json`` is the
    public contract. ``TriageRecord.model_json_schema()`` returns a
    Pydantic-generated schema that describes the same shape but differs in
    surface details (field order, ``$defs`` layout, ``anyOf`` vs ``oneOf``
    for unions, default representation). For documentation, code generation,
    or contract publication, use the file; for in-process Pydantic
    introspection, the generated schema is fine.

    Production performance note (for sub-system 2 consumers):

    Pydantic validation of a TriageRecord runs at roughly 13 microseconds per
    record. The slower step is jsonschema validation against the file schema
    (around 412 microseconds per record). When validating many records at
    runtime, cache a compiled ``jsonschema.validators.Draft202012Validator``
    at agent startup and reuse it; do not call ``jsonschema.validate`` in a
    hot loop (it rebuilds the validator on every call).

    See module docstring for the deferred-field audit list.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Required fields from the schema.
    decision_id: str = Field(min_length=1, max_length=128)
    decision_timestamp: datetime
    input_submission_id: str = Field(min_length=1, max_length=128)
    input_schema_version: str = Field(pattern=_SEMVER_PATTERN)
    agent_version: str = Field(min_length=1, max_length=128)
    risk_tier: RiskTier
    recommended_disposition: Disposition
    classification_rationale: ProseString = Field(min_length=1, max_length=8000)
    evidence_cited: list[EvidenceCitation] = Field(min_length=1)
    confidence_signal: ConfidenceSignal
    output_schema_version: str = Field(pattern=_SEMVER_PATTERN)

    # Optional fields. Some become conditionally required based on disposition;
    # see the model_validator below.
    extension_schema_version: Optional[str] = Field(
        default=None, pattern=_SEMVER_PATTERN
    )
    required_mitigations: Optional[list[MitigationString]] = Field(
        default=None, min_length=1
    )
    accountable_owner: Optional[str] = Field(
        default=None, min_length=1, max_length=256
    )
    supersedes: Optional[str] = Field(default=None, min_length=1, max_length=128)
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[ProseString] = Field(
        default=None, min_length=1, max_length=2000
    )
    review_interval_days: Optional[int] = Field(default=None, ge=1)
    regulatory_framework_tags: Optional[list[FrameworkTag]] = Field(default=None)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Serialize to dict, excluding unset optional fields by default.

        The schema declares optional fields as ``type: "string"`` (not
        ``["string", "null"]``); emitting them as JSON ``null`` violates the
        schema. ``exclude_none=True`` is the default so output always conforms.
        Callers wanting null-included output can pass ``exclude_none=False``.
        """
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        """Serialize to JSON, excluding unset optional fields by default."""
        kwargs.setdefault("exclude_none", True)
        return super().model_dump_json(**kwargs)

    @field_validator("decision_timestamp", "revoked_at")
    @classmethod
    def _require_timezone_aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Reject naive datetimes. Audit timestamps must include a timezone.

        The ``value is None`` guard is defensive. Pydantic v2 generally skips
        field validators on default-None Optional fields, so the None branch
        is rarely reached in normal use. The guard ensures the validator is
        safe when invoked directly or in a future code path that does pass
        None explicitly.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware (RFC 3339)")
        return value

    @field_serializer("decision_timestamp", "revoked_at")
    def _serialize_rfc3339(self, value: Optional[datetime]) -> Optional[str]:
        """Emit datetimes as RFC 3339 UTC with minimum fractional-second digits.

        Three precision tiers based on the actual sub-second precision:

        - microsecond == 0           -> ``YYYY-MM-DDTHH:MM:SSZ`` (no fractional)
        - microsecond % 1000 == 0    -> ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (millisecond)
        - otherwise                  -> ``YYYY-MM-DDTHH:MM:SS.mmmmmmZ`` (microsecond)

        Trailing zeros are trimmed so a millisecond-precision input like
        ``.123000`` serializes as ``.123Z`` rather than ``.123000Z``. Both forms
        are valid RFC 3339 but the trimmed form is what most downstream
        consumers emit.

        The ``value is None`` guard is reached when callers pass
        ``exclude_none=False`` to ``model_dump``/``model_dump_json``; the
        default behavior is to omit None fields and skip the serializer.
        """
        if value is None:
            return None
        utc = value.astimezone(timezone.utc)
        if utc.microsecond == 0:
            return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        if utc.microsecond % 1000 == 0:
            millis = utc.microsecond // 1000
            return utc.strftime(f"%Y-%m-%dT%H:%M:%S.{millis:03d}Z")
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @field_validator("regulatory_framework_tags")
    @classmethod
    def _framework_tags_unique(
        cls, value: Optional[list[str]]
    ) -> Optional[list[str]]:
        """Mirror the schema's ``uniqueItems: true`` on regulatory_framework_tags.

        The ``value is None`` guard mirrors the defensive pattern in
        ``_require_timezone_aware``: defensive against explicit-None calls.
        """
        if value is None:
            return None
        if len(value) != len(set(value)):
            raise ValueError("regulatory_framework_tags must be unique")
        return value

    @model_validator(mode="after")
    def _enforce_conditional_requirements(self) -> "TriageRecord":
        """Enforce the schema's ``allOf`` and ``dependentRequired`` cross-field rules.

        Three rules:

        - ``recommended_disposition == "conditional_approve"`` requires
          ``required_mitigations`` to be present (and non-empty by virtue of
          the field-level ``min_length=1``).
        - ``recommended_disposition == "escalate_senior_review"`` requires
          ``accountable_owner`` to be present.
        - ``revoked_at`` and ``revocation_reason`` are paired: both or neither.

        Mirrors the schema's ``allOf`` and ``dependentRequired`` clauses so
        Pydantic and the schema reject the same instances for the same reasons.

        Explicit ``is None`` comparisons (rather than ``not field``) make the
        intent unambiguous: we are checking presence of the optional field,
        not its truthiness.
        """
        if self.recommended_disposition == "conditional_approve":
            if self.required_mitigations is None:
                raise ValueError(
                    "required_mitigations is required when "
                    "recommended_disposition is 'conditional_approve'"
                )
        if self.recommended_disposition == "escalate_senior_review":
            if self.accountable_owner is None:
                raise ValueError(
                    "accountable_owner is required when "
                    "recommended_disposition is 'escalate_senior_review'"
                )
        if (self.revoked_at is None) != (self.revocation_reason is None):
            raise ValueError(
                "revoked_at and revocation_reason must be paired "
                "(both present or both absent)"
            )
        return self
