"""Aggregate citation-verification metrics across many records.

Single-record verification produces a RecordVerificationResult; this
module rolls many up into a dataset-level summary. The aggregator is
deliberately simple: counts, means, and per-status histograms. The
verifier itself is the place to put new signal types; this module just
sums them.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from eval.citations.citation_verifier import (
    RecordVerificationResult,
    ReferenceStatus,
)


__all__ = [
    "CitationAggregateMetrics",
    "compute_citation_metrics",
]


class CitationAggregateMetrics(BaseModel):
    """Aggregate citation-verification metrics across a record collection.

    Attributes:
        total_records: Number of RecordVerificationResults aggregated.
        total_field_citations: Total field citations across all records.
        total_chunk_citations: Total chunk citations across all records.
        field_status_counts: Map from ReferenceStatus to count, for
            field citations only.
        chunk_status_counts: Map from ReferenceStatus to count, for
            chunk citations only.
        overall_field_resolution_rate: Fraction of field citations
            resolved across all records. Vacuous 1.0 when no field
            citations exist.
        overall_chunk_resolution_rate: Fraction of chunk citations
            resolved across all records. Vacuous 1.0 when no chunk
            citations exist.
        overall_chunk_grounding_avg: Mean grounding_score across all
            resolved chunk citations in all records. None when no
            resolved chunk citations exist.
        records_with_any_field_failure: Count of records where at least
            one field citation did not resolve. A record-level signal
            distinct from the citation-level resolution rate.
        records_with_any_chunk_failure: Count of records where at least
            one chunk citation was unknown.
        records_with_any_grounding_flag: Count of records where at
            least one resolved chunk citation was flagged
            is_possibly_ungrounded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_records: int = Field(ge=0)
    total_field_citations: int = Field(ge=0)
    total_chunk_citations: int = Field(ge=0)
    field_status_counts: dict[str, int]
    chunk_status_counts: dict[str, int]
    overall_field_resolution_rate: float = Field(ge=0.0, le=1.0)
    overall_chunk_resolution_rate: float = Field(ge=0.0, le=1.0)
    overall_chunk_grounding_avg: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    records_with_any_field_failure: int = Field(ge=0)
    records_with_any_chunk_failure: int = Field(ge=0)
    records_with_any_grounding_flag: int = Field(ge=0)


def compute_citation_metrics(
    results: list[RecordVerificationResult],
) -> CitationAggregateMetrics:
    """Aggregate per-record verification results.

    Args:
        results: A list of RecordVerificationResults. May be empty;
            empty input produces a metrics object with zero counts and
            vacuous rates (documented per field).

    Returns:
        A CitationAggregateMetrics summarizing the inputs.
    """
    total_records = len(results)
    field_status_counter: Counter[str] = Counter()
    chunk_status_counter: Counter[str] = Counter()
    grounding_scores: list[float] = []
    rec_field_fail = 0
    rec_chunk_fail = 0
    rec_grounding_flag = 0

    for r in results:
        any_field_fail = False
        any_chunk_fail = False
        any_grounding = False
        for fc in r.field_citations:
            field_status_counter[fc.status] += 1
            if fc.status != "resolved":
                any_field_fail = True
        for cc in r.chunk_citations:
            chunk_status_counter[cc.status] += 1
            if cc.status != "resolved":
                any_chunk_fail = True
            if cc.is_possibly_ungrounded:
                any_grounding = True
            if cc.status == "resolved" and cc.grounding_score is not None:
                grounding_scores.append(cc.grounding_score)
        if any_field_fail:
            rec_field_fail += 1
        if any_chunk_fail:
            rec_chunk_fail += 1
        if any_grounding:
            rec_grounding_flag += 1

    total_field = sum(field_status_counter.values())
    total_chunk = sum(chunk_status_counter.values())
    field_resolved = field_status_counter.get("resolved", 0)
    chunk_resolved = chunk_status_counter.get("resolved", 0)

    field_rate = (
        field_resolved / total_field if total_field > 0 else 1.0
    )
    chunk_rate = (
        chunk_resolved / total_chunk if total_chunk > 0 else 1.0
    )
    grounding_avg = (
        sum(grounding_scores) / len(grounding_scores)
        if grounding_scores else None
    )

    return CitationAggregateMetrics(
        total_records=total_records,
        total_field_citations=total_field,
        total_chunk_citations=total_chunk,
        field_status_counts=dict(field_status_counter),
        chunk_status_counts=dict(chunk_status_counter),
        overall_field_resolution_rate=field_rate,
        overall_chunk_resolution_rate=chunk_rate,
        overall_chunk_grounding_avg=grounding_avg,
        records_with_any_field_failure=rec_field_fail,
        records_with_any_chunk_failure=rec_chunk_fail,
        records_with_any_grounding_flag=rec_grounding_flag,
    )
