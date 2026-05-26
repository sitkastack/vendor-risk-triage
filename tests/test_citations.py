"""Tests for the Phase 4 sub-system 2 citation verification suite.

Covers the path resolver, chunk-id extraction, grounding score
computation, the public CitationVerifier API, and aggregate metrics.

The verifier is fully deterministic (no LLM calls, no I/O), so tests
construct synthetic records and inputs inline rather than running an
agent.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from agent.output_models import (
    ConfidenceSignal,
    EvidenceCitation,
    TriageRecord,
)
from eval.citations import (
    ChunkCitationResult,
    CitationAggregateMetrics,
    CitationVerifier,
    FieldCitationResult,
    RecordVerificationResult,
    compute_citation_metrics,
)
from eval.citations.citation_verifier import (
    _CHUNK_ID_PATTERN,
    _OutOfBoundsError,
    _UnresolvableError,
    _jaccard_overlap,
    _resolve_path,
)
from retrieval.chunk import Chunk


# -- helpers ---------------------------------------------------------------


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_chunk(
    chunk_id: str = "osfi-e23:guideline-2023:page-7",
    text: str = "Federally regulated institutions shall maintain a model inventory including vendor-supplied models.",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        corpus_name=chunk_id.split(":")[0],
        document_name=chunk_id.split(":")[1],
        page_number=int(chunk_id.split("page-")[1]),
        text=text,
        content_hash=_hash(text),
    )


def _make_record(
    citations: list[EvidenceCitation],
    decision_id: str = "d-test",
    rationale: str = (
        "Standard rationale describing the basis for this classification "
        "with sufficient detail to meet contract requirements."
    ),
) -> TriageRecord:
    return TriageRecord(
        decision_id=decision_id,
        decision_timestamp=datetime.now(timezone.utc),
        input_submission_id="v-test",
        input_schema_version="1.0.0",
        agent_version="test:0.0.0",
        risk_tier="tier_3_elevated",
        recommended_disposition="conditional_approve",
        classification_rationale=rationale,
        evidence_cited=citations,
        confidence_signal=ConfidenceSignal(score=0.5, interpretation="moderate"),
        output_schema_version="1.0.0",
        required_mitigations=["maintain monitoring with quarterly review"],
    )


def _submission() -> dict[str, Any]:
    return {
        "vendor_id": "v-test",
        "vendor_name": "Acme AI",
        "schema_version": "1.0.0",
        "documentation_artifacts": [
            {"artifact_type": "soc2_report", "reference": "internal://d1.pdf"},
            {"artifact_type": "privacy_policy", "reference": "internal://d2.pdf"},
        ],
        "pii_processing_claims": {
            "processes_pii": True,
            "categories": ["contact_information"],
            "handling_notes": "Standard handling.",
        },
        "ai_features_disclosed": [
            {"name": "feature one", "decision_role": "advisory"},
        ],
    }


# -- path resolution ------------------------------------------------------


def test_resolve_path_bare_field() -> None:
    """A bare field name resolves to the field's value."""
    assert _resolve_path(_submission(), "vendor_id", []) == "v-test"


def test_resolve_path_nested_field() -> None:
    """A dotted path navigates into nested objects."""
    val = _resolve_path(_submission(), "pii_processing_claims.processes_pii", [])
    assert val is True


def test_resolve_path_array_index() -> None:
    """An array index navigates into a list."""
    val = _resolve_path(_submission(), "documentation_artifacts[0]", [])
    assert val["artifact_type"] == "soc2_report"


def test_resolve_path_array_index_then_field() -> None:
    """Indexing into an array then navigating to a nested field works."""
    val = _resolve_path(
        _submission(),
        "documentation_artifacts[1].artifact_type",
        [],
    )
    assert val == "privacy_policy"


def test_resolve_path_missing_top_field() -> None:
    """A top-level missing field raises UnresolvableError."""
    with pytest.raises(_UnresolvableError, match="not present"):
        _resolve_path(_submission(), "nonexistent", [])


