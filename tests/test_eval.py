"""Tests for the Phase 3 eval harness (sub-system 3).

These tests cover the four MVP modules: dataset loading, the runner,
metrics computation, and the canonical baseline dataset's shape.
PydanticAI's TestModel and FunctionModel let us exercise the runner
end-to-end without real LLM calls.

Test environment note: identical to test_agent_core.py — we set the
ANTHROPIC_API_KEY placeholder before pydantic_ai imports so the default
provider's construction-time validation passes in tests. We do not call
the real Anthropic API in this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

if not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = "test-placeholder-not-a-real-key"

import pytest
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart

from agent.agent import TriageAgent, TriageAgentConfig
from agent.output_models import TriageRecord
from eval import (
    AggregateMetrics,
    Dataset,
    EvalReport,
    ExampleResult,
    GradedExample,
    TriageEvalRunner,
    compute_metrics,
    load_dataset,
)


REPO_ROOT = Path(__file__).parent.parent
BASELINE_PATH = REPO_ROOT / "eval" / "datasets" / "tier-classification-baseline.jsonl"


# Canonical classification payloads keyed by tier. Each is a valid
# _TriageClassification shape; a FunctionModel returning one of these
# simulates an LLM that produced this classification.
_PAYLOAD_BY_TIER: dict[str, dict[str, Any]] = {
    "tier_1_low": {
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "Test rationale for tier_1_low.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."}
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
    },
    "tier_2_moderate": {
        "risk_tier": "tier_2_moderate",
        "recommended_disposition": "conditional_approve",
        "classification_rationale": "Test rationale for tier_2_moderate.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."}
        ],
        "confidence_signal": {"score": 0.75, "interpretation": "moderate"},
        "required_mitigations": ["Test mitigation."],
    },
    "tier_3_elevated": {
        "risk_tier": "tier_3_elevated",
        "recommended_disposition": "escalate_senior_review",
        "classification_rationale": "Test rationale for tier_3_elevated.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."}
        ],
        "confidence_signal": {"score": 0.7, "interpretation": "moderate"},
        "accountable_owner": "Senior Vendor Risk Manager",
    },
    "tier_4_high": {
        "risk_tier": "tier_4_high",
        "recommended_disposition": "reject",
        "classification_rationale": "Test rationale for tier_4_high.",
        "evidence_cited": [
            {"input_field_reference": "$.ai_usage_level", "reasoning": "Test."}
        ],
        "confidence_signal": {"score": 0.95, "interpretation": "high"},
    },
}


def _agent_that_perfectly_matches(dataset: Dataset) -> TriageAgent:
    """Build an agent that returns the expected output for every example in dataset.

    Constructs a lookup vendor_id -> matched payload (tier + disposition +
    any conditional fields required by the disposition). The FunctionModel
    scans the prompt for whichever vendor_id is being triaged and returns
    that exact payload. Simulates a perfectly-accurate agent so the
    runner's metrics can be verified on a known-correct baseline.
    """
    lookup: dict[str, dict[str, Any]] = {}
    for ex in dataset:
        payload = dict(_PAYLOAD_BY_TIER[ex.expected_tier])
        # Override the canned disposition with the example's expected one
        # (e.g., tier_4 in the baseline includes both reject and
        # escalate_senior_review; the canned default is reject).
        payload["recommended_disposition"] = ex.expected_disposition
        if ex.expected_disposition == "conditional_approve":
            payload.setdefault("required_mitigations", ["Test mitigation."])
        elif ex.expected_disposition == "escalate_senior_review":
            payload.setdefault("accountable_owner", "Senior Vendor Risk Manager")
        else:
            payload.pop("required_mitigations", None)
            payload.pop("accountable_owner", None)
        lookup[ex.submission["vendor_id"]] = payload

    def _call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt_text = ""
        for msg in messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    prompt_text += content
        for vid, payload in lookup.items():
            if vid in prompt_text:
                return ModelResponse(parts=[
                    ToolCallPart(tool_name="final_result", args=payload)
                ])
        raise AssertionError(
            f"_agent_that_perfectly_matches could not find any vendor_id in "
            f"the prompt; first 200 chars: {prompt_text[:200]!r}"
        )
    return TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))


def _agent_that_matches_expected_tier() -> TriageAgent:
    """Build an agent that returns the EXPECTED tier from the submission.

    Less precise than ``_agent_that_perfectly_matches``: returns the
    canned default disposition for each tier, which may not match the
    example's expected disposition. Used by tests that exercise
    tier-only agreement paths.
    """
    tier_marker_to_full = {
        "tier1": "tier_1_low",
        "tier2": "tier_2_moderate",
        "tier3": "tier_3_elevated",
        "tier4": "tier_4_high",
    }

    def _call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt_text = ""
        for msg in messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    prompt_text += content
        for marker, tier_full in tier_marker_to_full.items():
            if marker in prompt_text:
                return ModelResponse(parts=[
                    ToolCallPart(tool_name="final_result", args=_PAYLOAD_BY_TIER[tier_full])
                ])
        raise AssertionError(
            f"_agent_that_matches_expected_tier could not find a tier marker "
            f"in the prompt; first 200 chars: {prompt_text[:200]!r}"
        )
    return TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))


def _agent_that_always_returns(tier: str) -> TriageAgent:
    """Build an agent that always returns the given tier's canned payload.

    Useful for testing partial-agreement scenarios where the agent
    answers every example the same way.
    """
    payload = _PAYLOAD_BY_TIER[tier]
    def _call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=payload)
        ])
    return TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))


def _agent_that_raises() -> TriageAgent:
    """Build an agent whose FunctionModel returns invalid payloads.

    PydanticAI retries on invalid output; after retries are exhausted,
    UnexpectedModelBehavior is raised. The runner should catch this and
    record the error per example.
    """
    def _call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # Return a tool call with invalid structure (missing required fields).
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args={"risk_tier": "bogus"})
        ])
    return TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))


# -- GradedExample model ----------------------------------------------------


def test_graded_example_constructs_from_valid_data() -> None:
    """Minimum-valid GradedExample constructs without complaint."""
    ex = GradedExample(
        id="test-ex-1",
        submission={"vendor_id": "v-1", "schema_version": "1.0.0"},
        expected_tier="tier_1_low",
        expected_disposition="approve",
        reviewer_notes="Sufficient.",
    )
    assert ex.id == "test-ex-1"
    assert ex.expected_tier == "tier_1_low"


def test_graded_example_is_frozen() -> None:
    """GradedExample is immutable after construction (audit posture)."""
    ex = GradedExample(
        id="test-ex-1",
        submission={"vendor_id": "v-1", "schema_version": "1.0.0"},
        expected_tier="tier_1_low",
        expected_disposition="approve",
        reviewer_notes="Sufficient.",
    )
    with pytest.raises(ValidationError):
        ex.id = "mutated"  # type: ignore[misc]


def test_graded_example_rejects_extra_fields() -> None:
    """Unknown fields in a graded example are rejected (no silent drift)."""
    with pytest.raises(ValidationError):
        GradedExample(
            id="test-ex-1",
            submission={"vendor_id": "v-1", "schema_version": "1.0.0"},
            expected_tier="tier_1_low",
            expected_disposition="approve",
            reviewer_notes="Sufficient.",
            invented_field="should reject",  # type: ignore[call-arg]
        )


def test_graded_example_rejects_invalid_tier() -> None:
    """expected_tier must be one of the four enumerated values."""
    with pytest.raises(ValidationError):
        GradedExample(
            id="test-ex-1",
            submission={"vendor_id": "v-1", "schema_version": "1.0.0"},
            expected_tier="tier_99_extreme",  # type: ignore[arg-type]
            expected_disposition="approve",
            reviewer_notes="Sufficient.",
        )


def test_graded_example_rejects_empty_reviewer_notes() -> None:
    """reviewer_notes is required (audit signal); empty is rejected."""
    with pytest.raises(ValidationError):
        GradedExample(
            id="test-ex-1",
            submission={"vendor_id": "v-1", "schema_version": "1.0.0"},
            expected_tier="tier_1_low",
            expected_disposition="approve",
            reviewer_notes="",
        )


# -- Dataset loading --------------------------------------------------------


def test_load_baseline_dataset_returns_eight_examples() -> None:
    """The canonical baseline dataset loads with 8 examples in expected order."""
    ds = load_dataset(BASELINE_PATH)
    assert len(ds) == 8


def test_load_baseline_dataset_has_balanced_tier_distribution() -> None:
    """The baseline dataset has 2 examples per tier (regression on tier coverage).

    A baseline dataset that drifts away from balanced coverage is a
    quality regression: the eval would silently de-weight whichever
    tier loses representation.
    """
    ds = load_dataset(BASELINE_PATH)
    from collections import Counter
    counts = Counter(ex.expected_tier for ex in ds)
    for tier in ["tier_1_low", "tier_2_moderate", "tier_3_elevated", "tier_4_high"]:
        assert counts[tier] == 2, (
            f"baseline dataset has {counts[tier]} examples for {tier}; expected 2"
        )


def test_load_baseline_dataset_has_unique_ids() -> None:
    """Every example in the baseline dataset has a distinct id."""
    ds = load_dataset(BASELINE_PATH)
    ids = [ex.id for ex in ds]
    assert len(ids) == len(set(ids))


def test_load_baseline_dataset_content_hash_is_stable(tmp_path: Path) -> None:
    """Loading the same file twice yields the same content_hash."""
    ds1 = load_dataset(BASELINE_PATH)
    ds2 = load_dataset(BASELINE_PATH)
    assert ds1.content_hash == ds2.content_hash


def test_load_dataset_rejects_missing_file(tmp_path: Path) -> None:
    """A missing file raises FileNotFoundError, not a silent empty dataset."""
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "does-not-exist.jsonl")


def test_load_dataset_rejects_empty_file(tmp_path: Path) -> None:
    """An empty (or only-comments) file raises ValueError, not an empty dataset."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("# comment only\n\n   \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no examples"):
        load_dataset(empty)


