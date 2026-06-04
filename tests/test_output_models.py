"""Tests for the Phase 3 Pydantic output models.

These tests verify that ``agent.output_models.TriageRecord`` and its
sub-models conform to the Phase 1 data contract at
``schemas/output-contract-1.0.0.schema.json`` and that the audit-readiness
properties listed in the module docstring of ``agent/output_models.py``
actually hold.

Test categories:

- Construction from the canonical example.
- Conformance against the JSON Schema (positive and negative).
- Conditional requirements from the schema (allOf / dependentRequired).
- Per-field validation (length caps, semver patterns, control chars).
- Immutability of every frozen model (parametrized).
- Round-trip JSON serialization.
- The JSON Schema itself is well-formed and locks down every object level.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import jsonschema
import pytest
from jsonschema.validators import Draft202012Validator
from pydantic import ValidationError

from agent.output_models import (
    ConfidenceSignal,
    EvidenceCitation,
    TriageRecord,
)


REPO_ROOT = Path(__file__).parent.parent
# Phase 1 schema (1.0.0) is preserved for backward-compatibility
# assertions: the Pydantic model can still produce records that
# validate against the original public contract, regardless of how
# many version hops have been added since.
SCHEMA_PATH = REPO_ROOT / "schemas" / "output-contract-1.0.0.schema.json"
# Current schema is the one the framework writes today. Sourced from
# OUTPUT_SCHEMA_VERSION so a contract bump auto-updates this path.
from agent.agent import OUTPUT_SCHEMA_VERSION  # noqa: E402
CURRENT_SCHEMA_PATH = (
    REPO_ROOT / "schemas" / f"output-contract-{OUTPUT_SCHEMA_VERSION}.schema.json"
)
EXAMPLE_PATH = REPO_ROOT / "examples" / "triage-record.example.json"

try:
    SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())
    CURRENT_SCHEMA: dict[str, Any] = json.loads(CURRENT_SCHEMA_PATH.read_text())
except FileNotFoundError as exc:
    raise RuntimeError(
        f"output contract schema not found: {exc}. "
        "Run pytest from the repo root."
    ) from exc
except json.JSONDecodeError as exc:
    raise RuntimeError(
        f"output contract schema is not valid JSON: {exc}. "
        "Fix the schema file before running tests."
    ) from exc

# Build the validators once. ``jsonschema.validate`` rebuilds it on every call;
# pre-compiling speeds the test suite materially.
VALIDATOR = Draft202012Validator(SCHEMA)
CURRENT_VALIDATOR = Draft202012Validator(CURRENT_SCHEMA)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overrides`` into ``base`` for fixture construction.

    Shallow ``dict.update`` would replace nested dicts entirely; a test
    overriding only ``confidence_signal.score`` would lose ``interpretation``.
    Deep merge keeps the un-overridden sub-fields intact.
    """
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


_DISPOSITION_FOR_TIER: dict[str, str] = {
    "tier_1_low": "approve",
    "tier_2_moderate": "conditional_approve",
    "tier_3_elevated": "escalate_senior_review",
    "tier_4_high": "reject",
}


def make_record(risk_tier: str, **overrides: Any) -> TriageRecord:
    """Construct a minimum-valid TriageRecord for the given risk_tier.

    The default disposition for each tier satisfies the conditional schema
    rules (conditional_approve carries mitigations; escalate_senior_review
    carries an accountable_owner). Override any field, including nested ones,
    via kwargs; nested dicts are merged deeply.

    Examples:
        make_record("tier_1_low")
        make_record("tier_2_moderate", confidence_signal={"score": 0.99})
        make_record("tier_3_elevated", accountable_owner="VP Risk")

    For tests verifying the model REJECTS invalid inputs, construct the dict
    directly and call ``TriageRecord.model_validate(...)``; the fixture
    validates eagerly and would raise before returning.
    """
    disposition = _DISPOSITION_FOR_TIER[risk_tier]
    base: dict[str, Any] = {
        "decision_id": f"d-test-{risk_tier}",
        "decision_timestamp": "2026-05-27T14:32:18Z",
        "input_submission_id": f"s-test-{risk_tier}-001",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-agent-v0.4.0-test",
        "risk_tier": risk_tier,
        "recommended_disposition": disposition,
        "classification_rationale": f"Test rationale for {risk_tier} disposition {disposition}.",
        "evidence_cited": [
            {
                "input_field_reference": "$.ai_usage_level",
                "reasoning": "Test reasoning.",
            }
        ],
        "confidence_signal": {"score": 0.8, "interpretation": "high"},
        "output_schema_version": "1.0.0",
    }
    if disposition == "conditional_approve":
        base["required_mitigations"] = ["Test mitigation."]
    if disposition == "escalate_senior_review":
        base["accountable_owner"] = "Test Owner"
    return TriageRecord.model_validate(_deep_merge(base, overrides))


