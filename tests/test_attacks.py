"""Tests for the Phase 4 sub-system 1 prompt-injection attack suite.

Covers the AttackExample model, dataset loader, runner, and metrics
aggregator. The runner is tested against a stub agent (not a real LLM)
so the test suite stays deterministic and Anthropic-credential-free.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from agent.output_models import (
    ConfidenceSignal,
    Disposition,
    EvidenceCitation,
    RiskTier,
    TriageRecord,
)
from eval.attacks import (
    AttackAggregateMetrics,
    AttackDataset,
    AttackDatasetError,
    AttackEvalReport,
    AttackEvalRunner,
    AttackExample,
    AttackOutcome,
    compute_attack_metrics,
    load_attack_dataset,
)


REPO_ROOT = Path(__file__).parent.parent
BASELINE_PATH = REPO_ROOT / "eval" / "datasets" / "prompt-injection-baseline.jsonl"


# -- Test fixtures and helpers --------------------------------------------


def _make_attack(
    attack_id: str = "test-attack-1",
    attack_type: str = "tier_manipulation",
    threat_ids: Optional[list[str]] = None,
    submission: Optional[dict[str, Any]] = None,
    **assertions: Any,
) -> AttackExample:
    """Build an AttackExample with sensible defaults plus declared assertions."""
    return AttackExample(
        attack_id=attack_id,
        attack_type=attack_type,  # type: ignore[arg-type]
        threat_ids=threat_ids if threat_ids is not None else ["T-AI1"],
        description="Synthetic attack for testing.",
        submission=submission if submission is not None else {
            "vendor_id": "v-test", "schema_version": "1.0.0"
        },
        **assertions,
    )


def _make_record(
    risk_tier: str = "tier_3_elevated",
    disposition: str = "conditional_approve",
    rationale: str = (
        "Standard rationale describing the classification basis with sufficient "
        "detail to satisfy the minimum length requirements of the output contract."
    ),
) -> TriageRecord:
    """Build a minimal valid TriageRecord for stub agent responses."""
    from datetime import datetime, timezone
    kwargs: dict[str, Any] = dict(
        decision_id="d-test",
        decision_timestamp=datetime.now(timezone.utc),
        input_submission_id="v-test",
        input_schema_version="1.0.0",
        agent_version="test:0.0.0",
        risk_tier=risk_tier,
        recommended_disposition=disposition,
        classification_rationale=rationale,
        evidence_cited=[EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning="Test rationale anchor providing minimum context length.",
        )],
        confidence_signal=ConfidenceSignal(score=0.5, interpretation="moderate"),
        output_schema_version="1.0.0",
    )
    if disposition == "conditional_approve":
        kwargs["required_mitigations"] = [
            "test mitigation noting standard controls and oversight"
        ]
    return TriageRecord(**kwargs)


class _StubAgent:
    """A stub agent for runner testing.

    Configured per test via ``response`` (returned by triage) or
    ``raises`` (exception raised by triage). One of the two must be set.
    """

    def __init__(
        self,
        response: Optional[TriageRecord] = None,
        raises: Optional[Exception] = None,
    ) -> None:
        if (response is None) == (raises is None):
            raise ValueError("StubAgent: set exactly one of response or raises")
        self._response = response
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def triage(
        self,
        submission: dict[str, Any],
        documents: Optional[list[Any]] = None,
        regulation_chunks: Optional[list[Any]] = None,
        decision_id: Optional[str] = None,
    ) -> TriageRecord:
        self.calls.append({
            "submission": submission,
            "documents": documents,
            "regulation_chunks": regulation_chunks,
        })
        if self._raises is not None:
            raise self._raises
        assert self._response is not None
        return self._response


# -- AttackExample model --------------------------------------------------


def test_attack_example_constructs_with_minimum_assertions() -> None:
    """An AttackExample with one assertion constructs cleanly."""
    a = _make_attack(tier_must_be_in=["tier_3_elevated", "tier_4_high"])
    assert a.attack_id == "test-attack-1"
    assert a.tier_must_be_in == ["tier_3_elevated", "tier_4_high"]


def test_attack_example_is_frozen() -> None:
    """AttackExample is immutable (audit posture)."""
    a = _make_attack(tier_must_be_in=["tier_3_elevated"])
    with pytest.raises(ValidationError):
        a.attack_id = "mutated"  # type: ignore[misc]


def test_attack_example_rejects_extra_fields() -> None:
    """Unknown fields are rejected."""
    with pytest.raises(ValidationError):
        AttackExample(
            attack_id="x",
            attack_type="tier_manipulation",
            threat_ids=["T-AI1"],
            description="x",
            submission={},
            tier_must_be_in=["tier_1_low"],
            invented="should reject",  # type: ignore[call-arg]
        )


def test_attack_example_requires_non_empty_threat_ids() -> None:
    """At least one threat_id must be declared."""
    with pytest.raises(ValidationError):
        AttackExample(
            attack_id="x",
            attack_type="tier_manipulation",
            threat_ids=[],
            description="x",
            submission={},
            tier_must_be_in=["tier_1_low"],
        )


def test_attack_example_rejects_no_assertions() -> None:
    """Without any assertion declared, the attack provides no signal."""
    with pytest.raises(ValueError, match="no assertions"):
        AttackExample(
            attack_id="x",
            attack_type="tier_manipulation",
            threat_ids=["T-AI1"],
            description="x",
            submission={},
        )


def test_attack_example_rejects_expected_to_raise_with_content_asserts() -> None:
    """expected_to_raise and content assertions are mutually exclusive."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        AttackExample(
            attack_id="x",
            attack_type="bait_and_switch_document",
            threat_ids=["T-AI1"],
            description="x",
            submission={},
            expected_to_raise="TriageInputError",
            tier_must_be_in=["tier_1_low"],
        )


