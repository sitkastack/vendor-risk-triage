"""Retriever: the public API for retrieving regulation chunks.

A thin wrapper around BM25Index that adds:

- A simpler return signature: ``list[Chunk]`` instead of
  ``list[tuple[Chunk, float]]`` for consumers that only want the chunks,
  not the scores
- A natural place for future enrichment (reranking, query expansion,
  multi-index fanout) without changing the agent integration
- A single name for the abstraction the agent depends on

The Retriever is intentionally minimal. Future capabilities (vector
retrieval, hybrid, reranking) compose by accepting a different Index in
the constructor; the agent's signature does not change.
"""
from __future__ import annotations

from retrieval.chunk import Chunk
from retrieval.index import BM25Index


__all__ = [
    "Retriever",
]


class Retriever:
    """Query a corpus of regulation chunks for relevance to a query.

    Usage::

        from retrieval import BM25Index, CorpusLoader, Retriever

        loader = CorpusLoader()
        chunks = loader.load_pdf("osfi-e23", "guideline-2023", pdf_bytes)
        retriever = Retriever(BM25Index(chunks))
        relevant = retriever.query("regulated decisions for AI", top_k=5)
    """

    def __init__(self, index: BM25Index) -> None:
        """Construct a Retriever bound to a built index.

        Args:
            index: A constructed BM25Index. The Retriever does not own
                the index lifecycle; callers manage when to rebuild.
        """
        self._index: BM25Index = index

    @property
    def chunk_count(self) -> int:
        """Number of chunks in the underlying index."""
        return self._index.chunk_count

    def query(self, query_text: str, top_k: int = 5) -> list[Chunk]:
        """Return the top-k Chunks for the query.

        Args:
            query_text: Free-text query. Caller can include synonyms or
                regulation-specific terms ("model risk management",
                "regulated decision") since the underlying BM25 retrieval
                is lexical.
            top_k: Maximum chunks to return. The retriever may return
                fewer when the corpus is smaller than top_k or when fewer
                than top_k chunks score positively against the query.

        Returns:
            A list of Chunks ranked by relevance. Empty if no chunks
            scored above zero (the query did not match any chunk's
            tokens) or if the query has no tokens.
        """
        ranked = self._index.query(query_text, top_k=top_k)
        return [chunk for chunk, _score in ranked]
