"""Tests for the Phase 4 sub-system 4 LLM-as-judge harness.

Covers the Rubric model, the LLMJudge with FunctionModel-backed stubs
(no Anthropic credentials needed), edge-case short-circuit behavior
on the pre-built rubrics, judge result models, and aggregate metrics.

The judge is intentionally non-deterministic in production (LLM-backed).
Tests use FunctionModel stubs to make outcomes deterministic, but the
behavior asserted is what the judge does WITH the LLM, not bypassing it.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agent.output_models import (
    ConfidenceSignal,
    EvidenceCitation,
    TriageRecord,
)
from eval.judge import (
    CITATION_GROUNDING,
    JudgeAggregateMetrics,
    JudgeResult,
    LLMJudge,
    MITIGATION_APPROPRIATENESS,
    RATIONALE_COHERENCE,
    Rubric,
    RubricMetrics,
    compute_judge_metrics,
)
from retrieval.chunk import Chunk


# -- helpers ---------------------------------------------------------------


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stub_judge_model(
    score: float = 0.7,
    rationale: str = "Stub judge rationale for testing.",
) -> FunctionModel:
    """Return a FunctionModel that always answers with the given score+rationale."""
    def fn(messages: Any, info: Any) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="final_result",
            args={"score": score, "rationale": rationale},
        )])
    return FunctionModel(fn)


def _record(
    disposition: str = "conditional_approve",
    reasoning: str = "Standard reasoning text for testing the judge.",
    chunk_id_in_reasoning: Optional[str] = None,
    decision_id: str = "d-test",
) -> TriageRecord:
    if chunk_id_in_reasoning is not None:
        reasoning = f"Per chunk {chunk_id_in_reasoning}, {reasoning}"
    kwargs: dict[str, Any] = dict(
        decision_id=decision_id,
        decision_timestamp=datetime.now(timezone.utc),
        input_submission_id="v-test",
        input_schema_version="1.0.0",
        agent_version="test:0.0.0",
        risk_tier="tier_3_elevated",
        recommended_disposition=disposition,
        classification_rationale=(
            "Vendor processes PII for credit decisions in EU jurisdiction; "
            "this anchors a tier_3 classification based on PII categories "
            "and ai_act_self_classification."
        ),
        evidence_cited=[EvidenceCitation(
            input_field_reference="$.pii_processing_claims.processes_pii",
            reasoning=reasoning,
        )],
        confidence_signal=ConfidenceSignal(score=0.7, interpretation="moderate"),
        output_schema_version="1.0.0",
    )
    if disposition == "conditional_approve":
        kwargs["required_mitigations"] = ["monitor quarterly with documented review"]
    if disposition == "escalate_senior_review":
        kwargs["accountable_owner"] = "Test Owner"
    return TriageRecord(**kwargs)


def _submission() -> dict[str, Any]:
    return {
        "vendor_id": "v-test",
        "schema_version": "1.0.0",
        "vendor_name": "Test Vendor",
        "ai_usage_level": "core_business_decisions",
        "jurisdiction": "EU",
        "pii_processing_claims": {
            "processes_pii": True,
            "categories": ["financial"],
        },
    }


def _chunk(chunk_id: str = "osfi-e23:guideline:page-7") -> Chunk:
    text = "Federally regulated institutions shall maintain inventory."
    return Chunk(
        chunk_id=chunk_id,
        corpus_name=chunk_id.split(":")[0],
        document_name=chunk_id.split(":")[1],
        page_number=int(chunk_id.split("page-")[1]),
        text=text,
        content_hash=_hash(text),
    )


# -- Rubric model ----------------------------------------------------------


def test_rubric_constructs_with_name_and_description() -> None:
    r = Rubric(name="my_rubric", description="A description of the criterion.")
    assert r.name == "my_rubric"
    assert r.edge_case_handler is None


def test_rubric_is_frozen() -> None:
    r = Rubric(name="r1", description="x")
    with pytest.raises(ValidationError):
        r.name = "r2"  # type: ignore[misc]


def test_rubric_name_pattern_enforced() -> None:
    """Rubric names must be snake_case starting with a letter."""
    with pytest.raises(ValidationError):
        Rubric(name="My-Rubric", description="x")
    with pytest.raises(ValidationError):
        Rubric(name="1_rubric", description="x")


def test_rubric_rejects_empty_description() -> None:
    with pytest.raises(ValidationError):
        Rubric(name="r1", description="")


def test_rubric_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        Rubric(name="r1", description="x", invented_field=True)  # type: ignore[call-arg]


# -- pre-built rubrics ----------------------------------------------------


def test_pre_built_rubrics_have_distinct_names() -> None:
    names = {r.name for r in (RATIONALE_COHERENCE, CITATION_GROUNDING, MITIGATION_APPROPRIATENESS)}
    assert len(names) == 3


def test_rationale_coherence_has_no_edge_case_handler() -> None:
    """Rationale coherence always goes to the LLM; no short-circuit."""
    assert RATIONALE_COHERENCE.edge_case_handler is None


def test_citation_grounding_has_edge_case_handler() -> None:
    assert CITATION_GROUNDING.edge_case_handler is not None


def test_mitigation_appropriateness_has_edge_case_handler() -> None:
    assert MITIGATION_APPROPRIATENESS.edge_case_handler is not None


# -- LLMJudge core --------------------------------------------------------


def test_judge_returns_score_and_rationale_from_stub() -> None:
    judge = LLMJudge(model=_stub_judge_model(score=0.85, rationale="Specific rationale tied to PII fields."))
    result = judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    assert result.score == 0.85
    assert "PII" in result.rationale
    assert result.rubric_name == "rationale_coherence"
    assert result.was_edge_case is False


def test_judge_carries_decision_id_to_result() -> None:
    judge = LLMJudge(model=_stub_judge_model())
    rec = _record(decision_id="d-special-123")
    result = judge.judge(rec, _submission(), RATIONALE_COHERENCE)
    assert result.decision_id == "d-special-123"


def test_judge_records_model_version_on_result() -> None:
    judge = LLMJudge(model=_stub_judge_model())
    result = judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    # FunctionModel does not have model_name; falls back to lowercased class name
    assert result.judge_model_version != ""
    assert "function" in result.judge_model_version.lower()


def test_judge_run_timestamp_is_recent_utc() -> None:
    judge = LLMJudge(model=_stub_judge_model())
    before = datetime.now(timezone.utc)
    result = judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    after = datetime.now(timezone.utc)
    assert before <= result.run_timestamp <= after
    assert result.run_timestamp.tzinfo == timezone.utc


def test_judge_score_clamped_by_pydantic() -> None:
    """If the LLM somehow returns a score outside [0,1], pydantic-ai retries.

    Our stub returns 1.5 which fails _JudgeOutput validation. With retries
    exhausted the judge raises.
    """
    bad_stub = _stub_judge_model(score=1.5)  # invalid
    judge = LLMJudge(model=bad_stub, retries=0)
    with pytest.raises(Exception):  # pydantic-ai will surface this
        judge.judge(_record(), _submission(), RATIONALE_COHERENCE)


# -- citation grounding edge case ----------------------------------------


def test_citation_grounding_short_circuits_with_no_chunks() -> None:
    """No chunks supplied and no chunk_ids in reasoning -> short-circuit to 1.0."""
    judge = LLMJudge(model=_stub_judge_model(score=0.1))  # would return 0.1 if called
    result = judge.judge(_record(), _submission(), CITATION_GROUNDING)
    assert result.was_edge_case is True
    assert result.score == 1.0
    assert "vacuously" in result.rationale.lower()


def test_citation_grounding_calls_llm_when_chunks_supplied() -> None:
    """Supplying chunks bypasses the edge case; the LLM grades."""
    judge = LLMJudge(model=_stub_judge_model(score=0.3, rationale="Citation does not match the chunk."))
    chunk = _chunk()
    result = judge.judge(_record(), _submission(), CITATION_GROUNDING, regulation_chunks=[chunk])
    assert result.was_edge_case is False
    assert result.score == 0.3


def test_citation_grounding_calls_llm_when_chunk_id_in_reasoning() -> None:
    """If reasoning mentions a chunk_id but no chunks supplied, the LLM grades.

    This case represents the agent fabricating a citation; the rubric
    routes to the LLM to evaluate the fabrication.
    """
    judge = LLMJudge(model=_stub_judge_model(score=0.0, rationale="Agent invented a chunk_id."))
    record_with_fake_citation = _record(chunk_id_in_reasoning="osfi-e23:guideline-2099:page-99")
    result = judge.judge(record_with_fake_citation, _submission(), CITATION_GROUNDING)
    assert result.was_edge_case is False
    assert result.score == 0.0


# -- mitigation appropriateness edge case --------------------------------


def test_mitigation_short_circuits_for_reject() -> None:
    """Disposition=reject -> mitigations don't apply -> score 1.0 (vacuous)."""
    judge = LLMJudge(model=_stub_judge_model(score=0.1))
    record = _record(disposition="reject")
    result = judge.judge(record, _submission(), MITIGATION_APPROPRIATENESS)
    assert result.was_edge_case is True
    assert result.score == 1.0
    assert "reject" in result.rationale.lower()