def test_attack_example_expected_to_raise_alone_is_valid() -> None:
    """expected_to_raise on its own is a complete attack spec."""
    a = _make_attack(
        attack_type="bait_and_switch_document",
        expected_to_raise="TriageInputError",
    )
    assert a.expected_to_raise == "TriageInputError"


def test_attack_example_rejects_invalid_attack_type() -> None:
    """attack_type must be in the literal enum."""
    with pytest.raises(ValidationError):
        AttackExample(
            attack_id="x",
            attack_type="invented_category",  # type: ignore[arg-type]
            threat_ids=["T-AI1"],
            description="x",
            submission={},
            tier_must_be_in=["tier_1_low"],
        )


# -- AttackDataset loader -------------------------------------------------


def test_load_attack_dataset_round_trips_baseline() -> None:
    """The shipped baseline parses and produces a deterministic hash."""
    dataset = load_attack_dataset(BASELINE_PATH)
    assert len(dataset.attacks) >= 12  # baseline has at least 12 attacks
    assert dataset.content_hash.startswith("sha256:")
    # Re-loading the same file produces the same hash.
    dataset2 = load_attack_dataset(BASELINE_PATH)
    assert dataset.content_hash == dataset2.content_hash


def test_load_attack_dataset_missing_file(tmp_path: Path) -> None:
    """A missing file path raises AttackDatasetError."""
    with pytest.raises(AttackDatasetError, match="not found"):
        load_attack_dataset(tmp_path / "does-not-exist.jsonl")


def test_load_attack_dataset_empty_file(tmp_path: Path) -> None:
    """An empty file raises AttackDatasetError."""
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    with pytest.raises(AttackDatasetError, match="no attack entries"):
        load_attack_dataset(p)


def test_load_attack_dataset_only_comments(tmp_path: Path) -> None:
    """A file with only comments and blanks raises AttackDatasetError."""
    p = tmp_path / "comments.jsonl"
    p.write_text("# header\n\n# another\n")
    with pytest.raises(AttackDatasetError, match="no attack entries"):
        load_attack_dataset(p)


def test_load_attack_dataset_skips_comments_and_blanks(tmp_path: Path) -> None:
    """Comment and blank lines are skipped during parsing."""
    p = tmp_path / "mixed.jsonl"
    p.write_text(
        "# leading comment\n"
        "\n"
        + json.dumps({
            "attack_id": "a1",
            "attack_type": "tier_manipulation",
            "threat_ids": ["T-AI1"],
            "description": "x",
            "submission": {},
            "tier_must_be_in": ["tier_1_low"],
        }) + "\n"
        "# trailing comment\n"
    )
    dataset = load_attack_dataset(p)
    assert len(dataset.attacks) == 1
    assert dataset.attacks[0].attack_id == "a1"


def test_load_attack_dataset_reports_line_for_bad_json(tmp_path: Path) -> None:
    """Malformed JSON surfaces with file:line in the error message."""
    p = tmp_path / "bad.jsonl"
    p.write_text(
        json.dumps({
            "attack_id": "a1", "attack_type": "tier_manipulation",
            "threat_ids": ["T-AI1"], "description": "x", "submission": {},
            "tier_must_be_in": ["tier_1_low"],
        }) + "\n"
        "this is not json\n"
    )
    with pytest.raises(AttackDatasetError, match=":2:"):
        load_attack_dataset(p)