def test_resolve_path_missing_nested_field() -> None:
    """A nested missing field raises UnresolvableError naming the missing leg."""
    with pytest.raises(_UnresolvableError, match="invalid_leaf"):
        _resolve_path(
            _submission(),
            "pii_processing_claims.invalid_leaf",
            [],
        )


def test_resolve_path_out_of_bounds_array() -> None:
    """An index beyond the array raises OutOfBoundsError."""
    with pytest.raises(_OutOfBoundsError, match="index 5"):
        _resolve_path(_submission(), "documentation_artifacts[5]", [])


def test_resolve_path_field_on_non_object() -> None:
    """Navigating a field on a scalar value raises UnresolvableError."""
    with pytest.raises(_UnresolvableError, match="non-object"):
        _resolve_path(_submission(), "vendor_id.something", [])


def test_resolve_path_index_on_non_array() -> None:
    """Indexing into a non-list value raises UnresolvableError."""
    with pytest.raises(_UnresolvableError, match="non-array"):
        _resolve_path(_submission(), "vendor_id[0]", [])


def test_resolve_path_empty_path() -> None:
    """An empty path string is unresolvable."""
    with pytest.raises(_UnresolvableError, match="empty"):
        _resolve_path(_submission(), "", [])


def test_resolve_path_malformed_segment() -> None:
    """A malformed segment surfaces as unresolvable rather than crashing."""
    with pytest.raises(_UnresolvableError, match="malformed"):
        _resolve_path(_submission(), "foo-bar*baz", [])


# -- chunk-id pattern -----------------------------------------------------


def test_chunk_id_pattern_matches_canonical_form() -> None:
    """The canonical {corpus}:{document}:page-{N} pattern matches."""
    matches = _CHUNK_ID_PATTERN.findall("Per chunk osfi-e23:guideline-2023:page-7, ...")
    assert matches == ["osfi-e23:guideline-2023:page-7"]


def test_chunk_id_pattern_matches_multiple_in_text() -> None:
    """Multiple chunk_id mentions in one text are all captured."""
    text = (
        "First citation iso-42001:standard:page-1 then nist-ai-rmf:1.0:page-3 "
        "and finally eu-ai-act:reg-2024:page-12 closes the paragraph."
    )
    matches = _CHUNK_ID_PATTERN.findall(text)
    assert len(matches) == 3
    assert "iso-42001:standard:page-1" in matches


def test_chunk_id_pattern_skips_prose_with_colons() -> None:
    """Incidental colons in prose do not match the pattern."""
    text = "Note: the agent observed an inventory mismatch in 3:4 of cases."
    matches = _CHUNK_ID_PATTERN.findall(text)
    assert matches == []


def test_chunk_id_pattern_case_insensitive() -> None:
    """The pattern matches uppercase corpus names too (defensive)."""
    matches = _CHUNK_ID_PATTERN.findall("Per chunk OSFI-E23:GUIDELINE:page-7 above.")
    assert matches == ["OSFI-E23:GUIDELINE:page-7"]


# -- jaccard overlap ------------------------------------------------------


def test_jaccard_overlap_identical_text() -> None:
    """Identical text has overlap of 1.0."""
    s = "regulated institutions shall maintain inventory"
    assert _jaccard_overlap(s, s) == 1.0


def test_jaccard_overlap_disjoint_text() -> None:
    """Texts with no shared tokens have overlap 0.0."""
    assert _jaccard_overlap("foo bar baz", "alpha beta gamma") == 0.0


def test_jaccard_overlap_partial() -> None:
    """Partial overlap returns intersection/union ratio."""
    score = _jaccard_overlap("alpha beta gamma", "beta gamma delta")
    # Intersection: {beta, gamma}; Union: {alpha, beta, gamma, delta}
    assert score == pytest.approx(2 / 4)


def test_jaccard_overlap_empty_strings() -> None:
    """Empty inputs return 0.0 without crashing."""
    assert _jaccard_overlap("", "anything") == 0.0
    assert _jaccard_overlap("anything", "") == 0.0
    assert _jaccard_overlap("", "") == 0.0