def test_mitigation_short_circuits_for_approve() -> None:
    judge = LLMJudge(model=_stub_judge_model(score=0.1))
    record = _record(disposition="approve")
    result = judge.judge(record, _submission(), MITIGATION_APPROPRIATENESS)
    assert result.was_edge_case is True
    assert result.score == 1.0


def test_mitigation_short_circuits_for_escalate() -> None:
    judge = LLMJudge(model=_stub_judge_model(score=0.1))
    record = _record(disposition="escalate_senior_review")
    result = judge.judge(record, _submission(), MITIGATION_APPROPRIATENESS)
    assert result.was_edge_case is True


def test_mitigation_calls_llm_for_conditional_approve() -> None:
    """Conditional approve -> mitigations must be graded by the LLM."""
    judge = LLMJudge(model=_stub_judge_model(score=0.4, rationale="Mitigations too generic."))
    record = _record(disposition="conditional_approve")
    result = judge.judge(record, _submission(), MITIGATION_APPROPRIATENESS)
    assert result.was_edge_case is False
    assert result.score == 0.4


# -- documents + chunks reach the prompt ---------------------------------


def test_judge_includes_documents_in_prompt_when_supplied() -> None:
    """The judge prompt contains the document content when documents are passed."""
    captured: list[str] = []

    def capture(messages: Any, info: Any) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured.append(content)
        return ModelResponse(parts=[ToolCallPart(
            tool_name="final_result",
            args={"score": 0.5, "rationale": "ok"},
        )])

    from ingestion.document import Document
    doc = Document(
        source_reference="internal://doc1.pdf",
        artifact_type="soc2_report",
        page_count=1,
        extracted_text="SOC 2 distinctive marker phrase that the judge prompt should contain.",
        pages=["SOC 2 distinctive marker phrase that the judge prompt should contain."],
        content_hash=_hash("SOC 2 distinctive marker phrase that the judge prompt should contain."),
    )

    judge = LLMJudge(model=FunctionModel(capture))
    judge.judge(_record(), _submission(), RATIONALE_COHERENCE, documents=[doc])
    full = "\n".join(captured)
    assert "SOC 2 distinctive marker phrase" in full
    assert "internal://doc1.pdf" in full


