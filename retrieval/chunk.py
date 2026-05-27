"""Pydantic model for retrievable units of regulation text.

A Chunk is the atom of retrieval. The BM25 index ranks Chunks by their
relevance to a query; the Retriever surfaces the top-k Chunks; the agent
includes them in the LLM prompt under a clearly delimited regulation
context block.

A Chunk is identity-bearing: ``chunk_id`` uniquely identifies a piece of
text within a corpus, and the LLM's evidence_cited.reasoning can reference
specific chunks ("per OSFI E-23 chunk osfi-e23:guideline-2023:page-7").
The reference is auditable: a reviewer can look up the chunk_id, find the
exact text the agent saw, and verify the agent's reasoning against it.

Chunking strategy:

Two strategies are supported. Page-based (the default) wraps each
extracted PDF page in a single Chunk; section-aware sub-divides pages
by detected section headings, producing one Chunk per section with
the heading recorded on the ``section_heading`` field.

Deferred:

- [deferred-subsystem-5-followup] Sliding-window chunking (overlap N
  tokens between adjacent chunks). Improves recall on queries whose
  matching phrase straddles a chunk boundary. Multiplies index size.
- [deferred-phase-4-followup] Multi-granularity chunking (small + large
  chunks indexed together; reranker picks the right granularity per
  query).
- [deferred-phase-5] Cross-page section concatenation (a section
  spanning pages 7-9 emerges as one chunk rather than three). Requires
  carrying section state across page boundaries.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "Chunk",
]


class Chunk(BaseModel):
    """A retrievable unit of regulation text.

    Attributes:
        chunk_id: Stable unique identifier within a corpus. Convention is
            ``{corpus_name}:{document_name}:page-{N}`` for the default
            page-based chunking. Section-aware chunking extends the suffix
            to ``{corpus_name}:{document_name}:page-{N}:section-{idx}``
            where idx is 1-indexed section order within the page (or 0
            for the pre-first-heading preamble). The id appears in the
            LLM prompt and in the agent's reasoning.
        corpus_name: Short identifier for the regulation corpus, e.g.,
            ``osfi-e23``, ``nist-ai-rmf``, ``iso-42001``, ``eu-ai-act``,
            ``sox-icfr``. Free-form by design: deploying organizations
            choose names that match their internal vocabulary.
        document_name: Short identifier for the specific document version
            within the corpus, e.g., ``guideline-2023-09-15`` or ``1.0``.
            Separated from corpus_name so the same corpus can carry
            multiple document versions over time without renaming.
        page_number: 1-indexed page number within the source document. For
            non-PDF sources or sub-page chunking, defaults to 1 and the
            chunk_id carries the finer-grained position.
        text: The chunk's text content. Indexed for retrieval; included
            verbatim in the LLM prompt's regulation context block.
        content_hash: SHA-256 of ``text``, formatted ``sha256:<hex>``.
            Lets a reviewer verify that the chunk an agent cited still
            holds the text the agent saw at decision time.
        section_heading: Optional heading text for this chunk's section.
            Populated when section-aware chunking detects a heading at
            the start of the chunk's text range. None for default
            page-based chunking, for sub-chunks that fall before the
            first detected heading on a page, or when no headings are
            detected. Audit-readable: "from Section 4.2: Independent
            Validation" reads better than "page 15" in a reviewer note.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=256)
    corpus_name: str = Field(min_length=1, max_length=64)
    document_name: str = Field(min_length=1, max_length=128)
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    section_heading: Optional[str] = Field(default=None, max_length=256)
