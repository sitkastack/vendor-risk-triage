"""Document readers: extract text from vendor-submitted artifact bytes.

A reader takes the bytes of one artifact plus identifying metadata
(source reference and artifact type) and produces a ``Document`` with
extracted text and verification fields. Readers do NOT fetch bytes from
URIs; URI resolution is an institutional connector concern (the input
contract states explicitly that it "records the reference; it does not
parse the artifact"). The caller provides bytes; we extract.

MVP ships a single concrete reader: ``PDFReader``. SOC 2 reports, model
cards, data processing agreements, privacy policies, and architecture
documents are dominantly PDF in practice. Security questionnaires
(typically XLSX) and other formats are tagged for follow-up.

Audit posture:

- Every Document carries the SHA-256 of the bytes that produced it.
  Callers that have a claimed ``content_hash`` from the submission can
  verify the Document's hash matches before passing it to the agent.
- Encrypted PDFs raise ``DocumentReadError`` rather than emitting silent
  empty text. An encrypted SOC 2 report the agent cannot read is a
  problem the caller needs to handle; we do not mask it.
- Pages that produce no extractable text (image-only, scanned) produce a
  warning rather than an error. Scanned pages are common in older
  attestation reports; failing the entire extraction over one such page
  would be too brittle. The warning surfaces the issue to the caller.

Deferred:

- [deferred-subsystem-4-followup] ``XLSXReader`` for security questionnaires
- [deferred-subsystem-4-followup] Reader registry / dispatcher by URI
  scheme or artifact type
- [deferred-phase-4] OCR fallback for scanned pages (would invoke
  Tesseract or similar; introduces a heavy dependency)
- [deferred-phase-4] Table extraction (CC tables in SOC 2 lose structure)
- [deferred-phase-4] Form-field extraction
"""
from __future__ import annotations

import hashlib
import io
from typing import Protocol

import pypdf
from pypdf.errors import PdfReadError

from ingestion.document import ArtifactType, Document


__all__ = [
    "DocumentReader",
    "DocumentReadError",
    "PDFReader",
]


class DocumentReadError(Exception):
    """Raised when an artifact cannot be read.

    Specific causes (encrypted PDF, corrupted bytes, unsupported format)
    appear in the message. The exception type is shared across reader
    implementations so callers can handle "could not read this artifact"
    uniformly.
    """


class DocumentReader(Protocol):
    """Structural interface every reader implements.

    A reader is any object with a ``read`` method matching this signature.
    The Protocol exists so the agent and other consumers can be typed
    against the interface without importing a specific reader class.
    """

    def read(
        self,
        source_reference: str,
        artifact_type: ArtifactType,
        content: bytes,
    ) -> Document:
        ...  # pragma: no cover - protocol declaration


class PDFReader:
    """Extracts text from PDF bytes using pypdf.

    Usage::

        reader = PDFReader()
        with open("vendor-soc2.pdf", "rb") as f:
            doc = reader.read(
                source_reference="internal://docstore/vendor-soc2.pdf",
                artifact_type="soc2_report",
                content=f.read(),
            )
        print(doc.extracted_text)

    The reader is stateless; one instance can read many documents.
    Performance is bounded by pypdf's parsing speed (roughly 100-300
    pages/second for text PDFs on commodity hardware; scanned PDFs without
    OCR produce empty text quickly).
    """

    def read(
        self,
        source_reference: str,
        artifact_type: ArtifactType,
        content: bytes,
    ) -> Document:
        """Extract text from PDF bytes and return a Document.

        Args:
            source_reference: The URI/locator from the submission's
                ``documentation_artifacts[i].reference``. Recorded on the
                Document for audit traceability; not used for I/O.
            artifact_type: The artifact type the caller declared (matching
                the submission's enum). Recorded on the Document.
            content: The raw PDF bytes.

        Returns:
            A Document with per-page extracted text, content hash, and
            any extraction warnings.

        Raises:
            DocumentReadError: If the bytes are not a valid PDF, or the
                PDF is encrypted (encrypted PDFs require a password we do
                not have; failing loud is the audit-correct response).
        """
        content_hash = "sha256:" + hashlib.sha256(content).hexdigest()

        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
        except PdfReadError as exc:
            raise DocumentReadError(
                f"could not parse PDF at {source_reference!r}: {exc}"
            ) from exc
        except Exception as exc:  # pypdf can raise other exceptions on malformed input
            raise DocumentReadError(
                f"unexpected error parsing PDF at {source_reference!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if reader.is_encrypted:
            raise DocumentReadError(
                f"PDF at {source_reference!r} is encrypted; password-protected "
                "PDFs cannot be ingested by this reader. Decrypt before "
                "submitting or skip this artifact."
            )

        pages: list[str] = []
        warnings: list[str] = []
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - text extraction can fail on individual pages
                # A single page failing to extract should not lose the whole
                # document. Record the warning and emit an empty page.
                text = ""
                warnings.append(
                    f"page {page_index} extraction failed: "
                    f"{type(exc).__name__}: {str(exc)[:200]}"
                )
            if not text.strip():
                warnings.append(
                    f"page {page_index} produced no extractable text "
                    "(likely scanned or image-only; consider OCR)"
                )
            pages.append(text)

        # The separator default lives on Document; we read it here so the
        # joined text uses the same marker an LLM sees in the field
        # documentation.
        separator = Document.model_fields["page_separator"].default
        extracted_text = separator.join(pages)

        return Document(
            source_reference=source_reference,
            artifact_type=artifact_type,
            page_count=len(pages),
            extracted_text=extracted_text,
            pages=pages,
            content_hash=content_hash,
            extraction_warnings=warnings,
        )
