"""Tests for the Phase 3 retrieval package (sub-system 5).

Covers the Chunk model, the tokenizer used by BM25 indexing, the
BM25Index class, the Retriever wrapper, and the CorpusLoader that
bridges PDF ingestion to chunk creation.

These tests do not exercise real LLM calls (the retrieval layer is
LLM-independent by design) and do not require Anthropic credentials.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ingestion.readers import DocumentReadError
from retrieval import (
    BM25Index,
    Chunk,
    CorpusLoader,
    Retriever,
    tokenize,
)


REPO_ROOT = Path(__file__).parent.parent
REGULATION_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample-regulation.pdf"


def _chunk(
    chunk_id: str = "test:doc:page-1",
    corpus_name: str = "test",
    document_name: str = "doc",
    page_number: int = 1,
    text: str = "sample regulation text content for testing",
) -> Chunk:
    """Build a Chunk with sensible defaults; tests override per case."""
    return Chunk(
        chunk_id=chunk_id,
        corpus_name=corpus_name,
        document_name=document_name,
        page_number=page_number,
        text=text,
        content_hash="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


# -- Chunk model -----------------------------------------------------------


def test_chunk_constructs_from_valid_data() -> None:
    """A minimum-valid Chunk constructs without complaint."""
    c = _chunk()
    assert c.chunk_id == "test:doc:page-1"
    assert c.page_number == 1


def test_chunk_is_frozen() -> None:
    """Chunk is immutable after construction (audit posture)."""
    c = _chunk()
    with pytest.raises(ValidationError):
        c.text = "mutated"  # type: ignore[misc]


def test_chunk_rejects_extra_fields() -> None:
    """Unknown fields are rejected (no silent drift)."""
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="x",
            corpus_name="x",
            document_name="x",
            page_number=1,
            text="x",
            content_hash="sha256:" + "0" * 64,
            invented_field="should reject",  # type: ignore[call-arg]
        )


def test_chunk_rejects_zero_page_number() -> None:
    """page_number must be >= 1 (1-indexed)."""
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="x", corpus_name="x", document_name="x",
            page_number=0,  # invalid
            text="x",
            content_hash="sha256:" + "0" * 64,
        )


def test_chunk_rejects_empty_text() -> None:
    """text must be non-empty (otherwise nothing to retrieve)."""
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="x", corpus_name="x", document_name="x",
            page_number=1, text="",
            content_hash="sha256:" + "0" * 64,
        )


@pytest.mark.parametrize("bad_hash", [
    "abc123",
    "sha256:abc",
    "sha256:" + "0" * 63,
    "sha256:" + "g" * 64,
    "SHA256:" + "0" * 64,
])
def test_chunk_rejects_invalid_content_hash(bad_hash: str) -> None:
    """content_hash pattern matches the input/output contract format."""
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="x", corpus_name="x", document_name="x",
            page_number=1, text="x",
            content_hash=bad_hash,
        )


# -- tokenizer -------------------------------------------------------------


def test_tokenize_lowercase() -> None:
    """Tokens are lowercased for case-insensitive retrieval."""
    assert tokenize("OSFI E-23 Guideline") == ["osfi", "e-23", "guideline"]


def test_tokenize_preserves_regulation_acronyms() -> None:
    """Tokens like CC6.1, E-23, AI keep their punctuation intact."""
    tokens = tokenize("CC6.1 logical access and E-23 model risk")
    assert "cc6.1" in tokens
    assert "e-23" in tokens
    assert "ai" not in tokens  # not in this input
    assert "model" in tokens


def test_tokenize_skips_pure_punctuation() -> None:
    """Punctuation that is not part of a token does not produce empty tokens."""
    tokens = tokenize("hello, world! how are you?")
    assert "" not in tokens
    assert tokens == ["hello", "world", "how", "are", "you"]


def test_tokenize_empty_string() -> None:
    """An empty string produces an empty token list."""
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_tokenize_unicode_passes_through_only_ascii_letters() -> None:
    """Non-ASCII letters are excluded by the token pattern.

    The MVP tokenizer covers a-z and 0-9. Non-ASCII letters (Cyrillic,
    accented Latin, CJK) are NOT tokenized. Regulations occasionally
    contain non-ASCII text; those tokens will not be retrievable until a
    future tokenizer expands the character class. Documented here so
    the limitation is visible.
    """
    # Plain ASCII tokenizes normally.
    assert tokenize("regulation") == ["regulation"]
    # A non-ASCII character is treated as a token boundary.
    assert tokenize("café au lait") == ["caf", "au", "lait"]


# -- BM25Index -------------------------------------------------------------


def test_bm25_index_constructs_over_non_empty_chunks() -> None:
    """A non-empty chunk list builds an index."""
    chunks = [_chunk("a", text="alpha bravo"), _chunk("b", text="charlie delta")]
    index = BM25Index(chunks)
    assert index.chunk_count == 2


def test_bm25_index_rejects_empty_chunks() -> None:
    """An empty chunk list raises ValueError (cannot index zero docs)."""
    with pytest.raises(ValueError, match="at least one chunk"):
        BM25Index([])


def test_bm25_index_rejects_zero_token_chunk() -> None:
    """A chunk whose text tokenizes to zero tokens raises ValueError.

    BM25 cannot index a zero-token document; failing loud at index time
    is preferable to surfacing a confusing runtime error from inside the
    library.
    """
    # The text "!" produces no tokens under our tokenizer.
    bad = _chunk("bad", text="!")
    with pytest.raises(ValueError, match="produces no tokens"):
        BM25Index([bad])


def test_bm25_index_query_returns_ranked_results() -> None:
    """A query returns chunks ranked by relevance."""
    chunks = [
        _chunk("c1", text="AI systems used for regulated decisions follow OSFI E-23 model risk."),
        _chunk("c2", text="NIST AI RMF defines four functions: govern, map, measure, manage."),
        _chunk("c3", text="EU AI Act categorizes systems by risk including high-risk Annex III."),
    ]
    index = BM25Index(chunks)
    results = index.query("OSFI E-23", top_k=3)
    assert len(results) >= 1
    # The OSFI E-23 chunk must rank first.
    top_chunk, top_score = results[0]
    assert top_chunk.chunk_id == "c1"
    assert top_score > 0


def test_bm25_index_query_excludes_zero_score_results() -> None:
    """Chunks that score zero against the query are not returned.

    A chunk completely unrelated to the query should not appear in
    results, even if top_k would accommodate it. Otherwise users see
    irrelevant content that pads the prompt for no benefit.

    Uses a 5-chunk corpus so BM25 Okapi IDF math is well-behaved (with
    N <= 3 IDF can degenerate to zero or negative).
    """
    chunks = [
        _chunk("c1", text="AI model risk management framework alignment guidance"),
        _chunk("c2", text="cooking instructions for sourdough bread recipe homemade"),
        _chunk("c3", text="historical analysis of medieval architecture and design"),
        _chunk("c4", text="gardening tips for tomato cultivation in summer"),
        _chunk("c5", text="instructions for assembling office furniture from kits"),
    ]
    index = BM25Index(chunks)
    results = index.query("AI model risk", top_k=5)
    chunk_ids = [c.chunk_id for c, _s in results]
    assert "c1" in chunk_ids
    assert "c2" not in chunk_ids  # zero score, excluded
    assert "c3" not in chunk_ids
    assert "c4" not in chunk_ids
    assert "c5" not in chunk_ids


def test_bm25_index_query_empty_query_returns_empty() -> None:
    """A query that tokenizes to nothing returns no results."""
    chunks = [_chunk("c1", text="some content here")]
    index = BM25Index(chunks)
    assert index.query("") == []
    assert index.query("!!!") == []


def test_bm25_index_query_rejects_zero_top_k() -> None:
    """top_k must be >= 1."""
    chunks = [_chunk("c1", text="some content here")]
    index = BM25Index(chunks)
    with pytest.raises(ValueError, match="top_k"):
        index.query("content", top_k=0)


def test_bm25_index_query_respects_top_k_limit() -> None:
    """top_k bounds the number of results returned."""
    chunks = [
        _chunk(f"c{i}", text=f"AI regulation chunk number {i} content")
        for i in range(10)
    ]
    index = BM25Index(chunks)
    results = index.query("AI regulation", top_k=3)
    assert len(results) <= 3


def test_bm25_index_query_results_sorted_by_score_desc() -> None:
    """Returned results are sorted by descending score."""
    chunks = [
        _chunk("low", text="AI mentioned once briefly"),
        _chunk("high", text="AI AI AI AI regulation regulation regulation"),
        _chunk("med", text="AI regulation appears together"),
    ]
    index = BM25Index(chunks)
    results = index.query("AI regulation", top_k=5)
    scores = [s for _c, s in results]
    assert scores == sorted(scores, reverse=True)


# -- Retriever -------------------------------------------------------------


def test_retriever_returns_chunks_only() -> None:
    """The Retriever's public query returns Chunks, not (Chunk, score) tuples.

    Uses a 5-chunk corpus because BM25 Okapi IDF math degenerates on
    very small corpora (with N=1 and n=1, IDF goes negative; with N=2
    and n=1, IDF is exactly zero). Real deployments index hundreds to
    thousands of chunks, where IDF is well-behaved; tests that exercise
    behaviour as opposed to edge math use realistic sizes.
    """
    chunks = [
        _chunk("c1", text="AI regulation content for vendor risk"),
        _chunk("c2", text="cooking recipe with sourdough bread"),
        _chunk("c3", text="historical analysis of medieval architecture"),
        _chunk("c4", text="gardening tips for tomato cultivation"),
        _chunk("c5", text="instructions for assembling office furniture"),
    ]
    index = BM25Index(chunks)
    r = Retriever(index)
    results = r.query("AI", top_k=1)
    assert len(results) == 1
    assert isinstance(results[0], Chunk)
    assert results[0].chunk_id == "c1"


def test_retriever_exposes_chunk_count() -> None:
    """The retriever surfaces the underlying index's chunk count."""
    chunks = [_chunk(f"c{i}", text=f"text {i}") for i in range(7)]
    r = Retriever(BM25Index(chunks))
    assert r.chunk_count == 7