def test_jaccard_overlap_punctuation_only() -> None:
    """Punctuation-only strings tokenize to nothing -> 0.0."""
    assert _jaccard_overlap("!!! ???", "regulated institutions") == 0.0


# -- CitationVerifier ----------------------------------------------------


def test_verifier_default_threshold_is_set() -> None:
    """Default grounding_threshold of 0.15 is applied."""
    v = CitationVerifier()
    assert v._threshold == 0.15


def test_verifier_rejects_invalid_threshold() -> None:
    """Threshold must be in [0, 1]."""
    with pytest.raises(ValueError):
        CitationVerifier(grounding_threshold=-0.1)
    with pytest.raises(ValueError):
        CitationVerifier(grounding_threshold=1.5)


def test_verify_record_resolved_field_citation() -> None:
    """A field citation that resolves is reported as resolved."""
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning="vendor identifier matches a known entry in our records.",
        ),
    ])
    result = CitationVerifier().verify_record(record, _submission())
    assert result.field_resolution_rate == 1.0
    assert result.field_citations[0].status == "resolved"
    assert result.field_citations[0].resolved_value_repr is not None


def test_verify_record_supports_bare_field_reference() -> None:
    """Bare field references (no $. prefix) resolve too."""
    record = _make_record([
        EvidenceCitation(
            input_field_reference="vendor_id",
            reasoning="The vendor identifier matches a known entry in our records.",
        ),
    ])
    result = CitationVerifier().verify_record(record, _submission())
    assert result.field_citations[0].status == "resolved"


def test_verify_record_unresolvable_field_citation() -> None:
    """An unresolvable field reference is reported with status."""
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.nonexistent_field",
            reasoning="Refers to a field that should not exist in the submission.",
        ),
    ])
    result = CitationVerifier().verify_record(record, _submission())
    assert result.field_citations[0].status == "unresolvable_path"
    assert "not present" in result.field_citations[0].detail


def test_verify_record_out_of_bounds_array() -> None:
    """An out-of-bounds array index produces the out_of_bounds status."""
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.documentation_artifacts[10]",
            reasoning="Refers to the tenth document which does not exist here.",
        ),
    ])
    result = CitationVerifier().verify_record(record, _submission())
    assert result.field_citations[0].status == "out_of_bounds"
    assert "index 10" in result.field_citations[0].detail


def test_verify_record_chunk_citation_resolved() -> None:
    """A chunk_id mention pointing at a supplied chunk resolves."""
    chunk = _make_chunk()
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2023:page-7, federally regulated "
                "institutions shall maintain a model inventory."
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk]
    )
    assert len(result.chunk_citations) == 1
    assert result.chunk_citations[0].status == "resolved"
    assert result.chunk_citations[0].grounding_score is not None


def test_verify_record_chunk_citation_unknown() -> None:
    """A chunk_id mention not in the supplied chunks is unknown_chunk."""
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2099:page-99, vendor "
                "must demonstrate operational evidence per guidance."
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[]
    )
    assert len(result.chunk_citations) == 1
    assert result.chunk_citations[0].status == "unknown_chunk"
    assert result.chunk_citations[0].grounding_score is None


def test_verify_record_chunk_citation_low_grounding_flagged() -> None:
    """A resolved chunk with low token overlap is flagged is_possibly_ungrounded."""
    chunk = _make_chunk(
        text="Federally regulated institutions shall maintain a model inventory."
    )
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2023:page-7, automobiles in California "
                "must register annually with the state DMV before highway use."
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk]
    )
    cc = result.chunk_citations[0]
    assert cc.status == "resolved"
    assert cc.is_possibly_ungrounded is True
    assert cc.grounding_score is not None
    assert cc.grounding_score < 0.15


def test_verify_record_chunk_citation_high_grounding_not_flagged() -> None:
    """A resolved chunk with high token overlap is not flagged."""
    chunk = _make_chunk(
        text="Federally regulated financial institutions shall maintain a model inventory including vendor-supplied AI systems."
    )
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2023:page-7, federally regulated financial "
                "institutions shall maintain a model inventory including vendor-supplied AI systems."
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk]
    )
    cc = result.chunk_citations[0]
    assert cc.status == "resolved"
    assert cc.is_possibly_ungrounded is False
    assert cc.grounding_score is not None and cc.grounding_score > 0.5