def test_load_dataset_rejects_malformed_json(tmp_path: Path) -> None:
    """A line with malformed JSON raises ValueError pointing to the line number."""
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{this is not valid json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=":1:"):
        load_dataset(bad)


def test_load_dataset_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Two examples with the same id raise ValueError, identifying the duplicate."""
    valid_example = {
        "id": "dup-id",
        "submission": {"vendor_id": "v-1", "schema_version": "1.0.0"},
        "expected_tier": "tier_1_low",
        "expected_disposition": "approve",
        "reviewer_notes": "Test.",
    }
    dup = tmp_path / "dup.jsonl"
    dup.write_text(
        json.dumps(valid_example) + "\n" + json.dumps(valid_example) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate example id"):
        load_dataset(dup)


def test_load_dataset_ignores_blank_lines_and_comments(tmp_path: Path) -> None:
    """Blank lines and lines starting with # are skipped."""
    example = {
        "id": "ex-1",
        "submission": {"vendor_id": "v-1", "schema_version": "1.0.0"},
        "expected_tier": "tier_1_low",
        "expected_disposition": "approve",
        "reviewer_notes": "Test.",
    }
    content = (
        "# this is a comment\n"
        "\n"
        f"{json.dumps(example)}\n"
        "   \n"
        "# trailing comment\n"
    )
    p = tmp_path / "with-comments.jsonl"
    p.write_text(content, encoding="utf-8")
    ds = load_dataset(p)
    assert len(ds) == 1
    assert ds.examples[0].id == "ex-1"


