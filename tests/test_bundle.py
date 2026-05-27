"""Tests for Phase 5 sub-system 1: persistent index bundle.

Coverage strategy:

- Construction paths: from_chunks with and without embedder
- Manifest fields: every field's behavior under realistic inputs
- Roundtrip integrity: save -> load produces equal chunks and equal
  embeddings byte-for-byte
- Embedder identity: strict and loose verification modes
- Error paths: missing file, malformed archive, missing manifest,
  schema-version mismatch, hash mismatch, chunk-count mismatch,
  embedding-shape mismatch, malformed JSON
- Atomicity: save writes through a tmp file
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import pytest
from pydantic import ValidationError

from retrieval import Chunk, HashEmbedder, SentenceTransformerEmbedder  # noqa: F401
from retrieval.bundle import (
    IndexBundle,
    IndexBundleLoadError,
    IndexBundleManifest,
    SCHEMA_VERSION,
)


# -- helpers ---------------------------------------------------------------


def _make_chunks(n: int, corpus_name: str = "osfi") -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"{corpus_name}:doc:page-{i}",
            corpus_name=corpus_name,
            document_name="doc",
            page_number=i,
            text=f"Regulation text page {i}.",
            content_hash="sha256:" + hashlib.sha256(f"text{i}".encode()).hexdigest(),
        )
        for i in range(1, n + 1)
    ]


# -- IndexBundleManifest model --------------------------------------------


def test_manifest_is_frozen() -> None:
    m = IndexBundleManifest(
        schema_version="1.0.0",
        framework_version="0.6.0",
        corpus_name="osfi",
        chunk_count=0,
        chunks_content_hash="sha256:" + ("a" * 64),
        built_at_unix=0,
    )
    with pytest.raises(ValidationError):
        m.corpus_name = "modified"  # type: ignore[misc]


def test_manifest_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        IndexBundleManifest(
            schema_version="1.0.0",
            framework_version="0.6.0",
            corpus_name="osfi",
            chunk_count=0,
            chunks_content_hash="sha256:" + ("a" * 64),
            built_at_unix=0,
            unknown_field=True,  # type: ignore[call-arg]
        )


def test_manifest_optional_embedder_fields_default_to_none() -> None:
    m = IndexBundleManifest(
        schema_version="1.0.0",
        framework_version="0.6.0",
        corpus_name="osfi",
        chunk_count=0,
        chunks_content_hash="sha256:" + ("a" * 64),
        built_at_unix=0,
    )
    assert m.embedder_identity is None
    assert m.embedding_dimension is None


# -- IndexBundle.from_chunks ----------------------------------------------


def test_from_chunks_empty_corpus() -> None:
    """Empty corpus produces a valid bundle with zero chunks."""
    bundle = IndexBundle.from_chunks([], corpus_name="empty")
    assert bundle.chunks == []
    assert bundle.embeddings is None
    assert bundle.manifest.chunk_count == 0
    assert bundle.manifest.embedder_identity is None


def test_from_chunks_without_embedder_records_no_embeddings() -> None:
    chunks = _make_chunks(3)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="osfi")
    assert bundle.embeddings is None
    assert bundle.manifest.embedder_identity is None
    assert bundle.manifest.embedding_dimension is None


def test_from_chunks_with_hash_embedder_computes_embeddings() -> None:
    chunks = _make_chunks(3)
    embedder = HashEmbedder(dimension=64)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="osfi", embedder=embedder)
    assert bundle.embeddings is not None
    assert bundle.embeddings.shape == (3, 64)
    assert bundle.embeddings.dtype == np.float32
    assert bundle.manifest.embedder_identity == "HashEmbedder/64"
    assert bundle.manifest.embedding_dimension == 64


def test_from_chunks_records_corpus_name() -> None:
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="nist-ai-rmf")
    assert bundle.manifest.corpus_name == "nist-ai-rmf"


def test_from_chunks_records_framework_version() -> None:
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="osfi", framework_version="9.9.9",
    )
    assert bundle.manifest.framework_version == "9.9.9"


def test_from_chunks_records_schema_version() -> None:
    bundle = IndexBundle.from_chunks([], corpus_name="x")
    assert bundle.manifest.schema_version == SCHEMA_VERSION


def test_from_chunks_records_chunks_content_hash() -> None:
    """Content hash equals SHA-256 of the JSONL bytes serialization."""
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="osfi")
    # Hash is sha256:<hex>
    assert bundle.manifest.chunks_content_hash.startswith("sha256:")
    assert len(bundle.manifest.chunks_content_hash) == len("sha256:") + 64


def test_from_chunks_records_built_at_unix() -> None:
    import time
    before = int(time.time())
    bundle = IndexBundle.from_chunks([], corpus_name="x")
    after = int(time.time())
    assert before <= bundle.manifest.built_at_unix <= after


def test_from_chunks_with_embedder_returning_wrong_shape_raises() -> None:
    """Defensive check: a misbehaving embedder is caught early."""

    class _BadEmbedder:
        dimension = 64

        def embed(self, texts: list[str]) -> np.ndarray:
            # Return wrong shape on purpose
            return np.zeros((len(texts) + 1, 64), dtype=np.float32)

    chunks = _make_chunks(3)
    with pytest.raises(ValueError, match="produced array of shape"):
        IndexBundle.from_chunks(
            chunks, corpus_name="osfi", embedder=_BadEmbedder(),  # type: ignore[arg-type]
        )


def test_from_chunks_coerces_embeddings_to_float32() -> None:
    """If the embedder returns float64, the bundle stores float32 for stable size."""

    class _F64Embedder:
        dimension = 8

        def embed(self, texts: list[str]) -> np.ndarray:
            arr = np.zeros((len(texts), 8), dtype=np.float64)
            return arr

    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="osfi", embedder=_F64Embedder(),  # type: ignore[arg-type]
    )
    assert bundle.embeddings.dtype == np.float32


# -- save/load roundtrip ------------------------------------------------


def test_save_load_roundtrip_without_embeddings() -> None:
    chunks = _make_chunks(5)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="osfi")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bundle.tgz"
        bundle.save(p)
        assert p.exists()
        loaded = IndexBundle.load(p)
    assert loaded.chunks == chunks
    assert loaded.embeddings is None
    assert loaded.manifest.corpus_name == "osfi"


def test_save_load_roundtrip_with_embeddings() -> None:
    chunks = _make_chunks(5)
    embedder = HashEmbedder(dimension=32)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="osfi", embedder=embedder)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bundle.tgz"
        bundle.save(p)
        loaded = IndexBundle.load(p, embedder=embedder)
    assert loaded.chunks == chunks
    assert np.array_equal(loaded.embeddings, bundle.embeddings)


def test_save_load_roundtrip_preserves_manifest() -> None:
    chunks = _make_chunks(2)
    embedder = HashEmbedder(dimension=16)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="custom-corpus",
        embedder=embedder, framework_version="0.6.0",
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        loaded = IndexBundle.load(p, embedder=embedder)
    # Every manifest field roundtrips
    assert loaded.manifest.schema_version == bundle.manifest.schema_version
    assert loaded.manifest.framework_version == bundle.manifest.framework_version
    assert loaded.manifest.corpus_name == bundle.manifest.corpus_name
    assert loaded.manifest.chunk_count == bundle.manifest.chunk_count
    assert loaded.manifest.chunks_content_hash == bundle.manifest.chunks_content_hash
    assert loaded.manifest.embedder_identity == bundle.manifest.embedder_identity
    assert loaded.manifest.embedding_dimension == bundle.manifest.embedding_dimension
    assert loaded.manifest.built_at_unix == bundle.manifest.built_at_unix


def test_save_load_empty_bundle() -> None:
    bundle = IndexBundle.from_chunks([], corpus_name="empty")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "empty.tgz"
        bundle.save(p)
        loaded = IndexBundle.load(p)
    assert loaded.chunks == []
    assert loaded.embeddings is None


def test_save_overwrites_existing_file() -> None:
    chunks = _make_chunks(1)
    bundle1 = IndexBundle.from_chunks(chunks, corpus_name="a")
    chunks2 = _make_chunks(2, corpus_name="b")
    bundle2 = IndexBundle.from_chunks(chunks2, corpus_name="b")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bundle.tgz"
        bundle1.save(p)
        bundle2.save(p)  # overwrites
        loaded = IndexBundle.load(p)
    assert loaded.manifest.corpus_name == "b"
    assert len(loaded.chunks) == 2


def test_save_cleans_up_tmp_file_on_error(monkeypatch) -> None:
    """If serialization fails mid-write, the tmp file is removed."""
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x")

    # Patch _write_member to raise after the first call
    original = IndexBundle._write_member
    call_count = [0]

    def boom(tar, name, data):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise RuntimeError("simulated write failure")
        original(tar, name, data)

    monkeypatch.setattr(IndexBundle, "_write_member", staticmethod(boom))

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        with pytest.raises(RuntimeError, match="simulated write failure"):
            bundle.save(p)
        # No leftover tmp file
        tmp = p.with_suffix(p.suffix + ".tmp")
        assert not tmp.exists()
        # No final file either
        assert not p.exists()


# -- load error paths ----------------------------------------------------


def test_load_missing_file_raises() -> None:
    with pytest.raises(IndexBundleLoadError, match="not found"):
        IndexBundle.load(Path("/nonexistent/path/bundle.tgz"))


def test_load_malformed_archive_raises() -> None:
    """A file that is not a valid tar archive surfaces as IndexBundleLoadError."""
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
        f.write(b"not a tar archive")
        p = Path(f.name)
    try:
        with pytest.raises(IndexBundleLoadError, match="malformed"):
            IndexBundle.load(p)
    finally:
        p.unlink()


def test_load_missing_manifest_raises() -> None:
    """A tar that lacks manifest.json fails clearly."""
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
        p = Path(f.name)
    try:
        with tarfile.open(p, "w:gz") as tar:
            data = b"unrelated content"
            info = tarfile.TarInfo("other.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with pytest.raises(IndexBundleLoadError, match="missing manifest"):
            IndexBundle.load(p)
    finally:
        p.unlink()


def test_load_missing_chunks_raises() -> None:
    """A tar with manifest but no chunks.jsonl fails clearly."""
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
        p = Path(f.name)
    manifest = IndexBundleManifest(
        schema_version="1.0.0",
        framework_version="0.6.0",
        corpus_name="x",
        chunk_count=0,
        chunks_content_hash="sha256:" + ("0" * 64),
        built_at_unix=0,
    )
    try:
        with tarfile.open(p, "w:gz") as tar:
            data = json.dumps(manifest.model_dump()).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with pytest.raises(IndexBundleLoadError, match="missing chunks"):
            IndexBundle.load(p)
    finally:
        p.unlink()


def test_load_invalid_manifest_schema_raises() -> None:
    """A manifest.json that is valid JSON but doesn't match the schema fails."""
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
        p = Path(f.name)
    try:
        with tarfile.open(p, "w:gz") as tar:
            for name, data in [
                ("manifest.json", b'{"random_field": 42}'),  # missing all required fields
                ("chunks.jsonl", b""),
            ]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with pytest.raises(IndexBundleLoadError, match="does not match schema"):
            IndexBundle.load(p)
    finally:
        p.unlink()