# ---------------------------------------------------------------------------
# Construction from the canonical example
# ---------------------------------------------------------------------------


def test_canonical_example_constructs() -> None:
    """examples/triage-record.example.json constructs a valid TriageRecord."""
    example = json.loads(EXAMPLE_PATH.read_text())
    record = TriageRecord.model_validate(example)
    assert record.risk_tier == "tier_2_moderate"
    assert record.recommended_disposition == "conditional_approve"
    assert len(record.evidence_cited) == 3


@pytest.mark.parametrize("tier", [
    "tier_1_low",
    "tier_2_moderate",
    "tier_3_elevated",
    "tier_4_high",
])
def test_constructs_for_every_tier(tier: str) -> None:
    """Fixture produces a valid record for every risk_tier value."""
    record = make_record(tier)
    assert record.risk_tier == tier


def test_constructs_with_all_optional_fields() -> None:
    """All optional fields populated together construct successfully."""
    record = make_record(
        "tier_2_moderate",
        extension_schema_version="1.0.0",
        supersedes="d-prior-001",
        review_interval_days=90,
        regulatory_framework_tags=["EU_AI_Act_Annex_III", "OSFI_E_23"],
    )
    assert record.extension_schema_version == "1.0.0"
    assert record.supersedes == "d-prior-001"
    assert record.review_interval_days == 90


def test_constructs_with_custom_framework_tag() -> None:
    """Institution-specific framework tags matching the custom pattern are accepted."""
    record = make_record(
        "tier_1_low",
        regulatory_framework_tags=["custom:acme_bank:internal_aml_framework"],
    )
    assert record.regulatory_framework_tags == [
        "custom:acme_bank:internal_aml_framework"
    ]


# ---------------------------------------------------------------------------
# Per-field validation (rejection cases)
# ---------------------------------------------------------------------------


def test_rejects_missing_required_field() -> None:
    """Missing decision_id raises ValidationError."""
    valid = json.loads(EXAMPLE_PATH.read_text())
    del valid["decision_id"]
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(valid)


def test_rejects_extra_top_level_field() -> None:
    """extra='forbid' blocks unknown fields at the top level."""
    valid = json.loads(EXAMPLE_PATH.read_text())
    valid["unexpected_field"] = "sneaky"
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(valid)


def test_rejects_extra_nested_field() -> None:
    """extra='forbid' blocks unknown fields in nested objects."""
    valid = json.loads(EXAMPLE_PATH.read_text())
    valid["confidence_signal"]["sneaky"] = "extra"
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(valid)


@pytest.mark.parametrize("bad_tier", [
    "tier_5_extreme",
    "low",
    "TIER_1_LOW",
    "",
])
def test_rejects_invalid_risk_tier(bad_tier: str) -> None:
    """risk_tier must be one of the four enum values.

    Constructs the dict directly because the fixture takes risk_tier
    positionally; supplying it again as a kwarg is a Python TypeError.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["risk_tier"] = bad_tier
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


@pytest.mark.parametrize("bad_disposition", [
    "deny",
    "APPROVE",
    "",
])
def test_rejects_invalid_disposition(bad_disposition: str) -> None:
    """recommended_disposition must be one of the four enum values.

    Direct dict construction (see test_rejects_invalid_risk_tier for rationale).
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["recommended_disposition"] = bad_disposition
    # required_mitigations is fine to leave; the disposition check will fail first
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