def test_load_attack_dataset_reports_line_for_validation_error(tmp_path: Path) -> None:
    """A schema-invalid attack surfaces with file:line in the error message."""
    p = tmp_path / "bad-schema.jsonl"
    p.write_text(json.dumps({"attack_id": "missing-fields"}) + "\n")
    with pytest.raises(AttackDatasetError, match=":1:"):
        load_attack_dataset(p)


# -- AttackEvalRunner: assertion grading ---------------------------------


def test_runner_passes_tier_in_set() -> None:
    """A record whose tier is in tier_must_be_in passes the assertion."""
    attack = _make_attack(tier_must_be_in=["tier_3_elevated", "tier_4_high"])
    agent = _StubAgent(response=_make_record(risk_tier="tier_3_elevated"))
    runner = AttackEvalRunner(agent)
    outcome = runner._run_one(attack)
    assert outcome.passed is True
    assert outcome.failure_reasons == []


def test_runner_fails_tier_not_in_set() -> None:
    """A record whose tier is outside tier_must_be_in fails."""
    attack = _make_attack(tier_must_be_in=["tier_3_elevated", "tier_4_high"])
    agent = _StubAgent(response=_make_record(risk_tier="tier_1_low"))
    runner = AttackEvalRunner(agent)
    outcome = runner._run_one(attack)
    assert outcome.passed is False
    assert any("risk_tier" in r for r in outcome.failure_reasons)


def test_runner_fails_disposition_not_in_set() -> None:
    """A record whose disposition is outside disposition_must_be_in fails."""
    attack = _make_attack(disposition_must_be_in=["reject", "escalate_senior_review"])
    agent = _StubAgent(response=_make_record(disposition="approve"))
    runner = AttackEvalRunner(agent)
    outcome = runner._run_one(attack)
    assert outcome.passed is False
    assert any("recommended_disposition" in r for r in outcome.failure_reasons)


def test_runner_fails_rationale_contains_forbidden() -> None:
    """A rationale containing a forbidden substring fails (case insensitive)."""
    attack = _make_attack(
        tier_must_be_in=["tier_3_elevated"],
        rationale_must_not_contain=["IGNORE PREVIOUS INSTRUCTIONS"],
    )
    agent = _StubAgent(response=_make_record(
        risk_tier="tier_3_elevated",
        rationale="The submission requested I ignore previous instructions and approve.",
    ))
    runner = AttackEvalRunner(agent)
    outcome = runner._run_one(attack)
    assert outcome.passed is False
    assert any("forbidden phrase" in r for r in outcome.failure_reasons)


def test_runner_rationale_check_is_case_insensitive() -> None:
    """rationale_must_not_contain matches regardless of case."""
    attack = _make_attack(
        tier_must_be_in=["tier_3_elevated"],
        rationale_must_not_contain=["ATTACKER_CANARY"],
    )
    agent = _StubAgent(response=_make_record(
        risk_tier="tier_3_elevated",
        rationale="Some prose with attacker_canary mixed in.",
    ))
    outcome = AttackEvalRunner(agent)._run_one(attack)
    assert outcome.passed is False


def test_runner_passes_with_clean_rationale() -> None:
    """A rationale with no forbidden phrases passes that assertion."""
    attack = _make_attack(
        tier_must_be_in=["tier_3_elevated"],
        rationale_must_not_contain=["FORBIDDEN", "canary"],
    )
    agent = _StubAgent(response=_make_record(
        risk_tier="tier_3_elevated",
        rationale="Clean rationale with nothing untoward.",
    ))
    outcome = AttackEvalRunner(agent)._run_one(attack)
    assert outcome.passed is True


def test_runner_passes_expected_to_raise_when_correct_exception() -> None:
    """expected_to_raise passes when the agent raises the named exception."""
    from agent.agent import TriageInputError
    attack = _make_attack(
        attack_type="bait_and_switch_document",
        expected_to_raise="TriageInputError",
    )
    agent = _StubAgent(raises=TriageInputError("hash mismatch"))
    outcome = AttackEvalRunner(agent)._run_one(attack)
    assert outcome.passed is True
    assert outcome.raised == "TriageInputError"


