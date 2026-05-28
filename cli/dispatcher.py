"""Top-level argparse dispatcher for the ``vrt`` command.

Each subcommand is implemented in its own ``cli/cmd_*.py`` module and
exposes a ``run(args)`` function plus an ``add_arguments(parser)``
function. The dispatcher wires them into argparse subparsers.

Exit codes follow Unix convention:

- ``0``: success
- ``1``: subcommand-specific failure (drift detected, classification
  produced an error, etc.)
- ``2``: argparse error (unknown subcommand, missing required arg)
- specific subcommands document additional non-zero codes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

# Add repo root to sys.path so 'from _version import ...' works when the
# CLI is invoked as a console script from any working directory.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - only exercised when invoked as installed console script, not under pytest
    sys.path.insert(0, str(_REPO_ROOT))

from _version import FRAMEWORK_VERSION  # noqa: E402

from cli import (  # noqa: E402
    cmd_corpus,
    cmd_drift,
    cmd_migrate,
    cmd_render,
    cmd_triage,
    cmd_version,
)


__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser with subcommands.

    Exposed for tests that exercise the parsing layer without invoking
    any subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="vrt",
        description=(
            "Vendor risk triage framework command-line interface. "
            "Run 'vrt <subcommand> --help' for subcommand-specific help."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"vrt {FRAMEWORK_VERSION}",
        help="Print the framework version and exit.",
    )

    subparsers = parser.add_subparsers(
        title="subcommands",
        dest="subcommand",
        required=False,
    )

    _register_subcommand(
        subparsers,
        name="triage",
        help_text="Run the triage agent against a submission JSON file.",
        module=cmd_triage,
    )
    _register_subcommand(
        subparsers,
        name="render",
        help_text="Render an audit pack HTML from a TriageRecord JSON file.",
        module=cmd_render,
    )
    _register_subcommand(
        subparsers,
        name="migrate",
        help_text=(
            "Up-migrate records to a newer output-contract version."
        ),
        module=cmd_migrate,
    )
    _register_subcommand(
        subparsers,
        name="drift",
        help_text="Check classification drift against the baseline.",
        module=cmd_drift,
    )
    _register_subcommand(
        subparsers,
        name="corpus",
        help_text="Manage regulation corpora (build, list).",
        module=cmd_corpus,
    )
    _register_subcommand(
        subparsers,
        name="version",
        help_text=(
            "Print framework version + system prompt hash; verify "
            "pyproject.toml sync."
        ),
        module=cmd_version,
    )

    return parser


def _register_subcommand(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    module,
) -> None:
    """Wire a single subcommand into the dispatcher.

    The module is expected to expose ``add_arguments(parser)`` for
    flag registration and ``run(args) -> int`` for execution.
    """
    sp = subparsers.add_parser(name, help=help_text, description=help_text)
    module.add_arguments(sp)
    sp.set_defaults(_run=module.run)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the subcommand's exit code.

    Invoked by:

    - The ``vrt`` console script registered in ``pyproject.toml``
    - ``python -m cli`` (via ``cli/__main__.py``)
    - ``scripts/check_drift.py``, ``scripts/check_version_sync.py``,
      etc. via shim wrappers
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2

    run: Callable[[argparse.Namespace], int] = args._run
    return run(args)


if __name__ == "__main__":  # pragma: no cover - exercised by 'python -m cli' subprocess, not under pytest import
    sys.exit(main())