@pytest.mark.parametrize("bad_score", [-0.01, 1.01, 2.0, -1.0])
def test_rejects_confidence_score_out_of_range(bad_score: float) -> None:
    """confidence_signal.score must be in [0.0, 1.0]."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", confidence_signal={"score": bad_score})


@pytest.mark.parametrize("bad_score", [
    float("nan"),
    float("inf"),
    float("-inf"),
])
def test_rejects_confidence_score_non_finite(bad_score: float) -> None:
    """confidence_signal.score rejects NaN, +Inf, -Inf.

    Pydantic v2's ``ge=0.0, le=1.0`` constraint rejects all three implicitly
    (NaN compares as neither >= nor <= anything; Inf fails the upper bound;
    -Inf fails the lower bound). This test locks in that behavior so a
    future Pydantic change that silently accepts non-finite floats is
    caught loudly. Non-finite scores in an audit record would break any
    downstream confidence aggregation.
    """
    with pytest.raises(ValidationError):
        make_record("tier_1_low", confidence_signal={"score": bad_score})


def test_accepts_unicode_in_accountable_owner() -> None:
    """Role names may contain Unicode (international names, accented chars).

    Locks the current intentional behavior: Unicode is accepted in role
    names. Hardening against bidirectional/homoglyph attacks is tagged
    [deferred-phase-4] in the agent/output_models.py module docstring;
    until that work lands, role names like "Senior Risk Manager" and
    "Sénior Risk Manager" are both accepted as written.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["recommended_disposition"] = "escalate_senior_review"
    base["accountable_owner"] = "Сеньор Vendor Risk Manager"
    record = TriageRecord.model_validate(base)
    assert record.accountable_owner == "Сеньор Vendor Risk Manager"


def test_zero_width_chars_in_accountable_owner_currently_accepted() -> None:
    """Zero-width characters are currently accepted in accountable_owner.

    This is a known weakness: a homoglyph-style attack could embed
    U+200B (zero-width space) to make role names look identical to
    legitimate roles while differing in storage. Defense is tagged
    [deferred-phase-4] (Unicode bidi/homoglyph defenses) in the module
    docstring. This test pins the current behavior so the eventual
    hardening is a deliberate, visible change rather than a silent fix.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["recommended_disposition"] = "escalate_senior_review"
    base["accountable_owner"] = "Senior\u200bRisk Manager"  # ZWSP
    record = TriageRecord.model_validate(base)
    # Currently accepted; the test asserts the present-day behavior so a
    # future change (Phase 4 hardening) breaks this test deliberately.
    assert record.accountable_owner == "Senior\u200bRisk Manager"


@pytest.mark.parametrize("bad_band", ["very_high", "LOW", "extreme", ""])
def test_rejects_invalid_confidence_interpretation(bad_band: str) -> None:
    """confidence_signal.interpretation must be low/moderate/high."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            confidence_signal={"interpretation": bad_band},
        )


@pytest.mark.parametrize("score,band", [
    (0.95, "low"),         # high score, low band
    (0.95, "moderate"),    # high score, moderate band
    (0.3, "high"),         # low score, high band
    (0.3, "moderate"),     # low score, moderate band
    (0.6, "low"),          # moderate score, low band
    (0.6, "high"),         # moderate score, high band
    (0.0, "moderate"),     # boundary: 0.0 must be low
    (0.49, "moderate"),    # just below 0.5 must be low
    (0.5, "low"),          # 0.5 is moderate, not low
    (0.79, "high"),        # just below 0.8 must be moderate
    (0.8, "moderate"),     # 0.8 is high, not moderate
    (1.0, "low"),          # 1.0 is high
])
def test_confidence_signal_rejects_mismatched_band(
    score: float, band: str
) -> None:
    """ConfidenceSignal enforces band-matches-score at the contract layer.

    This check is intentionally also enforced in agent.agent._TriageClassification's
    validator at the LLM-output layer (so PydanticAI retries on mistakes), but
    the contract-layer enforcement here ensures records loaded from disk or
    constructed outside the agent path also conform.

    Boundary rule: 0.5 belongs to moderate, 0.8 belongs to high.
    """
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            confidence_signal={"score": score, "interpretation": band},
        )


@pytest.mark.parametrize("score,band", [
    (0.0, "low"),
    (0.49, "low"),
    (0.5, "moderate"),     # boundary
    (0.65, "moderate"),
    (0.79, "moderate"),
    (0.8, "high"),         # boundary
    (0.9, "high"),
    (1.0, "high"),
])
def test_confidence_signal_accepts_matched_band(
    score: float, band: str
) -> None:
    """ConfidenceSignal accepts every score/band combination that respects the boundaries."""
    record = make_record(
        "tier_1_low",
        confidence_signal={"score": score, "interpretation": band},
    )
    assert record.confidence_signal.score == score
    assert record.confidence_signal.interpretation == band


