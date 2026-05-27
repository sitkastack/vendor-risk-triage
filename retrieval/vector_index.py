"""Dense (vector) retrieval over a list of Chunks.

Pairs with BM25Index. Where BM25 captures lexical overlap (chunks
sharing tokens with the query rank high), VectorIndex captures
semantic similarity (chunks with similar meaning rank high even if
the vocabulary differs).

Implementation: pre-compute L2-normalized embeddings for all chunks at
construction; at query time, embed the query text and compute the dot
product against the chunk matrix (equivalent to cosine similarity).

Returns the same shape as BM25Index: ``list[tuple[Chunk, float]]``
sorted by descending score. The Retriever wraps either index
identically; HybridIndex composes both.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from retrieval.chunk import Chunk
from retrieval.embeddings import Embedder


__all__ = [
    "VectorIndex",
]


class VectorIndex:
    """In-memory dense index over a fixed list of Chunks.

    Construct once with a chunk list and an Embedder; query as many
    times as needed. Immutable after construction - rebuild on corpus
    change.

    Usage::

        from retrieval import VectorIndex
        from retrieval.embeddings import SentenceTransformerEmbedder

        index = VectorIndex(chunks, embedder=SentenceTransformerEmbedder())
        ranked = index.query("AI model governance", top_k=5)
        for chunk, score in ranked:
            print(chunk.chunk_id, score)
    """

    def __init__(
        self,
        chunks: list[Chunk],
        embedder: Embedder,
        precomputed_embeddings: Optional[np.ndarray] = None,
    ) -> None:
        """Build the dense index.

        Args:
            chunks: Non-empty list of Chunks to index.
            embedder: Any Embedder. The embedder's dimension is fixed
                at construction; the same embedder must be used for
                all subsequent queries (the index does not store the
                embedder reference; the user retains it).
            precomputed_embeddings: Optional pre-computed (N, D) array
                matching ``len(chunks)`` rows in chunk order. When
                supplied, the constructor skips the embed() call. Use
                this with ``IndexBundle.load`` to avoid re-embedding on
                cold start. The dtype is coerced to float32 to match
                the framework convention.

                Caller responsibility: the embeddings must have been
                produced by an embedder compatible with the load-time
                embedder. ``IndexBundle.load`` enforces identity by
                default; callers using this kwarg outside the bundle
                path should verify compatibility themselves.

        Raises:
            ValueError: If chunks is empty, or precomputed_embeddings
                shape disagrees with ``(len(chunks), embedder.dimension)``.
        """
        if not chunks:
            raise ValueError(
                "VectorIndex requires at least one chunk; cannot index an "
                "empty corpus."
            )
        self._chunks: list[Chunk] = list(chunks)
        self._embedder: Embedder = embedder
        self._dimension: int = embedder.dimension
        if precomputed_embeddings is not None:
            if precomputed_embeddings.shape != (len(chunks), self._dimension):
                raise ValueError(
                    f"precomputed_embeddings shape "
                    f"{precomputed_embeddings.shape} does not match "
                    f"({len(chunks)}, {self._dimension})"
                )
            self._embeddings: np.ndarray = precomputed_embeddings.astype(
                np.float32, copy=False
            )
        else:
            # Embed all chunks at construction. For very large corpora this
            # is the slow step; the framework does not stream because the
            # index is in-memory anyway (size = N * D * 4 bytes).
            chunk_texts = [c.text for c in self._chunks]
            self._embeddings = embedder.embed(chunk_texts)
            if self._embeddings.shape != (len(chunks), self._dimension):
                raise ValueError(
                    f"embedder returned shape {self._embeddings.shape}, "
                    f"expected ({len(chunks)}, {self._dimension})"
                )

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def dimension(self) -> int:
        return self._dimension

    def query(
        self, query_text: str, top_k: int = 5
    ) -> list[tuple[Chunk, float]]:
        """Return top-k Chunks ranked by cosine similarity to the query.

        Args:
            query_text: Free-text query. Embedded with the same Embedder
                that was used at construction.
            top_k: Maximum number of results. May return fewer if the
                corpus is smaller than top_k. Zero-score chunks (no
                vector overlap) are excluded.

        Returns:
            A list of (Chunk, score) tuples sorted by descending score.
            Scores are dot products of L2-normalized vectors, so they
            are cosine similarities in [-1, 1]. In practice for text
            embeddings, similarities are in [0, 1].
        """
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        query_emb = self._embedder.embed([query_text])
        if query_emb.shape != (1, self._dimension):
            raise ValueError(
                f"embedder returned query shape {query_emb.shape}, "
                f"expected (1, {self._dimension})"
            )
        # Cosine similarity = dot product since both sides are L2-normalized.
        # Resulting scores shape: (chunk_count,).
        scores = (self._embeddings @ query_emb[0]).astype(float)
        # Sort descending; keep positive scores only.
        # argsort gives ascending so negate.
        order = np.argsort(-scores)
        results: list[tuple[Chunk, float]] = []
        for i in order:
            score = float(scores[i])
            if score <= 0.0:
                # Negative or zero cosine = no useful similarity.
                continue
            results.append((self._chunks[i], score))
            if len(results) >= top_k:
                break
        return results
