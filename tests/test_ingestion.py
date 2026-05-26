"""Tests for the Phase 3 ingestion package (sub-system 4).

Covers the Document model, the PDFReader implementation, and the error
paths every reader must handle (malformed bytes, encrypted PDFs,
pages with no extractable text).
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ingestion import (
    ArtifactType,
    Document,
    DocumentReader,
    DocumentReadError,
    PDFReader,
)


REPO_ROOT = Path(__file__).parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample-soc2.pdf"


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Load the canonical fixture PDF (2-page synthetic SOC 2 report)."""
    return FIXTURE_PATH.read_bytes()


@pytest.fixture
def sample_pdf_hash(sample_pdf_bytes: bytes) -> str:
    """SHA-256 of the fixture, formatted as the input/output contracts use."""
    return "sha256:" + hashlib.sha256(sample_pdf_bytes).hexdigest()


# -- Document model --------------------------------------------------------


def test_document_constructs_from_valid_data() -> None:
    """Minimum-valid Document constructs without complaint."""
    doc = Document(
        source_reference="internal://docstore/test.pdf",
        artifact_type="soc2_report",
        page_count=1,
        extracted_text="Page 1 text.",
        pages=["Page 1 text."],
        content_hash="sha256:" + "0" * 64,
    )
    assert doc.source_reference == "internal://docstore/test.pdf"
    assert doc.page_count == 1
    assert len(doc.pages) == 1


def test_document_is_frozen() -> None:
    """Document is immutable after construction (audit posture)."""
    doc = Document(
        source_reference="internal://docstore/test.pdf",
        artifact_type="soc2_report",
        page_count=1,
        extracted_text="Page 1 text.",
        pages=["Page 1 text."],
        content_hash="sha256:" + "0" * 64,
    )
    with pytest.raises(ValidationError):
        doc.page_count = 99  # type: ignore[misc]


def test_document_rejects_extra_fields() -> None:
    """Unknown fields are rejected (no silent drift)."""
    with pytest.raises(ValidationError):
        Document(
            source_reference="internal://docstore/test.pdf",
            artifact_type="soc2_report",
            page_count=1,
            extracted_text="x",
            pages=["x"],
            content_hash="sha256:" + "0" * 64,
            invented_field="should reject",  # type: ignore[call-arg]
        )


def test_document_rejects_invalid_artifact_type() -> None:
    """artifact_type must be one of the contract's enumerated values."""
    with pytest.raises(ValidationError):
        Document(
            source_reference="internal://docstore/test.pdf",
            artifact_type="not_a_real_type",  # type: ignore[arg-type]
            page_count=1,
            extracted_text="x",
            pages=["x"],
            content_hash="sha256:" + "0" * 64,
        )


@pytest.mark.parametrize("bad_hash", [
    "abc123",                            # missing prefix
    "sha256:abc",                        # too short
    "sha256:" + "0" * 63,                # 63 hex chars not 64
    "sha256:" + "0" * 65,                # 65 hex chars
    "sha256:" + "g" * 64,                # non-hex character
    "SHA256:" + "0" * 64,                # wrong case on prefix
])
def test_document_rejects_invalid_content_hash(bad_hash: str) -> None:
    """content_hash pattern matches the input/output contract format."""
    with pytest.raises(ValidationError):
        Document(
            source_reference="internal://docstore/test.pdf",
            artifact_type="soc2_report",
            page_count=1,
            extracted_text="x",
            pages=["x"],
            content_hash=bad_hash,
        )


def test_document_rejects_negative_page_count() -> None:
    """page_count must be non-negative."""
    with pytest.raises(ValidationError):
        Document(
            source_reference="internal://docstore/test.pdf",
            artifact_type="soc2_report",
            page_count=-1,
            extracted_text="",
            pages=[],
            content_hash="sha256:" + "0" * 64,
        )


def test_document_accepts_zero_pages() -> None:
    """A degenerate zero-page document is allowed (constructor's job, not contract's)."""
    doc = Document(
        source_reference="internal://docstore/empty.pdf",
        artifact_type="other",
        page_count=0,
        extracted_text="",
        pages=[],
        content_hash="sha256:" + "0" * 64,
    )
    assert doc.page_count == 0


def test_document_default_warnings_is_empty_list() -> None:
    """extraction_warnings defaults to an empty list (clean extraction signal)."""
    doc = Document(
        source_reference="internal://docstore/test.pdf",
        artifact_type="soc2_report",
        page_count=1,
        extracted_text="x",
        pages=["x"],
        content_hash="sha256:" + "0" * 64,
    )
    assert doc.extraction_warnings == []


# -- PDFReader end to end --------------------------------------------------