@pytest.mark.parametrize("bad_version", [
    "1.0",
    "v1.0.0",
    "1.0.0-beta",
    "",
])
def test_rejects_invalid_input_schema_version(bad_version: str) -> None:
    """input_schema_version requires strict X.Y.Z semver.

    Note: the schema pattern ``^\\d+\\.\\d+\\.\\d+$`` accepts numeric-only
    leading zeros like ``01.00.00``. Tightening that to forbid leading zeros
    is a schema change, not a model change; deferred until the schema is
    versioned to 1.1.0.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["input_schema_version"] = bad_version
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


@pytest.mark.parametrize("bad_version", [
    "1.0",
    "v1.0.0",
    "1.0.0-beta",
])
def test_rejects_invalid_output_schema_version(bad_version: str) -> None:
    """output_schema_version requires strict X.Y.Z semver."""
    base = json.loads(EXAMPLE_PATH.read_text())
    base["output_schema_version"] = bad_version
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


@pytest.mark.parametrize("bad_version", [
    "1.0",
    "v1.0.0",
    "1.0.0-beta",
])
def test_rejects_invalid_extension_schema_version(bad_version: str) -> None:
    """extension_schema_version is Optional but when present, requires X.Y.Z semver.

    The Optional default is None (absent); when supplied, the pattern applies.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["extension_schema_version"] = bad_version
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


def test_accepts_valid_extension_schema_version() -> None:
    """extension_schema_version accepts X.Y.Z semver when supplied."""
    record = make_record(
        "tier_1_low",
        extension_schema_version="1.2.3",
    )
    assert record.extension_schema_version == "1.2.3"


def test_rejects_oversized_classification_rationale() -> None:
    """classification_rationale is capped at 8000 characters."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", classification_rationale="x" * 8001)


def test_rejects_empty_classification_rationale() -> None:
    """classification_rationale must be at least 1 character."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", classification_rationale="")


def test_rejects_empty_evidence_cited() -> None:
    """evidence_cited must contain at least one citation."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", evidence_cited=[])


def test_rejects_oversized_input_field_reference() -> None:
    """input_field_reference is capped at 512 characters."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            evidence_cited=[
                {
                    "input_field_reference": "x" * 513,
                    "reasoning": "ok",
                }
            ],
        )


def test_rejects_oversized_evidence_reasoning() -> None:
    """evidence_cited[].reasoning is capped at 2000 characters."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            evidence_cited=[
                {
                    "input_field_reference": "$.field",
                    "reasoning": "x" * 2001,
                }
            ],
        )


@pytest.mark.parametrize("bad_tag", [
    "EU_AI_Act_Annex_IV",
    "osfi_e_23",
    "custom:Acme:framework",
    "custom::framework",
    "custom:acme:",
])
def test_rejects_invalid_framework_tag(bad_tag: str) -> None:
    """regulatory_framework_tags entries must be standard or match the custom pattern."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", regulatory_framework_tags=[bad_tag])


def test_rejects_duplicate_framework_tags() -> None:
    """regulatory_framework_tags must be unique (mirrors schema uniqueItems)."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            regulatory_framework_tags=["OSFI_E_23", "OSFI_E_23"],
        )


def test_accepts_empty_framework_tags_list() -> None:
    """An explicit empty list for regulatory_framework_tags is accepted.

    The schema places no minItems on this field. ``None`` and ``[]`` are both
    valid; this test pins the empty-list case so it doesn't silently regress.
    """
    record = make_record("tier_1_low", regulatory_framework_tags=[])
    assert record.regulatory_framework_tags == []


def test_rejects_review_interval_days_zero_or_negative() -> None:
    """review_interval_days must be a positive integer."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", review_interval_days=0)


# ---------------------------------------------------------------------------
# Control character rejection (log injection defense)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("evil", [
    "ok\x00null",
    "before\x1b[31mANSI",
    "bell\x07inside",
    "del\x7fhere",
])
def test_rejects_control_chars_in_rationale(evil: str) -> None:
    """classification_rationale rejects control characters and ANSI escapes."""
    with pytest.raises(ValidationError):
        make_record("tier_1_low", classification_rationale=evil)


def test_allows_newlines_in_rationale() -> None:
    """Prose fields allow newlines (and tabs and CR)."""
    record = make_record(
        "tier_1_low",
        classification_rationale="line one.\nline two.\twith tab.",
    )
    assert "\n" in record.classification_rationale