def test_load_dataset_uses_filename_stem_as_default_name(tmp_path: Path) -> None:
    """Without an explicit name, the dataset is named after the file stem."""
    example = {
        "id": "ex-1",
        "submission": {"vendor_id": "v-1", "schema_version": "1.0.0"},
        "expected_tier": "tier_1_low",
        "expected_disposition": "approve",
        "reviewer_notes": "Test.",
    }
    p = tmp_path / "my-suite.jsonl"
    p.write_text(json.dumps(example) + "\n", encoding="utf-8")
    ds = load_dataset(p)
    assert ds.name == "my-suite"


def test_dataset_supports_iteration_and_len() -> None:
    """Dataset is iterable and supports len() for ergonomic use."""
    ds = load_dataset(BASELINE_PATH)
    n = 0
    for ex in ds:
        assert isinstance(ex, GradedExample)
        n += 1
    assert n == len(ds) == 8


# -- ExampleResult + metrics ------------------------------------------------


def test_example_result_succeeded_property() -> None:
    """succeeded is True iff record is non-None."""
    r_ok = ExampleResult(
        example_id="x", expected_tier="tier_1_low",
        expected_disposition="approve",
        record=None, error_type="X", error_message="Y",
    )
    assert not r_ok.succeeded


def test_example_result_tier_agrees_on_match() -> None:
    """tier_agrees is True when the record's tier matches expected."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_perfectly_matches(ds)
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    for r in report.results:
        assert r.tier_agrees, f"{r.example_id} did not agree on tier"


def test_example_result_disposition_agrees_on_match() -> None:
    """disposition_agrees is True when the record's disposition matches expected."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_perfectly_matches(ds)
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    for r in report.results:
        assert r.disposition_agrees, f"{r.example_id} did not agree on disposition"


