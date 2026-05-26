"""LLM-as-judge harness for semantic evaluation of TriageRecords.

Where the graded eval (sub-system 3) measures whether the agent's
classification matches a known-correct label, and citation verification
(sub-system 2) measures whether references resolve and tokens overlap,
the LLM judge answers questions that require semantic reading:

- Does the classification_rationale provide a defensible chain from
  the submission's specific facts to the assigned tier?
- Do the cited regulation chunks actually support the claims the
  agent makes about them?
- Are the required_mitigations matched to the risks the rationale
  identifies?

These questions are out of reach for deterministic checks. They are
also non-deterministic when answered by an LLM: the same record judged
twice may receive different scores. The framework acknowledges this
rather than hides it. JudgeResult carries the judge's model_version
and run_timestamp so audit trails can reconstruct the call.

Caveats the README expands on:

- Self-judging (same model produces and grades) yields correlated
  errors. Cross-model judging is recommended.
- Each judge call is one LLM round-trip. Budget accordingly: 3 rubrics
  over 100 records = 300 calls.
- The judge can itself hallucinate. Treat judge scores as an additional
  signal, not as ground truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from agent.output_models import TriageRecord
from ingestion.document import Document
from retrieval.chunk import Chunk


__all__ = [
    "JudgeResult",
    "LLMJudge",
    "Rubric",
]


_DEFAULT_JUDGE_SYSTEM_PROMPT = """\
You are an audit reviewer evaluating an AI agent's vendor risk classification.

Your role is to evaluate the agent's output against the specific criterion in the user prompt. You are NOT re-classifying the vendor; you are grading the agent's reasoning quality on one specific dimension.

Be specific in your rationale: cite the agent's actual text or the specific input fields when explaining your score. Generic praise or generic criticism is not useful audit signal.

Do not be lenient. A defensible AI classification has specific reasoning tied to specific inputs, not generic claims. An auditor reviewing your scores needs accurate signal, not encouragement.

Return your evaluation as a JSON object with two fields: a numeric score in [0.0, 1.0] and a rationale string. Score 1.0 means the criterion is fully satisfied; 0.0 means completely not. Use the full range; do not cluster at 0.5 or 1.0.
"""


class _JudgeOutput(BaseModel):
    """Internal output type for the underlying PydanticAI agent.

    The judge's LLM must produce JSON conforming to this shape. The
    framework copies the fields into a JudgeResult before returning.
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=2000)


class Rubric(BaseModel):
    """A single evaluation criterion the LLM judge can grade against.

    Attributes:
        name: Short identifier, snake_case. Used in metrics aggregation
            and audit trails. Stable across versions; changing a rubric's
            name breaks downstream metric comparisons.
        description: One-paragraph human-readable description of what
            the criterion measures and what scores mean. Embedded in
            the judge's user prompt verbatim.
        edge_case_handler: Optional callable taking (record, submission,
            documents, regulation_chunks) and returning either None (no
            edge case detected, proceed to LLM call) or a JudgeResult
            (edge case detected, return this without calling the LLM).
            Used by pre-built rubrics to short-circuit cases like "no
            chunks cited" without an LLM call.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=4000)
    edge_case_handler: Optional[Any] = None  # callable; typed as Any for Pydantic compatibility


class JudgeResult(BaseModel):
    """The graded outcome of running one Rubric over one TriageRecord.

    Attributes:
        rubric_name: The name of the Rubric used.
        decision_id: The TriageRecord.decision_id; carried through for
            cross-referencing with the original triage record.
        score: The judge's numeric score in [0, 1]. Higher means the
            criterion is more satisfied.
        rationale: The judge's free-text explanation of the score.
        judge_model_version: Identifier of the LLM model used as judge.
            Critical for cross-run comparability. Formatted as
            "{provider}:{model_name}" when available, "function-model"
            or "test-model" for stub-based runs.
        run_timestamp: When the judge call completed (UTC).
        was_edge_case: True if the result was produced by the rubric's
            edge_case_handler without an LLM call. Distinguishes deterministic
            short-circuit results (e.g., "no chunks to evaluate") from
            actual LLM judgements.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rubric_name: str
    decision_id: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=2000)
    judge_model_version: str
    run_timestamp: datetime
    was_edge_case: bool = False


