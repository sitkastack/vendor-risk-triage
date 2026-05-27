"""Tests for Phase 5 sub-system 7: drift detection (eval.drift).

Coverage targets the pure-Python drift comparison logic, the baseline
load/save round-trip, and the error paths. Tests construct
TriageRecord objects directly rather than going through the agent
pipeline; the drift checker's job is to compare records, and that
is what should be tested.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.output_models import (
    ConfidenceSignal,
    EvidenceCitation,
    TriageRecord,
)
from eval.drift import (
    BaselineLoadError,
    DriftCategory,
    DriftEntry,
    DriftReport,
    ScenarioDrift,
    check_drift,
    compare_records,
    load_baselines,
    save_baselines,
)


# -- helpers for building records --------------------------------------


def _base_record(
    *,
    risk_tier: str = "tier_2_moderate",
    recommended_disposition: str = "conditional_approve",
    confidence_score: float = 0.78,
    confidence_interpretation: str | None = None,
    classification_rationale: str = "Baseline rationale text for testing.",
    evidence_cited: list[dict[str, str]] | None = None,
    required_mitigations: list[str] | None = None,
    accountable_owner: str | None = None,
    regulatory_framework_tags: list[str] | None = None,
    review_interval_days: int | None = 180,
    decision_id: str = "d-test-baseline-001",
    decision_timestamp: datetime | None = None,
    agent_version: str = "vrt-agent-v0.6.0-test-prompt-69ef583c6dbe",
) -> TriageRecord:
    """Build a TriageRecord with sensible defaults; override per test."""
    if decision_timestamp is None:
        decision_timestamp = datetime(2026, 5, 27, 6, 0, 0, tzinfo=timezone.utc)
    if evidence_cited is None:
        evidence_cited = [{
            "input_field_reference": "$.ai_usage_level",
            "reasoning": "Baseline evidence reasoning text.",
        }]
    if recommended_disposition == "conditional_approve" and required_mitigations is None:
        required_mitigations = ["Baseline mitigation text."]
    if recommended_disposition == "escalate_senior_review" and accountable_owner is None:
        accountable_owner = "Senior Risk Officer"
    # Derive interpretation from score per ConfidenceSignal band rules:
    # <0.5 low, [0.5, 0.8) moderate, >=0.8 high
    if confidence_interpretation is None:
        if confidence_score < 0.5:
            confidence_interpretation = "low"
        elif confidence_score < 0.8:
            confidence_interpretation = "moderate"
        else:
            confidence_interpretation = "high"

    payload: dict[str, Any] = {
        "decision_id": decision_id,
        "decision_timestamp": decision_timestamp,
        "input_submission_id": "test-vendor-001",
        "input_schema_version": "1.0.0",
        "agent_version": agent_version,
        "risk_tier": risk_tier,
        "recommended_disposition": recommended_disposition,
        "classification_rationale": classification_rationale,
        "evidence_cited": [
            EvidenceCitation(**e) for e in evidence_cited
        ],
        "confidence_signal": ConfidenceSignal(
            score=confidence_score,
            interpretation=confidence_interpretation,
        ),
        "output_schema_version": "1.0.0",
        "review_interval_days": review_interval_days,
    }
    if required_mitigations is not None:
        payload["required_mitigations"] = required_mitigations
    if accountable_owner is not None:
        payload["accountable_owner"] = accountable_owner
    if regulatory_framework_tags is not None:
        payload["regulatory_framework_tags"] = regulatory_framework_tags

    return TriageRecord(**payload)


# -- DriftEntry / DriftCategory ----------------------------------------


def test_drift_category_values() -> None:
    """The two categories are 'hard' and 'soft'."""
    assert DriftCategory.HARD.value == "hard"
    assert DriftCategory.SOFT.value == "soft"


def test_drift_entry_is_frozen() -> None:
    """DriftEntry is immutable."""
    entry = DriftEntry(
        category=DriftCategory.HARD,
        field_path="risk_tier",
        baseline_value="a",
        current_value="b",
        message="x",
    )
    with pytest.raises(Exception):
        entry.field_path = "other"  # type: ignore[misc]


# -- compare_records: no drift ------------------------------------------


def test_identical_records_produce_no_drift() -> None:
    """Two equal records (modulo ignored fields) produce empty drift list."""
    baseline = _base_record()
    current = _base_record()
    entries = compare_records(baseline, current)
    assert entries == []


def test_different_decision_id_is_not_drift() -> None:
    """decision_id is per-run; it should not surface as drift."""
    baseline = _base_record(decision_id="d-baseline-aaa")
    current = _base_record(decision_id="d-current-bbb")
    entries = compare_records(baseline, current)
    assert entries == []


def test_different_decision_timestamp_is_not_drift() -> None:
    """decision_timestamp is per-run; it should not surface as drift."""
    baseline = _base_record(
        decision_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    current = _base_record(
        decision_timestamp=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    entries = compare_records(baseline, current)
    assert entries == []


def test_different_agent_version_is_not_drift() -> None:
    """agent_version changes when intentional; not a drift signal."""
    baseline = _base_record(agent_version="vrt-agent-v0.6.0-x-prompt-aaa")
    current = _base_record(agent_version="vrt-agent-v0.7.0-x-prompt-bbb")
    entries = compare_records(baseline, current)
    assert entries == []


# -- compare_records: hard drift ----------------------------------------


def test_risk_tier_change_is_hard_drift() -> None:
    """tier change always fires hard drift."""
    baseline = _base_record(risk_tier="tier_2_moderate")
    current = _base_record(risk_tier="tier_3_elevated")
    entries = compare_records(baseline, current)
    assert len(entries) == 1
    assert entries[0].category == DriftCategory.HARD
    assert entries[0].field_path == "risk_tier"
    assert entries[0].baseline_value == "tier_2_moderate"
    assert entries[0].current_value == "tier_3_elevated"


def test_disposition_change_is_hard_drift() -> None:
    """disposition change always fires hard drift."""
    baseline = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["a"],
    )
    current = _base_record(
        recommended_disposition="approve",
        required_mitigations=None,
    )
    entries = compare_records(baseline, current)
    categories = [e.category for e in entries]
    paths = [e.field_path for e in entries]
    assert DriftCategory.HARD in categories
    assert "recommended_disposition" in paths


def test_accountable_owner_presence_change_is_hard_drift() -> None:
    """Owner appearing where it was absent (or vice versa) is hard drift."""
    baseline = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["a"],
        accountable_owner=None,
    )
    current = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["a"],
        accountable_owner="Senior Risk Officer",
    )
    entries = compare_records(baseline, current)
    hard_entries = [e for e in entries if e.category == DriftCategory.HARD]
    paths = [e.field_path for e in hard_entries]
    assert "accountable_owner" in paths


def test_evidence_count_change_is_hard_drift() -> None:
    """Adding/removing an evidence citation is hard drift."""
    baseline = _base_record(evidence_cited=[
        {"input_field_reference": "$.a", "reasoning": "one"},
    ])
    current = _base_record(evidence_cited=[
        {"input_field_reference": "$.a", "reasoning": "one"},
        {"input_field_reference": "$.b", "reasoning": "two"},
    ])
    entries = compare_records(baseline, current)
    hard_entries = [e for e in entries if e.category == DriftCategory.HARD]
    paths = [e.field_path for e in hard_entries]
    assert "evidence_cited" in paths


def test_regulatory_framework_tags_change_is_hard_drift() -> None:
    """Tag set change fires hard drift."""
    baseline = _base_record(regulatory_framework_tags=["OSFI_E_23"])
    current = _base_record(
        regulatory_framework_tags=["OSFI_E_23", "NIST_AI_RMF"],
    )
    entries = compare_records(baseline, current)
    hard_entries = [e for e in entries if e.category == DriftCategory.HARD]
    paths = [e.field_path for e in hard_entries]
    assert "regulatory_framework_tags" in paths


def test_regulatory_framework_tags_same_set_different_order_no_drift() -> None:
    """Tag set is a set; order does not matter."""
    baseline = _base_record(
        regulatory_framework_tags=["OSFI_E_23", "NIST_AI_RMF"],
    )
    current = _base_record(
        regulatory_framework_tags=["NIST_AI_RMF", "OSFI_E_23"],
    )
    entries = compare_records(baseline, current)
    assert entries == []


def test_regulatory_framework_tags_none_vs_empty_no_drift() -> None:
    """None and empty list both mean 'no tags'; not drift."""
    baseline = _base_record(regulatory_framework_tags=None)
    # The output contract requires regulatory_framework_tags to be either
    # absent or a non-empty list, so we exercise the None-to-None case.
    current = _base_record(regulatory_framework_tags=None)
    entries = compare_records(baseline, current)
    assert entries == []


# -- compare_records: soft drift ----------------------------------------


def test_confidence_delta_within_threshold_no_drift() -> None:
    """Confidence shift below threshold is ignored."""
    baseline = _base_record(confidence_score=0.78)
    current = _base_record(confidence_score=0.80)  # delta 0.02 < 0.05
    entries = compare_records(baseline, current)
    assert entries == []


def test_confidence_delta_at_threshold_no_drift() -> None:
    """Delta exactly at threshold is not drift (strict > with float tolerance)."""
    baseline = _base_record(confidence_score=0.75)
    current = _base_record(confidence_score=0.80)  # delta nominally 0.05
    entries = compare_records(baseline, current)
    assert entries == []


def test_confidence_delta_beyond_threshold_is_soft_drift() -> None:
    """Delta beyond threshold fires soft drift."""
    baseline = _base_record(confidence_score=0.75)
    current = _base_record(confidence_score=0.85)  # delta 0.10 > 0.05
    entries = compare_records(baseline, current)
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert "confidence_signal.score" in paths


def test_custom_threshold_respected() -> None:
    """Threshold parameter overrides the default."""
    baseline = _base_record(confidence_score=0.75)
    current = _base_record(confidence_score=0.80)  # delta nominally 0.05
    # Default threshold 0.05 -> no drift; custom 0.01 -> drift
    assert compare_records(baseline, current) == []
    entries = compare_records(
        baseline, current, soft_confidence_threshold=0.01,
    )
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert "confidence_signal.score" in paths


def test_classification_rationale_text_change_is_soft_drift() -> None:
    """Rationale text difference fires soft drift."""
    baseline = _base_record(classification_rationale="A reason.")
    current = _base_record(classification_rationale="A different reason.")
    entries = compare_records(baseline, current)
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert "classification_rationale" in paths


def test_required_mitigations_text_change_is_soft_drift() -> None:
    """Mitigation text difference (same count) fires soft drift."""
    baseline = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["First mitigation v1."],
    )
    current = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["First mitigation v2 reworded."],
    )
    entries = compare_records(baseline, current)
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert "required_mitigations" in paths


def test_accountable_owner_text_change_is_soft_drift() -> None:
    """Owner role-name text change (both set) is soft drift."""
    baseline = _base_record(
        recommended_disposition="escalate_senior_review",
        accountable_owner="Director, Risk",
    )
    current = _base_record(
        recommended_disposition="escalate_senior_review",
        accountable_owner="Senior Director, Operational Risk",
    )
    entries = compare_records(baseline, current)
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert "accountable_owner" in paths


def test_evidence_reasoning_text_change_is_soft_drift() -> None:
    """Same-count evidence with different reasoning text is soft drift."""
    baseline = _base_record(evidence_cited=[
        {"input_field_reference": "$.a", "reasoning": "Reasoning v1."},
    ])
    current = _base_record(evidence_cited=[
        {"input_field_reference": "$.a", "reasoning": "Reasoning v2."},
    ])
    entries = compare_records(baseline, current)
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert any("reasoning" in p for p in paths)


def test_evidence_field_reference_change_is_soft_drift() -> None:
    """Same-count evidence with different input field reference is soft drift."""
    baseline = _base_record(evidence_cited=[
        {"input_field_reference": "$.a", "reasoning": "Same."},
    ])
    current = _base_record(evidence_cited=[
        {"input_field_reference": "$.b", "reasoning": "Same."},
    ])
    entries = compare_records(baseline, current)
    soft_entries = [e for e in entries if e.category == DriftCategory.SOFT]
    paths = [e.field_path for e in soft_entries]
    assert any("input_field_reference" in p for p in paths)


# -- compare_records: complex scenarios ---------------------------------


def test_multiple_simultaneous_drifts_all_reported() -> None:
    """One comparison can produce multiple drift entries."""
    baseline = _base_record(
        risk_tier="tier_2_moderate",
        confidence_score=0.78,
        classification_rationale="Original text.",
    )
    current = _base_record(
        risk_tier="tier_3_elevated",
        confidence_score=0.90,
        classification_rationale="New text.",
    )
    entries = compare_records(baseline, current)
    paths = [e.field_path for e in entries]
    assert "risk_tier" in paths
    assert "confidence_signal.score" in paths
    assert "classification_rationale" in paths


# -- check_drift across scenarios --------------------------------------


def test_check_drift_empty_baseline_empty_report() -> None:
    """No baselines -> empty report."""
    report = check_drift(baselines={}, currents={})
    assert report.total_scenarios == 0
    assert not report.has_any_drift


def test_check_drift_no_drift_report() -> None:
    """All scenarios matching produces a no-drift report."""
    baseline = _base_record()
    current = _base_record()
    report = check_drift(
        baselines={"scenario-1": baseline},
        currents={"scenario-1": current},
    )
    assert report.total_scenarios == 1
    assert not report.has_any_drift
    assert report.scenarios_with_hard_drift == 0
    assert report.scenarios_with_soft_drift == 0


def test_check_drift_missing_current_is_hard_drift() -> None:
    """A baseline scenario missing from current results is hard drift."""
    baseline = _base_record()
    report = check_drift(
        baselines={"scenario-1": baseline},
        currents={},
    )
    assert report.has_hard_drift
    assert report.scenarios_with_hard_drift == 1


def test_check_drift_extra_current_ignored() -> None:
    """A scenario in current but not baseline is ignored (no error)."""
    baseline = _base_record()
    current_extra = _base_record(decision_id="d-extra-current")
    report = check_drift(
        baselines={"scenario-1": baseline},
        currents={
            "scenario-1": baseline,
            "scenario-extra": current_extra,
        },
    )
    assert report.total_scenarios == 1  # only the baseline-scoped one
    assert not report.has_any_drift


def test_check_drift_records_threshold_used() -> None:
    """The report records the threshold used for the run."""
    report = check_drift(
        baselines={}, currents={}, soft_confidence_threshold=0.10,
    )
    assert report.soft_confidence_threshold == 0.10


def test_check_drift_total_entries() -> None:
    """total_entries sums across scenarios."""
    b1 = _base_record(risk_tier="tier_1_low",
                      recommended_disposition="approve",
                      required_mitigations=None)
    b2 = _base_record(risk_tier="tier_2_moderate",
                      confidence_score=0.78)
    c1 = _base_record(risk_tier="tier_2_moderate",  # drift
                      recommended_disposition="approve",
                      required_mitigations=None)
    c2 = _base_record(risk_tier="tier_2_moderate",
                      confidence_score=0.90)  # drift
    report = check_drift(
        baselines={"s1": b1, "s2": b2},
        currents={"s1": c1, "s2": c2},
    )
    # At least 2 entries (one per scenario)
    assert report.total_entries >= 2


# -- ScenarioDrift convenience properties -------------------------------


def test_scenario_drift_no_entries() -> None:
    sd = ScenarioDrift(scenario_id="s", entries=[])
    assert not sd.has_any_drift
    assert not sd.has_hard_drift
    assert not sd.has_soft_drift


def test_scenario_drift_only_soft() -> None:
    sd = ScenarioDrift(
        scenario_id="s",
        entries=[DriftEntry(
            category=DriftCategory.SOFT,
            field_path="x", baseline_value="a", current_value="b",
            message="msg",
        )],
    )
    assert sd.has_any_drift
    assert not sd.has_hard_drift
    assert sd.has_soft_drift


def test_scenario_drift_with_hard() -> None:
    sd = ScenarioDrift(
        scenario_id="s",
        entries=[
            DriftEntry(
                category=DriftCategory.HARD,
                field_path="x", baseline_value="a", current_value="b",
                message="msg",
            ),
            DriftEntry(
                category=DriftCategory.SOFT,
                field_path="y", baseline_value="c", current_value="d",
                message="msg",
            ),
        ],
    )
    assert sd.has_hard_drift
    assert sd.has_soft_drift


def test_required_mitigations_added_where_none_were_before() -> None:
    """Mitigations going from None/empty to non-empty fires soft drift.

    Note: this is an edge case because disposition-conditional rules
    typically tie mitigations presence to disposition. But the check
    handles the standalone diff defensively.
    """
    # Both records use approve disposition (no mitigations required by
    # disposition rule), but we exercise the diff with one having
    # mitigations and the other not.
    baseline = _base_record(
        recommended_disposition="approve",
        required_mitigations=None,
    )
    # The schema disallows required_mitigations on approve, so we can't
    # construct a current with mitigations + approve. Use
    # conditional_approve on both, with one having None mitigations
    # bypassed via model_copy.
    base_with_mit = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["Existing mitigation."],
    )
    # model_copy with required_mitigations=None to simulate the
    # "removed" path; the baseline.bypass test is symmetric.
    # We construct directly via model_validate bypass.
    no_mit = _base_record(
        recommended_disposition="conditional_approve",
        required_mitigations=["Existing mitigation."],
    )
    no_mit = no_mit.model_copy(update={"required_mitigations": None})
    # Now no_mit has None; base_with_mit has 1 mitigation.
    # Test direction A: baseline empty -> current has mitigations.
    entries_a = compare_records(no_mit, base_with_mit)
    paths_a = [e.field_path for e in entries_a]
    assert "required_mitigations" in paths_a

    # Test direction B: baseline has mitigations -> current empty.
    entries_b = compare_records(base_with_mit, no_mit)
    paths_b = [e.field_path for e in entries_b]
    assert "required_mitigations" in paths_b


def test_enum_value_helper_handles_enums() -> None:
    """The internal _enum_value helper extracts .value from enum-like objects."""
    from eval.drift.checker import _enum_value
    from enum import Enum

    class FakeEnum(str, Enum):
        FOO = "foo"
    assert _enum_value(FakeEnum.FOO) == "foo"
    # Plain string passes through
    assert _enum_value("plain_string") == "plain_string"


def test_truncate_helper_handles_short_text() -> None:
    """The internal _truncate helper passes short text through unchanged."""
    from eval.drift.checker import _truncate
    short = "hello world"
    assert _truncate(short) == short
    # Long text gets truncated with ellipsis
    long = "x" * 200
    truncated = _truncate(long)
    assert truncated.endswith("...")
    assert len(truncated) <= 123  # max_len + len("...")


# -- baseline file load/save -------------------------------------------


def test_save_and_load_baselines_roundtrip(tmp_path: Path) -> None:
    """Save then load returns equivalent records."""
    baseline_path = tmp_path / "baseline.jsonl"
    record = _base_record()
    save_baselines({"scenario-1": record}, path=baseline_path)
    loaded = load_baselines(path=baseline_path)
    assert "scenario-1" in loaded
    loaded_record = loaded["scenario-1"]
    # Round-trip through JSON canonicalizes datetime; allow ms-level
    # equality on decision_timestamp.
    assert loaded_record.risk_tier == record.risk_tier
    assert loaded_record.recommended_disposition == record.recommended_disposition
    assert loaded_record.confidence_signal.score == record.confidence_signal.score
    assert loaded_record.classification_rationale == record.classification_rationale


def test_save_baselines_creates_parent_directory(tmp_path: Path) -> None:
    """Save creates the parent directory if needed."""
    nested_path = tmp_path / "nested" / "dir" / "baseline.jsonl"
    record = _base_record()
    save_baselines({"s1": record}, path=nested_path)
    assert nested_path.exists()


def test_save_baselines_writes_header_comment(tmp_path: Path) -> None:
    """The saved file has a comment header recording regeneration time."""
    baseline_path = tmp_path / "baseline.jsonl"
    record = _base_record()
    save_baselines({"s1": record}, path=baseline_path)
    content = baseline_path.read_text()
    assert content.startswith("#")
    assert "Last regenerated" in content
    assert "Framework version" in content


def test_save_baselines_sorts_by_scenario_id(tmp_path: Path) -> None:
    """Saved file orders scenarios by id for deterministic diff."""
    baseline_path = tmp_path / "baseline.jsonl"
    r = _base_record()
    save_baselines(
        {"b": r, "a": r, "c": r},
        path=baseline_path,
    )
    content = baseline_path.read_text()
    # The first non-comment line should be scenario "a"
    record_lines = [
        line for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert '"id": "a"' in record_lines[0]
    assert '"id": "b"' in record_lines[1]
    assert '"id": "c"' in record_lines[2]


def test_load_baselines_missing_file_raises() -> None:
    """Missing file raises BaselineLoadError with actionable message."""
    with pytest.raises(BaselineLoadError, match="not found"):
        load_baselines(path=Path("/nonexistent/baseline.jsonl"))


def test_load_baselines_invalid_json_raises(tmp_path: Path) -> None:
    """Malformed JSON on any line raises BaselineLoadError."""
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text("not valid json\n")
    with pytest.raises(BaselineLoadError, match="not valid JSON"):
        load_baselines(path=bad_path)


def test_load_baselines_non_object_raises(tmp_path: Path) -> None:
    """A line that's a JSON array (not object) is rejected."""
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text("[1, 2, 3]\n")
    with pytest.raises(BaselineLoadError, match="not a JSON object"):
        load_baselines(path=bad_path)