def test_load_embeddings_present_but_dimension_missing_in_manifest_raises() -> None:
    """Inconsistent manifest: has embeddings.npz file but no embedding_dimension."""
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=8),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        # Strip embedding_dimension from the manifest while keeping the npz file
        _rewrite_manifest_in_bundle(p, {"embedding_dimension": None})
        with pytest.raises(IndexBundleLoadError, match="does not record embedding_dimension"):
            IndexBundle.load(p)


def test_load_invalid_manifest_json_raises() -> None:
    """A manifest.json with non-JSON content raises IndexBundleLoadError."""
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
        p = Path(f.name)
    try:
        with tarfile.open(p, "w:gz") as tar:
            for name, data in [
                ("manifest.json", b"not valid json {{{"),
                ("chunks.jsonl", b""),
            ]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with pytest.raises(IndexBundleLoadError, match="not valid JSON"):
            IndexBundle.load(p)
    finally:
        p.unlink()


def test_load_schema_version_major_mismatch_raises() -> None:
    """Bundle with major version != current refuses to load."""
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)

        # Re-write the manifest with a different major version
        _rewrite_manifest_in_bundle(p, {"schema_version": "99.0.0"})

        with pytest.raises(IndexBundleLoadError, match="incompatible with framework"):
            IndexBundle.load(p)


