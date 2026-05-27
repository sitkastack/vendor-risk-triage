"""Persistent index format for retrieval corpora.

The default ``BM25Index`` and ``VectorIndex`` are built from a fresh
chunk list on every process start. For a small corpus (one regulation,
~50 pages) this is sub-second. For the framework's full target corpus
(OSFI E-23 + NIST AI RMF + EU AI Act + ISO 42001 + SOX/AS 2201, ~600
pages with section-aware chunking) the BM25 build is still fast but the
vector embedding step takes ~30 seconds with the default sentence-
transformers model. Production deployments cold-start frequently
enough that re-embedding on every start is wasteful.

``IndexBundle`` is the on-disk format that solves this. It bundles:

- The Chunks (JSONL), so the BM25 index can be rebuilt instantly.
- The pre-computed embeddings (NumPy .npz), so the vector index can be
  reconstructed without re-running the embedder.
- A manifest (JSON) recording framework version, schema version,
  build timestamp, source corpus identifier, chunk count, embedder
  identity, and the content_hash of the bundled chunks.

The three components are packaged in a single .tar.gz file. Audit
benefits:

- One artifact, one SHA-256 to verify and ship to a SIEM.
- Inspect-able: ``tar -tzvf bundle.tgz`` lists contents; everything
  inside is plain text or a NumPy .npz that can be loaded standalone.
- Diffable manifest: an auditor reviewing two bundle versions sees a
  clear JSON diff of what changed.

Trust-and-verify on load:

- Schema version is checked against the current schema version. Bundles
  produced by an incompatible major version are refused with a clear
  error pointing at the schema-migration story (Phase 7).
- Embedder identity is recorded as ``{type_name}/{dimension}`` and,
  when the embedder exposes a ``model_name`` attribute (the
  SentenceTransformerEmbedder case), as
  ``{type_name}/{model_name}/{dimension}``. Bundles with mismatched
  embedder identity are refused at load time unless the caller
  explicitly opts in to dimension-only verification.

Deferred:

- [deferred-phase-7] Schema migration (write a one-time converter when
  the first migration is actually needed, not speculatively)
- [deferred-phase-6] CLI command ``sitkastack bundle build`` and
  ``sitkastack bundle load`` for one-line corpus operations
- [deferred-phase-5-later] Embedding compression (the .npz format
  already stores float32; a fp16 variant would halve disk size for a
  small recall trade-off; revisit if disk becomes a constraint)
- [deferred-phase-5-later] Differential updates (rebuild only changed
  chunks; the framework's immutable-corpus posture makes this low
  priority but it would help large corpora that update incrementally)
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from retrieval.chunk import Chunk
from retrieval.embeddings import Embedder


__all__ = [
    "IndexBundle",
    "IndexBundleManifest",
    "IndexBundleLoadError",
    "SCHEMA_VERSION",
]


SCHEMA_VERSION: str = "1.0.0"
"""Bundle file format schema version. Bumped on any breaking change
to the manifest fields, the file layout, or the embedding encoding.

