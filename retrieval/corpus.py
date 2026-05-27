"""Corpus loading: turn regulation source bytes into Chunks.

A CorpusLoader bridges the ingestion layer (which produces Documents)
and the retrieval layer (which indexes Chunks). The loader handles PDF
inputs by delegating to PDFReader and chunking the result.

Two chunking strategies are supported:

- Page-based (default): one Chunk per non-empty page. Cheap and simple.
- Section-aware (sectionize=True): each page is sub-divided by detected
  section headings; each section becomes a Chunk with section_heading
  set. Improves audit-trail readability and retrieval quality on queries
  that reference specific sections.

The loader does NOT fetch bytes. The same separation-of-concerns
discipline used elsewhere applies: byte fetching is an institutional
connector concern (the framework remains corpus-agnostic), so callers
supply bytes and the loader chunks them.

Deferred:

- [deferred-subsystem-5-followup] Real corpus manifest (URLs and fetch
  instructions for the five primary regulations: OSFI E-23, ISO 42001,
  NIST AI RMF, EU AI Act, SOX/ICFR) - the framework ships the loader;
  deploying orgs ship their authorised corpus copies
- [deferred-phase-4-followup] Non-PDF source formats (HTML regulators
  publish guidance pages directly to the web; many EU AI Act documents
  are HTML-first)
- [deferred-phase-5] Cross-page section concatenation (a section
  spanning pages 7-9 emerges as one chunk rather than three)
"""
from __future__ import annotations

import hashlib
from typing import Optional, Pattern

from ingestion.document import ArtifactType
from ingestion.readers import DocumentReader, PDFReader
from retrieval.chunk import Chunk
from retrieval.sectionizer import detect_sections


__all__ = [
    "CorpusLoader",
]