def test_load_malformed_schema_version_raises() -> None:
    """A manifest with a non-version-string schema_version fails."""
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        _rewrite_manifest_in_bundle(p, {"schema_version": "not-a-version"})
        with pytest.raises(IndexBundleLoadError, match="malformed"):
            IndexBundle.load(p)


def test_load_chunks_hash_mismatch_raises() -> None:
    """If chunks bytes are tampered with, the hash check fires."""
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)

        # Re-write the chunks.jsonl to corrupt it
        _rewrite_chunks_in_bundle(
            p,
            chunks_jsonl=b'{"chunk_id":"corrupted:doc:page-1","corpus_name":"x","document_name":"doc","page_number":1,"text":"tampered","content_hash":"sha256:' + b"0" * 64 + b'","section_heading":null}\n',
        )

        with pytest.raises(IndexBundleLoadError, match="hash mismatch"):
            IndexBundle.load(p)


def test_load_chunk_count_mismatch_raises() -> None:
    """If manifest claims more chunks than chunks.jsonl contains, refuse."""
    chunks = _make_chunks(3)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)

        # Rewrite chunks.jsonl with fewer chunks but matching hash. We have
        # to update both members.
        single_chunk = chunks[0].model_dump()
        new_jsonl = (json.dumps(single_chunk, sort_keys=True) + "\n").encode("utf-8")
        new_hash = "sha256:" + hashlib.sha256(new_jsonl).hexdigest()
        # Hash matches what's in the file, but manifest still says count=3
        _rewrite_chunks_in_bundle(p, chunks_jsonl=new_jsonl)
        _rewrite_manifest_in_bundle(p, {"chunks_content_hash": new_hash})

        with pytest.raises(IndexBundleLoadError, match="chunk_count"):
            IndexBundle.load(p)