def test_pdf_reader_reads_fixture_successfully(
    sample_pdf_bytes: bytes, sample_pdf_hash: str
) -> None:
    """PDFReader produces a valid Document from the canonical fixture."""
    reader = PDFReader()
    doc = reader.read(
        source_reference="internal://docstore/sample-soc2.pdf",
        artifact_type="soc2_report",
        content=sample_pdf_bytes,
    )
    assert isinstance(doc, Document)
    assert doc.source_reference == "internal://docstore/sample-soc2.pdf"
    assert doc.artifact_type == "soc2_report"
    assert doc.content_hash == sample_pdf_hash
    assert doc.page_count == 2
    assert len(doc.pages) == 2


def test_pdf_reader_extracts_expected_text_content(sample_pdf_bytes: bytes) -> None:
    """The fixture's known text shows up in the extracted output."""
    reader = PDFReader()
    doc = reader.read(
        source_reference="internal://docstore/sample-soc2.pdf",
        artifact_type="soc2_report",
        content=sample_pdf_bytes,
    )
    assert "Sample SOC 2 Type II Attestation Report" in doc.pages[0]
    assert "Section 2: Control Activities" in doc.pages[1]


def test_pdf_reader_joins_pages_with_separator(sample_pdf_bytes: bytes) -> None:
    """extracted_text includes both pages joined by the page_separator."""
    reader = PDFReader()
    doc = reader.read(
        source_reference="internal://docstore/sample-soc2.pdf",
        artifact_type="soc2_report",
        content=sample_pdf_bytes,
    )
    assert doc.page_separator in doc.extracted_text
    # Both pages' first lines appear in the joined text
    assert "Sample SOC 2 Type II Attestation Report" in doc.extracted_text
    assert "Section 2: Control Activities" in doc.extracted_text


def test_pdf_reader_content_hash_is_deterministic(sample_pdf_bytes: bytes) -> None:
    """Same bytes produce same content_hash across calls."""
    reader = PDFReader()
    doc1 = reader.read(
        source_reference="x",
        artifact_type="soc2_report",
        content=sample_pdf_bytes,
    )
    doc2 = reader.read(
        source_reference="y",
        artifact_type="model_card",
        content=sample_pdf_bytes,
    )
    assert doc1.content_hash == doc2.content_hash


def test_pdf_reader_no_warnings_for_clean_fixture(sample_pdf_bytes: bytes) -> None:
    """The fixture extracts cleanly with no warnings."""
    reader = PDFReader()
    doc = reader.read(
        source_reference="internal://docstore/sample-soc2.pdf",
        artifact_type="soc2_report",
        content=sample_pdf_bytes,
    )
    assert doc.extraction_warnings == []


# -- PDFReader error paths -------------------------------------------------


def test_pdf_reader_raises_on_non_pdf_bytes() -> None:
    """Random bytes are rejected with DocumentReadError, not silent empty text."""
    reader = PDFReader()
    with pytest.raises(DocumentReadError) as excinfo:
        reader.read(
            source_reference="internal://docstore/bogus.pdf",
            artifact_type="soc2_report",
            content=b"this is not a pdf, it is just bytes",
        )
    assert "bogus.pdf" in str(excinfo.value)


def test_pdf_reader_raises_on_empty_bytes() -> None:
    """Empty bytes are rejected (cannot parse zero bytes as PDF)."""
    reader = PDFReader()
    with pytest.raises(DocumentReadError):
        reader.read(
            source_reference="internal://docstore/empty.pdf",
            artifact_type="soc2_report",
            content=b"",
        )


def test_pdf_reader_raises_on_encrypted_pdf() -> None:
    """Encrypted PDFs raise DocumentReadError with a clear message.

    Generates a tiny encrypted PDF inline (no external fixture needed)
    using pypdf's writer so the test stays self-contained.
    """
    import pypdf

    # Build a one-page PDF in memory, then encrypt it.
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(user_password="secret", owner_password="secret")
    buf = io.BytesIO()
    writer.write(buf)
    encrypted_bytes = buf.getvalue()

    reader = PDFReader()
    with pytest.raises(DocumentReadError) as excinfo:
        reader.read(
            source_reference="internal://docstore/encrypted.pdf",
            artifact_type="soc2_report",
            content=encrypted_bytes,
        )
    msg = str(excinfo.value)
    assert "encrypted" in msg.lower()
    assert "encrypted.pdf" in msg