def test_example_result_tier_agrees_false_when_agent_raised() -> None:
    """tier_agrees and disposition_agrees are False when record is None."""
    r = ExampleResult(
        example_id="x", expected_tier="tier_1_low",
        expected_disposition="approve",
        record=None, error_type="X", error_message="Y",
    )
    assert not r.tier_agrees
    assert not r.disposition_agrees


def test_compute_metrics_with_empty_results() -> None:
    """An empty result list produces zero counts and zero rates (no division by zero)."""
    metrics = compute_metrics([])
    assert metrics.total == 0
    assert metrics.succeeded == 0
    assert metrics.failed == 0
    assert metrics.tier_agreement_rate == 0.0
    assert metrics.disposition_agreement_rate == 0.0
    assert metrics.evidence_count_min is None
    assert metrics.evidence_count_max is None
    assert metrics.evidence_count_mean is None


def test_compute_metrics_perfect_run() -> None:
    """A run where every example agreed shows 100% on both metrics."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_perfectly_matches(ds)
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.metrics.total == 8
    assert report.metrics.succeeded == 8
    assert report.metrics.failed == 0
    assert report.metrics.tier_agreement_count == 8
    assert report.metrics.tier_agreement_rate == 1.0
    assert report.metrics.disposition_agreement_count == 8
    assert report.metrics.disposition_agreement_rate == 1.0


def test_compute_metrics_partial_run_always_tier_1() -> None:
    """An agent answering tier_1_low for every example shows partial agreement.

    The baseline dataset has 2 tier_1 examples; an always-tier_1 agent
    agrees on those 2 only. Agreement rate is 2/8 = 0.25.
    """
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_always_returns("tier_1_low")
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.metrics.tier_agreement_count == 2
    assert report.metrics.tier_agreement_rate == pytest.approx(2 / 8)
    assert report.metrics.disposition_agreement_count == 2  # 2 tier_1 examples approve
    assert report.metrics.disposition_agreement_rate == pytest.approx(2 / 8)


def test_compute_metrics_evidence_count_stats() -> None:
    """Evidence count stats reflect the LLM-produced evidence lengths.

    All canned payloads produce exactly one evidence_cited entry; the
    min, max, and mean should all be 1.
    """
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.metrics.evidence_count_min == 1
    assert report.metrics.evidence_count_max == 1
    assert report.metrics.evidence_count_mean == 1.0


# -- TriageEvalRunner end-to-end --------------------------------------------


def test_runner_records_all_examples() -> None:
    """Every dataset example produces one ExampleResult in dataset order."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert len(report.results) == len(ds)
    assert [r.example_id for r in report.results] == [ex.id for ex in ds]