def test_retriever_default_top_k_is_five() -> None:
    """Default top_k is 5 when not specified."""
    chunks = [_chunk(f"c{i}", text=f"AI regulation chunk number {i}") for i in range(10)]
    r = Retriever(BM25Index(chunks))
    results = r.query("AI regulation")
    assert len(results) == 5


# -- CorpusLoader ----------------------------------------------------------


@pytest.fixture
def regulation_pdf_bytes() -> bytes:
    """Load the canonical regulation fixture."""
    return REGULATION_FIXTURE_PATH.read_bytes()


def test_corpus_loader_produces_chunks_from_pdf(regulation_pdf_bytes: bytes) -> None:
    """The CorpusLoader produces one Chunk per non-empty page of the PDF."""
    loader = CorpusLoader()
    chunks = loader.load_pdf(
        corpus_name="sample-reg",
        document_name="guideline-2026",
        content=regulation_pdf_bytes,
    )
    assert len(chunks) == 3  # The fixture has 3 pages with text
    for c in chunks:
        assert c.corpus_name == "sample-reg"
        assert c.document_name == "guideline-2026"


def test_corpus_loader_chunk_id_convention(regulation_pdf_bytes: bytes) -> None:
    """Chunk ids follow the {corpus}:{document}:page-{N} convention."""
    loader = CorpusLoader()
    chunks = loader.load_pdf(
        corpus_name="osfi-e23",
        document_name="guideline-2023",
        content=regulation_pdf_bytes,
    )
    for i, c in enumerate(chunks, start=1):
        assert c.chunk_id == f"osfi-e23:guideline-2023:page-{i}"
        assert c.page_number == i


