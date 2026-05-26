"""Embedder Protocol and default implementations.

The retrieval layer is vendor-agnostic at the embedding level: any
class implementing the Embedder Protocol can plug into VectorIndex.
The framework ships two implementations:

- HashEmbedder: deterministic hash-based pseudo-embeddings. No
  external dependencies. Used in tests and as a fallback when
  sentence-transformers is not installed. Does NOT capture semantic
  similarity; chunks with disjoint vocabularies score near-zero.
- SentenceTransformerEmbedder: production-grade semantic embeddings
  via the sentence-transformers library. Lazy import; install via
  the [vector] extra.

Adding a new embedder (Voyage, OpenAI, Cohere, local Llama) requires
only implementing the Protocol. No other framework changes.

All embeddings are L2-normalized so cosine similarity becomes a dot
product. The Protocol contract specifies this.
"""
from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


__all__ = [
    "Embedder",
    "HashEmbedder",
    "SentenceTransformerEmbedder",
]


class Embedder(Protocol):
    """The embedding interface VectorIndex depends on.

    Implementations must:

    - Return embeddings as a numpy array of shape ``(len(texts), D)``
      where ``D`` is the implementation's fixed embedding dimension.
    - L2-normalize every row so cosine similarity equals dot product.
    - Be deterministic given fixed inputs (or document the
      non-determinism source explicitly).

    The Protocol does not require a constructor signature; concrete
    implementations may take whatever configuration they need.
    """

    @property
    def dimension(self) -> int:
        """The output embedding dimension."""
        ...

    def embed(self, texts: list[str]) -> np.ndarray:
        """Encode texts to an L2-normalized (N, D) array.

        Args:
            texts: List of strings to embed. May be empty.

        Returns:
            A numpy array of shape (len(texts), self.dimension). Empty
            input produces a (0, D) array.
        """
        ...


class HashEmbedder:
    """Deterministic hash-based pseudo-embeddings, no external deps.

    Tokenizes each input and maps tokens into a fixed-dimension vector
    via a hash function (each token contributes to one dimension based
    on hash modulo). The result is L2-normalized.

    What this captures:
        Lexical overlap. Texts sharing tokens get similar embeddings.

    What this does NOT capture:
        Semantic similarity. "AI governance" and "AI management" have
        zero shared tokens and so produce near-orthogonal embeddings.
        Use HashEmbedder for tests and as a fallback only; for real
        retrieval use a learned embedder.

    Determinism: completely deterministic given fixed dimension. Same
    text always produces the same vector across processes and platforms.
    """

    def __init__(self, dimension: int = 64) -> None:
        """Construct a HashEmbedder.

        Args:
            dimension: Output dimension. Default 64 is enough for tests
                and small-corpus toy use. Smaller dimensions collide
                more; larger dimensions are wasteful for hash-based.
        """
        if dimension < 4:
            raise ValueError(f"dimension must be >= 4, got {dimension}")
        self._dimension: int = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        rows: list[np.ndarray] = []
        for text in texts:
            vec = np.zeros(self._dimension, dtype=np.float32)
            # Tokenize on whitespace and punctuation, lowercase.
            # Same rule as retrieval.tokenize but inlined to avoid a
            # circular import.
            import re
            tokens = re.findall(r"[a-z0-9][a-z0-9.\-_]*", text.lower())
            for tok in tokens:
                # Hash token to a dimension index and accumulate.
                h = hashlib.sha256(tok.encode("utf-8")).digest()
                # First 4 bytes -> uint32 -> mod dimension
                idx = int.from_bytes(h[:4], "big") % self._dimension
                # Sign from next byte to allow cancellation
                sign = 1.0 if (h[4] & 1) else -1.0
                vec[idx] += sign
            # L2-normalize
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec = vec / norm
            # else: empty/punctuation-only text -> zero vector preserved
            rows.append(vec)
        return np.stack(rows)


class SentenceTransformerEmbedder:
    """Wraps sentence-transformers for production semantic embeddings.

    Lazy-imports sentence-transformers at construction. Install the
    optional dependency via the ``[vector]`` extra::

        pip install 'sitkastack-vrt[vector]'

    Or directly::

        pip install sentence-transformers

    Default model is ``all-MiniLM-L6-v2`` (384-dim, ~80MB, fast and
    good enough for regulation text). Pass a different model name to
    use any sentence-transformers-compatible checkpoint.

    Determinism: the model weights are fixed at install time, but the
    inference path uses floating-point arithmetic that may vary by
    platform/CPU instruction set. Differences are typically below 1e-6;
    rerank results should be stable. Document this for audit.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for "
                "SentenceTransformerEmbedder. Install with: "
                "pip install 'sitkastack-vrt[vector]' "
                "or pip install sentence-transformers"
            ) from exc
        self._model_name: str = model_name
        self._model = SentenceTransformer(model_name)
        # Probe the dimension; sentence-transformers exposes this.
        self._dimension: int = int(self._model.get_sentence_embedding_dimension())

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        # normalize_embeddings=True returns L2-normalized vectors,
        # matching the Embedder Protocol contract.
        arr = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return arr.astype(np.float32)
