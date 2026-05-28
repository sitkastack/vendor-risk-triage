"""Smoke test for scripts/harvest_corpus_artifacts.py.

The harvest script runs the real pipeline (chunk -> BM25 -> retrieve ->
triage -> render) against a regulation PDF and saves artifacts. This
test exercises it against a synthetic multi-section PDF via the --pdf
path (no network, no real corpus), asserting the three artifacts are
produced and the record validates.

The script lives in scripts/ (operational tooling, like
build_corpus_bundles.py and check_drift.py) and is not in the coverage
gate; this smoke test documents its usage and proves the pipeline
wiring holds, which is the signal that matters for a content/demo tool.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "harvest_corpus_artifacts.py"

reportlab = pytest.importorskip("reportlab")


def _load_harvest():
    spec = importlib.util.spec_from_file_location(
        "_harvest", _SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["_harvest"] = module
    spec.loader.exec_module(module)
    return module


def _synthetic_regulation_pdf() -> bytes:
    """A multi-section synthetic regulation PDF.

    Enough sections (mostly filler, a few with the query's salient
    terms) that BM25 has a real corpus to discriminate over, avoiding
    the single-document IDF degeneracy.
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    filler = (
        "Definitions and interpretation. The following terms apply to "
        "the scope of supervised entities and their reporting obligations."
    )
    targeted = (
        "Model Risk Management Governance. A federally regulated financial "
        "institution must establish accountability for oversight of "
        "artificial intelligence systems and third-party model providers "
        "across the model lifecycle, including data classification and PII."
    )
    sections = [
        f"Section {i + 1}. {targeted if i % 5 == 0 else filler}"
        for i in range(20)
    ]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for para in sections:
        for j in range(0, len(para), 88):
            c.drawString(72, y, para[j:j + 88])
            y -= 15
            if y < 80:
                c.showPage()
                y = 720
        y -= 12
        if y < 80:
            c.showPage()
            y = 720
    c.showPage()
    c.save()
    return buf.getvalue()


def test_harvest_produces_artifacts(tmp_path: Path) -> None:
    harvest = _load_harvest()

    pdf_path = tmp_path / "synthetic-reg.pdf"
    pdf_path.write_bytes(_synthetic_regulation_pdf())
    out_dir = tmp_path / "artifacts"

    code = harvest.main([
        "osfi-e23", "--pdf", str(pdf_path), "--output-dir", str(out_dir),
    ])
    assert code == 0

    pack = out_dir / "osfi-e23-audit-pack.html"
    transcript = out_dir / "osfi-e23-retrieval-transcript.md"
    record = out_dir / "osfi-e23-record.json"
    assert pack.exists() and pack.read_text().startswith("<!DOCTYPE html>")
    assert transcript.exists() and "Retrieval transcript" in transcript.read_text()
    assert record.exists()

    # The harvested record validates against the output contract.
    from schemas.validate import validate_output
    ok, errors = validate_output(json.loads(record.read_text()))
    assert ok, f"harvested record should validate: {errors}"


def test_harvest_unknown_corpus_exits_2(tmp_path: Path) -> None:
    harvest = _load_harvest()
    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(_synthetic_regulation_pdf())
    code = harvest.main([
        "not-a-corpus", "--pdf", str(pdf_path),
        "--output-dir", str(tmp_path / "out"),
    ])
    assert code == 2


def test_harvest_missing_pdf_exits_2(tmp_path: Path) -> None:
    harvest = _load_harvest()
    code = harvest.main([
        "osfi-e23", "--pdf", str(tmp_path / "nope.pdf"),
        "--output-dir", str(tmp_path / "out"),
    ])
    assert code == 2