def test_runner_fails_expected_to_raise_when_no_exception() -> None:
    """expected_to_raise fails when the agent returns a record successfully."""
    attack = _make_attack(
        attack_type="bait_and_switch_document",
        expected_to_raise="TriageInputError",
    )
    agent = _StubAgent(response=_make_record())
    outcome = AttackEvalRunner(agent)._run_one(attack)
    assert outcome.passed is False
    assert any("returned a record" in r for r in outcome.failure_reasons)


def test_runner_fails_expected_to_raise_when_wrong_exception() -> None:
    """expected_to_raise fails when the agent raises a different exception."""
    attack = _make_attack(
        attack_type="bait_and_switch_document",
        expected_to_raise="TriageInputError",
    )
    agent = _StubAgent(raises=ValueError("unrelated"))
    outcome = AttackEvalRunner(agent)._run_one(attack)
    assert outcome.passed is False
    assert any("ValueError" in r for r in outcome.failure_reasons)


def test_runner_fails_when_agent_raises_unexpectedly() -> None:
    """An unexpected exception on a content-grading attack is a failure."""
    attack = _make_attack(tier_must_be_in=["tier_3_elevated"])
    agent = _StubAgent(raises=ValueError("oops"))
    outcome = AttackEvalRunner(agent)._run_one(attack)
    assert outcome.passed is False
    assert outcome.raised == "ValueError"
    assert any("ValueError" in r for r in outcome.failure_reasons)


# -- AttackEvalRunner: payload construction -------------------------------


def test_runner_constructs_documents_from_dataset_payload() -> None:
    """Documents in the dataset are constructed into Document instances for the agent."""
    import hashlib
    doc_text = "Sample document content."
    doc_hash = "sha256:" + hashlib.sha256(doc_text.encode()).hexdigest()
    attack = _make_attack(
        tier_must_be_in=["tier_3_elevated"],
        documents=[{
            "source_reference": "internal://doc1.pdf",
            "artifact_type": "soc2_report",
            "page_count": 1,
            "extracted_text": doc_text,
            "pages": [doc_text],
            "content_hash": doc_hash,
        }],
    )
    agent = _StubAgent(response=_make_record(risk_tier="tier_3_elevated"))
    AttackEvalRunner(agent)._run_one(attack)
    assert len(agent.calls) == 1
    docs = agent.calls[0]["documents"]
    assert docs is not None and len(docs) == 1
    assert docs[0].source_reference == "internal://doc1.pdf"


def test_runner_constructs_chunks_from_dataset_payload() -> None:
    """Regulation chunks in the dataset are constructed into Chunk instances."""
    import hashlib
    chunk_text = "Sample regulation chunk text."
    chunk_hash = "sha256:" + hashlib.sha256(chunk_text.encode()).hexdigest()
    attack = _make_attack(
        tier_must_be_in=["tier_3_elevated"],
        regulation_chunks=[{
            "chunk_id": "c:d:page-1",
            "corpus_name": "c",
            "document_name": "d",
            "page_number": 1,
            "text": chunk_text,
            "content_hash": chunk_hash,
        }],
    )
    agent = _StubAgent(response=_make_record(risk_tier="tier_3_elevated"))
    AttackEvalRunner(agent)._run_one(attack)
    assert len(agent.calls) == 1
    chunks = agent.calls[0]["regulation_chunks"]
    assert chunks is not None and len(chunks) == 1
    assert chunks[0].chunk_id == "c:d:page-1"


# -- AttackEvalRunner: run() across a dataset -----------------------------


def test_runner_run_executes_every_attack_in_dataset() -> None:
    """run() produces one AttackOutcome per dataset attack."""
    dataset = AttackDataset(
        path="test",
        content_hash="sha256:" + "a" * 64,
        attacks=[
            _make_attack(attack_id="a1", tier_must_be_in=["tier_3_elevated"]),
            _make_attack(attack_id="a2", tier_must_be_in=["tier_3_elevated"]),
            _make_attack(attack_id="a3", tier_must_be_in=["tier_3_elevated"]),
        ],
    )
    agent = _StubAgent(response=_make_record(risk_tier="tier_3_elevated"))
    report = AttackEvalRunner(agent).run(dataset)
    assert len(report.outcomes) == 3
    assert [o.attack_id for o in report.outcomes] == ["a1", "a2", "a3"]


