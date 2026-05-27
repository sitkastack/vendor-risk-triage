"""Tests for Phase 4.5 commit 4: section-aware chunking.

Covers the sectionizer's pattern matching against the major regulatory
styles (OSFI numbered, EU AI Act keyword, SOX section, all-caps), the
custom-pattern hook, the integration through CorpusLoader, and the
backward-compat default behavior.
"""
from __future__ import annotations

import hashlib
import re

import pytest
from pydantic import ValidationError

from ingestion.document import Document
from ingestion.readers import DocumentReader
from retrieval import (
    Chunk,
    CorpusLoader,
    DEFAULT_SECTION_PATTERNS,
    Section,
    detect_sections,
)


# -- helpers ---------------------------------------------------------------


class _FakeReader(DocumentReader):
    """Test double that returns pre-supplied page text without parsing PDFs."""

    def __init__(self, pages: list[str]) -> None:
        self._pages = pages

    def read(self, source_reference, artifact_type, content):
        full = "\n".join(self._pages)
        return Document(
            source_reference=source_reference,
            artifact_type=artifact_type,
            page_count=len(self._pages),
            extracted_text=full,
            pages=self._pages,
            content_hash="sha256:" + hashlib.sha256(full.encode()).hexdigest(),
        )


# -- Chunk model: section_heading field -----------------------------------


def test_chunk_section_heading_defaults_to_none() -> None:
    """Backward compat: existing Chunks not passing section_heading get None."""
    c = Chunk(
        chunk_id="x:y:page-1",
        corpus_name="x",
        document_name="y",
        page_number=1,
        text="some text",
        content_hash="sha256:" + ("a" * 64),
    )
    assert c.section_heading is None


def test_chunk_section_heading_accepts_string() -> None:
    c = Chunk(
        chunk_id="x:y:page-1:section-1",
        corpus_name="x",
        document_name="y",
        page_number=1,
        text="some text",
        content_hash="sha256:" + ("a" * 64),
        section_heading="3.1 Roles and responsibilities",
    )
    assert c.section_heading == "3.1 Roles and responsibilities"


def test_chunk_rejects_section_heading_too_long() -> None:
    """section_heading capped at 256 chars matching chunk_id."""
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="x:y:page-1:section-1",
            corpus_name="x",
            document_name="y",
            page_number=1,
            text="t",
            content_hash="sha256:" + ("a" * 64),
            section_heading="A" * 257,
        )


# -- sectionizer: pattern matching ----------------------------------------


def test_detect_sections_osfi_style_hierarchical_numbered() -> None:
    """3.1, 3.2, 4.1 style headings are detected."""
    text = (
        "3.1 Roles and responsibilities\n\n"
        "Body text here.\n\n"
        "3.2 Documentation\n\n"
        "More body text.\n"
    )
    sections = detect_sections(text)
    assert len(sections) == 2
    assert sections[0].heading_text == "3.1 Roles and responsibilities"
    assert sections[1].heading_text == "3.2 Documentation"


def test_detect_sections_eu_ai_act_style_article_annex() -> None:
    """Article 1, Article 2, Annex III style headings are detected."""
    text = (
        "Article 1\n\n"
        "Subject matter content.\n\n"
        "Article 2\n\n"
        "Scope content.\n\n"
        "Annex III\n\n"
        "High-risk AI systems content.\n"
    )
    sections = detect_sections(text)
    headings = [s.heading_text for s in sections]
    assert "Article 1" in headings
    assert "Article 2" in headings
    assert "Annex III" in headings


def test_detect_sections_sox_style_section_keyword() -> None:
    """Section 302, Section 404 style headings are detected."""
    text = (
        "Section 302\n\n"
        "Corporate responsibility for financial reports.\n\n"
        "Section 404\n\n"
        "Management assessment.\n"
    )
    sections = detect_sections(text)
    headings = [s.heading_text for s in sections]
    assert "Section 302" in headings
    assert "Section 404" in headings


def test_detect_sections_all_caps_heading() -> None:
    """ALL CAPS lines of sufficient length are detected as headings."""
    text = (
        "OPERATIONAL FRAMEWORK\n\n"
        "This section describes the framework.\n\n"
        "MODEL GOVERNANCE\n\n"
        "Governance content here.\n"
    )
    sections = detect_sections(text)
    headings = [s.heading_text for s in sections]
    assert "OPERATIONAL FRAMEWORK" in headings
    assert "MODEL GOVERNANCE" in headings


def test_detect_sections_top_level_numbered_with_caps() -> None:
    """Top-level '4 OPERATIONAL FRAMEWORK' style is detected."""
    text = "4 OPERATIONAL FRAMEWORK\n\nBody follows.\n"
    sections = detect_sections(text)
    assert len(sections) == 1
    assert sections[0].heading_text == "4 OPERATIONAL FRAMEWORK"


