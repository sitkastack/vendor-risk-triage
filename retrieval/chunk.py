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

Chunking strategy (MVP):

One chunk per page. ``PDFReader`` (sub-system 4) already produces
per-page text; the CorpusLoader wraps each page in a Chunk. This is the
cheapest strategy and works because regulations are mostly text-dense
without massive single-paragraph pages.

Deferred:

- [deferred-subsystem-5-followup] Section-aware chunking (detect headings
  and group neighboring text into a chunk per section). Improves recall
  on queries that name a specific section. Requires PDF structure
  inference that pypdf does not provide out of the box.
- [deferred-subsystem-5-followup] Sliding-window chunking (overlap N
  tokens between adjacent chunks). Improves recall on queries whose
  matching phrase straddles a chunk boundary. Multiplies index size.
- [deferred-phase-4] Multi-granularity chunking (small + large chunks
  indexed together; reranker picks the right granularity per query).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "Chunk",
]


class Chunk(BaseModel):
    """A retrievable unit of regulation text.

    Attributes:
        chunk_id: Stable unique identifier within a corpus. Convention is
            ``{corpus_name}:{document_name}:page-{N}`` for the MVP page-
            based chunking. Future chunking strategies will use the same
            namespace prefix and extend the suffix (e.g.,
            ``osfi-e23:guideline-2023:section-3.2``). The id appears in
            the LLM prompt and in the agent's reasoning.
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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=256)
    corpus_name: str = Field(min_length=1, max_length=64)
    document_name: str = Field(min_length=1, max_length=128)
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
