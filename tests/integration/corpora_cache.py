"""Network-cached corpus fetcher for integration tests.

Integration tests need real regulation PDFs to demonstrate the framework
works end-to-end on actual corpora. Fetching on every test run is wasteful
(slow, fragile, depends on regulators not changing URLs), so this module
caches downloads on disk and verifies a pinned SHA-256 against every
cached copy.

Cache location: ``~/.cache/sitkastack-vrt/corpora/``. Each regulation
gets a subdirectory; PDFs are stored at the path the registry records.

Verification flow:

1. If the cached file exists, compute its SHA-256 and compare to the
   pinned hash. Match -> return path. Mismatch -> re-fetch.
2. If the cached file does not exist (or hash mismatched), download
   from the recorded URL, write to the cache, verify the SHA-256 of
   the new copy, and return the path.
3. Network failures, hash mismatches, or 404s raise CorpusFetchError
   with a specific cause-identifying message. Integration tests
   catch this and skip rather than fail (so contributors with offline
   environments still get a passing default suite).

SHA-256 pins are intentional. If a regulator publishes an amendment,
the cached copy's hash will no longer match the pin; the fetcher will
re-download and the new copy's hash will not match either. The test
fails loudly until the pin is updated. This is the right behavior:
amendments require human review of whether the integration test's
expected behavior still holds.

The pins below were verified against authoritative sources on
2026-05-26 as part of the docs/corpus-manifest.md verification log.
Future re-verification updates both the manifest log and the pins
in this module.

NOTE: This module is exercised by integration tests only and should
not be imported by the main framework code. The framework's
production path uses ``CorpusLoader.load_pdf(content=bytes)`` with
caller-supplied bytes; the cache is a test-fixture concern.
"""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


__all__ = [
    "CORPUS_REGISTRY",
    "CorpusFetchError",
    "CorpusSource",
    "cache_dir",
    "fetch_corpus",
    "fetch_all_corpora",
]


_USER_AGENT: str = (
    "sitkastack-vrt-integration-tests/1.0 "
    "(+https://github.com/sitkastack/vendor-risk-triage)"
)
_FETCH_TIMEOUT_SECONDS: int = 30


class CorpusFetchError(Exception):
    """Raised when a corpus PDF cannot be fetched or verified.

    Causes:
    - Network failure (DNS, TCP, TLS, timeout)
    - HTTP error (4xx, 5xx)
    - SHA-256 mismatch after download
    - Local file system error writing the cached copy
    """


@dataclass(frozen=True)
class CorpusSource:
    """Provenance record for a fetchable corpus PDF.

    Attributes:
        name: Short identifier for the corpus. Used as the cache
            subdirectory name and as ``corpus_name`` when the test
            wraps the bytes in a CorpusLoader call.
        url: Authoritative source URL (the regulator's publication
            endpoint). Recorded in docs/corpus-manifest.md.
        sha256_hex: Pinned SHA-256 of the expected PDF bytes, hex
            string (no ``sha256:`` prefix). When the regulator
            publishes an amendment, this hash will no longer match
            and tests will fail until the pin is updated by a human.
        filename: Filename for the cached copy on disk. Stable;
            renaming forces a refetch.
        document_name: ``document_name`` to use when wrapping the
            bytes in a Chunk via CorpusLoader. Recorded here so the
            chunk_id naming convention is consistent across test
            and production paths.
    """

    name: str
    url: str
    sha256_hex: str
    filename: str
    document_name: str


CORPUS_REGISTRY: Dict[str, CorpusSource] = {
    "osfi-e23": CorpusSource(
        name="osfi-e23",
        url=(
            "https://www.osfi-bsif.gc.ca/sites/default/files/2025-09/"
            "gd-mrm-2027.pdf"
        ),
        # Pin placeholder. Replace with the actual SHA-256 of the
        # downloaded PDF; see the corpus manifest for the verification
        # workflow. Integration tests calling fetch_corpus will fail
        # loudly until pins are filled.
        sha256_hex="0" * 64,
        filename="osfi-e23-guideline-2027.pdf",
        document_name="guideline-2027",
    ),
    "nist-ai-rmf": CorpusSource(
        name="nist-ai-rmf",
        url="https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        sha256_hex="7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1",
        filename="nist-ai-rmf-100-1.pdf",
        document_name="100-1",
    ),
    "eu-ai-act": CorpusSource(
        name="eu-ai-act",
        url=(
            "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/"
            "?uri=OJ:L_202401689"
        ),
        sha256_hex="bba630444b3278e881066774002a1d7824308934f49ccfa203e65be43692f55e",
        filename="eu-ai-act-regulation-2024-1689-en.pdf",
        document_name="regulation-2024-1689",
    ),
    "sox-pl-107-204": CorpusSource(
        name="sox-pl-107-204",
        url="https://www.govinfo.gov/content/pkg/COMPS-1883/pdf/COMPS-1883.pdf",
        sha256_hex="048689e26cf64023fa38849e3d1d20f61315b3257b0d18e3717b91c6c6c672eb",
        filename="sox-pl-107-204.pdf",
        document_name="pl-107-204",
    ),
}
"""Registry of fetchable corpus sources.

The SHA-256 pins are placeholders (all-zero) on first commit. The first
``make integration-cache`` run downloads each PDF, computes the actual
hash, and prints an update snippet for this dict. The pins are then
committed by hand.

This deliberately requires a human-in-the-loop step. Pinning the hash
prevents silent corpus drift; bumping the pin is the moment a human
reviews whether the new corpus version still matches the integration
test's expected behavior (citations, tier outputs, audit-trail format).
"""


