"""``vrt drift`` subcommand: classification drift check.

Thin wrapper around ``scripts.check_drift.main``. The implementation
lives in the existing script; this module is a CLI-aware shim so
``vrt drift`` and ``python scripts/check_drift.py`` produce identical
behavior.

Usage::

    vrt drift                          # check, exit 0/1
    vrt drift --update-baseline        # regenerate baseline
    vrt drift --threshold 0.10         # custom confidence delta
    vrt drift --baseline custom.jsonl  # custom baseline path

Exit codes match scripts/check_drift.py:

- ``0``: no drift
- ``1``: drift detected (hard or soft)
- ``2``: setup error
"""
from __future__ import annotations

import argparse
from pathlib import Path


__all__ = ["add_arguments", "run"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``drift`` arguments. Mirrors check_drift.py exactly."""
    from eval.drift import (
        DEFAULT_BASELINE_PATH,
        DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
    )

    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Regenerate the baseline file from the current framework's "
            "output. Use after accepting a drift as intentional."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
        help=(
            f"Confidence score delta below which differences are "
            f"ignored. Default {DEFAULT_SOFT_CONFIDENCE_THRESHOLD}."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Path to the baseline JSONL file.",
    )


def run(args: argparse.Namespace) -> int:
    """Run the drift check via the existing script's main()."""
    from scripts.check_drift import main as script_main

    # Build the argv form the script's argparse expects. The shim
    # preserves the existing script's contract; the CLI's argparse
    # already validated the args, so we just translate.
    argv: list[str] = []
    if args.update_baseline:
        argv.append("--update-baseline")
    if args.threshold is not None:
        argv.extend(["--threshold", str(args.threshold)])
    if args.baseline is not None:
        argv.extend(["--baseline", str(args.baseline)])

    return script_main(argv)
