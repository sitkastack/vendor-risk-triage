"""Tests for Phase 5 sub-system 6: audit log shipping adapter.

Coverage targets the envelope model, the build helper, the parse +
verify path, and the canonical-bytes serializer that underlies the
content hash.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.output_models import TriageRecord
from reporting import (
    AuditLogEnvelope,
    AuditLogParseError,
    ENVELOPE_SCHEMA_VERSION,
    build_envelope,
    parse_jsonl_line,
)
from reporting.audit_log import _record_canonical_bytes


REPO_ROOT = Path(__file__).parent.parent
EXPECTED_DIR = REPO_ROOT / "examples" / "expected-records"


def _load_record(scenario_index: int) -> TriageRecord:
    """Load demo scenario N's TriageRecord."""
    rec_glob = list(EXPECTED_DIR.glob(f"0{scenario_index}-*.expected.json"))
    rec_d = json.loads(rec_glob[0].read_text())
    rec_d["decision_timestamp"] = datetime.fromisoformat(
        rec_d["decision_timestamp"].replace("Z", "+00:00")
    )
    return TriageRecord(**rec_d)


@pytest.fixture(scope="module")
def sample_record() -> TriageRecord:
    return _load_record(3)


# -- AuditLogEnvelope model --------------------------------------------


def test_envelope_is_frozen(sample_record: TriageRecord) -> None:
    env = build_envelope(
        record=sample_record,
        sequence_number=1,
        deployment_id="test-env",
    )
    with pytest.raises(ValidationError):
        env.sequence_number = 2  # type: ignore[misc]


def test_envelope_rejects_extras(sample_record: TriageRecord) -> None:
    """Unknown fields are rejected (no silent drift)."""
    with pytest.raises(ValidationError):
        AuditLogEnvelope(
            envelope_schema_version="1.0.0",
            record_content_hash="sha256:" + "a" * 64,
            record=sample_record,
            sequence_number=1,
            deployment_id="test",
            shipped_at=datetime.now(timezone.utc),
            unknown_field="oops",  # type: ignore[call-arg]
        )


def test_envelope_requires_aware_shipped_at(sample_record: TriageRecord) -> None:
    """Naive datetime in shipped_at is rejected."""
    with pytest.raises(ValidationError):
        AuditLogEnvelope(
            envelope_schema_version="1.0.0",
            record_content_hash="sha256:" + "a" * 64,
            record=sample_record,
            sequence_number=1,
            deployment_id="test",
            shipped_at=datetime(2026, 5, 22, 9, 33, 0),  # no tz
        )


def test_envelope_hash_pattern_enforced(sample_record: TriageRecord) -> None:
    """record_content_hash must match the sha256:<64hex> pattern."""
    with pytest.raises(ValidationError):
        AuditLogEnvelope(
            envelope_schema_version="1.0.0",
            record_content_hash="not-a-valid-hash",
            record=sample_record,
            sequence_number=1,
            deployment_id="test",
            shipped_at=datetime.now(timezone.utc),
        )


def test_envelope_sequence_number_non_negative(sample_record: TriageRecord) -> None:
    """Sequence numbers cannot be negative."""
    with pytest.raises(ValidationError):
        AuditLogEnvelope(
            envelope_schema_version="1.0.0",
            record_content_hash="sha256:" + "a" * 64,
            record=sample_record,
            sequence_number=-1,
            deployment_id="test",
            shipped_at=datetime.now(timezone.utc),
        )


# -- build_envelope -----------------------------------------------------


def test_build_envelope_sets_schema_version(sample_record: TriageRecord) -> None:
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    assert env.envelope_schema_version == ENVELOPE_SCHEMA_VERSION


