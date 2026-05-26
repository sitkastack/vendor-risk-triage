"""Deterministic citation verification for TriageRecord evidence_cited entries.

The agent's output contract requires every classification decision to
carry evidence_cited entries pointing at the input fields, documents,
or regulation context that motivated the decision. Whether those
references actually resolve, and whether the agent's claims about
cited regulation chunks actually appear in those chunks, is the first
concrete hallucination signal the framework can surface.

What this module measures:

Reference verifiability (deterministic):
  Each EvidenceCitation has an input_field_reference. We parse it as
  either a bare field name or a JSONPath-lite expression and try to
  resolve it against the submission (or against the supplied
  documents list when the reference is documentation_artifacts[N]).
  Outcomes: resolved, unresolvable_path, out_of_bounds.

Chunk citation verifiability (deterministic):
  The agent is instructed to mention regulation chunk_ids in the
  reasoning text when it relies on retrieved context. We regex-extract
  chunk_id patterns from the reasoning and verify each one is in the
  supplied regulation_chunks list. Outcomes: resolved, unknown_chunk.

Chunk grounding (heuristic, token overlap):
  For each chunk citation that resolves, we compute Jaccard overlap
  between the tokenized reasoning text and the tokenized chunk text.
  A low overlap score does NOT prove the LLM hallucinated; it indicates
  the citation is a candidate for closer review. The threshold is
  configurable and disclosed clearly in the README and below.

What this module does NOT measure:

  Semantic grounding: does the cited chunk actually entail the LLM's
  specific claim about it? Token overlap correlates with grounding
  weakly. A claim with vocabulary completely disjoint from its source
  chunk is almost certainly ungrounded, but high overlap does not
  prove grounding (the LLM could be copying surface tokens while
  asserting their opposite). The LLM-as-judge sub-system (Phase 4
  sub-system 4) addresses semantic grounding.

  Citation completeness: did the LLM cite every source it actually
  used? This verifier checks declared citations; undeclared sourcing
  is invisible to it.

The verifier does no I/O and makes no model calls. Test runs do not
require credentials.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agent.output_models import EvidenceCitation, TriageRecord
from retrieval.chunk import Chunk
from retrieval.index import tokenize


__all__ = [
    "CitationVerifier",
    "ChunkCitationResult",
    "FieldCitationResult",
    "RecordVerificationResult",
    "ReferenceStatus",
]


ReferenceStatus = Literal[
    "resolved",
    "unresolvable_path",
    "out_of_bounds",
    "unknown_chunk",
]
"""Outcome of attempting to resolve one citation reference.

- resolved: the reference points at an existing field, document, or
  chunk that was supplied to the agent
- unresolvable_path: the JSONPath-style reference does not navigate to
  any value in the submission (e.g., $.nonexistent_field, or a nested
  path through a missing parent)
- out_of_bounds: an array index in the reference exceeds the array
  length (e.g., $.documentation_artifacts[5] when only 2 exist)
- unknown_chunk: a chunk_id mentioned in reasoning text is not in the
  supplied regulation_chunks list (the agent referenced a chunk that
  was not retrieved for it)
"""


# Chunk-id regex.
#
# The framework's chunk_id convention is {corpus_name}:{document_name}:page-{N}
# (Phase 3 sub-system 5). Each component starts with an alphanumeric and
# allows hyphens, dots, and underscores internally. The regex below matches
# this pattern as a token: word boundaries on either side, no internal
# whitespace, page suffix required.
#
# Precision/recall tradeoff disclosed in README: this regex may miss creative
# phrasings ("see page 7 of OSFI E-23") and may false-positive on incidental
# colons (rare in regulation prose). A future contract bump adding
# structured cited_chunk_ids would replace this heuristic entirely.
_CHUNK_ID_PATTERN = re.compile(
    r"\b([a-z0-9][a-z0-9.\-_]*:[a-z0-9][a-z0-9.\-_]*:page-\d+)\b",
    re.IGNORECASE,
)


class FieldCitationResult(BaseModel):
    """Verification outcome for one EvidenceCitation's input_field_reference.

    Attributes:
        input_field_reference: The raw reference string as it appeared
            in the EvidenceCitation.
        status: The resolution outcome.
        resolved_value_repr: A short repr of the value the reference
            resolved to, when status=resolved. None for other statuses.
            Used for audit trails; not for semantic verification.
        detail: Human-readable explanation, especially for non-resolved
            outcomes. E.g., "$.documentation_artifacts[5]: array has
            length 2".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_field_reference: str
    status: ReferenceStatus
    resolved_value_repr: Optional[str] = None
    detail: str = ""