def test_verify_record_empty_citations() -> None:
    """A record with no citations has vacuous 1.0 resolution rates."""
    # Have to satisfy the contract minimum: at least one evidence_cited
    # entry. So we use a minimal but valid citation with a resolvable
    # field and no chunk mentions.
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning="No chunk citations here; just an anchor field reference.",
        ),
    ])
    result = CitationVerifier().verify_record(record, _submission())
    assert result.field_resolution_rate == 1.0
    assert result.chunk_resolution_rate == 1.0  # vacuous (no chunks)
    assert result.chunk_grounding_avg is None
    assert result.chunk_citations == []


def test_verify_record_multiple_chunks_in_one_reasoning() -> None:
    """Multiple chunk_id mentions in one reasoning text are all verified."""
    chunk1 = _make_chunk("osfi-e23:guideline-2023:page-7", "Model inventory required.")
    chunk2 = _make_chunk("iso-42001:standard:page-1", "AI management system standard.")
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2023:page-7 and chunk "
                "iso-42001:standard:page-1, vendor risk must be assessed."
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk1, chunk2]
    )
    assert len(result.chunk_citations) == 2
    chunk_ids = [c.chunk_id for c in result.chunk_citations]
    assert "osfi-e23:guideline-2023:page-7" in chunk_ids
    assert "iso-42001:standard:page-1" in chunk_ids


def test_verify_record_decision_id_carried_through() -> None:
    """The RecordVerificationResult carries the record's decision_id."""
    record = _make_record(
        decision_id="d-special-1",
        citations=[
            EvidenceCitation(
                input_field_reference="$.vendor_id",
                reasoning="Standard reference for testing decision_id passthrough.",
            ),
        ],
    )
    result = CitationVerifier().verify_record(record, _submission())
    assert result.decision_id == "d-special-1"


def test_verify_record_grounding_threshold_zero_disables_flag() -> None:
    """grounding_threshold=0.0 means nothing is flagged."""
    chunk = _make_chunk(text="A regulation chunk about institutions.")
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2023:page-7, "
                "completely unrelated text discussing alpha bravo charlie."
            ),
        ),
    ])
    verifier = CitationVerifier(grounding_threshold=0.0)
    result = verifier.verify_record(record, _submission(), regulation_chunks=[chunk])
    cc = result.chunk_citations[0]
    assert cc.status == "resolved"
    # grounding_score is low but threshold is 0.0; flagged is False
    assert cc.is_possibly_ungrounded is False


def test_verify_record_excerpt_truncated_to_window() -> None:
    """Reasoning excerpts around chunk_id mentions stay short for audit logs."""
    chunk = _make_chunk()
    long_prefix = "x " * 200  # 400 chars of filler before the chunk_id
    long_suffix = " y" * 200
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                long_prefix + "osfi-e23:guideline-2023:page-7" + long_suffix
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk]
    )
    cc = result.chunk_citations[0]
    # 60 chars on each side plus the chunk_id itself; well under any
    # huge dump
    assert len(cc.reasoning_excerpt) < 200


# -- CitationAggregateMetrics --------------------------------------------


def test_compute_metrics_empty_list() -> None:
    """An empty results list produces zero counts and vacuous rates."""
    m = compute_citation_metrics([])
    assert m.total_records == 0
    assert m.total_field_citations == 0
    assert m.overall_field_resolution_rate == 1.0
    assert m.overall_chunk_grounding_avg is None


def test_compute_metrics_single_record() -> None:
    """A single result aggregates to that record's numbers."""
    chunk = _make_chunk()
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning="Per chunk osfi-e23:guideline-2023:page-7, model inventory required.",
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk]
    )
    m = compute_citation_metrics([result])
    assert m.total_records == 1
    assert m.total_field_citations == 1
    assert m.total_chunk_citations == 1
    assert m.overall_field_resolution_rate == 1.0
    assert m.overall_chunk_resolution_rate == 1.0


