"""``vrt version`` subcommand: print framework version + verify sync.

Prints FRAMEWORK_VERSION and SYSTEM_PROMPT_HASH, and runs the
pyproject.toml sync check. Two output modes:

- Default (human-readable): pretty-printed
- ``--json``: machine-readable for scripting

Exit codes:

- ``0``: versions consistent, output emitted
- ``1``: pyproject.toml version disagrees with FRAMEWORK_VERSION
  (mirrors scripts/check_version_sync.py behavior)
- ``2``: setup error
"""
from __future__ import annotations

import argparse
import json
import sys


__all__ = ["add_arguments", "run"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``version`` arguments."""
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print version info as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--skip-sync-check",
        action="store_true",
        help=(
            "Skip the pyproject.toml sync check. By default the "
            "subcommand exits 1 if pyproject.toml is out of sync."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Print version info; optionally verify pyproject sync."""
    from _version import FRAMEWORK_VERSION
    from agent.agent import SYSTEM_PROMPT_HASH

    info: dict[str, str] = {
        "framework_version": FRAMEWORK_VERSION,
        "system_prompt_hash": SYSTEM_PROMPT_HASH,
    }

    sync_ok = True
    sync_detail = ""
    if not args.skip_sync_check:
        sync_ok, sync_detail = _check_pyproject_sync(FRAMEWORK_VERSION)
        info["pyproject_sync"] = "ok" if sync_ok else "mismatch"
        if not sync_ok:
            info["pyproject_detail"] = sync_detail

    if args.json_output:
        print(json.dumps(info, indent=2, sort_keys=True))
    else:
        print(f"Framework version:    {FRAMEWORK_VERSION}")
        print(f"System prompt hash:   {SYSTEM_PROMPT_HASH}")
        if not args.skip_sync_check:
            if sync_ok:
                print(f"pyproject.toml sync:  ok")
            else:
                print(f"pyproject.toml sync:  MISMATCH")
                print(f"  {sync_detail}")
                print(
                    "  Update pyproject.toml or _version.py to match. "
                    "See docs/maintenance-workflow.md section 1."
                )

    return 0 if sync_ok else 1


def _check_pyproject_sync(framework_version: str) -> tuple[bool, str]:
    """Verify pyproject.toml's version matches FRAMEWORK_VERSION.

    Returns (ok, detail). When ok is False, detail explains the
    mismatch in a single line suitable for stderr.
    """
    try:
        from scripts.check_version_sync import _read_pyproject_version
        from pathlib import Path
    except ImportError as exc:  # pragma: no cover - defensive; scripts module is always importable when framework is installed
        return False, f"could not run sync check: {exc}"

    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"

    try:
        pyproject_version = _read_pyproject_version(pyproject_path)
    except (FileNotFoundError, ValueError) as exc:  # pragma: no cover - pyproject.toml is always present in a valid framework checkout
        return False, f"could not read pyproject.toml: {exc}"

    if pyproject_version != framework_version:
        return False, (
            f"pyproject.toml version {pyproject_version!r} != "
            f"FRAMEWORK_VERSION {framework_version!r}"
        )
    return True, ""