class ChunkCitationResult(BaseModel):
    """Verification outcome for one chunk_id mentioned in reasoning text.

    Attributes:
        chunk_id: The chunk_id as mentioned in the reasoning text.
        status: resolved or unknown_chunk.
        reasoning_excerpt: A short slice of reasoning text around the
            chunk_id mention (up to 200 chars), for audit context.
        grounding_score: Jaccard overlap between the tokenized
            reasoning text and the tokenized chunk text, in [0, 1].
            Only computed when status=resolved; None otherwise.
        is_possibly_ungrounded: True when status=resolved and
            grounding_score is below the configured threshold. A
            heuristic flag, not a hallucination verdict.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    status: ReferenceStatus
    reasoning_excerpt: str = ""
    grounding_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_possibly_ungrounded: bool = False


class RecordVerificationResult(BaseModel):
    """Aggregate of all citation verifications for one TriageRecord.

    Attributes:
        decision_id: The TriageRecord.decision_id; carried through for
            cross-referencing.
        field_citations: One FieldCitationResult per EvidenceCitation
            in the record, in order.
        chunk_citations: One ChunkCitationResult per chunk_id mention
            extracted from reasoning text, across all EvidenceCitations.
            May be empty for records with no chunk citations.
        field_resolution_rate: Fraction of field_citations that
            resolved successfully. 1.0 when there are no field
            citations (vacuous; documented).
        chunk_resolution_rate: Fraction of chunk_citations that
            resolved successfully. 1.0 when there are no chunk
            citations (vacuous).
        chunk_grounding_avg: Mean grounding_score across resolved chunk
            citations. None when no resolved chunk citations exist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    field_citations: list[FieldCitationResult]
    chunk_citations: list[ChunkCitationResult]
    field_resolution_rate: float = Field(ge=0.0, le=1.0)
    chunk_resolution_rate: float = Field(ge=0.0, le=1.0)
    chunk_grounding_avg: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class CitationVerifier:
    """Verify citations on a TriageRecord against the inputs that produced it.

    The verifier is stateless beyond its grounding threshold; one
    instance can verify any number of records.

    Usage::

        from eval.citations import CitationVerifier

        verifier = CitationVerifier()
        result = verifier.verify_record(
            record=triage_record,
            submission=submission_dict,
            documents=docs_list,
            regulation_chunks=chunks_list,
        )
        for fc in result.field_citations:
            if fc.status != "resolved":
                print(fc.input_field_reference, fc.detail)
        for cc in result.chunk_citations:
            if cc.is_possibly_ungrounded:
                print(cc.chunk_id, cc.grounding_score)
    """

    def __init__(self, grounding_threshold: float = 0.15) -> None:
        """Construct a verifier.

        Args:
            grounding_threshold: Jaccard overlap below which a resolved
                chunk citation is flagged is_possibly_ungrounded. Default
                0.15 picked from informal calibration against the
                synthetic test corpus; deploying organizations should
                tune against their own ground truth. Setting this to
                0.0 disables the heuristic flag (everything resolved
                counts as grounded).
        """
        if not 0.0 <= grounding_threshold <= 1.0:
            raise ValueError(
                f"grounding_threshold must be in [0, 1], got {grounding_threshold}"
            )
        self._threshold: float = grounding_threshold

    def verify_record(
        self,
        record: TriageRecord,
        submission: dict[str, Any],
        documents: Optional[list[Any]] = None,
        regulation_chunks: Optional[list[Chunk]] = None,
    ) -> RecordVerificationResult:
        """Verify all citations on one TriageRecord.

        Args:
            record: The triage record whose citations to verify.
            submission: The submission dict that produced the record.
                Must be the actual submission, not a fresh copy with
                different values, or field resolution will fail.
            documents: The documents list passed to the agent, if any.
                Used to validate $.documentation_artifacts[N] references
                against actual document positions.
            regulation_chunks: The chunk list passed to the agent, if
                any. Used to validate chunk_id mentions in reasoning.

        Returns:
            A RecordVerificationResult summarizing every field and chunk
            citation outcome.
        """
        documents = documents or []
        regulation_chunks = regulation_chunks or []
        chunks_by_id: dict[str, Chunk] = {c.chunk_id: c for c in regulation_chunks}

        # Verify each EvidenceCitation's input_field_reference.
        field_results: list[FieldCitationResult] = [
            self._verify_field_citation(citation, submission, documents)
            for citation in record.evidence_cited
        ]

        # Extract and verify every chunk_id mention across all reasoning texts.
        chunk_results: list[ChunkCitationResult] = []
        for citation in record.evidence_cited:
            chunk_results.extend(
                self._verify_chunks_in_reasoning(citation.reasoning, chunks_by_id)
            )

        # Aggregate.
        if field_results:
            field_resolution_rate = sum(
                1 for r in field_results if r.status == "resolved"
            ) / len(field_results)
        else:  # pragma: no cover  -- contract enforces evidence_cited minItems=1
            field_resolution_rate = 1.0

        resolved_chunks = [r for r in chunk_results if r.status == "resolved"]
        if chunk_results:
            chunk_resolution_rate = len(resolved_chunks) / len(chunk_results)
        else:
            chunk_resolution_rate = 1.0  # Vacuous.

        if resolved_chunks:
            chunk_grounding_avg: Optional[float] = sum(
                r.grounding_score or 0.0 for r in resolved_chunks
            ) / len(resolved_chunks)
        else:
            chunk_grounding_avg = None

        return RecordVerificationResult(
            decision_id=record.decision_id,
            field_citations=field_results,
            chunk_citations=chunk_results,
            field_resolution_rate=field_resolution_rate,
            chunk_resolution_rate=chunk_resolution_rate,
            chunk_grounding_avg=chunk_grounding_avg,
        )

    # -- private --------------------------------------------------------

    def _verify_field_citation(
        self,
        citation: EvidenceCitation,
        submission: dict[str, Any],
        documents: list[Any],
    ) -> FieldCitationResult:
        """Resolve one EvidenceCitation's input_field_reference."""
        ref = citation.input_field_reference

        # Strip the optional "$." prefix to support both bare field names
        # ("vendor_id") and JSONPath-lite ("$.vendor_id") references.
        path = ref[2:] if ref.startswith("$.") else ref

        try:
            value = _resolve_path(submission, path, documents=documents)
        except _OutOfBoundsError as exc:
            return FieldCitationResult(
                input_field_reference=ref,
                status="out_of_bounds",
                detail=str(exc),
            )
        except _UnresolvableError as exc:
            return FieldCitationResult(
                input_field_reference=ref,
                status="unresolvable_path",
                detail=str(exc),
            )

        return FieldCitationResult(
            input_field_reference=ref,
            status="resolved",
            resolved_value_repr=_short_repr(value),
        )

    def _verify_chunks_in_reasoning(
        self,
        reasoning: str,
        chunks_by_id: dict[str, Chunk],
    ) -> list[ChunkCitationResult]:
        """Extract chunk_id mentions from reasoning and verify each."""
        results: list[ChunkCitationResult] = []
        for match in _CHUNK_ID_PATTERN.finditer(reasoning):
            chunk_id = match.group(1)
            # Excerpt of reasoning around the mention for audit context.
            start = max(0, match.start() - 60)
            end = min(len(reasoning), match.end() + 60)
            excerpt = reasoning[start:end]

            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                results.append(ChunkCitationResult(
                    chunk_id=chunk_id,
                    status="unknown_chunk",
                    reasoning_excerpt=excerpt,
                ))
                continue

            grounding = _jaccard_overlap(reasoning, chunk.text)
            results.append(ChunkCitationResult(
                chunk_id=chunk_id,
                status="resolved",
                reasoning_excerpt=excerpt,
                grounding_score=grounding,
                is_possibly_ungrounded=(grounding < self._threshold),
            ))
        return results


