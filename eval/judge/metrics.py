"""Aggregate JudgeResult metrics across many records.

Where one JudgeResult covers one (record, rubric) pair, aggregation
rolls many up into per-rubric summary statistics. Useful for
dataset-level questions like "how does this agent score on rationale
coherence on average?" or "what's the spread of citation grounding
scores?"

The aggregator is deliberately simple: counts, means, min/max, and
edge-case-skip rates. The LLMJudge produces the signal; this module
just sums it.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean, stdev
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from eval.judge.judge import JudgeResult


__all__ = [
    "JudgeAggregateMetrics",
    "RubricMetrics",
    "compute_judge_metrics",
]


class RubricMetrics(BaseModel):
    """Per-rubric summary across a collection of JudgeResults.

    Attributes:
        rubric_name: The rubric this row summarizes.
        total: Number of JudgeResults for this rubric.
        edge_case_count: How many of the total were short-circuited by
            the rubric's edge_case_handler (no LLM call).
        llm_judged_count: total - edge_case_count. The number of
            results that involved an actual LLM call.
        mean_score: Mean score across all results in this rubric
            (including edge cases). Vacuous 0.0 when total is 0.
        min_score: Minimum score across results. None when total is 0.
        max_score: Maximum score across results. None when total is 0.
        score_stdev: Standard deviation of scores across results.
            None when total < 2.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rubric_name: str
    total: int = Field(ge=0)
    edge_case_count: int = Field(ge=0)
    llm_judged_count: int = Field(ge=0)
    mean_score: float = Field(ge=0.0, le=1.0)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    score_stdev: Optional[float] = Field(default=None, ge=0.0)


class JudgeAggregateMetrics(BaseModel):
    """Roll-up across all JudgeResults supplied.

    Attributes:
        total_judge_results: Total JudgeResults aggregated.
        unique_decisions: Count of distinct decision_ids touched.
        unique_models: Sorted list of judge_model_versions seen. More
            than one indicates heterogeneous judging (cross-model setup
            or model upgrade mid-batch). The audit trail cares.
        by_rubric: One RubricMetrics per rubric_name encountered, sorted
            by rubric_name for stable output ordering.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_judge_results: int = Field(ge=0)
    unique_decisions: int = Field(ge=0)
    unique_models: list[str]
    by_rubric: list[RubricMetrics]


def compute_judge_metrics(results: list[JudgeResult]) -> JudgeAggregateMetrics:
    """Aggregate judge results into per-rubric metrics.

    Args:
        results: Any list of JudgeResults, possibly mixed across
            rubrics, decisions, and judge models. May be empty.

    Returns:
        A JudgeAggregateMetrics with per-rubric summary statistics.
    """
    by_rubric_results: dict[str, list[JudgeResult]] = defaultdict(list)
    unique_decisions: set[str] = set()
    unique_models: set[str] = set()
    for r in results:
        by_rubric_results[r.rubric_name].append(r)
        unique_decisions.add(r.decision_id)
        unique_models.add(r.judge_model_version)

    by_rubric: list[RubricMetrics] = []
    for rubric_name in sorted(by_rubric_results.keys()):
        rubric_results = by_rubric_results[rubric_name]
        total = len(rubric_results)
        edge_count = sum(1 for r in rubric_results if r.was_edge_case)
        scores = [r.score for r in rubric_results]
        by_rubric.append(RubricMetrics(
            rubric_name=rubric_name,
            total=total,
            edge_case_count=edge_count,
            llm_judged_count=total - edge_count,
            mean_score=mean(scores),
            min_score=min(scores),
            max_score=max(scores),
            score_stdev=stdev(scores) if total >= 2 else None,
        ))

    return JudgeAggregateMetrics(
        total_judge_results=len(results),
        unique_decisions=len(unique_decisions),
        unique_models=sorted(unique_models),
        by_rubric=by_rubric,
    )