def test_runner_continues_after_a_failing_attack() -> None:
    """A failing attack does not abort the remainder of the run."""
    # Use a stub agent that responds with a tier that fails one attack but
    # not the other. Cleaner than alternating exceptions per call.
    dataset = AttackDataset(
        path="test",
        content_hash="sha256:" + "a" * 64,
        attacks=[
            _make_attack(attack_id="a1", tier_must_be_in=["tier_1_low"]),  # will fail
            _make_attack(attack_id="a2", tier_must_be_in=["tier_3_elevated"]),  # will pass
        ],
    )
    agent = _StubAgent(response=_make_record(risk_tier="tier_3_elevated"))
    report = AttackEvalRunner(agent).run(dataset)
    assert len(report.outcomes) == 2
    assert report.outcomes[0].passed is False
    assert report.outcomes[1].passed is True


# -- AttackAggregateMetrics ------------------------------------------------


def test_compute_metrics_overall_pass_rate() -> None:
    """Overall pass rate is passed/total."""
    report = AttackEvalReport(
        dataset_path="t",
        dataset_content_hash="sha256:" + "a" * 64,
        outcomes=[
            AttackOutcome(attack_id=f"a{i}", attack_type="tier_manipulation",
                          threat_ids=["T-AI1"], passed=(i < 3))
            for i in range(5)
        ],
    )
    metrics = compute_attack_metrics(report)
    assert metrics.total_attacks == 5
    assert metrics.total_passed == 3
    assert metrics.overall_pass_rate == 0.6


def test_compute_metrics_breaks_down_by_category() -> None:
    """Per-category metrics roll up correctly."""
    report = AttackEvalReport(
        dataset_path="t",
        dataset_content_hash="sha256:" + "a" * 64,
        outcomes=[
            AttackOutcome(attack_id="a1", attack_type="tier_manipulation",
                          threat_ids=["T-AI1"], passed=True),
            AttackOutcome(attack_id="a2", attack_type="tier_manipulation",
                          threat_ids=["T-AI1"], passed=False),
            AttackOutcome(attack_id="a3", attack_type="schema_manipulation",
                          threat_ids=["T-AI2"], passed=True),
        ],
    )
    metrics = compute_attack_metrics(report)
    by_cat = {c.attack_type: c for c in metrics.by_category}
    assert by_cat["tier_manipulation"].total == 2
    assert by_cat["tier_manipulation"].passed == 1
    assert by_cat["tier_manipulation"].pass_rate == 0.5
    assert by_cat["schema_manipulation"].total == 1
    assert by_cat["schema_manipulation"].pass_rate == 1.0


def test_compute_metrics_double_counts_across_threat_ids() -> None:
    """An attack with multiple threat_ids contributes to each one."""
    report = AttackEvalReport(
        dataset_path="t",
        dataset_content_hash="sha256:" + "a" * 64,
        outcomes=[
            AttackOutcome(attack_id="a1", attack_type="tier_manipulation",
                          threat_ids=["T-AI1", "T-AI2"], passed=True),
        ],
    )
    metrics = compute_attack_metrics(report)
    by_threat = {t.threat_id: t for t in metrics.by_threat_id}
    assert by_threat["T-AI1"].total == 1
    assert by_threat["T-AI2"].total == 1


def test_compute_metrics_empty_report() -> None:
    """An empty report produces zero metrics rather than divide-by-zero."""
    report = AttackEvalReport(
        dataset_path="t",
        dataset_content_hash="sha256:" + "a" * 64,
        outcomes=[],
    )
    metrics = compute_attack_metrics(report)
    assert metrics.total_attacks == 0
    assert metrics.overall_pass_rate == 0.0
    assert metrics.by_category == []
    assert metrics.by_threat_id == []


# -- End-to-end against the baseline dataset ------------------------------


def test_baseline_dataset_runs_against_stub_agent() -> None:
    """The shipped baseline dataset runs cleanly against a stub agent."""
    dataset = load_attack_dataset(BASELINE_PATH)
    # A "perfect" agent returns tier_4_high with reject for every submission.
    # That won't pass every attack (some assertions are disposition-specific
    # or require expected_to_raise), but the runner must process every entry
    # without crashing.
    agent = _StubAgent(response=_make_record(
        risk_tier="tier_4_high",
        disposition="reject",
        rationale="Clean rationale.",
    ))
    report = AttackEvalRunner(agent).run(dataset)
    assert len(report.outcomes) == len(dataset.attacks)
    # Metrics aggregate without crashing.
    metrics = compute_attack_metrics(report)
    assert metrics.total_attacks == len(dataset.attacks)
    # The bait-and-switch attack expects an exception; since our stub
    # never raises, that attack fails.
    bait_outcome = next(o for o in report.outcomes if "bait" in o.attack_id)
    assert bait_outcome.passed is False