Loaders refuse bundles with incompatible major versions and direct
callers to the schema-migration tools (Phase 7 deliverable).
"""


# File names inside the tar archive. Stable; renaming these is a
# breaking schema change.
_MANIFEST_FILENAME = "manifest.json"
_CHUNKS_FILENAME = "chunks.jsonl"
_EMBEDDINGS_FILENAME = "embeddings.npz"


class IndexBundleLoadError(Exception):
    """Raised when an IndexBundle file cannot be loaded.

    Causes include:

    - File not found or unreadable
    - Tar archive is malformed
    - Manifest is missing or unparseable
    - Schema version is incompatible
    - Embedded chunks are not valid Pydantic Chunk models
    - Embeddings file is present but shape disagrees with the chunk
      count or manifest-recorded dimension
    - Embedder identity check fails (and the caller did not opt in to
      dimension-only verification)
    """


class IndexBundleManifest(BaseModel):
    """Recorded provenance and shape for an IndexBundle.

    The manifest travels inside the bundle as ``manifest.json`` and is
    the first thing a loader reads. It serves three audiences:

    - The framework loader, which verifies compatibility before
      attempting to materialize chunks or embeddings.
    - An auditor reviewing what a bundle contains, who reads the
      manifest as a human-readable summary of the build.
    - A future migration tool, which reads the schema_version field
      to decide what conversion (if any) is needed.

    Attributes:
        schema_version: Bundle format schema version, ``MAJOR.MINOR.PATCH``.
            Loaders check the major version.
        framework_version: ``FRAMEWORK_VERSION`` of the sitkastack
            framework that built this bundle. Recorded for audit; not
            used to gate loading.
        corpus_name: The corpus identifier passed to ``IndexBundle.from_chunks``.
            Audit-readable: ``osfi-e23``, ``nist-ai-rmf``, etc.
        chunk_count: Number of chunks in the bundle. Verified against
            the actual chunks.jsonl content at load time.
        chunks_content_hash: SHA-256 of the chunks.jsonl bytes,
            formatted ``sha256:<hex>``. An auditor verifies bundle
            integrity by re-hashing the chunks.jsonl extracted from
            the tar and comparing.
        embedder_identity: Identifier string for the embedder that
            produced the bundled embeddings, or ``None`` if no
            embeddings are bundled. Format:
            ``{type_name}/{model_name}/{dimension}`` when the embedder
            exposes model_name, else ``{type_name}/{dimension}``.
        embedding_dimension: Dimension D of the embeddings, or ``None``
            if no embeddings are bundled.
        built_at_unix: UNIX timestamp (seconds since epoch) when the
            bundle was built. Audit-defensibility marker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    framework_version: str = Field(min_length=1)
    corpus_name: str = Field(min_length=1, max_length=64)
    chunk_count: int = Field(ge=0)
    chunks_content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    embedder_identity: Optional[str] = Field(default=None, max_length=256)
    embedding_dimension: Optional[int] = Field(default=None, ge=1)
    built_at_unix: int = Field(ge=0)