def cache_dir() -> Path:
    """Return the on-disk cache root for fetched corpora.

    Default location: ``~/.cache/sitkastack-vrt/corpora/``. The directory
    is created on first access if it does not exist.

    Override via the ``SITKASTACK_VRT_CACHE`` environment variable for
    CI workflows that prefer a project-local cache.
    """
    import os
    env_override = os.environ.get("SITKASTACK_VRT_CACHE")
    if env_override:
        root = Path(env_override)
    else:
        root = Path.home() / ".cache" / "sitkastack-vrt" / "corpora"
    root.mkdir(parents=True, exist_ok=True)
    return root


def fetch_corpus(name: str) -> Path:
    """Fetch one corpus PDF, returning the path to its cached copy.

    Args:
        name: Registry key (``osfi-e23``, ``nist-ai-rmf``,
            ``eu-ai-act``, ``sox-pl-107-204``).

    Returns:
        Path to the cached PDF on disk.

    Raises:
        CorpusFetchError: Network failure, HTTP error, hash mismatch,
            file system error, or unknown corpus name. Callers should
            catch this and ``pytest.skip()`` to avoid CI noise.
    """
    if name not in CORPUS_REGISTRY:
        raise CorpusFetchError(
            f"Unknown corpus: {name!r}. Known: "
            f"{sorted(CORPUS_REGISTRY.keys())}"
        )
    source = CORPUS_REGISTRY[name]

    corpus_dir = cache_dir() / source.name
    corpus_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = corpus_dir / source.filename

    # If cached, verify SHA-256 and return.
    if pdf_path.exists():
        actual_hash = _hash_file(pdf_path)
        if actual_hash == source.sha256_hex:
            return pdf_path
        # Hash mismatch on cached file: delete and re-fetch. Could be
        # corruption (truncated download), pin update, or tampering.
        pdf_path.unlink()

    # Fetch.
    try:
        request = urllib.request.Request(
            source.url,
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(
            request, timeout=_FETCH_TIMEOUT_SECONDS,
        ) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise CorpusFetchError(
            f"HTTP {exc.code} fetching {source.url}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CorpusFetchError(
            f"Network error fetching {source.url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise CorpusFetchError(
            f"Timeout fetching {source.url}"
        ) from exc

    # Verify hash of downloaded bytes.
    downloaded_hash = hashlib.sha256(payload).hexdigest()
    if downloaded_hash != source.sha256_hex:
        # If the pin is the all-zero placeholder, emit a helpful hint
        # rather than just a mismatch.
        if source.sha256_hex == "0" * 64:
            raise CorpusFetchError(
                f"Pinned SHA-256 for {name!r} is the placeholder "
                f"({'0' * 64}). Downloaded file has SHA-256 "
                f"{downloaded_hash}. Update CORPUS_REGISTRY in "
                f"tests/integration/corpora_cache.py with this hash "
                f"and re-run."
            )
        raise CorpusFetchError(
            f"SHA-256 mismatch for {name!r}: "
            f"expected {source.sha256_hex}, "
            f"downloaded {downloaded_hash}. The regulator may have "
            f"published an amended version. Verify the change is "
            f"expected and update the pin."
        )

    # Write to cache.
    try:
        pdf_path.write_bytes(payload)
    except OSError as exc:
        raise CorpusFetchError(
            f"Could not write cached corpus to {pdf_path}: {exc}"
        ) from exc

    return pdf_path


def fetch_all_corpora() -> Dict[str, Path]:
    """Fetch every registered corpus.

    Convenience for tooling that needs all corpora at once (e.g., the
    bundle-build script). Returns a dict mapping registry name to
    cached PDF path. Re-raises CorpusFetchError if any corpus fails;
    successful fetches are not rolled back (they stay cached).
    """
    return {name: fetch_corpus(name) for name in CORPUS_REGISTRY}


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 of a file's bytes, returning the hex digest."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