def test_compute_metrics_counts_records_with_failures() -> None:
    """Per-record failure counts roll up correctly."""
    # Record 1: field failure
    r1 = CitationVerifier().verify_record(
        _make_record([
            EvidenceCitation(
                input_field_reference="$.nonexistent",
                reasoning="A reference that will not resolve to any field.",
            ),
        ]),
        _submission(),
    )
    # Record 2: clean
    r2 = CitationVerifier().verify_record(
        _make_record([
            EvidenceCitation(
                input_field_reference="$.vendor_id",
                reasoning="A reference that resolves cleanly without issue.",
            ),
        ]),
        _submission(),
    )
    m = compute_citation_metrics([r1, r2])
    assert m.records_with_any_field_failure == 1
    assert m.total_records == 2


def test_compute_metrics_counts_records_with_chunk_failure() -> None:
    """A record with at least one unknown_chunk increments records_with_any_chunk_failure."""
    # Reference a chunk that wasn't supplied
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning="Per chunk osfi-e23:guideline-2099:page-99, vendor must comply with regulation.",
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[]
    )
    m = compute_citation_metrics([result])
    assert m.records_with_any_chunk_failure == 1
    assert m.chunk_status_counts.get("unknown_chunk", 0) == 1


def test_verify_record_short_repr_truncates_long_values() -> None:
    """Long resolved values are truncated in resolved_value_repr."""
    huge_string = "x" * 500
    submission = _submission()
    submission["pii_processing_claims"]["handling_notes"] = huge_string
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.pii_processing_claims.handling_notes",
            reasoning="The handling notes field contains a long block of content.",
        ),
    ])
    result = CitationVerifier().verify_record(record, submission)
    fc = result.field_citations[0]
    assert fc.status == "resolved"
    assert fc.resolved_value_repr is not None
    # Truncated to 80 chars (default max_len), ending in "..."
    assert len(fc.resolved_value_repr) <= 80
    assert fc.resolved_value_repr.endswith("...")


def test_compute_metrics_double_counts_grounding_flag_per_record() -> None:
    """A record with multiple flagged chunks counts once in records_with_any_grounding_flag."""
    chunk = _make_chunk(text="Institutions shall maintain inventory.")
    # Two chunk citations in one record, both flagged
    record = _make_record([
        EvidenceCitation(
            input_field_reference="$.vendor_id",
            reasoning=(
                "Per chunk osfi-e23:guideline-2023:page-7, automobile registration "
                "in California requires the state DMV. Per chunk "
                "osfi-e23:guideline-2023:page-7, weather forecasts indicate snow tomorrow."
            ),
        ),
    ])
    result = CitationVerifier().verify_record(
        record, _submission(), regulation_chunks=[chunk]
    )
    m = compute_citation_metrics([result])
    # Two flagged chunks but only one record contributing to the count
    assert m.records_with_any_grounding_flag == 1


# -- result model immutability + extras ----------------------------------


def test_field_citation_result_is_frozen() -> None:
    """FieldCitationResult is immutable."""
    r = FieldCitationResult(input_field_reference="$.x", status="resolved")
    with pytest.raises(ValidationError):
        r.status = "out_of_bounds"  # type: ignore[misc]


def test_chunk_citation_result_score_must_be_in_unit_interval() -> None:
    """grounding_score is constrained to [0, 1]."""
    with pytest.raises(ValidationError):
        ChunkCitationResult(
            chunk_id="x:y:page-1",
            status="resolved",
            grounding_score=1.5,
        )


def test_record_verification_result_extras_rejected() -> None:
    """Extra fields on result models are rejected."""
    with pytest.raises(ValidationError):
        RecordVerificationResult(
            decision_id="d",
            field_citations=[],
            chunk_citations=[],
            field_resolution_rate=1.0,
            chunk_resolution_rate=1.0,
            invented=True,  # type: ignore[call-arg]
        )