class IndexBundle:
    """A persistent, file-backed collection of Chunks and embeddings.

    Two construction paths:

    - ``IndexBundle.from_chunks(chunks, corpus_name, embedder=...)``:
      build from in-memory chunks, optionally computing embeddings.
    - ``IndexBundle.load(path)``: load from a previously-saved bundle
      file.

    Two read accessors:

    - ``bundle.chunks``: the list of Chunks.
    - ``bundle.embeddings``: the (N, D) NumPy array, or ``None`` if no
      embeddings were bundled.

    One write method:

    - ``bundle.save(path)``: write the bundle as a tar.gz file.

    The manifest is exposed as ``bundle.manifest`` for audit/inspection.

    Bundles are immutable from the consumer's perspective. The internal
    chunks list is the same Python object that was passed to
    ``from_chunks``; callers should not mutate it after construction.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        manifest: IndexBundleManifest,
        embeddings: Optional[np.ndarray] = None,
    ) -> None:
        """Direct construction. Callers normally use ``from_chunks`` or ``load``.

        Args:
            chunks: The chunks the bundle wraps.
            manifest: The manifest describing the bundle's provenance
                and shape. Must agree with the chunks and embeddings
                arguments; consistency is the caller's responsibility
                at this entry point. The classmethod constructors
                guarantee consistency.
            embeddings: Optional (N, D) NumPy array, one row per chunk
                in the same order. None means embeddings were not
                bundled.
        """
        self._chunks = chunks
        self._manifest = manifest
        self._embeddings = embeddings

    @property
    def chunks(self) -> list[Chunk]:
        """The chunks in the bundle, in bundle order."""
        return self._chunks

    @property
    def embeddings(self) -> Optional[np.ndarray]:
        """The (N, D) embeddings array, or None if not bundled."""
        return self._embeddings

    @property
    def manifest(self) -> IndexBundleManifest:
        """The manifest recording provenance and shape."""
        return self._manifest

    @classmethod
    def from_chunks(
        cls,
        chunks: list[Chunk],
        corpus_name: str,
        embedder: Optional[Embedder] = None,
        framework_version: str = "0.6.0",
    ) -> "IndexBundle":
        """Build a bundle from in-memory chunks.

        Args:
            chunks: The chunks to bundle. May be empty (produces an
                empty-corpus bundle, useful for testing).
            corpus_name: Short identifier for the corpus, recorded on
                the manifest. Should match the ``corpus_name`` field of
                the chunks; not enforced here (callers building
                multi-corpus bundles know what they are doing).
            embedder: Optional Embedder. When supplied, the bundle
                computes and stores embeddings for every chunk's text.
                When None, the bundle stores chunks only and the
                manifest records ``embedder_identity=None``.
            framework_version: The framework version to record on the
                manifest. Default matches the current pinned version;
                callers from CI/release pipelines should pass the
                actual version explicitly.

        Returns:
            A new IndexBundle. The embeddings array (if any) is a
            float32 (N, D) NumPy array in the same row order as
            ``chunks``.
        """
        # Compute the chunks-portion content hash. Hashing the
        # serialized JSONL form (rather than the Chunk model dict) lets
        # the manifest's recorded hash be reproduced by re-hashing the
        # chunks.jsonl bytes extracted from a saved bundle.
        jsonl_bytes = _chunks_to_jsonl_bytes(chunks)
        chunks_hash = "sha256:" + hashlib.sha256(jsonl_bytes).hexdigest()

        embeddings: Optional[np.ndarray] = None
        embedder_identity: Optional[str] = None
        embedding_dimension: Optional[int] = None
        if embedder is not None:
            texts = [c.text for c in chunks]
            embeddings = embedder.embed(texts)
            if embeddings.shape != (len(chunks), embedder.dimension):
                raise ValueError(
                    f"Embedder produced array of shape {embeddings.shape} "
                    f"for {len(chunks)} chunks; expected "
                    f"({len(chunks)}, {embedder.dimension})."
                )
            # Force float32 for stable on-disk size and dtype.
            if embeddings.dtype != np.float32:
                embeddings = embeddings.astype(np.float32)
            embedder_identity = _compute_embedder_identity(embedder)
            embedding_dimension = embedder.dimension

        manifest = IndexBundleManifest(
            schema_version=SCHEMA_VERSION,
            framework_version=framework_version,
            corpus_name=corpus_name,
            chunk_count=len(chunks),
            chunks_content_hash=chunks_hash,
            embedder_identity=embedder_identity,
            embedding_dimension=embedding_dimension,
            built_at_unix=int(time.time()),
        )
        return cls(chunks=chunks, manifest=manifest, embeddings=embeddings)

    @classmethod
    def load(
        cls,
        path: Path,
        embedder: Optional[Embedder] = None,
        verify_embedder_identity: bool = True,
    ) -> "IndexBundle":
        """Load a bundle from a previously-saved tar.gz file.

        Args:
            path: Path to the bundle file.
            embedder: Optional Embedder used to verify identity. When
                the bundle contains embeddings and ``verify_embedder_identity``
                is True, the embedder's computed identity must match
                the manifest's recorded ``embedder_identity``; otherwise
                IndexBundleLoadError is raised. When the bundle contains
                no embeddings, the embedder argument is ignored.
            verify_embedder_identity: When True (the default), enforce
                strict identity match between the load-time embedder
                and the bundle-time embedder. When False, only the
                embedding dimension is checked (looser; suitable when
                the caller intentionally swapped to a compatible
                embedder).

        Returns:
            A fully materialized IndexBundle with chunks, embeddings
            (if present), and manifest.

        Raises:
            IndexBundleLoadError: For any failure category listed on
                the exception class itself.
        """
        if not path.exists():
            raise IndexBundleLoadError(f"Bundle file not found: {path}")

        try:
            with tarfile.open(path, mode="r:gz") as tar:
                manifest_bytes = _safe_extract(tar, _MANIFEST_FILENAME)
                if manifest_bytes is None:
                    raise IndexBundleLoadError(
                        f"Bundle is missing {_MANIFEST_FILENAME}"
                    )
                chunks_bytes = _safe_extract(tar, _CHUNKS_FILENAME)
                if chunks_bytes is None:
                    raise IndexBundleLoadError(
                        f"Bundle is missing {_CHUNKS_FILENAME}"
                    )
                embeddings_bytes = _safe_extract(tar, _EMBEDDINGS_FILENAME)
        except tarfile.TarError as exc:
            raise IndexBundleLoadError(
                f"Bundle archive is malformed: {exc}"
            ) from exc

        # Parse manifest first; everything else depends on it.
        try:
            manifest_dict = json.loads(manifest_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IndexBundleLoadError(
                f"Bundle manifest is not valid JSON: {exc}"
            ) from exc
        try:
            manifest = IndexBundleManifest(**manifest_dict)
        except Exception as exc:
            raise IndexBundleLoadError(
                f"Bundle manifest does not match schema: {exc}"
            ) from exc

        # Schema version compatibility check.
        try:
            bundle_major = int(manifest.schema_version.split(".")[0])
        except (ValueError, IndexError):
            raise IndexBundleLoadError(
                f"Bundle schema version is malformed: "
                f"{manifest.schema_version!r}"
            )
        current_major = int(SCHEMA_VERSION.split(".")[0])
        if bundle_major != current_major:
            raise IndexBundleLoadError(
                f"Bundle schema version {manifest.schema_version} is "
                f"incompatible with framework schema version "
                f"{SCHEMA_VERSION}. Use the Phase 7 schema-migration "
                f"tool to convert this bundle."
            )

        # Verify chunks content hash before parsing chunks.
        actual_chunks_hash = "sha256:" + hashlib.sha256(chunks_bytes).hexdigest()
        if actual_chunks_hash != manifest.chunks_content_hash:
            raise IndexBundleLoadError(
                f"Chunks content hash mismatch. Manifest recorded "
                f"{manifest.chunks_content_hash}; actual is "
                f"{actual_chunks_hash}. The bundle may be corrupted "
                f"or tampered with."
            )

        # Parse chunks from JSONL.
        try:
            chunks = _jsonl_bytes_to_chunks(chunks_bytes)
        except Exception as exc:
            raise IndexBundleLoadError(
                f"Bundle chunks are not valid Chunk models: {exc}"
            ) from exc
        if len(chunks) != manifest.chunk_count:
            raise IndexBundleLoadError(
                f"Manifest records chunk_count={manifest.chunk_count} "
                f"but {len(chunks)} chunks were parsed."
            )

        # Load embeddings if present.
        embeddings: Optional[np.ndarray] = None
        if embeddings_bytes is not None:
            if manifest.embedding_dimension is None:
                raise IndexBundleLoadError(
                    "Bundle contains embeddings file but manifest does "
                    "not record embedding_dimension."
                )
            try:
                with np.load(io.BytesIO(embeddings_bytes)) as npz:
                    if "embeddings" not in npz.files:
                        raise IndexBundleLoadError(
                            "Embeddings file is missing the "
                            "'embeddings' array."
                        )
                    embeddings = np.array(npz["embeddings"], dtype=np.float32)
            except IndexBundleLoadError:
                raise
            except Exception as exc:
                raise IndexBundleLoadError(
                    f"Embeddings file is unreadable: {exc}"
                ) from exc

            expected_shape = (len(chunks), manifest.embedding_dimension)
            if embeddings.shape != expected_shape:
                raise IndexBundleLoadError(
                    f"Embeddings shape mismatch. Expected {expected_shape}, "
                    f"got {embeddings.shape}."
                )

            # Optional identity check against a caller-supplied embedder.
            if embedder is not None:
                if verify_embedder_identity:
                    expected_identity = _compute_embedder_identity(embedder)
                    if expected_identity != manifest.embedder_identity:
                        raise IndexBundleLoadError(
                            f"Embedder identity mismatch. Bundle was "
                            f"built with {manifest.embedder_identity!r}; "
                            f"load-time embedder is {expected_identity!r}. "
                            f"Pass verify_embedder_identity=False to "
                            f"override (dimension is verified either way)."
                        )
                else:
                    # Loose check: dimension only.
                    if embedder.dimension != manifest.embedding_dimension:
                        raise IndexBundleLoadError(
                            f"Embedder dimension mismatch. Bundle "
                            f"dimension is {manifest.embedding_dimension}; "
                            f"load-time embedder dimension is "
                            f"{embedder.dimension}."
                        )

        return cls(chunks=chunks, manifest=manifest, embeddings=embeddings)

    def save(self, path: Path) -> None:
        """Write the bundle to a tar.gz file.

        Atomicity: writes to a temporary file in the same directory
        first, then renames into place. Callers concurrently reading
        the destination path during a save see either the pre-save
        bundle or the post-save bundle, never a partial write.

        Args:
            path: Destination path. The parent directory must exist;
                it is the caller's responsibility to mkdir if needed.
                Existing files at the destination are overwritten.
        """
        # Atomic write: tmp file in same dir, then rename.
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with tarfile.open(tmp_path, mode="w:gz") as tar:
                self._write_member(
                    tar=tar,
                    name=_MANIFEST_FILENAME,
                    data=json.dumps(
                        self._manifest.model_dump(),
                        indent=2,
                        sort_keys=True,
                    ).encode("utf-8"),
                )
                self._write_member(
                    tar=tar,
                    name=_CHUNKS_FILENAME,
                    data=_chunks_to_jsonl_bytes(self._chunks),
                )
                if self._embeddings is not None:
                    npz_buf = io.BytesIO()
                    np.savez_compressed(npz_buf, embeddings=self._embeddings)
                    self._write_member(
                        tar=tar,
                        name=_EMBEDDINGS_FILENAME,
                        data=npz_buf.getvalue(),
                    )
            tmp_path.replace(path)
        except Exception:
            # Clean up the tmp file on any error before re-raising.
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    @staticmethod
    def _write_member(tar: tarfile.TarFile, name: str, data: bytes) -> None:
        """Append a single named member to an open tar archive."""
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        info.mtime = 0  # Deterministic: zero mtime for diff-friendliness.
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))


# -- helpers ---------------------------------------------------------------


def _chunks_to_jsonl_bytes(chunks: list[Chunk]) -> bytes:
    """Serialize chunks to JSONL bytes.

    Each line is a JSON dump of one Chunk's model_dump() output.
    Sorted keys for diff-friendliness and stable hashes.
    """
    lines = [
        json.dumps(c.model_dump(), sort_keys=True)
        for c in chunks
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _jsonl_bytes_to_chunks(data: bytes) -> list[Chunk]:
    """Parse JSONL bytes back to a list of Chunks.

    Blank lines (including the trailing newline) are tolerated and
    produce no chunks. Malformed lines raise; the caller catches and
    re-raises as IndexBundleLoadError.
    """
    chunks: list[Chunk] = []
    text = data.decode("utf-8")
    for line in text.split("\n"):
        if not line.strip():
            continue
        chunks.append(Chunk(**json.loads(line)))
    return chunks


def _compute_embedder_identity(embedder: Embedder) -> str:
    """Compute the identity string recorded on the manifest.

    Format:
    - ``{type_name}/{model_name}/{dimension}`` when the embedder
      exposes a ``model_name`` attribute (SentenceTransformerEmbedder).
    - ``{type_name}/{dimension}`` otherwise (HashEmbedder, any other
      Embedder Protocol implementer).

    The identity is the equality check at load time. Two embedders
    that produce the same identity are treated as interchangeable.
    """
    type_name = type(embedder).__name__
    model_name = getattr(embedder, "model_name", None)
    if model_name:
        return f"{type_name}/{model_name}/{embedder.dimension}"
    return f"{type_name}/{embedder.dimension}"


def _safe_extract(tar: tarfile.TarFile, name: str) -> Optional[bytes]:
    """Extract a named member's bytes, returning None if absent.

    Defensive: returns None rather than raising on missing members,
    so the caller can raise an IndexBundleLoadError with a clearer
    message.
    """
    try:
        member = tar.getmember(name)
    except KeyError:
        return None
    f = tar.extractfile(member)
    if f is None:  # pragma: no cover
        # Member exists but is not a regular file. Treat as missing;
        # the caller will surface as a malformed-bundle error.
        return None
    return f.read()
