"""In-memory BM25 index over a list of Chunks.

Lexical retrieval, not vector embeddings, on purpose:

- Vendor-agnostic: no embedding model means no provider lock-in for the
  retrieval layer (the same lock-in concern that drove the agent's choice
  of PydanticAI for vendor-agnostic LLM calls).
- Deterministic: BM25 scores are a pure function of the corpus and the
  query. The same query produces the same ranked results across runs and
  across years, which embedding models cannot guarantee (model updates,
  even minor ones, perturb embeddings).
- Auditable: a reviewer can inspect why a chunk ranked where it did
  (which query tokens matched, their inverse document frequency). With
  embeddings, "the cosine similarity was high" is harder to defend.
- Pure Python: rank-bm25 has one dependency (numpy). No GPU, no large
  model file, no inference cost per query.

BM25 limitations are real and accepted for MVP:

- Misses semantic matches: a query "AI governance" will not match a
  chunk that talks about "AI management systems" unless they share
  literal tokens. Mitigation: queries are constructed by the caller, not
  raw user text; the caller can include synonyms.
- Sensitive to phrasing: regulations use specific terms ("data
  controller", "high-risk AI system") that retrieve well, but loose
  paraphrases retrieve worse.
- No stemming: "regulating" and "regulation" are different tokens.
  Tradeoff for transparency.

Deferred:

- [deferred-subsystem-5-followup] Persisted index (parquet or pickle) so
  large corpora do not re-index every Retriever construction
- [deferred-phase-4] Vector embeddings as a complementary signal
- [deferred-phase-4] Hybrid lexical + vector with reranker
- [deferred-phase-4] Query expansion via thesaurus or LLM
"""
from __future__ import annotations

import re
from typing import Optional

from rank_bm25 import BM25Okapi

from retrieval.chunk import Chunk


__all__ = [
    "BM25Index",
    "tokenize",
]


# Token pattern: sequences starting with letter or digit, allowing
# internal hyphens, dots, and underscores. Captures regulation-specific
# tokens like "e-23", "cc6.1", "iso", "42001", "annex". Skips pure
# punctuation. Lowercased before matching for case-insensitive retrieval.
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9.\-_]*")


def tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 indexing or query matching.

    The same function is used at index time (over each chunk) and at
    query time (over the query string), so retrieval depends on a single
    consistent tokenization. The function is intentionally simple and
    transparent: lowercase, then extract token-like sequences. No
    stopword removal, no stemming, no normalization. A reviewer can read
    this function and predict its output.

    Args:
        text: Any string. Empty string and whitespace-only strings
            return an empty list (BM25 handles this).

    Returns:
        A list of lowercase token strings, in order of appearance.
    """
    return _TOKEN_PATTERN.findall(text.lower())


class BM25Index:
    """In-memory BM25 index over a fixed list of Chunks.

    Construct once with a chunk list; query as many times as needed. The
    index is immutable after construction (add/remove operations are not
    supported; build a new index on corpus change).

    Usage::

        from retrieval import BM25Index

        index = BM25Index(chunks)
        ranked = index.query("regulated decisions for AI", top_k=5)
        for chunk, score in ranked:
            print(chunk.chunk_id, score)
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        """Build the index over a list of Chunks.

        Args:
            chunks: Non-empty list of Chunks. Order is preserved; the
                index returns query results by score, but Chunks with
                tied scores are returned in original list order.

        Raises:
            ValueError: If ``chunks`` is empty (BM25 over zero documents
                is not meaningful).
        """
        if not chunks:
            raise ValueError(
                "BM25Index requires at least one chunk; cannot index an "
                "empty corpus."
            )
        self._chunks: list[Chunk] = list(chunks)
        tokenized = [tokenize(c.text) for c in self._chunks]
        # BM25Okapi requires every document to have at least one token.
        # A chunk whose text contains no token-like sequences (e.g., only
        # punctuation) would break the underlying library. Surface this
        # loudly rather than silently miscount.
        for i, toks in enumerate(tokenized):
            if not toks:
                raise ValueError(
                    f"chunk at index {i} (chunk_id={self._chunks[i].chunk_id!r}) "
                    "produces no tokens; BM25 cannot index zero-token text. "
                    "Filter such chunks before indexing or omit them from "
                    "the corpus."
                )
        self._bm25: BM25Okapi = BM25Okapi(tokenized)

    @property
    def chunk_count(self) -> int:
        """Number of chunks in the index."""
        return len(self._chunks)

    def query(
        self, query_text: str, top_k: int = 5
    ) -> list[tuple[Chunk, float]]:
        """Return the top-k Chunks ranked by BM25 score for the query.

        Args:
            query_text: Free-text query. Tokenized with the same function
                used at index time so retrieval is consistent.
            top_k: Maximum number of results to return. The index may
                return fewer if the corpus is smaller than top_k, or if
                some chunks score zero against the query (zero-score
                chunks are excluded from results to avoid surfacing
                irrelevant content).

        Returns:
            A list of (Chunk, score) tuples sorted by descending score.
            Empty list if the query has no tokens or no chunks score
            above zero.
        """
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        query_tokens = tokenize(query_text)
        if not query_tokens:
            # An empty query has no semantic meaning; return nothing
            # rather than ranking every chunk by chance.
            return []
        scores = self._bm25.get_scores(query_tokens)
        # Pair scores with chunks, keep only positive scores, sort
        # descending. Zero scores mean no query tokens matched the chunk.
        scored = [
            (self._chunks[i], float(scores[i]))
            for i in range(len(self._chunks))
            if scores[i] > 0
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]
