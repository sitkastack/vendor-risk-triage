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


def _try_fetch(name: str) -> Optional[Path]:
    """Attempt a corpus fetch; return None on failure.

    Integration tests use this to skip cleanly when corpora are not
    available (offline contributors, CI without network, regulators
    serving 5xx).
    """
    try:
        return fetch_corpus(name)
    except CorpusFetchError:
        return None


@pytest.fixture(scope="session")
def osfi_e23_pdf() -> Path:
    """Cached OSFI E-23 PDF. Skips test if unfetchable."""
    path = _try_fetch("osfi-e23")
    if path is None:
        pytest.skip(
            "OSFI E-23 PDF unavailable (network or pin issue). See "
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
    """Cached EU AI Act PDF (English). Skips test if unfetchable."""
    path = _try_fetch("eu-ai-act")
    if path is None:
        pytest.skip(
            "EU AI Act PDF unavailable (network or pin issue). See "
            "tests/integration/README.md for setup."
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
    """Skips real-LLM tests when ANTHROPIC_API_KEY is not set.

    Real-LLM tests are gated by both the ``real_llm`` marker AND
    presence of an API key. A contributor running
    ``pytest -m real_llm`` without an API key gets a clean skip
    rather than an Anthropic SDK error.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set; skipping real-LLM test.")
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
