"""Tests for the retrieval/corpora.py registry.

This module's purpose is to hold the data structures that describe
fetchable regulation corpora. The fetcher logic lives separately in
``tests/integration/corpora_cache.py``. These tests verify the data
structures themselves: registry shape, CorpusSource immutability,
and that the consumers in ``cli/cmd_corpus.py`` and
``scripts/build_corpus_bundles.py`` can import the registry from the
runtime location.
"""
from __future__ import annotations

import pytest

from retrieval.corpora import CORPUS_REGISTRY, CorpusSource


def test_registry_contains_four_corpora() -> None:
    """The registry has exactly four entries (the framework's named corpora)."""
    expected = {"osfi-e23", "nist-ai-rmf", "eu-ai-act", "sox-pl-107-204"}
    assert set(CORPUS_REGISTRY.keys()) == expected


def test_corpus_source_is_frozen() -> None:
    """CorpusSource is a frozen dataclass; instances are immutable."""
    source = CORPUS_REGISTRY["nist-ai-rmf"]
    with pytest.raises(Exception):
        source.name = "different"  # type: ignore[misc]


def test_every_source_has_required_fields() -> None:
    """Every CorpusSource has name, url, sha256_hex, filename, document_name."""
    for name, source in CORPUS_REGISTRY.items():
        assert isinstance(source, CorpusSource)
        assert source.name == name, (
            f"source.name {source.name!r} != registry key {name!r}"
        )
        assert source.url.startswith("https://"), (
            f"{name}: url should be https; got {source.url!r}"
        )
        assert len(source.sha256_hex) == 64, (
            f"{name}: sha256_hex should be 64 hex chars; "
            f"got {len(source.sha256_hex)}"
        )
        assert source.filename.endswith(".pdf"), (
            f"{name}: filename should end with .pdf; got {source.filename!r}"
        )
        assert source.document_name, (
            f"{name}: document_name should be non-empty"
        )


def test_runtime_location_importable() -> None:
    """retrieval/corpora can be imported without touching tests/."""
    # Re-import to confirm the module is self-contained and doesn't
    # pull in tests.integration.corpora_cache (or its dependencies).
    import sys

    # Drop any cached test-side import
    for mod_name in list(sys.modules.keys()):
        if "corpora_cache" in mod_name:
            del sys.modules[mod_name]

    # The runtime import should succeed on its own
    from retrieval.corpora import CORPUS_REGISTRY as runtime_registry
    assert len(runtime_registry) == 4


def test_backwards_compat_via_tests_integration() -> None:
    """tests.integration.corpora_cache still re-exports the registry.

    Existing test files import CORPUS_REGISTRY from the cache module.
    The cache module re-imports from retrieval.corpora and re-exports
    for backwards compatibility. Confirm the two paths produce the
    same data.
    """
    from tests.integration.corpora_cache import CORPUS_REGISTRY as via_tests
    from retrieval.corpora import CORPUS_REGISTRY as via_runtime
    # Identity, not just equality: it's the same dict object
    assert via_tests is via_runtime


def test_corpus_source_class_identity() -> None:
    """CorpusSource imported from either location is the same class."""
    from tests.integration.corpora_cache import CorpusSource as TestsCS
    from retrieval.corpora import CorpusSource as RuntimeCS
    assert TestsCS is RuntimeCS


def test_cli_consumer_uses_runtime_location() -> None:
    """cli/cmd_corpus._run_list imports CORPUS_REGISTRY from retrieval.corpora.

    This is a regression guard: previously cli/cmd_corpus.py imported
    from tests.integration.corpora_cache, which would break wheel
    installs. The fix moved the import to the runtime location;
    verify here that the import resolves correctly.
    """
    import inspect
    from cli import cmd_corpus

    # Inspect the source to confirm the runtime location is the import target
    source = inspect.getsource(cmd_corpus._run_list)
    assert "from retrieval.corpora import CORPUS_REGISTRY" in source
    assert "from tests.integration" not in source


def test_scripts_consumer_uses_runtime_location() -> None:
    """scripts/build_corpus_bundles.py imports CORPUS_REGISTRY from retrieval.

    fetch_corpus still imports from tests.integration.corpora_cache
    (that's the fetcher logic, not a data structure), but the
    registry itself comes from the runtime location.
    """
    import inspect
    from scripts import build_corpus_bundles

    source = inspect.getsource(build_corpus_bundles)
    assert "from retrieval.corpora import CORPUS_REGISTRY" in source
    # fetch_corpus comes from the tests-side fetcher; that's correct
    assert "from tests.integration.corpora_cache import fetch_corpus" in source