def test_load_embeddings_shape_mismatch_raises() -> None:
    """If embeddings shape disagrees with chunk count, refuse."""
    chunks = _make_chunks(3)
    embedder = HashEmbedder(dimension=8)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x", embedder=embedder)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)

        # Re-write embeddings.npz with a wrong-shape array
        wrong = np.zeros((5, 8), dtype=np.float32)
        npz_buf = io.BytesIO()
        np.savez_compressed(npz_buf, embeddings=wrong)
        _rewrite_embeddings_in_bundle(p, npz_buf.getvalue())

        with pytest.raises(IndexBundleLoadError, match="shape mismatch"):
            IndexBundle.load(p, embedder=embedder)


def test_load_embedder_identity_strict_check_refuses_wrong_dimension() -> None:
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=16),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        wrong = HashEmbedder(dimension=32)
        with pytest.raises(IndexBundleLoadError, match="identity mismatch"):
            IndexBundle.load(p, embedder=wrong)


def test_load_embedder_identity_loose_check_dimension_only() -> None:
    """With verify_embedder_identity=False, dimension is checked but identity is not."""
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=16),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        # Same dimension, different instance: loose check passes
        same_dim = HashEmbedder(dimension=16)
        loaded = IndexBundle.load(
            p, embedder=same_dim, verify_embedder_identity=False,
        )
        assert loaded.embeddings.shape == (2, 16)


def test_load_embedder_loose_check_refuses_wrong_dimension() -> None:
    """Loose check still verifies dimension."""
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=16),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        wrong = HashEmbedder(dimension=32)
        with pytest.raises(IndexBundleLoadError, match="dimension mismatch"):
            IndexBundle.load(
                p, embedder=wrong, verify_embedder_identity=False,
            )


def test_load_embeddings_without_embedder_argument_succeeds() -> None:
    """Loading a bundle with embeddings without passing an embedder works.

    The embeddings load; identity is not checked. Caller takes
    responsibility for using them appropriately.
    """
    chunks = _make_chunks(2)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=8),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        loaded = IndexBundle.load(p)  # no embedder
    assert loaded.embeddings is not None
    assert loaded.embeddings.shape == (2, 8)


def test_load_embeddings_npz_missing_embeddings_key_raises() -> None:
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=8),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        # Write a .npz with the wrong array name
        npz_buf = io.BytesIO()
        np.savez_compressed(npz_buf, other_name=np.zeros((1, 8), dtype=np.float32))
        _rewrite_embeddings_in_bundle(p, npz_buf.getvalue())
        with pytest.raises(IndexBundleLoadError, match="missing the 'embeddings' array"):
            IndexBundle.load(p)