class LLMJudge:
    """Run rubrics against TriageRecords with an LLM as the grader.

    The judge wraps a PydanticAI Agent configured with _JudgeOutput as
    its output_type, so the underlying LLM is required to produce
    JSON conforming to {score, rationale}. PydanticAI handles retries
    on malformed output; if the LLM persistently fails to produce
    valid structured output, the underlying exception bubbles to the
    caller.

    Usage::

        from pydantic_ai.models.test import TestModel
        from eval.judge import LLMJudge
        from eval.judge.rubrics import RATIONALE_COHERENCE

        judge = LLMJudge(model=TestModel())
        result = judge.judge(
            record=triage_record,
            submission=submission_dict,
            documents=docs_list,
            regulation_chunks=chunks_list,
            rubric=RATIONALE_COHERENCE,
        )
        print(result.score, result.rationale)
    """

    def __init__(
        self,
        model: Model,
        retries: int = 2,
        system_prompt: str = _DEFAULT_JUDGE_SYSTEM_PROMPT,
    ) -> None:
        """Construct a judge.

        Args:
            model: A PydanticAI Model instance. Cross-model judging
                (judge model different from triage model) is
                recommended; the README documents why.
            retries: How many times to retry malformed LLM output before
                surfacing the failure. Default 2 matches the triage
                agent.
            system_prompt: Override the default audit-reviewer system
                prompt. The default suits the three pre-built rubrics.
        """
        self._model: Model = model
        self._system_prompt: str = system_prompt
        self._pydantic_agent: Agent[None, _JudgeOutput] = Agent(
            model=model,
            output_type=_JudgeOutput,
            system_prompt=system_prompt,
            retries=retries,
        )
        # Derive a model version string for the audit trail. TestModel
        # and FunctionModel do not have a canonical "name" attribute the
        # way provider-backed models do; fall back to the class name.
        self._model_version: str = _resolve_model_version(model)

    def judge(
        self,
        record: TriageRecord,
        submission: dict[str, Any],
        rubric: Rubric,
        documents: Optional[list[Document]] = None,
        regulation_chunks: Optional[list[Chunk]] = None,
    ) -> JudgeResult:
        """Grade one TriageRecord against one Rubric.

        Args:
            record: The triage record to evaluate.
            submission: The submission dict that produced the record.
            rubric: The Rubric to grade against.
            documents: The documents passed to the triage agent, if any.
                Included in the judge's prompt so the judge has full
                context.
            regulation_chunks: The regulation chunks passed to the
                triage agent, if any. Included in the judge's prompt.

        Returns:
            A JudgeResult with the score, rationale, and audit metadata.

        Raises:
            pydantic_ai.exceptions.UnexpectedModelBehavior: If the LLM
                cannot produce conforming output after retries. The
                caller decides whether to retry with a different model
                or surface the failure.
        """
        documents = documents or []
        regulation_chunks = regulation_chunks or []

        # Edge case short-circuit. The pre-built rubrics use this to
        # avoid LLM calls for vacuously-satisfied cases (e.g., citation
        # grounding when no chunks were cited).
        if rubric.edge_case_handler is not None:
            short_circuit = rubric.edge_case_handler(
                record, submission, documents, regulation_chunks
            )
            if short_circuit is not None:
                # The handler returns a (score, rationale) tuple, which
                # we wrap into a JudgeResult with the right metadata.
                score, rationale = short_circuit
                return JudgeResult(
                    rubric_name=rubric.name,
                    decision_id=record.decision_id,
                    score=score,
                    rationale=rationale,
                    judge_model_version=self._model_version,
                    run_timestamp=datetime.now(timezone.utc),
                    was_edge_case=True,
                )

        # Build the user prompt and call the LLM.
        user_prompt = _build_judge_prompt(
            rubric=rubric,
            record=record,
            submission=submission,
            documents=documents,
            regulation_chunks=regulation_chunks,
        )
        result = self._pydantic_agent.run_sync(user_prompt)
        output: _JudgeOutput = result.output

        return JudgeResult(
            rubric_name=rubric.name,
            decision_id=record.decision_id,
            score=output.score,
            rationale=output.rationale,
            judge_model_version=self._model_version,
            run_timestamp=datetime.now(timezone.utc),
            was_edge_case=False,
        )