def test_judge_includes_chunks_in_prompt_when_supplied() -> None:
    """The judge prompt contains the chunk content when chunks are passed."""
    captured: list[str] = []

    def capture(messages: Any, info: Any) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured.append(content)
        return ModelResponse(parts=[ToolCallPart(
            tool_name="final_result",
            args={"score": 0.5, "rationale": "ok"},
        )])

    judge = LLMJudge(model=FunctionModel(capture))
    chunk = _chunk()
    judge.judge(_record(), _submission(), CITATION_GROUNDING, regulation_chunks=[chunk])
    full = "\n".join(captured)
    assert "osfi-e23:guideline:page-7" in full
    assert "shall maintain inventory" in full


def test_judge_prompt_contains_criterion_description() -> None:
    """The Rubric description ends up in the user prompt verbatim."""
    captured: list[str] = []

    def capture(messages: Any, info: Any) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured.append(content)
        return ModelResponse(parts=[ToolCallPart(
            tool_name="final_result",
            args={"score": 0.5, "rationale": "ok"},
        )])

    judge = LLMJudge(model=FunctionModel(capture))
    judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    full = "\n".join(captured)
    # A specific phrase from RATIONALE_COHERENCE description
    assert "defensible chain" in full


def test_judge_prompt_excludes_record_metadata() -> None:
    """Internal metadata (decision_id, agent_version, timestamps) is NOT in the prompt.

    The judge grades content, not metadata. Metadata in the prompt is noise.
    """
    captured: list[str] = []

    def capture(messages: Any, info: Any) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured.append(content)
        return ModelResponse(parts=[ToolCallPart(
            tool_name="final_result",
            args={"score": 0.5, "rationale": "ok"},
        )])

    judge = LLMJudge(model=FunctionModel(capture))
    rec = _record(decision_id="d-metadata-test-marker")
    judge.judge(rec, _submission(), RATIONALE_COHERENCE)
    full = "\n".join(captured)
    # The record's decision_id, agent_version, and decision_timestamp should
    # be absent from the prompt (they're not in _serialize_record_for_judge).
    assert "d-metadata-test-marker" not in full
    assert "agent_version" not in full


# -- aggregate metrics ----------------------------------------------------


def test_compute_metrics_empty_list() -> None:
    m = compute_judge_metrics([])
    assert m.total_judge_results == 0
    assert m.unique_decisions == 0
    assert m.unique_models == []
    assert m.by_rubric == []


def test_compute_metrics_single_rubric() -> None:
    judge = LLMJudge(model=_stub_judge_model(score=0.8))
    r = judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    m = compute_judge_metrics([r])
    assert m.total_judge_results == 1
    assert m.unique_decisions == 1
    assert len(m.by_rubric) == 1
    rubric_metrics = m.by_rubric[0]
    assert rubric_metrics.rubric_name == "rationale_coherence"
    assert rubric_metrics.mean_score == 0.8
    assert rubric_metrics.min_score == 0.8
    assert rubric_metrics.max_score == 0.8