# -- path resolution helpers ----------------------------------------------


class _UnresolvableError(Exception):
    """Internal: the reference path does not navigate to anything."""


class _OutOfBoundsError(Exception):
    """Internal: an array index exceeds the available array length."""


# Pattern for parsing one path segment. Supports:
#   field
#   field[N]
#   [N]    (when at start, against documents array)
_SEGMENT_PATTERN = re.compile(r"^(?:([A-Za-z_][A-Za-z0-9_]*))?(\[\d+\])?$")


def _resolve_path(
    submission: dict[str, Any],
    path: str,
    documents: list[Any],
) -> Any:
    """Navigate ``path`` (dotted, possibly with indices) into ``submission``.

    Supports the patterns the output contract uses for input_field_reference:

      - ``vendor_id``
      - ``pii_processing_claims.handling_notes``
      - ``documentation_artifacts[0]``
      - ``documentation_artifacts[0].content_hash``
      - ``ai_features_disclosed[2].decision_role``

    Path length is bounded upstream by the EvidenceCitation
    input_field_reference maxLength=512 contract; the resolver does not
    enforce its own depth limit because the contract is the source of
    truth.

    Special case: ``documentation_artifacts[N]`` resolves first against
    the submission (which may carry an array of declared documents).
    A reference to a document index not present in the submission is
    treated as out_of_bounds, even if the agent received a documents
    list of different length. This matches the contract's intent: the
    reference is a pointer into the submitted submission, not into the
    agent's internal extracted-documents state.

    Args:
        submission: The submission dict to navigate.
        path: Dotted path like "field.subfield[0].leaf". No leading dot.
        documents: The documents list (unused for resolution; kept in
            signature for symmetry and possible future expansion).

    Returns:
        The value at the path.

    Raises:
        _UnresolvableError: If any segment does not exist in the parent.
        _OutOfBoundsError: If an array index exceeds the parent's length.
    """
    if not path:
        raise _UnresolvableError("empty reference path")

    current: Any = submission
    segments = path.split(".")
    walked: list[str] = []

    for raw_seg in segments:
        walked.append(raw_seg)
        match = _SEGMENT_PATTERN.match(raw_seg)
        if not match:
            raise _UnresolvableError(
                f"malformed path segment {raw_seg!r} in {path!r}"
            )
        field, index_part = match.group(1), match.group(2)

        # Field part (e.g., "documentation_artifacts").
        if field is not None:
            if not isinstance(current, dict):
                raise _UnresolvableError(
                    f"path {'.'.join(walked)!r}: cannot navigate field "
                    f"{field!r} on non-object value"
                )
            if field not in current:
                raise _UnresolvableError(
                    f"path {'.'.join(walked)!r}: field {field!r} not present"
                )
            current = current[field]

        # Index part (e.g., "[0]").
        if index_part is not None:
            idx = int(index_part[1:-1])
            if not isinstance(current, list):
                raise _UnresolvableError(
                    f"path {'.'.join(walked)!r}: cannot index "
                    f"non-array value"
                )
            if idx >= len(current):
                raise _OutOfBoundsError(
                    f"path {'.'.join(walked)!r}: index {idx} exceeds "
                    f"array length {len(current)}"
                )
            current = current[idx]

    return current


def _short_repr(value: Any, max_len: int = 80) -> str:
    """Render a value for the audit trail without dumping huge content."""
    rendered = repr(value)
    if len(rendered) <= max_len:
        return rendered
    return rendered[: max_len - 3] + "..."


# -- grounding heuristic --------------------------------------------------


def _jaccard_overlap(claim_text: str, source_text: str) -> float:
    """Jaccard similarity between the tokenized claim and source.

    Uses retrieval.tokenize so token rules match the indexing pipeline:
    lowercase, preserve regulation-acronym punctuation. Empty texts
    return 0.0 (no overlap possible).
    """
    claim_tokens = set(tokenize(claim_text))
    source_tokens = set(tokenize(source_text))
    if not claim_tokens or not source_tokens:
        return 0.0
    intersection = claim_tokens & source_tokens
    union = claim_tokens | source_tokens
    return len(intersection) / len(union)