def test_build_envelope_computes_content_hash(sample_record: TriageRecord) -> None:
    """The content hash matches SHA-256 of the canonical record bytes."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    expected = "sha256:" + hashlib.sha256(
        _record_canonical_bytes(sample_record)
    ).hexdigest()
    assert env.record_content_hash == expected


def test_build_envelope_default_shipped_at_is_recent(
    sample_record: TriageRecord,
) -> None:
    """shipped_at defaults to current UTC when omitted."""
    before = datetime.now(timezone.utc)
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    after = datetime.now(timezone.utc)
    assert before <= env.shipped_at <= after


def test_build_envelope_explicit_shipped_at_preserved(
    sample_record: TriageRecord,
) -> None:
    """An explicit shipped_at is preserved exactly (test determinism)."""
    fixed_ts = datetime(2026, 6, 1, 12, 30, 45, tzinfo=timezone.utc)
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
        shipped_at=fixed_ts,
    )
    assert env.shipped_at == fixed_ts


def test_build_envelope_replay_of_recorded(sample_record: TriageRecord) -> None:
    """The replay_of reference is preserved when supplied."""
    env = build_envelope(
        record=sample_record, sequence_number=99,
        deployment_id="x", replay_of="prior-decision-id:42",
    )
    assert env.replay_of == "prior-decision-id:42"


def test_build_envelope_replay_of_defaults_to_none(
    sample_record: TriageRecord,
) -> None:
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    assert env.replay_of is None


# -- serialization ------------------------------------------------------


def test_to_jsonl_line_ends_with_newline(sample_record: TriageRecord) -> None:
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    line = env.to_jsonl_line()
    assert line.endswith("\n")
    assert line.count("\n") == 1


def test_to_jsonl_line_no_extraneous_whitespace_in_structure(
    sample_record: TriageRecord,
) -> None:
    """JSON structural separators are compact (no space after colon or comma).

    Note: ': ' and ', ' can legitimately appear INSIDE string values
    (vendor prose, role names, mitigation text). The compact-separators
    requirement applies to the JSON structural separators between
    fields, not to the content of string values. We verify the
    structural compactness by parsing and re-serializing and
    confirming byte-identity.
    """
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    line = env.to_jsonl_line().rstrip("\n")
    # Re-serialize the parsed payload with the same separators; should
    # match. If the original used non-compact separators, the re-dump
    # would differ.
    parsed = json.loads(line)
    redumped = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    assert line == redumped


def test_to_jsonl_line_deterministic_for_equal_envelopes(
    sample_record: TriageRecord,
) -> None:
    """Two envelopes with identical inputs produce byte-identical lines."""
    fixed = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    env_a = build_envelope(
        record=sample_record, sequence_number=42,
        deployment_id="acme-prod", shipped_at=fixed,
    )
    env_b = build_envelope(
        record=sample_record, sequence_number=42,
        deployment_id="acme-prod", shipped_at=fixed,
    )
    assert env_a.to_jsonl_line() == env_b.to_jsonl_line()


def test_to_dict_matches_parsed_line(sample_record: TriageRecord) -> None:
    """to_dict() output equals json.loads(to_jsonl_line())."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    via_dict = env.to_dict()
    via_line = json.loads(env.to_jsonl_line())
    assert via_dict == via_line


def test_to_jsonl_line_excludes_none_replay_of(
    sample_record: TriageRecord,
) -> None:
    """replay_of is omitted from output when None (clean JSON)."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    line = env.to_jsonl_line()
    assert "replay_of" not in line


# -- parse_jsonl_line ---------------------------------------------------


def test_parse_jsonl_line_roundtrip(sample_record: TriageRecord) -> None:
    """build + serialize + parse produces an equal envelope."""
    env = build_envelope(
        record=sample_record, sequence_number=42,
        deployment_id="acme-prod",
    )
    line = env.to_jsonl_line()
    parsed = parse_jsonl_line(line)
    assert parsed == env


def test_parse_jsonl_line_tolerates_missing_newline(
    sample_record: TriageRecord,
) -> None:
    """Parsing tolerates a missing trailing newline (defensive)."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    line_no_newline = env.to_jsonl_line().rstrip("\n")
    parsed = parse_jsonl_line(line_no_newline)
    assert parsed == env


def test_parse_jsonl_line_invalid_json_raises() -> None:
    with pytest.raises(AuditLogParseError, match="not valid JSON"):
        parse_jsonl_line("this is not json {{{")


def test_parse_jsonl_line_non_object_raises() -> None:
    """A JSON value that's not an object (array, scalar) is rejected."""
    with pytest.raises(AuditLogParseError, match="must be a JSON object"):
        parse_jsonl_line("[1, 2, 3]")


def test_parse_jsonl_line_missing_version_raises() -> None:
    """A payload without envelope_schema_version is rejected."""
    payload = {"record": {}, "sequence_number": 1}
    line = json.dumps(payload)
    with pytest.raises(AuditLogParseError, match="version is missing"):
        parse_jsonl_line(line)


def test_parse_jsonl_line_malformed_version_raises() -> None:
    payload = {
        "envelope_schema_version": "not-a-version",
        "record_content_hash": "sha256:" + "a" * 64,
        "record": {},
        "sequence_number": 1,
        "deployment_id": "x",
        "shipped_at": "2026-05-22T09:33:00Z",
    }
    line = json.dumps(payload)
    with pytest.raises(AuditLogParseError, match="missing or malformed"):
        parse_jsonl_line(line)