def test_rejects_control_chars_in_mitigation() -> None:
    """required_mitigations entries also screen control characters."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_2_moderate",
            required_mitigations=["ok\x00null"],
        )


def test_rejects_control_chars_in_revocation_reason() -> None:
    """revocation_reason rejects control characters (ProseString applied).

    Pairs with the canonical control-char tests on classification_rationale
    to verify ProseString defense applies consistently across all prose
    fields, including the paired-revocation field.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["revoked_at"] = "2026-06-01T00:00:00Z"
    base["revocation_reason"] = "vendor terminated\x07bell"
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


def test_rejects_empty_revocation_reason() -> None:
    """revocation_reason min_length=1 rejects empty string when supplied.

    Mirrors the empty-rationale rejection for consistency. revocation_reason
    is Optional (default None) but when present must be at least one character.
    """
    base = json.loads(EXAMPLE_PATH.read_text())
    base["revoked_at"] = "2026-06-01T00:00:00Z"
    base["revocation_reason"] = ""
    with pytest.raises(ValidationError):
        TriageRecord.model_validate(base)


def test_validator_returns_none_for_explicit_none_revoked_at() -> None:
    """Explicit None for revoked_at is accepted (mirrors framework_tags pattern).

    Pydantic v2 invokes _require_timezone_aware with None when the field is
    explicitly supplied as None, exercising the defensive guard. The paired
    revocation_reason must also be None to satisfy the model_validator.
    """
    record = make_record("tier_1_low", revoked_at=None, revocation_reason=None)
    assert record.revoked_at is None
    assert record.revocation_reason is None


# ---------------------------------------------------------------------------
# Conditional requirements (allOf / dependentRequired in the schema)
# ---------------------------------------------------------------------------


def test_conditional_approve_requires_mitigations() -> None:
    """conditional_approve disposition without required_mitigations is rejected."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_2_moderate",
            recommended_disposition="conditional_approve",
            required_mitigations=None,
        )


def test_escalate_senior_review_requires_accountable_owner() -> None:
    """escalate_senior_review disposition without accountable_owner is rejected."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_3_elevated",
            recommended_disposition="escalate_senior_review",
            accountable_owner=None,
        )


def test_approve_does_not_require_mitigations() -> None:
    """Plain 'approve' disposition does not require required_mitigations."""
    record = make_record("tier_1_low", recommended_disposition="approve")
    assert record.required_mitigations is None


def test_reject_does_not_require_accountable_owner() -> None:
    """The 'reject' disposition does not require accountable_owner."""
    record = make_record(
        "tier_4_high",
        recommended_disposition="reject",
        accountable_owner=None,
    )
    assert record.recommended_disposition == "reject"


