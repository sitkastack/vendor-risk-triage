"""Build IndexBundles from cached regulation PDFs (local-only).

Run this script after fetching the regulation PDFs to produce bundle
files for inclusion in the repo or for distribution.

Usage::

    # First, set up the cache by running integration tests once
    # (they will fail with placeholder-hash errors on first run; copy
    # the printed hashes into tests/integration/corpora_cache.py).

    # Then build bundles:
    python -m scripts.build_corpus_bundles

    # Bundles land in corpora/<name>/<name>.bundle.tgz

For each registered corpus this script:

1. Reads the cached PDF via tests/integration/corpora_cache.fetch_corpus
2. Chunks the PDF with sectionize=True (one Chunk per detected section)
3. Computes embeddings with SentenceTransformerEmbedder (default model
   all-MiniLM-L6-v2; ~80MB one-time download into the
   sentence-transformers cache)
4. Wraps the chunks + embeddings into an IndexBundle
5. Saves the bundle to corpora/<name>/<name>.bundle.tgz

The script does not require network at run time once the PDFs are
cached and the sentence-transformers model is downloaded.

Output structure::

    corpora/
    ├── nist-ai-rmf/
    │   └── nist-ai-rmf-100-1.bundle.tgz
    ├── sox-pl-107-204/
    │   └── sox-pl-107-204.bundle.tgz
    └── eu-ai-act/
        └── eu-ai-act-regulation-2024-1689.bundle.tgz

The OSFI bundle is intentionally NOT built into the committed corpora/
directory because of license terms; users build it locally on their
own machine. See docs/corpus-manifest.md.

This script is run only by maintainers preparing a release or by users
preparing their own bundles. It is not part of the framework's runtime
code and is excluded from coverage.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from retrieval import (
    CorpusLoader,
    IndexBundle,
    SentenceTransformerEmbedder,
)
from tests.integration.corpora_cache import CORPUS_REGISTRY, fetch_corpus


# Corpora that ARE committed into the repo. OSFI is excluded; users
# build it locally after fetching their authorized copy.
_COMMITTED_CORPORA: tuple[str, ...] = (
    "nist-ai-rmf",
    "sox-pl-107-204",
    "eu-ai-act",
)


def build_bundle(
    corpus_name: str,
    output_root: Path,
    embedder: SentenceTransformerEmbedder,
) -> Path:
    """Build one bundle. Returns the saved bundle path."""
    source = CORPUS_REGISTRY[corpus_name]
    print(f"\n[{corpus_name}] fetching/verifying cached PDF...")
    pdf_path = fetch_corpus(corpus_name)
    print(f"[{corpus_name}] PDF at {pdf_path} ({pdf_path.stat().st_size:,} bytes)")

    print(f"[{corpus_name}] chunking with sectionize=True...")
    loader = CorpusLoader()
    chunks = loader.load_pdf(
        corpus_name=corpus_name,
        document_name=source.document_name,
        content=pdf_path.read_bytes(),
        sectionize=True,
    )
    print(f"[{corpus_name}] produced {len(chunks)} chunks")

    print(
        f"[{corpus_name}] embedding {len(chunks)} chunks with "
        f"{type(embedder).__name__}/{embedder.model_name}..."
    )
    bundle = IndexBundle.from_chunks(
        chunks=chunks,
        corpus_name=corpus_name,
        embedder=embedder,
    )

    output_dir = output_root / corpus_name
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"{corpus_name}.bundle.tgz"
    print(f"[{corpus_name}] saving bundle to {bundle_path}...")
    bundle.save(bundle_path)
    print(
        f"[{corpus_name}] bundle saved: {bundle_path.stat().st_size:,} bytes"
    )
    return bundle_path


def build_all(
    output_root: Path = Path("corpora"),
    corpora: Iterable[str] = _COMMITTED_CORPORA,
) -> list[Path]:
    """Build bundles for the committed-corpora set.

    The embedder is constructed once and reused across all bundles to
    avoid re-loading the sentence-transformers model.
    """
    embedder = SentenceTransformerEmbedder()
    paths: list[Path] = []
    for name in corpora:
        paths.append(build_bundle(name, output_root, embedder))
    return paths


if __name__ == "__main__":
    try:
        bundle_paths = build_all()
    except Exception as exc:
        print(f"\nBuild failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"\nBuilt {len(bundle_paths)} bundle(s):")
    for p in bundle_paths:
        print(f"  - {p}")