def test_pdf_reader_warns_on_empty_page(sample_pdf_bytes: bytes) -> None:
    """A PDF page with no extractable text produces an extraction warning.

    Common in scanned attestation reports: pypdf returns "" for image-only
    pages. We surface this as a warning rather than failing, since the
    rest of the document may still be useful.
    """
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)  # blank page, no text
    buf = io.BytesIO()
    writer.write(buf)
    blank_pdf_bytes = buf.getvalue()

    reader = PDFReader()
    doc = reader.read(
        source_reference="internal://docstore/blank.pdf",
        artifact_type="soc2_report",
        content=blank_pdf_bytes,
    )
    assert doc.page_count == 1
    assert any("page 1 produced no extractable text" in w for w in doc.extraction_warnings)


def test_pdf_reader_wraps_unexpected_parser_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-PdfReadError exceptions during parsing are wrapped in DocumentReadError.

    pypdf can raise exception types other than PdfReadError on malformed
    input (e.g., generic ValueError, AssertionError). All such failures
    should surface as DocumentReadError with the original exception class
    in the message, so callers do not have to catch pypdf's internal
    exception hierarchy.
    """
    import ingestion.readers as readers_mod

    class _BoomReader:
        def __init__(self, stream: Any) -> None:
            raise ValueError("simulated pypdf internal failure")

    monkeypatch.setattr(readers_mod.pypdf, "PdfReader", _BoomReader)

    reader = PDFReader()
    with pytest.raises(DocumentReadError) as excinfo:
        reader.read(
            source_reference="internal://docstore/odd.pdf",
            artifact_type="soc2_report",
            content=b"any bytes - we monkeypatched the parser",
        )
    msg = str(excinfo.value)
    assert "unexpected error" in msg
    assert "ValueError" in msg
    assert "odd.pdf" in msg


def test_pdf_reader_records_warning_on_per_page_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single page raising during extract_text yields a warning, not a hard failure.

    Resilience property: one bad page in a 30-page SOC 2 report should
    not lose the other 29 pages of usable text. The failing page's text
    is recorded as empty and the failure surfaces as an extraction
    warning.
    """
    import ingestion.readers as readers_mod

    # Build a real two-page PDF first; we will monkeypatch extract_text
    # on the resulting Page objects.
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    original_PdfReader = readers_mod.pypdf.PdfReader

    class _FlakyPagesReader:
        def __init__(self, stream: Any) -> None:
            self._inner = original_PdfReader(stream)
            self.is_encrypted = False

        @property
        def pages(self) -> list[Any]:
            # First page raises on extract_text; second returns "".
            class _FailPage:
                def extract_text(self) -> str:
                    raise RuntimeError("simulated extraction failure")
            class _EmptyPage:
                def extract_text(self) -> str:
                    return ""
            return [_FailPage(), _EmptyPage()]

    monkeypatch.setattr(readers_mod.pypdf, "PdfReader", _FlakyPagesReader)

    reader = PDFReader()
    doc = reader.read(
        source_reference="internal://docstore/flaky.pdf",
        artifact_type="soc2_report",
        content=pdf_bytes,
    )
    assert doc.page_count == 2
    # Page 1 failed; warning records the failure.
    assert any("page 1 extraction failed" in w for w in doc.extraction_warnings)
    assert any("RuntimeError" in w for w in doc.extraction_warnings)
    # Both pages produced no text, so each also gets an "empty page" warning.
    assert any("page 1 produced no extractable text" in w for w in doc.extraction_warnings)
    assert any("page 2 produced no extractable text" in w for w in doc.extraction_warnings)


# -- DocumentReader Protocol -----------------------------------------------


def test_pdf_reader_satisfies_protocol() -> None:
    """PDFReader can be used wherever DocumentReader is required.

    Protocol structural typing: any object with a ``read`` method of the
    right shape works. PDFReader has it; this test pins that fact in
    case the method signature drifts.
    """
    reader: DocumentReader = PDFReader()  # would fail mypy if it did not satisfy
    assert hasattr(reader, "read")
    assert callable(reader.read)


def test_custom_reader_can_satisfy_protocol() -> None:
    """A duck-typed reader (not PDFReader) is acceptable wherever Protocol is required.

    Forward compatibility: future readers (XLSX, HTML, OCR-backed) need
    only match the Protocol shape; they do not need to inherit from a
    base class.
    """
    class _CustomReader:
        def read(self, source_reference: str, artifact_type: ArtifactType, content: bytes) -> Document:
            return Document(
                source_reference=source_reference,
                artifact_type=artifact_type,
                page_count=1,
                extracted_text="custom",
                pages=["custom"],
                content_hash="sha256:" + "f" * 64,
            )

    reader: DocumentReader = _CustomReader()
    doc = reader.read("ref", "other", b"\x00\x01\x02")
    assert doc.extracted_text == "custom"