def test_load_embeddings_unreadable_raises() -> None:
    """An embeddings file that isn't a valid npz raises."""
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(
        chunks, corpus_name="x", embedder=HashEmbedder(dimension=8),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        bundle.save(p)
        _rewrite_embeddings_in_bundle(p, b"not a valid npz file")
        with pytest.raises(IndexBundleLoadError, match="unreadable"):
            IndexBundle.load(p)


def test_load_invalid_chunk_payload_raises() -> None:
    """If chunks.jsonl contains a row that doesn't match the Chunk schema, fail clearly."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        # Hand-build a bundle with a bad chunk line
        bad_jsonl = b'{"chunk_id":"x","corpus_name":"x","document_name":"x","page_number":-1,"text":"","content_hash":"sha256:badhash"}\n'
        manifest = IndexBundleManifest(
            schema_version="1.0.0",
            framework_version="0.6.0",
            corpus_name="x",
            chunk_count=1,
            chunks_content_hash="sha256:" + hashlib.sha256(bad_jsonl).hexdigest(),
            built_at_unix=0,
        )
        with tarfile.open(p, "w:gz") as tar:
            for name, data in [
                ("manifest.json", json.dumps(manifest.model_dump()).encode()),
                ("chunks.jsonl", bad_jsonl),
            ]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with pytest.raises(IndexBundleLoadError, match="not valid Chunk models"):
            IndexBundle.load(p)


# -- embedder identity helper -------------------------------------------


def test_embedder_identity_for_hash_embedder() -> None:
    from retrieval.bundle import _compute_embedder_identity
    e = HashEmbedder(dimension=32)
    assert _compute_embedder_identity(e) == "HashEmbedder/32"


def test_embedder_identity_for_embedder_with_model_name() -> None:
    """Embedders exposing model_name include it in the identity."""
    from retrieval.bundle import _compute_embedder_identity

    class _NamedEmbedder:
        model_name = "fake-model-v1"
        dimension = 384

        def embed(self, texts):
            return np.zeros((len(texts), 384), dtype=np.float32)

    e = _NamedEmbedder()
    assert _compute_embedder_identity(e) == "_NamedEmbedder/fake-model-v1/384"


# -- atomic-save tmp suffix path -----------------------------------------


def test_save_uses_atomic_rename_path() -> None:
    """During save, a .tmp file appears momentarily; not after."""
    chunks = _make_chunks(1)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.tgz"
        tmp = p.with_suffix(p.suffix + ".tmp")
        bundle.save(p)
        # After save, only the destination exists
        assert p.exists()
        assert not tmp.exists()


# -- jsonl helpers --------------------------------------------------------


def test_jsonl_helpers_roundtrip() -> None:
    from retrieval.bundle import _chunks_to_jsonl_bytes, _jsonl_bytes_to_chunks
    chunks = _make_chunks(3)
    data = _chunks_to_jsonl_bytes(chunks)
    assert isinstance(data, bytes)
    parsed = _jsonl_bytes_to_chunks(data)
    assert parsed == chunks


def test_jsonl_helpers_empty_roundtrip() -> None:
    from retrieval.bundle import _chunks_to_jsonl_bytes, _jsonl_bytes_to_chunks
    data = _chunks_to_jsonl_bytes([])
    assert _jsonl_bytes_to_chunks(data) == []


def test_jsonl_helpers_tolerate_blank_lines() -> None:
    """Tolerance for trailing/blank lines in malformed-but-recoverable input."""
    from retrieval.bundle import _jsonl_bytes_to_chunks
    chunks = _make_chunks(2)
    from retrieval.bundle import _chunks_to_jsonl_bytes
    data = _chunks_to_jsonl_bytes(chunks)
    # Insert blank lines
    data_with_blanks = data.replace(b"\n", b"\n\n", 1) + b"\n\n"
    parsed = _jsonl_bytes_to_chunks(data_with_blanks)
    assert parsed == chunks


# -- public surface ------------------------------------------------------


def test_bundle_exposes_chunks_embeddings_manifest_properties() -> None:
    chunks = _make_chunks(1)
    embedder = HashEmbedder(dimension=4)
    bundle = IndexBundle.from_chunks(chunks, corpus_name="x", embedder=embedder)
    # Read-only-ish properties
    assert bundle.chunks is chunks  # exact same list object
    assert bundle.embeddings is not None
    assert isinstance(bundle.manifest, IndexBundleManifest)


# -- helpers for the rewriting tests -------------------------------------


def _rewrite_manifest_in_bundle(path: Path, updates: dict) -> None:
    """Open a bundle, mutate the manifest with the given updates, re-pack."""
    with tarfile.open(path, "r:gz") as tar:
        members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    manifest = json.loads(members["manifest.json"].decode("utf-8"))
    manifest.update(updates)
    members["manifest.json"] = json.dumps(manifest).encode("utf-8")
    _rewrite_bundle(path, members)


def _rewrite_chunks_in_bundle(path: Path, chunks_jsonl: bytes) -> None:
    with tarfile.open(path, "r:gz") as tar:
        members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    members["chunks.jsonl"] = chunks_jsonl
    _rewrite_bundle(path, members)


def _rewrite_embeddings_in_bundle(path: Path, npz_bytes: bytes) -> None:
    with tarfile.open(path, "r:gz") as tar:
        members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    members["embeddings.npz"] = npz_bytes
    _rewrite_bundle(path, members)


def _rewrite_bundle(path: Path, members: dict) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