class CorpusLoader:
    """Loads regulation source bytes into a list of Chunks.

    Constructs Chunks with a consistent naming scheme:
    ``{corpus_name}:{document_name}:page-{N}``.

    Usage::

        from pathlib import Path
        from retrieval import CorpusLoader

        loader = CorpusLoader()
        chunks = loader.load_pdf(
            corpus_name="osfi-e23",
            document_name="guideline-2023-09-15",
            content=Path("osfi-e23-guideline.pdf").read_bytes(),
        )
    """

    def __init__(self, reader: Optional[DocumentReader] = None) -> None:
        """Construct a CorpusLoader.

        Args:
            reader: Optional DocumentReader for PDF extraction. Defaults
                to PDFReader. Passing a custom reader is useful for tests
                and for future reader implementations (XLSX, HTML).
        """
        self._reader: DocumentReader = reader if reader is not None else PDFReader()

    def load_pdf(
        self,
        corpus_name: str,
        document_name: str,
        content: bytes,
        sectionize: bool = False,
        section_patterns: Optional[tuple[Pattern[str], ...]] = None,
    ) -> list[Chunk]:
        """Load a PDF as a list of Chunks.

        With ``sectionize=False`` (the default), each non-empty page
        becomes one Chunk. The chunk_id is
        ``{corpus_name}:{document_name}:page-{N}``. The section_heading
        field is left None.

        With ``sectionize=True``, each page is scanned for section
        headings using the supplied patterns (or DEFAULT_SECTION_PATTERNS).
        Pages containing detected headings are split: text before the
        first heading becomes a "preamble" chunk with section_heading=None,
        and each section becomes its own chunk with section_heading set
        to the detected heading text. Pages with no detected headings
        produce a single chunk identical to the page-based output.

        Pages that produce no extractable text (image-only, scanned pages
        without OCR) are skipped with no Chunk emitted. Pages whose
        sections are entirely whitespace are also skipped at the section
        granularity.

        Args:
            corpus_name: Short identifier for the corpus, e.g.,
                ``osfi-e23``. Recorded on every Chunk.
            document_name: Short identifier for this specific document
                within the corpus, e.g., ``guideline-2023-09-15``.
                Recorded on every Chunk.
            content: PDF bytes. Caller has fetched these from wherever
                their corpus lives.
            sectionize: If True, sub-divide each page by detected section
                headings. Default False preserves the page-based
                behavior for backward compatibility.
            section_patterns: Optional override pattern set for section
                detection. Defaults to DEFAULT_SECTION_PATTERNS. Ignored
                when sectionize=False.

        Returns:
            A list of Chunks in document order (page order; within a
            page, section order). May be empty if every page produced
            no text.

        Raises:
            ingestion.readers.DocumentReadError: If the PDF cannot be
                parsed at all (malformed, encrypted, etc.). The error
                surfaces from the underlying reader unchanged.
        """
        artifact_type: ArtifactType = "other"
        document = self._reader.read(
            source_reference=f"corpus://{corpus_name}/{document_name}",
            artifact_type=artifact_type,
            content=content,
        )
        chunks: list[Chunk] = []
        for page_index, page_text in enumerate(document.pages, start=1):
            if not page_text.strip():
                continue  # Skip pages with no extractable text.
            if sectionize:
                chunks.extend(self._chunk_page_by_section(
                    corpus_name=corpus_name,
                    document_name=document_name,
                    page_index=page_index,
                    page_text=page_text,
                    section_patterns=section_patterns,
                ))
            else:
                chunks.append(self._chunk_page_whole(
                    corpus_name=corpus_name,
                    document_name=document_name,
                    page_index=page_index,
                    page_text=page_text,
                ))
        return chunks

    @staticmethod
    def _chunk_page_whole(
        corpus_name: str,
        document_name: str,
        page_index: int,
        page_text: str,
    ) -> Chunk:
        """Build a single page-based Chunk (default chunking strategy)."""
        return Chunk(
            chunk_id=f"{corpus_name}:{document_name}:page-{page_index}",
            corpus_name=corpus_name,
            document_name=document_name,
            page_number=page_index,
            text=page_text,
            content_hash="sha256:" + hashlib.sha256(
                page_text.encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    def _chunk_page_by_section(
        corpus_name: str,
        document_name: str,
        page_index: int,
        page_text: str,
        section_patterns: Optional[tuple[Pattern[str], ...]],
    ) -> list[Chunk]:
        """Sub-divide a page into section-aware Chunks.

        Returns one Chunk per detected section, plus an optional preamble
        Chunk for text appearing before the first heading. If no sections
        are detected, returns a single Chunk identical to the page-based
        output (no section_heading).

        Empty sub-chunks (whitespace-only text between headings) are
        skipped silently.
        """
        sections = detect_sections(page_text, patterns=section_patterns)
        if not sections:
            return [CorpusLoader._chunk_page_whole(
                corpus_name=corpus_name,
                document_name=document_name,
                page_index=page_index,
                page_text=page_text,
            )]

        chunks: list[Chunk] = []
        # Preamble: text from start of page to start of first section.
        first_start = sections[0].start_offset
        if first_start > 0:
            preamble = page_text[:first_start]
            if preamble.strip():
                chunks.append(Chunk(
                    chunk_id=(
                        f"{corpus_name}:{document_name}"
                        f":page-{page_index}:section-0"
                    ),
                    corpus_name=corpus_name,
                    document_name=document_name,
                    page_number=page_index,
                    text=preamble,
                    content_hash="sha256:" + hashlib.sha256(
                        preamble.encode("utf-8")
                    ).hexdigest(),
                    section_heading=None,
                ))

        # One chunk per detected section.
        for section_idx, section in enumerate(sections, start=1):
            section_text = page_text[section.start_offset:section.end_offset]
            if not section_text.strip():  # pragma: no cover
                # Defensive: a section's text spans from its heading line
                # to the next heading. Since detect_sections requires
                # non-empty stripped lines to match, section_text always
                # contains at least the heading characters. Branch retained
                # as a safety net against future refactors that decouple
                # the start_offset from the heading line.
                continue
            chunks.append(Chunk(
                chunk_id=(
                    f"{corpus_name}:{document_name}"
                    f":page-{page_index}:section-{section_idx}"
                ),
                corpus_name=corpus_name,
                document_name=document_name,
                page_number=page_index,
                text=section_text,
                content_hash="sha256:" + hashlib.sha256(
                    section_text.encode("utf-8")
                ).hexdigest(),
                section_heading=section.heading_text,
            ))
        return chunks
