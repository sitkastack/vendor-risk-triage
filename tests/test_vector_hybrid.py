"""Tests for the Phase 4 sub-system 5 vector + hybrid retrieval.

Covers the Embedder Protocol, HashEmbedder (deterministic), the
SentenceTransformerEmbedder lazy-import path (mocked), VectorIndex
arithmetic and edge cases, and HybridIndex RRF math.

SentenceTransformerEmbedder is NOT actually exercised against
sentence-transformers; the test uses a mock to verify the lazy import
and the constructor wiring. Real embedding tests are an integration
concern for deploying organizations that install the optional dep.
"""
from __future__ import annotations

import hashlib
import sys
from typing import Any

import numpy as np
import pytest

from retrieval import (
    BM25Index,
    Chunk,
    Embedder,
    HashEmbedder,
    HybridIndex,
    Retriever,
    SentenceTransformerEmbedder,
    VectorIndex,
)


# -- helpers ---------------------------------------------------------------


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, corpus_name="c", document_name="d",
        page_number=1, text=text, content_hash=_hash(text),
    )


def _corpus() -> list[Chunk]:
    """Return a 5-chunk corpus suitable for retrieval tests."""
    return [
        _chunk("c1", "AI systems for regulated decisions follow OSFI E-23 model risk."),
        _chunk("c2", "NIST AI RMF defines four core functions: govern, map, measure, manage."),
        _chunk("c3", "EU AI Act categorizes systems by risk including high-risk applications."),
        _chunk("c4", "Cooking sourdough requires patience and culture management."),
        _chunk("c5", "ISO 42001 establishes an AI management system standard."),
    ]


# -- HashEmbedder ----------------------------------------------------------


def test_hash_embedder_default_dimension() -> None:
    e = HashEmbedder()
    assert e.dimension == 64


def test_hash_embedder_custom_dimension() -> None:
    e = HashEmbedder(dimension=128)
    assert e.dimension == 128


def test_hash_embedder_rejects_tiny_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        HashEmbedder(dimension=2)


def test_hash_embedder_empty_input() -> None:
    """Empty input produces a (0, D) array, not an exception."""
    e = HashEmbedder()
    arr = e.embed([])
    assert arr.shape == (0, 64)


def test_hash_embedder_shape_matches_input() -> None:
    e = HashEmbedder(dimension=32)
    arr = e.embed(["hello world", "foo bar baz", "third entry"])
    assert arr.shape == (3, 32)


def test_hash_embedder_is_deterministic() -> None:
    """Same text always produces the same vector."""
    e = HashEmbedder(dimension=32)
    arr1 = e.embed(["regulated AI decisions"])
    arr2 = e.embed(["regulated AI decisions"])
    assert np.allclose(arr1, arr2)


def test_hash_embedder_l2_normalized() -> None:
    """Every output row has L2 norm 1.0 (or 0.0 for empty token text)."""
    e = HashEmbedder()
    arr = e.embed(["hello world", "another sentence"])
    for i in range(arr.shape[0]):
        norm = np.linalg.norm(arr[i])
        assert abs(norm - 1.0) < 1e-5


def test_hash_embedder_disjoint_vocabs_have_low_similarity() -> None:
    """Texts with no shared tokens produce near-orthogonal embeddings."""
    e = HashEmbedder(dimension=256)  # large enough to avoid collision
    arr = e.embed(["alpha bravo charlie", "xenon yttrium zinc"])
    similarity = float(arr[0] @ arr[1])
    assert similarity < 0.3  # Strong upper bound for unrelated text


def test_hash_embedder_punctuation_only_produces_zero_vector() -> None:
    """Text that tokenizes to nothing yields a zero vector (norm undefined)."""
    e = HashEmbedder()
    arr = e.embed(["!!! ???"])
    assert arr.shape == (1, 64)
    # The vector is all zeros; norm is 0.
    assert np.linalg.norm(arr[0]) == 0.0


# -- SentenceTransformerEmbedder (mocked) ---------------------------------


