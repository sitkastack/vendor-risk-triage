"""``vrt corpus`` subcommand: manage regulation corpora.

Two sub-actions:

- ``vrt corpus build``: build IndexBundles from cached regulation
  PDFs. Wraps ``scripts.build_corpus_bundles``.
- ``vrt corpus list``: print the registered corpora.

The build action requires the regulation PDFs to be cached locally
first (integration tests do this on first run). See
``docs/corpus-manifest.md`` for sourcing instructions.

Exit codes:

- ``0``: action completed
- ``1``: action failed (PDF missing from cache, bundle write failed)
- ``2``: setup error (unknown sub-action, missing prerequisite)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


__all__ = ["add_arguments", "run"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``corpus`` arguments with nested sub-actions."""
    sub = parser.add_subparsers(
        title="corpus actions",
        dest="action",
        required=False,
    )

    build = sub.add_parser(
        "build",
        help="Build IndexBundles from cached regulation PDFs.",
    )
    build.add_argument(
        "regulation",
        nargs="?",
        default=None,
        help=(
            "Regulation name to build (e.g., 'nist-ai-rmf'). When "
            "omitted, builds all committed corpora. Run 'vrt corpus "
            "list' to see registered names."
        ),
    )
    build.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path("corpora"),
        help=(
            "Output directory root. Bundles are organized as "
            "<output-dir>/<name>/<name>.bundle.tgz. Default: corpora/"
        ),
    )

    sub.add_parser(
        "list",
        help="List registered regulation corpora.",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch to the requested corpus sub-action."""
    if args.action is None:
        print(
            "ERROR: 'vrt corpus' requires a sub-action. Run "
            "'vrt corpus --help' to see available actions.",
            file=sys.stderr,
        )
        return 2

    if args.action == "build":
        return _run_build(args)
    if args.action == "list":
        return _run_list()
    print(
        f"ERROR: unknown action '{args.action}'.",
        file=sys.stderr,
    )
    return 2


def _run_build(args: argparse.Namespace) -> int:
    """Build one or all corpus bundles via the existing build script."""
    try:
        from scripts.build_corpus_bundles import (
            _COMMITTED_CORPORA,
            build_all,
            build_bundle,
        )
        from retrieval import SentenceTransformerEmbedder
    except ImportError as exc:  # pragma: no cover - defensive; framework's own modules always importable in normal operation
        print(
            f"ERROR: could not import build_corpus_bundles: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        if args.regulation is None:
            # Build all committed corpora
            paths = build_all(output_root=args.output_dir)
            print(f"\nBuilt {len(paths)} bundle(s):")
            for p in paths:
                print(f"  - {p}")
            return 0

        # Build a single named corpus
        if args.regulation not in _COMMITTED_CORPORA:
            print(
                f"ERROR: unknown or non-committed regulation "
                f"'{args.regulation}'. Committed names: "
                f"{', '.join(_COMMITTED_CORPORA)}",
                file=sys.stderr,
            )
            return 2

        embedder = SentenceTransformerEmbedder()
        path = build_bundle(
            args.regulation,
            output_root=args.output_dir,
            embedder=embedder,
        )
        print(f"\nBuilt bundle: {path}")
        return 0
    except Exception as exc:
        # The build script raises on cache-miss or write failure.
        print(f"ERROR: corpus build failed: {exc}", file=sys.stderr)
        return 1


def _run_list() -> int:
    """Print the registered corpora."""
    try:
        from scripts.build_corpus_bundles import _COMMITTED_CORPORA
        from retrieval.corpora import CORPUS_REGISTRY
    except ImportError as exc:  # pragma: no cover - defensive; framework's own modules always importable in normal operation
        print(
            f"ERROR: could not import corpus registry: {exc}",
            file=sys.stderr,
        )
        return 2

    print("Registered corpora:")
    print()
    for name in sorted(CORPUS_REGISTRY.keys()):
        source = CORPUS_REGISTRY[name]
        committed = "committed" if name in _COMMITTED_CORPORA else "local-only"
        doc_name = getattr(source, "document_name", "")
        print(f"  {name}  ({committed})")
        if doc_name:
            print(f"    document: {doc_name}")
    print()
    print(
        "Build a single corpus: vrt corpus build <name>\n"
        "Build all committed:   vrt corpus build"
    )
    return 0
