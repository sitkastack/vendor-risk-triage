"""Hybrid lexical + dense retrieval via reciprocal rank fusion.

Combines BM25Index (lexical, sub-system 5) and VectorIndex (dense,
this sub-system) into a single retrieval surface. Lexical captures
exact-token matches and regulation-specific acronyms; dense captures
semantic similarity when vocabulary differs from the corpus. Hybrid
gets both signals.

Reciprocal Rank Fusion (RRF):

For each chunk, compute its rank in each index's top-N result list.
Score = sum over indexes of 1 / (k + rank), where k=60 is the standard
constant from the original Cormack paper. Items not appearing in a
given index's top-N contribute 0 from that index.

Why RRF rather than weighted score combination:
- Robust to scale differences (BM25 scores and cosine similarities
  live in incomparable ranges; normalization is fragile)
- No hyperparameter tuning beyond the RRF constant (k=60 is widely
  accepted as a reasonable default)
- Order-preserving: an item ranked first in both indexes scores
  highest; an item ranked first in one but absent from the other
  still scores meaningfully

The framework's pre-built HybridIndex always uses k=60. Future tuning
is exposed through the constructor.
"""
from __future__ import annotations

from retrieval.chunk import Chunk
from retrieval.embeddings import Embedder
from retrieval.index import BM25Index
from retrieval.vector_index import VectorIndex


__all__ = [
    "HybridIndex",
]


_RRF_DEFAULT_K: int = 60
"""Standard RRF constant from Cormack, Clarke, Buettcher (2009)."""


class HybridIndex:
    """Lexical + dense retrieval combined via reciprocal rank fusion.

    Constructs a BM25Index and a VectorIndex over the same chunks,
    then combines per-query top-N results from each via RRF. The
    chunks-must-match constraint is enforced by construction (both
    indexes built from the same list inside HybridIndex).

    Usage::

        from retrieval import HybridIndex
        from retrieval.embeddings import SentenceTransformerEmbedder

        index = HybridIndex(chunks, embedder=SentenceTransformerEmbedder())
        ranked = index.query("AI model governance", top_k=5)
        for chunk, score in ranked:
            print(chunk.chunk_id, score)
    """

    def __init__(
        self,
        chunks: list[Chunk],
        embedder: Embedder,
        rrf_k: int = _RRF_DEFAULT_K,
        fanout: int = 50,
    ) -> None:
        """Build the hybrid index.

        Args:
            chunks: Non-empty list of Chunks. Used to build both the
                BM25 and Vector indexes; chunks-match by construction.
            embedder: An Embedder for the underlying VectorIndex.
            rrf_k: The RRF constant. Default 60. Higher values
                de-emphasize the difference between near-top ranks;
                lower values emphasize the top positions more strongly.
            fanout: How many top results to pull from each underlying
                index before RRF combination. Default 50. Larger
                fanout improves recall at the cost of latency; smaller
                fanout may miss chunks that one index ranks low.

        Raises:
            ValueError: If chunks is empty, rrf_k < 1, or fanout < 1.
        """
        if not chunks:
            raise ValueError(
                "HybridIndex requires at least one chunk; cannot index an "
                "empty corpus."
            )
        if rrf_k < 1:
            raise ValueError(f"rrf_k must be >= 1, got {rrf_k}")
        if fanout < 1:
            raise ValueError(f"fanout must be >= 1, got {fanout}")
        self._chunks: list[Chunk] = list(chunks)
        self._bm25: BM25Index = BM25Index(chunks)
        self._vector: VectorIndex = VectorIndex(chunks, embedder)
        self._rrf_k: int = rrf_k
        self._fanout: int = fanout

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def query(
        self, query_text: str, top_k: int = 5
    ) -> list[tuple[Chunk, float]]:
        """Return the top-k Chunks by RRF score over BM25 + Vector ranks.

        Args:
            query_text: Free-text query.
            top_k: Maximum number of fused results to return.

        Returns:
            A list of (Chunk, rrf_score) tuples sorted by descending
            RRF score. Scores are NOT cosine similarities or BM25 scores
            directly; they are RRF values that combine the two rankings.
            Use them for ordering; do not interpret them as probabilities
            or similarities.
        """
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        # Pull top-fanout from each index.
        bm25_results = self._bm25.query(query_text, top_k=self._fanout)
        vec_results = self._vector.query(query_text, top_k=self._fanout)

        # Map chunk_id -> rank (1-indexed) in each list.
        bm25_rank: dict[str, int] = {
            c.chunk_id: rank + 1
            for rank, (c, _s) in enumerate(bm25_results)
        }
        vec_rank: dict[str, int] = {
            c.chunk_id: rank + 1
            for rank, (c, _s) in enumerate(vec_results)
        }

        # Union the chunk_ids; compute RRF score for each.
        union_ids: set[str] = set(bm25_rank.keys()) | set(vec_rank.keys())
        chunks_by_id: dict[str, Chunk] = {c.chunk_id: c for c in self._chunks}

        scored: list[tuple[Chunk, float]] = []
        for chunk_id in union_ids:
            score = 0.0
            if chunk_id in bm25_rank:
                score += 1.0 / (self._rrf_k + bm25_rank[chunk_id])
            if chunk_id in vec_rank:
                score += 1.0 / (self._rrf_k + vec_rank[chunk_id])
            scored.append((chunks_by_id[chunk_id], score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]