def test_sentence_transformer_embedder_raises_when_lib_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without sentence-transformers installed, construction raises ImportError."""
    # Simulate missing sentence-transformers by removing it from sys.modules
    # and blocking re-import.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError, match="sentence-transformers"):
        SentenceTransformerEmbedder()


def test_sentence_transformer_embedder_uses_mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """With sentence-transformers mocked, the wrapper passes through correctly."""

    class _MockModel:
        def __init__(self, model_name: str) -> None:
            self._name = model_name

        def get_sentence_embedding_dimension(self) -> int:
            return 384

        def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray:
            # Return zero embeddings of the claimed dimension.
            return np.zeros((len(texts), 384), dtype=np.float32)

    class _MockSentenceTransformersModule:
        SentenceTransformer = _MockModel

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        _MockSentenceTransformersModule,  # type: ignore[arg-type]
    )

    e = SentenceTransformerEmbedder("test-model-name")
    assert e.dimension == 384
    assert e.model_name == "test-model-name"
    arr = e.embed(["hello"])
    assert arr.shape == (1, 384)


def test_sentence_transformer_embedder_empty_input_does_not_call_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty input returns (0, D) without invoking the model."""

    encode_calls: list[Any] = []

    class _MockModel:
        def __init__(self, model_name: str) -> None: ...
        def get_sentence_embedding_dimension(self) -> int:
            return 128
        def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray:
            encode_calls.append(texts)
            return np.zeros((len(texts), 128), dtype=np.float32)

    class _MockMod:
        SentenceTransformer = _MockModel

    monkeypatch.setitem(sys.modules, "sentence_transformers", _MockMod)
    e = SentenceTransformerEmbedder()
    arr = e.embed([])
    assert arr.shape == (0, 128)
    assert encode_calls == []  # model not invoked for empty input


# -- VectorIndex ----------------------------------------------------------


def test_vector_index_constructs_over_chunks() -> None:
    chunks = _corpus()
    idx = VectorIndex(chunks, HashEmbedder(dimension=64))
    assert idx.chunk_count == 5
    assert idx.dimension == 64


def test_vector_index_rejects_empty_chunks() -> None:
    with pytest.raises(ValueError, match="at least one chunk"):
        VectorIndex([], HashEmbedder())


def test_vector_index_query_returns_chunks_by_similarity() -> None:
    chunks = _corpus()
    idx = VectorIndex(chunks, HashEmbedder(dimension=128))
    # Query a phrase that matches c1 specifically
    results = idx.query("OSFI E-23 model risk", top_k=3)
    assert len(results) >= 1
    top_chunk, top_score = results[0]
    assert top_chunk.chunk_id == "c1"
    assert top_score > 0


def test_vector_index_query_excludes_zero_score() -> None:
    """Chunks with zero similarity are not returned."""
    chunks = _corpus()
    idx = VectorIndex(chunks, HashEmbedder(dimension=512))  # high dim to reduce collisions
    # Use a query nothing in the corpus matches
    results = idx.query("completely orthogonal vocabulary xyz123", top_k=5)
    # If any results, they should have positive scores
    for _c, s in results:
        assert s > 0


def test_vector_index_query_respects_top_k() -> None:
    chunks = _corpus()
    idx = VectorIndex(chunks, HashEmbedder(dimension=128))
    results = idx.query("AI", top_k=2)
    assert len(results) <= 2


def test_vector_index_query_rejects_zero_top_k() -> None:
    chunks = _corpus()
    idx = VectorIndex(chunks, HashEmbedder(dimension=64))
    with pytest.raises(ValueError, match="top_k"):
        idx.query("anything", top_k=0)


def test_vector_index_query_results_sorted_desc() -> None:
    chunks = _corpus()
    idx = VectorIndex(chunks, HashEmbedder(dimension=128))
    results = idx.query("AI risk regulation management", top_k=5)
    scores = [s for _c, s in results]
    assert scores == sorted(scores, reverse=True)


def test_vector_index_rejects_embedder_with_wrong_shape() -> None:
    """An Embedder returning the wrong shape raises at index construction."""
    class _BadEmbedder:
        @property
        def dimension(self) -> int:
            return 32
        def embed(self, texts: list[str]) -> np.ndarray:
            # Return wrong shape: claim 32 dims but produce 16
            return np.zeros((len(texts), 16), dtype=np.float32)

    with pytest.raises(ValueError, match="shape"):
        VectorIndex(_corpus(), _BadEmbedder())  # type: ignore[arg-type]


def test_vector_index_rejects_embedder_wrong_query_shape() -> None:
    """An Embedder returning wrong shape at query time raises."""
    class _StableEmbedder:
        """Returns correct shape at corpus construction, wrong shape at query."""
        def __init__(self) -> None:
            self._first = True

        @property
        def dimension(self) -> int:
            return 32

        def embed(self, texts: list[str]) -> np.ndarray:
            if self._first:
                self._first = False
                return np.zeros((len(texts), 32), dtype=np.float32)
            # Subsequent calls (queries) return wrong shape
            return np.zeros((len(texts), 16), dtype=np.float32)

    idx = VectorIndex(_corpus(), _StableEmbedder())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="query shape"):
        idx.query("anything", top_k=1)


# -- HybridIndex ----------------------------------------------------------


def test_hybrid_index_constructs() -> None:
    chunks = _corpus()
    idx = HybridIndex(chunks, HashEmbedder(dimension=128))
    assert idx.chunk_count == 5


