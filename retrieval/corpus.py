"""Corpus loading: turn regulation source bytes into Chunks.

A CorpusLoader bridges the ingestion layer (which produces Documents)
and the retrieval layer (which indexes Chunks). For MVP the loader
handles PDF inputs by delegating to PDFReader and chunking the result
one chunk per page.

The loader does NOT fetch bytes. The same separation-of-concerns
discipline used elsewhere applies: byte fetching is an institutional
connector concern (the framework remains corpus-agnostic), so callers
supply bytes and the loader chunks them.

Deferred:

- [deferred-subsystem-5-followup] Real corpus manifest (URLs and fetch
  instructions for the five primary regulations: OSFI E-23, ISO 42001,
  NIST AI RMF, EU AI Act, SOX/ICFR) - the framework ships the loader;
  deploying orgs ship their authorised corpus copies
- [deferred-subsystem-5-followup] Section-aware chunking (detect
  headings, group by section instead of by page)
- [deferred-phase-4] Non-PDF source formats (HTML regulators publish
  guidance pages directly to the web; many EU AI Act documents are
  HTML-first)
"""
from __future__ import annotations

import hashlib
from typing import Optional

from ingestion.document import ArtifactType
from ingestion.readers import DocumentReader, PDFReader
from retrieval.chunk import Chunk


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
    ) -> list[Chunk]:
        """Load a PDF as a list of per-page Chunks.

        The PDFReader extracts per-page text; each non-empty page becomes
        one Chunk. Pages that produce no extractable text (image-only,
        scanned pages without OCR) are skipped with no Chunk emitted;
        the PDFReader's warning is consumed silently because no Chunk
        is being added. Callers wanting to surface those warnings can
        invoke PDFReader directly and pass the Document to a different
        chunking strategy.

        Args:
            corpus_name: Short identifier for the corpus, e.g.,
                ``osfi-e23``. Recorded on every Chunk.
            document_name: Short identifier for this specific document
                within the corpus, e.g., ``guideline-2023-09-15``.
                Recorded on every Chunk.
            content: PDF bytes. Caller has fetched these from wherever
                their corpus lives.

        Returns:
            A list of Chunks, one per non-empty page, in page order.
            May be empty if every page produced no text (e.g., a fully
            scanned PDF without OCR).

        Raises:
            ingestion.readers.DocumentReadError: If the PDF cannot be
                parsed at all (malformed, encrypted, etc.). The error
                surfaces from the underlying reader unchanged.
        """
        # ArtifactType is the input contract's artifact_type enum; for
        # corpus PDFs we use "other" because regulation documents are
        # not one of the vendor-artifact categories the contract enumerates.
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
            chunks.append(
                Chunk(
                    chunk_id=f"{corpus_name}:{document_name}:page-{page_index}",
                    corpus_name=corpus_name,
                    document_name=document_name,
                    page_number=page_index,
                    text=page_text,
                    content_hash="sha256:" + hashlib.sha256(
                        page_text.encode("utf-8")
                    ).hexdigest(),
                )
            )
        return chunks