def test_runner_isolates_per_example_errors() -> None:
    """An agent that always raises produces a failure result per example, not abort.

    Per-example error isolation is the core resilience property: one
    bad example must not mask the agent's behaviour on the rest.
    """
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_raises()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.metrics.failed == 8
    assert report.metrics.succeeded == 0
    for r in report.results:
        assert r.record is None
        assert r.error_type == "UnexpectedModelBehavior"


def test_runner_report_records_dataset_content_hash() -> None:
    """The report's dataset_content_hash matches the dataset's content_hash."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.dataset_content_hash == ds.content_hash


def test_runner_report_records_agent_version() -> None:
    """The report's agent_version matches the agent's agent_version."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.agent_version == agent.agent_version


def test_runner_report_run_timestamp_is_utc_aware() -> None:
    """The report's run_timestamp has a timezone (no naive datetimes)."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    assert report.run_timestamp.tzinfo is not None


def test_runner_assigns_eval_specific_decision_ids() -> None:
    """The runner generates eval-specific decision_ids so reports do not collide.

    Decision ids encode the dataset name and example id so a record from
    an eval run is distinguishable from a production record on inspection.
    """
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    for r in report.results:
        assert r.record is not None
        assert r.record.decision_id.startswith("d-eval-")
        assert ds.name in r.record.decision_id
        assert r.example_id in r.record.decision_id


# -- EvalReport ------------------------------------------------------------


def test_eval_report_is_frozen() -> None:
    """EvalReport is immutable after construction (audit posture)."""
    ds = load_dataset(BASELINE_PATH)
    agent = _agent_that_matches_expected_tier()
    runner = TriageEvalRunner(agent)
    report = runner.run(ds)
    with pytest.raises(ValidationError):
        report.dataset_name = "mutated"  # type: ignore[misc]


def test_eval_report_rejects_extra_fields() -> None:
    """Unknown fields on an EvalReport are rejected at construction."""
    with pytest.raises(ValidationError):
        EvalReport(
            run_timestamp="2026-05-26T00:00:00Z",  # type: ignore[arg-type]
            agent_version="vrt-agent-v0.4.0-test",
            dataset_name="x",
            dataset_content_hash="0123456789abcdef",
            results=[],
            metrics=compute_metrics([]),
            invented_field="should reject",  # type: ignore[call-arg]
        )


# -- AgentProtocol --------------------------------------------------------


def test_runner_accepts_any_agent_protocol_implementer() -> None:
    """A duck-typed agent (not TriageAgent) works as long as it implements the protocol.

    Decoupling test: the runner depends on the protocol, not the concrete
    class. Substituting an unrelated implementation should run cleanly.
    """
    class _Stub:
        @property
        def agent_version(self) -> str:
            return "vrt-agent-stub-v0"

        def triage(self, submission: dict[str, Any], decision_id: Optional[str] = None) -> TriageRecord:
            # Always return a tier_1_low record.
            return TriageRecord(
                decision_id=decision_id or "d-stub-001",
                decision_timestamp="2026-05-26T00:00:00Z",  # type: ignore[arg-type]
                input_submission_id=submission["vendor_id"],
                input_schema_version=submission["schema_version"],
                agent_version=self.agent_version,
                risk_tier="tier_1_low",
                recommended_disposition="approve",
                classification_rationale="Stub rationale.",
                evidence_cited=[{"input_field_reference": "$.x", "reasoning": "Stub."}],  # type: ignore[list-item]
                confidence_signal={"score": 0.9, "interpretation": "high"},  # type: ignore[arg-type]
                output_schema_version="1.0.0",
            )

    ds = load_dataset(BASELINE_PATH)
    runner = TriageEvalRunner(_Stub())  # type: ignore[arg-type]
    report = runner.run(ds)
    assert report.agent_version == "vrt-agent-stub-v0"
    # Stub answers tier_1_low for everything; agrees with the 2 tier_1 examples.
    assert report.metrics.tier_agreement_count == 2