# -- prompt building -----------------------------------------------------


def _build_judge_prompt(
    rubric: Rubric,
    record: TriageRecord,
    submission: dict[str, Any],
    documents: list[Document],
    regulation_chunks: list[Chunk],
) -> str:
    """Build the user prompt for one judging call.

    The prompt structure: criterion description first (the question
    the judge is answering), then the agent's record (the answer being
    graded), then the inputs the agent saw (so the judge has the same
    context).
    """
    body = (
        f"Evaluate the agent's classification record below against this criterion:\n"
        f"\n"
        f"{rubric.description}\n"
        f"\n"
        f"AGENT'S CLASSIFICATION RECORD:\n"
        f"{_serialize_record_for_judge(record)}\n"
        f"\n"
        f"ORIGINAL SUBMISSION:\n"
        f"{json.dumps(submission, indent=2, sort_keys=True, default=str)}\n"
    )
    if documents:
        body += "\nVENDOR DOCUMENTS AVAILABLE TO THE AGENT:\n"
        for doc in documents:
            body += (
                f"--- Document: {doc.source_reference} "
                f"({doc.artifact_type}, {doc.page_count} pages) ---\n"
                f"{doc.extracted_text}\n"
                f"--- End document ---\n"
            )
    if regulation_chunks:
        body += "\nREGULATION CONTEXT AVAILABLE TO THE AGENT:\n"
        for chunk in regulation_chunks:
            body += (
                f"--- Chunk {chunk.chunk_id} (corpus: {chunk.corpus_name}, "
                f"page: {chunk.page_number}) ---\n"
                f"{chunk.text}\n"
                f"--- End chunk ---\n"
            )

    body += (
        f"\nReturn your evaluation as JSON with fields 'score' (float in [0, 1]) "
        f"and 'rationale' (string explaining the score with specific reference "
        f"to the agent's text)."
    )
    return body


def _serialize_record_for_judge(record: TriageRecord) -> str:
    """Render the parts of a TriageRecord the judge needs.

    Excludes metadata fields (decision_id, timestamps, agent_version,
    schema versions) that are irrelevant to grading content quality.
    """
    relevant = {
        "risk_tier": record.risk_tier,
        "recommended_disposition": record.recommended_disposition,
        "classification_rationale": record.classification_rationale,
        "evidence_cited": [
            {
                "input_field_reference": ec.input_field_reference,
                "reasoning": ec.reasoning,
            }
            for ec in record.evidence_cited
        ],
        "confidence_signal": {
            "score": record.confidence_signal.score,
            "interpretation": record.confidence_signal.interpretation,
        },
        "required_mitigations": list(record.required_mitigations) if record.required_mitigations else [],
        "regulatory_framework_tags": list(record.regulatory_framework_tags) if record.regulatory_framework_tags else [],
    }
    return json.dumps(relevant, indent=2, sort_keys=True, default=str)


def _resolve_model_version(model: Model) -> str:
    """Best-effort identifier for the judge's model.

    Provider-backed models expose model_name; test stubs do not. The
    audit trail wants something that distinguishes them.
    """
    name = getattr(model, "model_name", None)
    if name:
        return str(name)
    # Defensive fallback for hypothetical Model implementations without
    # model_name. PydanticAI's FunctionModel and TestModel both expose
    # model_name, so this branch is unreachable with current pydantic-ai.
    return type(model).__name__.lower().replace("model", "-model")  # pragma: no cover