def test_compute_metrics_multiple_rubrics_grouped() -> None:
    judge = LLMJudge(model=_stub_judge_model(score=0.6))
    r1 = judge.judge(_record(decision_id="d-1"), _submission(), RATIONALE_COHERENCE)
    r2 = judge.judge(_record(decision_id="d-1"), _submission(), CITATION_GROUNDING)  # short-circuits
    r3 = judge.judge(_record(decision_id="d-2"), _submission(), RATIONALE_COHERENCE)
    m = compute_judge_metrics([r1, r2, r3])
    by_name = {rm.rubric_name: rm for rm in m.by_rubric}
    assert by_name["rationale_coherence"].total == 2
    assert by_name["citation_grounding"].total == 1
    assert by_name["citation_grounding"].edge_case_count == 1
    assert by_name["citation_grounding"].llm_judged_count == 0
    assert m.unique_decisions == 2


def test_compute_metrics_stdev_is_none_for_single_observation() -> None:
    judge = LLMJudge(model=_stub_judge_model(score=0.5))
    r = judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    m = compute_judge_metrics([r])
    assert m.by_rubric[0].score_stdev is None


def test_compute_metrics_stdev_computed_for_multiple_observations() -> None:
    """With 2+ scores in the rubric, stdev is computed."""
    j1 = LLMJudge(model=_stub_judge_model(score=0.2))
    j2 = LLMJudge(model=_stub_judge_model(score=0.8))
    r1 = j1.judge(_record(decision_id="d-1"), _submission(), RATIONALE_COHERENCE)
    r2 = j2.judge(_record(decision_id="d-2"), _submission(), RATIONALE_COHERENCE)
    m = compute_judge_metrics([r1, r2])
    assert m.by_rubric[0].mean_score == pytest.approx(0.5)
    assert m.by_rubric[0].score_stdev is not None
    assert m.by_rubric[0].score_stdev > 0


def test_compute_metrics_tracks_unique_models() -> None:
    """Multiple judge models in one batch are surfaced in unique_models."""
    j1 = LLMJudge(model=_stub_judge_model(score=0.5))
    j2 = LLMJudge(model=_stub_judge_model(score=0.7))
    r1 = j1.judge(_record(decision_id="d-1"), _submission(), RATIONALE_COHERENCE)
    r2 = j2.judge(_record(decision_id="d-2"), _submission(), RATIONALE_COHERENCE)
    m = compute_judge_metrics([r1, r2])
    # Both judges use FunctionModel; both report the same model_version
    assert len(m.unique_models) == 1


# -- result model immutability + extras --------------------------------


def test_judge_result_is_frozen() -> None:
    judge = LLMJudge(model=_stub_judge_model())
    r = judge.judge(_record(), _submission(), RATIONALE_COHERENCE)
    with pytest.raises(ValidationError):
        r.score = 0.0  # type: ignore[misc]


def test_judge_result_score_must_be_in_unit_interval() -> None:
    with pytest.raises(ValidationError):
        JudgeResult(
            rubric_name="r", decision_id="d", score=1.5,
            rationale="x", judge_model_version="m",
            run_timestamp=datetime.now(timezone.utc),
        )


def test_rubric_metrics_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        RubricMetrics(
            rubric_name="r", total=0, edge_case_count=0, llm_judged_count=0,
            mean_score=0.0, invented=True,  # type: ignore[call-arg]
        )


def test_judge_aggregate_metrics_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        JudgeAggregateMetrics(
            total_judge_results=0, unique_decisions=0,
            unique_models=[], by_rubric=[], invented=True,  # type: ignore[call-arg]
        )


# -- custom rubric -------------------------------------------------------


def test_custom_rubric_works_with_judge() -> None:
    """User-defined rubrics with no edge case handler work via the LLM path."""
    custom = Rubric(
        name="custom_test",
        description="Test criterion for a custom rubric implementation.",
    )
    judge = LLMJudge(model=_stub_judge_model(score=0.9))
    result = judge.judge(_record(), _submission(), custom)
    assert result.rubric_name == "custom_test"
    assert result.score == 0.9
    assert result.was_edge_case is False


def test_custom_rubric_with_edge_case_handler() -> None:
    """User-defined rubrics can supply their own edge_case_handler."""

    def always_short_circuit(record: Any, sub: Any, docs: Any, chunks: Any) -> Optional[tuple[float, str]]:
        return (0.5, "Custom short-circuit applied.")

    custom = Rubric(
        name="custom_short_circuit",
        description="Test custom edge case handler short circuits in advance.",
        edge_case_handler=always_short_circuit,
    )
    judge = LLMJudge(model=_stub_judge_model(score=0.0))
    result = judge.judge(_record(), _submission(), custom)
    assert result.was_edge_case is True
    assert result.score == 0.5