def test_revoked_at_requires_revocation_reason() -> None:
    """revoked_at without revocation_reason is rejected (paired fields)."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            revoked_at="2026-06-01T00:00:00Z",
        )


def test_revocation_reason_requires_revoked_at() -> None:
    """revocation_reason without revoked_at is rejected (paired fields)."""
    with pytest.raises(ValidationError):
        make_record(
            "tier_1_low",
            revocation_reason="Vendor terminated.",
        )


def test_both_revocation_fields_present() -> None:
    """Both paired revocation fields together are accepted."""
    record = make_record(
        "tier_1_low",
        revoked_at="2026-06-01T12:00:00Z",
        revocation_reason="Vendor terminated.",
    )
    assert record.revoked_at is not None
    assert record.revocation_reason == "Vendor terminated."


# ---------------------------------------------------------------------------
# Datetime handling
# ---------------------------------------------------------------------------


def test_rejects_naive_decision_timestamp() -> None:
    """Naive datetime in decision_timestamp is rejected."""
    naive = datetime(2026, 5, 27, 14, 32, 18)
    with pytest.raises(ValidationError):
        make_record("tier_1_low", decision_timestamp=naive)


def test_accepts_offset_timezone_serializes_utc() -> None:
    """Non-UTC timezones are accepted; serialization normalizes to UTC."""
    plus_five = timezone(timedelta(hours=5))
    record = make_record(
        "tier_1_low",
        decision_timestamp=datetime(2026, 5, 27, 19, 32, 18, tzinfo=plus_five),
    )
    serialized = record.model_dump(mode="json")
    # 19:32 in +05 is 14:32 in UTC.
    assert "14:32:18" in serialized["decision_timestamp"]
    assert serialized["decision_timestamp"].endswith("Z")


@pytest.mark.parametrize("microsecond,expected_suffix", [
    (0, "T14:32:18Z"),
    (123000, "T14:32:18.123Z"),
    (123456, "T14:32:18.123456Z"),
    (1000, "T14:32:18.001Z"),
    (1, "T14:32:18.000001Z"),
])
def test_rfc3339_minimum_digits_fractional(
    microsecond: int, expected_suffix: str
) -> None:
    """Fractional seconds emit with the minimum digits needed to preserve precision.

    Millisecond-precision timestamps (microsecond divisible by 1000) emit three
    digits; sub-millisecond timestamps emit six. Exact-second timestamps emit
    no fractional. All forms are valid RFC 3339; this test pins the chosen
    serialization style so downstream consumers see consistent output.
    """
    record = make_record(
        "tier_1_low",
        decision_timestamp=datetime(2026, 5, 27, 14, 32, 18, microsecond, tzinfo=timezone.utc),
    )
    serialized = record.model_dump(mode="json")
    assert serialized["decision_timestamp"].endswith(expected_suffix), (
        f"Expected suffix {expected_suffix!r}, got {serialized['decision_timestamp']!r}"
    )


def test_serializer_returns_none_for_none_revoked_at_when_include_none() -> None:
    """The serializer's defensive None path is reached when exclude_none=False.

    Documents the defensive behavior of ``_serialize_rfc3339``: when a caller
    explicitly asks for None values in the dump, the serializer is invoked
    with None and returns None (rather than raising on ``.astimezone``).
    """
    record = make_record("tier_1_low")  # revoked_at defaults to None
    dumped = record.model_dump(mode="json", exclude_none=False)
    assert "revoked_at" in dumped
    assert dumped["revoked_at"] is None


def test_validator_returns_none_for_explicit_none_framework_tags() -> None:
    """Explicit None for regulatory_framework_tags is accepted.

    Documents the defensive None handling in ``_framework_tags_unique``: even
    when the caller passes ``regulatory_framework_tags=None`` explicitly
    (rather than relying on the default), the validator returns None cleanly.
    """
    record = make_record("tier_1_low", regulatory_framework_tags=None)
    assert record.regulatory_framework_tags is None


# ---------------------------------------------------------------------------
# Immutability (every frozen model)
# ---------------------------------------------------------------------------


_FROZEN_FACTORIES: list[tuple[str, Callable[[], Any], str, Any]] = [
    (
        "TriageRecord",
        lambda: make_record("tier_1_low"),
        "agent_version",
        "vrt-agent-tampered",
    ),
    (
        "EvidenceCitation",
        lambda: EvidenceCitation(input_field_reference="$.f", reasoning="r"),
        "reasoning",
        "tampered",
    ),
    (
        "ConfidenceSignal",
        lambda: ConfidenceSignal(score=0.5, interpretation="moderate"),
        "score",
        0.99,
    ),
]


@pytest.mark.parametrize(
    "model_name,factory,attr,new_value",
    _FROZEN_FACTORIES,
    ids=[t[0] for t in _FROZEN_FACTORIES],
)
def test_models_are_frozen(
    model_name: str,
    factory: Callable[[], Any],
    attr: str,
    new_value: Any,
) -> None:
    """Every frozen model raises when mutated post-construction."""
    instance = factory()
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        setattr(instance, attr, new_value)


# ---------------------------------------------------------------------------
# Schema conformance (Pydantic outputs validate against the file schema)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", [
    "tier_1_low",
    "tier_2_moderate",
    "tier_3_elevated",
    "tier_4_high",
])
def test_pydantic_output_validates_against_schema(tier: str) -> None:
    """Pydantic serialization conforms to the JSON Schema for every tier.

    Uses ``model_dump(mode='json')`` rather than ``json.loads(model_dump_json())``
    to skip the string round-trip; both produce equivalent dicts but the
    direct dump is faster.
    """
    record = make_record(tier)
    payload = record.model_dump(mode="json")
    VALIDATOR.validate(payload)


def test_canonical_example_validates_against_schema() -> None:
    """The example file validates against the CURRENT contract.

    The example record is bumped alongside the framework's
    OUTPUT_SCHEMA_VERSION so adopters reading the canonical example
    see the contract the framework actually writes today.
    """
    example = json.loads(EXAMPLE_PATH.read_text())
    CURRENT_VALIDATOR.validate(example)


def test_schema_is_valid_jsonschema_2020_12() -> None:
    """The schema file itself is a well-formed Draft 2020-12 schema."""
    Draft202012Validator.check_schema(SCHEMA)


def _is_object_schema(node: dict[str, Any]) -> bool:
    """Heuristic: does this dict represent an object schema?

    Either it declares ``"type": "object"`` explicitly, or it uses
    ``properties`` keyword (which implies object semantics in Draft 2020-12).
    """
    if node.get("type") == "object":
        return True
    if "properties" in node and "type" not in node:
        return True
    return False


def test_schema_locks_down_every_object_level() -> None:
    """Every data-shape object schema declares additionalProperties=false.

    The walker only checks object schemas that describe DATA. JSON Schema
    composition keywords (``if``, ``then``, ``else``, ``allOf``, ``anyOf``,
    ``oneOf``, ``not``, ``dependentSchemas``) introduce sub-schemas that act
    as validation predicates, not as field types; those don't need an
    ``additionalProperties`` declaration of their own. The data shapes they
    constrain are checked at their definition site.

    The root and ``$defs/base`` are exempt because the root's
    ``unevaluatedProperties: false`` carries through the $ref, locking down
    the entire document including $defs/base. All other inline object
    schemas (``confidence_signal``, ``evidence_cited.items``) use explicit
    ``additionalProperties: false`` directly.
    """
    root_locked = (
        SCHEMA.get("additionalProperties") is False
        or SCHEMA.get("unevaluatedProperties") is False
    )
    base = SCHEMA.get("$defs", {}).get("base", {})
    base_locked = (
        base.get("additionalProperties") is False
        or base.get("unevaluatedProperties") is False
    )
    assert root_locked or base_locked, (
        "Either the root or $defs/base must declare "
        "additionalProperties=false or unevaluatedProperties=false"
    )

    exempt_paths = {"$", "$.$defs.base"}
    composition_keywords = {
        "if",
        "then",
        "else",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "dependentSchemas",
    }

    def in_composition(path: str) -> bool:
        """Return True if the path traverses a schema-composition keyword."""
        parts = path.split(".")
        return any(part.split("[")[0] in composition_keywords for part in parts)

    def check(node: Any, path: str = "$") -> None:
        if isinstance(node, dict):
            if (
                _is_object_schema(node)
                and path not in exempt_paths
                and not in_composition(path)
            ):
                if node.get("additionalProperties") is not False:
                    raise AssertionError(
                        f"Data-shape object schema at {path} must declare "
                        f"additionalProperties=false; got "
                        f"additionalProperties={node.get('additionalProperties')!r}"
                    )
            for key, value in node.items():
                check(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                check(item, f"{path}[{index}]")

    check(SCHEMA)


@pytest.mark.parametrize("mutation,name", [
    (
        lambda d: d.update({"sneaky_top_level": "extra"}),
        "extra-at-top-level",
    ),
    (
        lambda d: d["confidence_signal"].update({"sneaky_nested": "extra"}),
        "extra-at-nested-level",
    ),
    (
        lambda d: d["evidence_cited"][0].update({"sneaky_array_item": "extra"}),
        "extra-in-array-item",
    ),
    (
        lambda d: d.update({"risk_tier": "tier_5_extreme"}),
        "out-of-range-tier",
    ),
    (
        lambda d: d.pop("decision_id"),
        "missing-required-field",
    ),
    (
        lambda d: d.update({"recommended_disposition": "conditional_approve"})
        or d.pop("required_mitigations", None),
        "conditional-approve-missing-mitigations",
    ),
])
def test_schema_rejects_mutation(
    mutation: Callable[[dict[str, Any]], None], name: str
) -> None:
    """The schema rejects each of these mutations (negative conformance)."""
    valid = json.loads(EXAMPLE_PATH.read_text())
    mutation(valid)
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(valid)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_equality() -> None:
    """model_validate(model_dump_json(x)) == x for a representative record."""
    record = make_record("tier_2_moderate")
    round_tripped = TriageRecord.model_validate_json(record.model_dump_json())
    assert round_tripped == record


def test_round_trip_example_file() -> None:
    """The example file round-trips through TriageRecord."""
    example = json.loads(EXAMPLE_PATH.read_text())
    record = TriageRecord.model_validate(example)
    payload = record.model_dump(mode="json")
    # Re-validate the serialized payload against the CURRENT schema
    # (the example is bumped to track OUTPUT_SCHEMA_VERSION).
    CURRENT_VALIDATOR.validate(payload)