def test_parse_jsonl_line_incompatible_major_version_raises(
    sample_record: TriageRecord,
) -> None:
    """A future major version raises with a clear message."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    payload = json.loads(env.to_jsonl_line())
    payload["envelope_schema_version"] = "99.0.0"
    line = json.dumps(payload)
    with pytest.raises(AuditLogParseError, match="incompatible"):
        parse_jsonl_line(line)


def test_parse_jsonl_line_schema_mismatch_raises(
    sample_record: TriageRecord,
) -> None:
    """A payload that fails Pydantic validation raises clearly."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    payload = json.loads(env.to_jsonl_line())
    payload["sequence_number"] = -5  # violates ge=0
    line = json.dumps(payload)
    with pytest.raises(AuditLogParseError, match="does not match schema"):
        parse_jsonl_line(line)


def test_parse_jsonl_line_detects_record_tampering(
    sample_record: TriageRecord,
) -> None:
    """Modifying the embedded record breaks the content-hash check."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    line = env.to_jsonl_line()
    # Tamper with the record's tier (changes the canonical bytes)
    tampered = re.sub(r'"tier_3_elevated"', '"tier_1_low"', line, count=1)
    with pytest.raises(AuditLogParseError, match="hash mismatch"):
        parse_jsonl_line(tampered)


def test_parse_jsonl_line_verify_hash_false_skips_check(
    sample_record: TriageRecord,
) -> None:
    """With verify_hash=False, a tampered record parses (caller responsibility)."""
    env = build_envelope(
        record=sample_record, sequence_number=1, deployment_id="x",
    )
    line = env.to_jsonl_line()
    tampered = re.sub(r'"tier_3_elevated"', '"tier_1_low"', line, count=1)
    parsed = parse_jsonl_line(tampered, verify_hash=False)
    # Parse succeeds (caller has its own integrity mechanism).
    # risk_tier may be a string or enum depending on Pydantic v2 mode;
    # normalize.
    tier_value = (
        parsed.record.risk_tier.value
        if hasattr(parsed.record.risk_tier, "value")
        else str(parsed.record.risk_tier)
    )
    assert tier_value == "tier_1_low"


# -- canonical bytes ---------------------------------------------------


def test_canonical_bytes_are_sorted_keys(sample_record: TriageRecord) -> None:
    """Canonical serialization uses sorted keys for hash stability."""
    canonical = _record_canonical_bytes(sample_record)
    payload = json.loads(canonical)
    # Check top-level keys are alphabetically sorted in the serialization
    re_keys = re.findall(r'"([^"]+)":', canonical.decode("utf-8"))
    # The first half of the keys at top level should be sorted; some keys
    # appear inside nested structures so we can't just check all keys.
    # Instead verify that re-serializing with sorted keys yields the
    # same bytes.
    redumped = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    assert canonical == redumped


def test_canonical_bytes_structurally_compact(sample_record: TriageRecord) -> None:
    """Canonical bytes use compact structural separators.

    String values may legitimately contain ': ' or ', ' (prose text);
    we verify structural compactness by re-serialization byte-identity.
    """
    canonical = _record_canonical_bytes(sample_record)
    parsed = json.loads(canonical)
    redumped = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    assert canonical == redumped


def test_canonical_bytes_deterministic(sample_record: TriageRecord) -> None:
    """Two canonical serializations of the same record are byte-identical."""
    a = _record_canonical_bytes(sample_record)
    b = _record_canonical_bytes(sample_record)
    assert a == b


def test_canonical_bytes_exclude_none(sample_record: TriageRecord) -> None:
    """Unset optional fields are excluded (not emitted as null)."""
    # Scenario 1 (tier 1 approve) has no required_mitigations
    record = _load_record(1)
    canonical = _record_canonical_bytes(record)
    payload = json.loads(canonical)
    assert "required_mitigations" not in payload
    assert "accountable_owner" not in payload


# -- multi-scenario coverage --------------------------------------------


@pytest.mark.parametrize("scenario_index", range(1, 6))
def test_build_envelope_works_for_every_demo_scenario(
    scenario_index: int,
) -> None:
    """All five demo scenarios produce valid envelopes."""
    record = _load_record(scenario_index)
    env = build_envelope(
        record=record, sequence_number=scenario_index,
        deployment_id=f"demo-{scenario_index}",
    )
    assert env.record.decision_id == record.decision_id
    # Round-trip
    line = env.to_jsonl_line()
    parsed = parse_jsonl_line(line)
    assert parsed.record.decision_id == record.decision_id


# -- public surface ---------------------------------------------------


def test_envelope_schema_version_is_one_dot_zero_dot_zero() -> None:
    """The wire format is at 1.0.0 for the initial release."""
    assert ENVELOPE_SCHEMA_VERSION == "1.0.0"


def test_audit_log_parse_error_is_an_exception() -> None:
    """AuditLogParseError can be caught as a generic Exception."""
    try:
        raise AuditLogParseError("test")
    except Exception as exc:
        assert "test" in str(exc)