def test_load_baselines_missing_keys_raises(tmp_path: Path) -> None:
    """A line missing 'id' or 'record' is rejected."""
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text('{"id": "s1"}\n')
    with pytest.raises(BaselineLoadError, match="missing"):
        load_baselines(path=bad_path)


def test_load_baselines_invalid_record_raises(tmp_path: Path) -> None:
    """A record payload that doesn't match TriageRecord raises."""
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text(
        '{"id": "s1", "record": {"this_is": "not a valid TriageRecord"}}\n'
    )
    with pytest.raises(BaselineLoadError, match="does not validate"):
        load_baselines(path=bad_path)


def test_load_baselines_skips_comment_lines(tmp_path: Path) -> None:
    """Comment lines (starting with #) and blank lines are skipped."""
    baseline_path = tmp_path / "baseline.jsonl"
    record = _base_record()
    save_baselines({"s1": record}, path=baseline_path)
    # The saved file has comment lines; loading should still work.
    loaded = load_baselines(path=baseline_path)
    assert "s1" in loaded


def test_load_baselines_handles_revoked_at(tmp_path: Path) -> None:
    """A baseline record with revoked_at parses correctly."""
    baseline_path = tmp_path / "baseline.jsonl"
    record = _base_record()
    revoked = record.model_copy(update={
        "revoked_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "revocation_reason": "Test revocation.",
    })
    save_baselines({"s1": revoked}, path=baseline_path)
    loaded = load_baselines(path=baseline_path)
    assert loaded["s1"].revoked_at is not None
    assert loaded["s1"].revoked_at.tzinfo is not None


# -- demo scenarios baseline roundtrip ----------------------------------


def test_demo_scenarios_baseline_loads_cleanly() -> None:
    """The checked-in baseline file loads without error."""
    repo_root = Path(__file__).parent.parent
    baseline_path = (
        repo_root / "eval" / "baselines" / "demo-scenarios.baseline.jsonl"
    )
    if not baseline_path.exists():
        pytest.skip("baseline file not present in this run")
    loaded = load_baselines(path=baseline_path)
    assert len(loaded) == 5  # five demo scenarios
    # Tier classifications match the curated dataset
    tiers = {sid: _enum_value(r.risk_tier) for sid, r in loaded.items()}
    tier_values = set(tiers.values())
    assert "tier_1_low" in tier_values
    assert "tier_4_high" in tier_values


def _enum_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)