def test_detect_sections_returns_empty_when_no_headings() -> None:
    """Body-only text yields no sections."""
    text = (
        "This is just body text with no headings.\n"
        "It has multiple sentences. No section markers.\n"
    )
    assert detect_sections(text) == []


def test_detect_sections_does_not_match_mid_sentence() -> None:
    """Body text containing 'article 1' or '3.1 the' should NOT match.

    Lowercase 'article' and non-capital follower fail the pattern guards.
    """
    text = (
        "Some body text mentioning article 1 and 3.1 the answer to a "
        "question. No real headings.\n"
    )
    assert detect_sections(text) == []


def test_detect_sections_offsets_are_correct() -> None:
    """Section offsets point at line starts in the original text."""
    text = (
        "3.1 Heading One\n"
        "Body of one.\n"
        "3.2 Heading Two\n"
        "Body of two.\n"
    )
    sections = detect_sections(text)
    assert len(sections) == 2
    # First heading starts at offset 0
    assert sections[0].start_offset == 0
    # End of first section is the start of the second
    assert sections[0].end_offset == sections[1].start_offset
    # Last section ends at text length
    assert sections[1].end_offset == len(text)
    # The text slice at the offsets matches the original
    assert text[sections[0].start_offset:sections[0].end_offset].startswith("3.1 Heading One")
    assert text[sections[1].start_offset:sections[1].end_offset].startswith("3.2 Heading Two")


def test_detect_sections_accepts_custom_patterns() -> None:
    """Callers can supply their own pattern set."""
    # A pattern matching only "RULE N" style headings
    custom = (re.compile(r"^RULE \d+$"),)
    text = (
        "RULE 1\n"
        "First rule body.\n"
        "Article 5\n"  # Would match default but not custom
        "RULE 2\n"
        "Second rule body.\n"
    )
    sections = detect_sections(text, patterns=custom)
    headings = [s.heading_text for s in sections]
    assert headings == ["RULE 1", "RULE 2"]
    assert "Article 5" not in headings


def test_detect_sections_empty_text() -> None:
    """Empty input yields no sections."""
    assert detect_sections("") == []


def test_detect_sections_whitespace_only_text() -> None:
    """Whitespace-only input yields no sections."""
    assert detect_sections("   \n\n  \t\n") == []


def test_section_model_is_frozen() -> None:
    s = Section(
        heading_text="3.1 Heading",
        start_offset=0,
        end_offset=100,
    )
    with pytest.raises(ValidationError):
        s.heading_text = "modified"  # type: ignore[misc]


def test_section_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        Section(
            heading_text="x",
            start_offset=0,
            end_offset=10,
            unknown_field=True,  # type: ignore[call-arg]
        )


def test_default_section_patterns_is_tuple_of_patterns() -> None:
    """The default patterns export is a tuple of compiled Patterns."""
    assert isinstance(DEFAULT_SECTION_PATTERNS, tuple)
    assert len(DEFAULT_SECTION_PATTERNS) >= 1
    for p in DEFAULT_SECTION_PATTERNS:
        # re.Pattern is the type returned by re.compile
        assert hasattr(p, "match"), f"Expected compiled pattern, got {type(p)}"


# -- CorpusLoader integration ---------------------------------------------


def _osfi_pages() -> list[str]:
    return [
        (
            "3.1 Roles and responsibilities\n\n"
            "Boards of directors and senior management are responsible.\n\n"
            "3.2 Documentation\n\n"
            "Institutions shall document the model lifecycle.\n"
        ),
        (
            "4 OPERATIONAL FRAMEWORK\n\n"
            "This section describes the operational expectations.\n\n"
            "4.1 Model inventory\n\n"
            "Institutions shall maintain a current inventory.\n"
        ),
    ]


def test_load_pdf_default_is_page_based() -> None:
    """sectionize defaults to False; chunks are per-page with no section_heading."""
    loader = CorpusLoader(reader=_FakeReader(_osfi_pages()))
    chunks = loader.load_pdf("osfi-e23", "guideline-2023", b"<fake>")
    assert len(chunks) == 2
    assert all(c.section_heading is None for c in chunks)
    assert chunks[0].chunk_id == "osfi-e23:guideline-2023:page-1"
    assert chunks[1].chunk_id == "osfi-e23:guideline-2023:page-2"


def test_load_pdf_sectionize_splits_pages_by_heading() -> None:
    """sectionize=True produces a chunk per detected section."""
    loader = CorpusLoader(reader=_FakeReader(_osfi_pages()))
    chunks = loader.load_pdf(
        "osfi-e23", "guideline-2023", b"<fake>", sectionize=True
    )
    # 2 sections on page 1 + 2 sections on page 2 = 4 chunks total
    assert len(chunks) == 4
    headings = [c.section_heading for c in chunks]
    assert headings == [
        "3.1 Roles and responsibilities",
        "3.2 Documentation",
        "4 OPERATIONAL FRAMEWORK",
        "4.1 Model inventory",
    ]


