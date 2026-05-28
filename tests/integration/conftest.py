"""Shared fixtures and skip helpers for integration tests.

The default pytest run excludes ``integration`` and ``real_llm`` markers
via ``addopts`` in pyproject.toml. To run integration tests::

    pytest -m integration

To include real-LLM tests (requires ANTHROPIC_API_KEY and costs money)::

    pytest -m "integration and real_llm"

Or to run everything including slow + paid tests::

    pytest -m ""    # empty marker filter = include all
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional

import pytest

from tests.integration.corpora_cache import (
    CORPUS_REGISTRY,
    CorpusFetchError,
    fetch_corpus,
)


# -- corpus fixtures -----------------------------------------------------


def _try_fetch(name: str, verify: bool = True) -> Optional[Path]:
    """Attempt a corpus fetch; return None on failure.

    Integration tests use this to skip cleanly when corpora are not
    available (offline contributors, CI without network, regulators
    serving 5xx). ``verify=False`` fetches a source that is not
    content-hash-pinnable (see fetch_corpus).
    """
    try:
        return fetch_corpus(name, verify=verify)
    except CorpusFetchError:
        return None


@pytest.fixture(scope="session")
def osfi_e23_pdf() -> Path:
    """Cached OSFI E-23 PDF. Skips test if unfetchable.

    Fetched with verify=False: the OSFI print-PDF route is
    non-deterministic (per-fetch token), so it has no stable
    content-hash pin. The guideline text it returns is stable, which is
    what the integration test asserts against.
    """
    path = _try_fetch("osfi-e23", verify=False)
    if path is None:
        pytest.skip(
            "OSFI E-23 PDF unavailable (network). See "
            "tests/integration/README.md for setup."
        )
    return path


@pytest.fixture(scope="session")
def nist_ai_rmf_pdf() -> Path:
    """Cached NIST AI RMF 100-1 PDF. Skips test if unfetchable."""
    path = _try_fetch("nist-ai-rmf")
    if path is None:
        pytest.skip(
            "NIST AI RMF PDF unavailable (network or pin issue). See "
            "tests/integration/README.md for setup."
        )
    return path


@pytest.fixture(scope="session")
def eu_ai_act_pdf() -> Path:
    """Cached EU AI Act PDF (English). Skips test if unfetchable.

    Fetched with verify=False because EUR-Lex returns an empty body to
    scripted clients (the live download won't succeed at all; the
    empty-body guard in fetch_corpus turns that into a clean skip).
    The verify=False mode also accepts a manually-placed cached PDF
    without a hash check, so dropping the EU AI Act PDF into
    ``~/.cache/sitkastack-vrt/corpora/eu-ai-act/eu-ai-act-regulation-2024-1689-en.pdf``
    (downloaded once via a browser from the registry URL) is enough to
    make this test run.
    """
    path = _try_fetch("eu-ai-act", verify=False)
    if path is None:
        pytest.skip(
            "EU AI Act PDF unavailable. EUR-Lex blocks scripted "
            "fetches; download the PDF in a browser and place it in "
            "the cache. See tests/integration/README.md."
        )
    return path


@pytest.fixture(scope="session")
def sox_pdf() -> Path:
    """Cached SOX (PL 107-204) PDF. Skips test if unfetchable."""
    path = _try_fetch("sox-pl-107-204")
    if path is None:
        pytest.skip(
            "SOX PL 107-204 PDF unavailable (network or pin issue). "
            "See tests/integration/README.md for setup."
        )
    return path


# -- real-LLM fixture ---------------------------------------------------


@pytest.fixture(scope="session")
def anthropic_api_key() -> str:
    """Skips real-LLM tests when ANTHROPIC_API_KEY is missing or a placeholder.

    Real-LLM tests are gated by both the ``real_llm`` marker AND a
    valid-looking API key. A contributor running
    ``pytest -m real_llm`` (or ``-m integration``, which collects the
    dual-tagged real-LLM smoke test) without a key, OR with a
    placeholder value exported (a common pattern in venv setups),
    gets a clean skip rather than an Anthropic SDK 401.

    Real Anthropic API keys start with ``sk-ant-``. Anything else
    (empty, whitespace, ``placeholder``, an OpenAI key, etc.) is
    treated as absent.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not key.startswith("sk-ant-"):
        pytest.skip(
            "ANTHROPIC_API_KEY missing or appears to be a placeholder; "
            "skipping real-LLM test."
        )
    return key


# -- demo vendor submission --------------------------------------------


@pytest.fixture(scope="session")
def demo_vendor_submission() -> dict:
    """A representative vendor submission for integration tests.

    A scenario the agent should be able to triage credibly: a third-
    party document-OCR vendor (Tier 3 elevated by default in most
    risk frameworks because of training-data exposure, customer
    PII flow, and regulator scrutiny on data residency).
    """
    return {
        "vendor_name": "TextLens AI Inc.",
        "service_description": (
            "Cloud-based OCR and document classification service "
            "designed for financial services. Customers upload "
            "scanned identity documents, account statements, and "
            "loan applications via an HTTPS API. The vendor's models "
            "extract structured fields (name, address, account "
            "numbers) and return them in JSON. Documents are "
            "retained for 7 days for retry/replay; embeddings are "
            "retained for 30 days for model improvement (opt-in)."
        ),
        "data_classification": "PII_FINANCIAL",
        "data_residency": "US_EAST",
        "sub_processors": [
            "AWS (Virginia)",
            "OpenAI API (for fallback OCR on low-confidence pages)",
        ],
        "soc2_status": "Type II report dated 2025-09",
        "iso27001_status": "Not certified",
        "model_provenance": (
            "Fine-tuned vision-language model based on open-weight "
            "Llama 3.2 11B Vision; training data includes proprietary "
            "synthetic financial documents and the publicly licensed "
            "DocBank corpus."
        ),
        "intended_use_cases": [
            "Customer onboarding identity verification",
            "Loan document intake automation",
            "Statement digitization for migrated accounts",
        ],
    }
