"""Pydantic models for ingested vendor documentation artifacts.

A ``Document`` carries the extracted text from a single vendor-submitted
artifact (a SOC 2 report, a model card, a data processing agreement, etc.)
along with the metadata an auditor needs to verify what was ingested:
the source reference from the submission, the artifact type the submission
claimed, the SHA-256 of the bytes actually parsed, page-level text for
downstream chunking, and any warnings raised during extraction.

The ``Document`` is intentionally separate from the agent's ``TriageRecord``.
A record is the agent's decision artifact; a Document is an intermediate
input the agent may have consulted. Multiple Documents may flow into a
single triage call. The ``content_hash`` field is the audit link: a
Document's content_hash is verifiable against the
``documentation_artifacts[i].content_hash`` field on the original
submission, proving the agent saw the exact bytes the vendor referenced.

Audit posture (Phase 2 threat model):

- ``Document`` instances are frozen. Once extracted, the content is fixed.
- ``content_hash`` is required (not optional like on the input submission).
  Every parsed Document has a known hash; mismatch detection is a defense
  against bait-and-switch between the reference submitted and the bytes
  actually parsed.
- ``extraction_warnings`` is a list of strings rather than a free-form
  text field; structured warnings let downstream code branch on them.

Deferred to later phases (tagged for git-grep):

- [deferred-subsystem-4-followup] XLSX reader (security questionnaires)
- [deferred-phase-4] OCR for scanned PDFs (extracted_text would be empty
  on scanned PDFs today; a warning is emitted)
- [deferred-phase-4] Table extraction (CC tables in SOC 2 reports lose
  structure under plain-text extraction)
- [deferred-phase-4] Form-field extraction (security questionnaires
  often have form fields)
- [deferred-phase-4] HTML, plain-text readers
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "ArtifactType",
    "Document",
]


# Matches the enum on ``documentation_artifacts[i].artifact_type`` in
# schemas/input-contract-1.0.0.schema.json. Repeated here as a Literal so
# Document validation rejects unknown artifact types at construction.
ArtifactType = Literal[
    "soc2_report",
    "security_questionnaire",
    "model_card",
    "data_processing_agreement",
    "privacy_policy",
    "architecture_document",
    "other",
]


class Document(BaseModel):
    """Extracted content from one vendor documentation artifact.

    Constructed by a ``DocumentReader`` implementation. Consumed by the
    agent (or other downstream code) as input alongside the submission.

    Attributes:
        source_reference: The reference string from the original
            submission's ``documentation_artifacts[i].reference``. Carried
            through so a record can name which artifact it consulted.
        artifact_type: The kind of artifact, matching the input contract's
            enum. The reader does not infer this; the caller declares it
            from the submission.
        page_count: Number of pages in the source. 1 for non-paginated
            formats. Used by sub-system 5 RAG chunking and by readers
            that want to surface document size to the agent.
        extracted_text: Full extracted text with page boundaries marked
            using the ``page_separator``. Suitable for inclusion in an
            LLM prompt as a single string.
        pages: Per-page extracted text. ``pages[i]`` is the text of page
            i+1. Length equals ``page_count``. Empty strings are allowed
            for pages where extraction returned nothing (scanned pages,
            image-only pages); such pages produce a warning.
        content_hash: SHA-256 hex digest of the bytes that produced this
            Document, formatted as ``sha256:<hex>``. Matches the format
            used in the input contract's ``content_hash`` field.
        extraction_warnings: Non-fatal issues encountered during
            extraction. Examples: "page 3 produced no extractable text
            (likely scanned)". An empty list means clean extraction.
        page_separator: The string used to join ``pages`` into
            ``extracted_text``. Defaults to a page-break marker that is
            both human-readable and easy for the LLM to recognize.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_reference: str = Field(min_length=1, max_length=1024)
    artifact_type: ArtifactType
    page_count: int = Field(ge=0)
    extracted_text: str
    pages: list[str]
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    extraction_warnings: list[str] = Field(default_factory=list)
    page_separator: str = Field(default="\n\n[---- PAGE BREAK ----]\n\n")