def test_load_pdf_sectionize_chunk_ids_carry_section_index() -> None:
    loader = CorpusLoader(reader=_FakeReader(_osfi_pages()))
    chunks = loader.load_pdf(
        "osfi-e23", "guideline-2023", b"<fake>", sectionize=True
    )
    assert chunks[0].chunk_id == "osfi-e23:guideline-2023:page-1:section-1"
    assert chunks[1].chunk_id == "osfi-e23:guideline-2023:page-1:section-2"
    assert chunks[2].chunk_id == "osfi-e23:guideline-2023:page-2:section-1"
    assert chunks[3].chunk_id == "osfi-e23:guideline-2023:page-2:section-2"


def test_load_pdf_sectionize_chunks_preserve_page_number() -> None:
    loader = CorpusLoader(reader=_FakeReader(_osfi_pages()))
    chunks = loader.load_pdf("osfi-e23", "g", b"<fake>", sectionize=True)
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 1
    assert chunks[2].page_number == 2
    assert chunks[3].page_number == 2


def test_load_pdf_sectionize_no_headings_falls_back_to_page() -> None:
    """A page with no detected headings produces a single page-based chunk."""
    pages = ["Just body text with no headings. Multiple sentences here.\n"]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf("c", "d", b"<x>", sectionize=True)
    assert len(chunks) == 1
    # Falls back to the page chunk_id format
    assert chunks[0].chunk_id == "c:d:page-1"
    assert chunks[0].section_heading is None


def test_load_pdf_sectionize_preamble_chunk_when_text_before_first_heading() -> None:
    """Text before the first detected heading becomes a preamble (section-0) chunk."""
    pages = [
        "This is preamble text before any heading.\n\n"
        "3.1 First section\n\n"
        "Body of first section.\n"
    ]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf("c", "d", b"<x>", sectionize=True)
    assert len(chunks) == 2
    # First chunk is the preamble
    assert chunks[0].chunk_id == "c:d:page-1:section-0"
    assert chunks[0].section_heading is None
    assert "preamble text" in chunks[0].text
    # Second chunk is the first detected section
    assert chunks[1].chunk_id == "c:d:page-1:section-1"
    assert chunks[1].section_heading == "3.1 First section"


def test_load_pdf_sectionize_no_preamble_when_first_heading_at_start() -> None:
    """If the first heading is the first line, no preamble chunk is emitted."""
    pages = [
        "3.1 Heading at start\n\n"
        "Body content.\n"
    ]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf("c", "d", b"<x>", sectionize=True)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "c:d:page-1:section-1"
    assert chunks[0].section_heading == "3.1 Heading at start"


def test_load_pdf_sectionize_skips_empty_pages() -> None:
    """Empty pages produce no chunks even with sectionize=True."""
    pages = ["", "  \n  ", "3.1 Real heading\n\nBody.\n"]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf("c", "d", b"<x>", sectionize=True)
    # Only the page with content produces a chunk
    assert len(chunks) == 1
    assert chunks[0].page_number == 3
    assert chunks[0].section_heading == "3.1 Real heading"


def test_load_pdf_sectionize_accepts_custom_patterns() -> None:
    """The section_patterns argument flows through to detect_sections."""
    custom = (re.compile(r"^RULE \d+$"),)
    pages = [
        "RULE 1\n"
        "Body of rule one.\n"
        "Article 5\n"  # Would match default but not custom
        "Body that should be part of rule one section.\n"
    ]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf(
        "c", "d", b"<x>", sectionize=True, section_patterns=custom,
    )
    # Custom pattern matches only "RULE 1", so we get one section chunk
    headings = [c.section_heading for c in chunks if c.section_heading]
    assert headings == ["RULE 1"]


def test_load_pdf_sectionize_content_hash_matches_section_text() -> None:
    """Each section chunk's content_hash is computed from its actual section text."""
    pages = ["3.1 Heading A\n\nBody A content.\n\n3.2 Heading B\n\nBody B content.\n"]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf("c", "d", b"<x>", sectionize=True)
    for c in chunks:
        expected = "sha256:" + hashlib.sha256(c.text.encode("utf-8")).hexdigest()
        assert c.content_hash == expected


def test_load_pdf_sectionize_default_pattern_pages_with_no_match_use_page_chunk() -> None:
    """A page where the default patterns find nothing produces the whole-page chunk."""
    pages = [
        "This page has no headings recognized by the default pattern set. "
        "Just paragraphs of body content describing some topic without any "
        "section markers, article references, or numbered hierarchies.\n"
    ]
    loader = CorpusLoader(reader=_FakeReader(pages))
    chunks = loader.load_pdf("c", "d", b"<x>", sectionize=True)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "c:d:page-1"  # page-based fallback
    assert chunks[0].section_heading is None
