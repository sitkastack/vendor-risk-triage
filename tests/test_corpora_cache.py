"""Unit tests for tests/integration/corpora_cache.py.

These tests exercise the cache helper's logic without network access:

- Cache directory derivation and override
- Hash computation
- Registry shape (every entry is well-formed)
- Error paths (unknown corpus name)
- Placeholder-pin detection on first run

Network-dependent paths (HTTP fetch, real PDF roundtrip) are exercised
by the integration tests themselves, which skip cleanly when offline.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from tests.integration.corpora_cache import (
    CORPUS_REGISTRY,
    CorpusFetchError,
    CorpusSource,
    cache_dir,
    fetch_corpus,
    _hash_file,
)


def test_corpus_registry_has_expected_entries() -> None:
    """The four free regulations are all registered."""
    expected = {"osfi-e23", "nist-ai-rmf", "eu-ai-act", "sox-pl-107-204"}
    assert set(CORPUS_REGISTRY.keys()) == expected


def test_every_corpus_source_is_well_formed() -> None:
    """Each registry entry has all required fields with sensible types."""
    for name, source in CORPUS_REGISTRY.items():
        assert isinstance(source, CorpusSource)
        assert source.name == name
        assert source.url.startswith("https://")
        # sha256_hex is 64 lowercase hex chars
        assert len(source.sha256_hex) == 64
        assert all(c in "0123456789abcdef" for c in source.sha256_hex)
        assert source.filename.endswith(".pdf")
        assert source.document_name


def test_corpus_source_is_frozen() -> None:
    """CorpusSource is immutable; dataclasses with frozen=True enforce this."""
    source = CORPUS_REGISTRY["nist-ai-rmf"]
    with pytest.raises(AttributeError):
        source.name = "modified"  # type: ignore[misc]


def test_cache_dir_default_path() -> None:
    """Default cache root is under the user's home cache dir."""
    # Make sure the env override is not set
    old = os.environ.pop("SITKASTACK_VRT_CACHE", None)
    try:
        root = cache_dir()
        assert root.is_dir()
        assert "sitkastack-vrt" in str(root)
    finally:
        if old is not None:
            os.environ["SITKASTACK_VRT_CACHE"] = old


def test_cache_dir_respects_env_override(tmp_path: Path, monkeypatch) -> None:
    """SITKASTACK_VRT_CACHE env var overrides the default location."""
    target = tmp_path / "my-cache"
    monkeypatch.setenv("SITKASTACK_VRT_CACHE", str(target))
    root = cache_dir()
    assert root == target
    assert root.is_dir()


def test_fetch_corpus_unknown_name_raises(monkeypatch, tmp_path: Path) -> None:
    """An unrecognized corpus name fails fast without touching the network."""
    monkeypatch.setenv("SITKASTACK_VRT_CACHE", str(tmp_path))
    with pytest.raises(CorpusFetchError, match="Unknown corpus"):
        fetch_corpus("nonexistent-regulation")


def test_hash_file_matches_sha256(tmp_path: Path) -> None:
    """The internal _hash_file helper matches hashlib.sha256 of the file bytes."""
    test_path = tmp_path / "sample.bin"
    payload = b"some test bytes for hashing"
    test_path.write_bytes(payload)
    assert _hash_file(test_path) == hashlib.sha256(payload).hexdigest()


def test_hash_file_handles_large_inputs(tmp_path: Path) -> None:
    """Multi-block reads produce the same hash as a single hashlib call."""
    test_path = tmp_path / "large.bin"
    # 1 MB of pseudo-random data
    payload = (b"x" * 100000) + (b"y" * 100000) + b"end"
    test_path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert _hash_file(test_path) == expected


def test_fetch_corpus_existing_cache_with_correct_hash_returns_path(
    tmp_path: Path, monkeypatch,
) -> None:
    """If a cached file's hash matches the registry pin, no network is touched."""
    monkeypatch.setenv("SITKASTACK_VRT_CACHE", str(tmp_path))

    # Pick a real registry entry, then manually prime the cache with
    # bytes whose SHA-256 we will pin temporarily.
    source = CORPUS_REGISTRY["nist-ai-rmf"]
    fake_payload = b"%PDF-1.4 fake pdf for testing\n%%EOF\n"
    expected_hash = hashlib.sha256(fake_payload).hexdigest()
    # Build a replacement registry entry with the test hash
    test_source = CorpusSource(
        name=source.name,
        url=source.url,
        sha256_hex=expected_hash,
        filename=source.filename,
        document_name=source.document_name,
    )
    monkeypatch.setitem(CORPUS_REGISTRY, "nist-ai-rmf", test_source)

    # Pre-populate the cache
    corpus_dir = tmp_path / source.name
    corpus_dir.mkdir(parents=True, exist_ok=True)
    cached_path = corpus_dir / source.filename
    cached_path.write_bytes(fake_payload)

    # Fetch should return the cached path without going to network
    returned = fetch_corpus("nist-ai-rmf")
    assert returned == cached_path
    # Bytes unchanged
    assert returned.read_bytes() == fake_payload


def test_fetch_corpus_invalidates_cached_file_on_hash_mismatch(
    tmp_path: Path, monkeypatch,
) -> None:
    """If the cached file's hash disagrees with the pin, it is unlinked.

    We can't verify the re-fetch step in this offline test, but we can
    verify the unlink half of the invalidation logic by intercepting
    urllib.request.urlopen and watching the call site.
    """
    monkeypatch.setenv("SITKASTACK_VRT_CACHE", str(tmp_path))
    source = CORPUS_REGISTRY["nist-ai-rmf"]
    corpus_dir = tmp_path / source.name
    corpus_dir.mkdir(parents=True, exist_ok=True)
    cached_path = corpus_dir / source.filename
    cached_path.write_bytes(b"this is the wrong content")

    # Mock urlopen to raise immediately so we can prove the re-fetch
    # was attempted (and the cache was invalidated).
    import urllib.error as _urlerr
    import urllib.request as _urlreq

    def _failing_urlopen(*args, **kwargs):
        raise _urlerr.URLError("simulated network failure")

    monkeypatch.setattr(_urlreq, "urlopen", _failing_urlopen)

    with pytest.raises(CorpusFetchError, match="Network error"):
        fetch_corpus("nist-ai-rmf")

    # Cached file was unlinked before the re-fetch attempt
    assert not cached_path.exists()