def test_corpus_loader_content_hashes_are_deterministic(regulation_pdf_bytes: bytes) -> None:
    """Loading the same PDF twice produces chunks with identical content_hashes."""
    loader = CorpusLoader()
    chunks1 = loader.load_pdf("c", "d", regulation_pdf_bytes)
    chunks2 = loader.load_pdf("c", "d", regulation_pdf_bytes)
    assert [c.content_hash for c in chunks1] == [c.content_hash for c in chunks2]


def test_corpus_loader_raises_on_invalid_pdf() -> None:
    """A non-PDF passed to load_pdf surfaces as DocumentReadError."""
    loader = CorpusLoader()
    with pytest.raises(DocumentReadError):
        loader.load_pdf("c", "d", b"this is not a pdf")


def test_corpus_loader_end_to_end_with_retriever(regulation_pdf_bytes: bytes) -> None:
    """Full pipeline: PDF -> CorpusLoader -> BM25Index -> Retriever -> Chunks."""
    loader = CorpusLoader()
    chunks = loader.load_pdf("sample-reg", "guideline-2026", regulation_pdf_bytes)
    retriever = Retriever(BM25Index(chunks))

    # The fixture's page 3 talks about vendor SOC 2 attestation.
    results = retriever.query("vendor SOC 2 attestation", top_k=1)
    assert len(results) == 1
    assert results[0].page_number == 3

    # The fixture's page 2 talks about model inventory.
    results = retriever.query("model inventory", top_k=1)
    assert len(results) == 1
    assert results[0].page_number == 2


def test_corpus_loader_accepts_custom_reader() -> None:
    """A custom DocumentReader can be passed instead of the default PDFReader.

    Decoupling test: the CorpusLoader does not hard-bind to PDFReader.
    Future readers (XLSX, HTML, OCR-backed PDF) satisfying the Protocol
    work without CorpusLoader changes.
    """
    from ingestion.document import Document

    class _MockReader:
        def read(self, source_reference: str, artifact_type: Any, content: bytes) -> Document:
            return Document(
                source_reference=source_reference,
                artifact_type=artifact_type,
                page_count=2,
                extracted_text="mock page 1\n---\nmock page 2",
                pages=["mock page 1", "mock page 2"],
                content_hash="sha256:" + "a" * 64,
            )

    loader = CorpusLoader(reader=_MockReader())  # type: ignore[arg-type]
    chunks = loader.load_pdf("c", "d", b"any bytes")
    assert len(chunks) == 2
    assert chunks[0].text == "mock page 1"
    assert chunks[1].text == "mock page 2"


def test_corpus_loader_skips_pages_with_no_text() -> None:
    """Pages that produce empty text are skipped (no Chunk emitted)."""
    from ingestion.document import Document

    class _MixedReader:
        def read(self, source_reference: str, artifact_type: Any, content: bytes) -> Document:
            return Document(
                source_reference=source_reference,
                artifact_type=artifact_type,
                page_count=3,
                extracted_text="page 1 text\n---\n\n---\npage 3 text",
                pages=["page 1 text", "", "page 3 text"],
                content_hash="sha256:" + "a" * 64,
                extraction_warnings=["page 2 produced no extractable text"],
            )

    loader = CorpusLoader(reader=_MixedReader())  # type: ignore[arg-type]
    chunks = loader.load_pdf("c", "d", b"any bytes")
    assert len(chunks) == 2  # page 2 skipped
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 3