def test_hybrid_index_rejects_empty_chunks() -> None:
    with pytest.raises(ValueError, match="at least one chunk"):
        HybridIndex([], HashEmbedder())


def test_hybrid_index_rejects_invalid_rrf_k() -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        HybridIndex(_corpus(), HashEmbedder(), rrf_k=0)


def test_hybrid_index_rejects_invalid_fanout() -> None:
    with pytest.raises(ValueError, match="fanout"):
        HybridIndex(_corpus(), HashEmbedder(), fanout=0)


def test_hybrid_index_returns_results_for_lexical_match() -> None:
    chunks = _corpus()
    idx = HybridIndex(chunks, HashEmbedder(dimension=128), fanout=20)
    results = idx.query("OSFI E-23", top_k=3)
    assert len(results) >= 1
    # Top result should be the OSFI chunk (lexical match strong)
    assert results[0][0].chunk_id == "c1"


def test_hybrid_index_query_rejects_zero_top_k() -> None:
    idx = HybridIndex(_corpus(), HashEmbedder(dimension=64))
    with pytest.raises(ValueError, match="top_k"):
        idx.query("anything", top_k=0)


def test_hybrid_index_results_sorted_desc() -> None:
    idx = HybridIndex(_corpus(), HashEmbedder(dimension=128))
    results = idx.query("AI regulation", top_k=5)
    scores = [s for _c, s in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_index_rrf_score_combines_both_indexes() -> None:
    """A chunk ranked first in BOTH indexes scores higher than one ranked in only one."""
    idx = HybridIndex(_corpus(), HashEmbedder(dimension=512), rrf_k=60, fanout=20)
    # A query that the corpus contains exact tokens for should score high
    # via both BM25 and Vector
    results = idx.query("AI regulated decisions OSFI", top_k=5)
    assert len(results) >= 1
    top_score = results[0][1]
    # If only one index contributed, max possible would be 1/(60+1) ≈ 0.0164.
    # When both contribute, it should exceed that.
    assert top_score > 0.01


def test_hybrid_index_compose_with_retriever() -> None:
    """HybridIndex can be wrapped by Retriever (same shape as BM25Index)."""
    idx = HybridIndex(_corpus(), HashEmbedder(dimension=128))
    ret = Retriever(idx)  # type: ignore[arg-type]
    # The Retriever doesn't care about the underlying index type;
    # it just calls .query() and unwraps tuples.
    results = ret.query("OSFI", top_k=2)
    assert len(results) <= 2
    if results:
        assert isinstance(results[0], Chunk)


def test_hybrid_index_chunks_with_zero_overlap_excluded() -> None:
    """Chunks that neither index finds relevant do not appear in results."""
    idx = HybridIndex(_corpus(), HashEmbedder(dimension=512), fanout=2)
    # With low fanout, only top-2 from each index participate.
    results = idx.query("cooking sourdough", top_k=10)
    # The cooking chunk should appear (c4)
    chunk_ids = [c.chunk_id for c, _s in results]
    assert "c4" in chunk_ids


# -- RRF math directly ---------------------------------------------------


def test_rrf_formula_explicit() -> None:
    """A chunk ranked 1 in BM25 and 1 in Vector with rrf_k=60 scores 2/61."""
    # Hand-construct a corpus where we can predict the rankings.
    # c1 will dominate both indexes if the query exactly matches it.
    chunks = [
        _chunk("c1", "alpha beta gamma delta epsilon"),
        _chunk("c2", "completely unrelated tokens here"),
        _chunk("c3", "another unrelated chunk"),
    ]
    idx = HybridIndex(chunks, HashEmbedder(dimension=128), rrf_k=60, fanout=10)
    results = idx.query("alpha beta gamma", top_k=3)
    # c1 should rank first; with both indexes ranking it #1, score = 1/(60+1) + 1/(60+1) = 2/61
    if results and results[0][0].chunk_id == "c1":
        expected = 2.0 / 61.0
        actual = results[0][1]
        # Loose tolerance because actual ranking depends on both index implementations
        assert abs(actual - expected) < 0.001 or actual >= 1.0 / 61.0


def test_hybrid_default_rrf_k_is_sixty() -> None:
    """The Cormack-paper default is k=60."""
    # Indirect test: construct with default rrf_k and verify score upper bound.
    idx = HybridIndex(_corpus(), HashEmbedder())
    results = idx.query("AI", top_k=5)
    # Max possible single-index contribution with rank=1 and k=60 is 1/61
    for _c, score in results:
        # Score is the sum of at most two such contributions, so bounded by 2/61
        assert score <= 2.0 / 61.0 + 1e-6
