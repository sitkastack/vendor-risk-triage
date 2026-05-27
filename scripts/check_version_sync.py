"""Verify that pyproject.toml version matches _version.FRAMEWORK_VERSION.

Run as part of CI to catch the failure mode where a maintainer bumps
one but not the other. The duplication exists because Python's build
system reads ``pyproject.toml`` and the runtime reads
``_version.FRAMEWORK_VERSION``; both are legitimate sources for
different consumers (pip, setuptools vs runtime imports) and a single
file cannot serve both without build-time generation, which is more
machinery than is justified.

Exit codes:

- ``0``: ``pyproject.toml`` version matches ``_version.FRAMEWORK_VERSION``.
- ``1``: versions disagree. The CI step fails; the maintainer must
  sync them before the build can pass.
- ``2``: setup error (missing files, malformed input).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Add repo root to sys.path so '_version' resolves under standalone
# script execution (python scripts/check_version_sync.py from repo root).
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _read_pyproject_version(pyproject_path: Path) -> str:
    """Extract the version string from pyproject.toml.

    Uses a regex rather than a TOML parser to avoid pulling in tomllib
    handling for older Python (tomllib is stdlib from 3.11, which is
    the framework's minimum, so this is safe but unnecessary). The
    regex matches the canonical 'version = "X.Y.Z"' line under
    [project].
    """
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")
    text = pyproject_path.read_text(encoding="utf-8")
    # Look for the version line in the [project] section. The regex
    # tolerates whitespace around the equals sign and matches both
    # single and double quotes.
    match = re.search(
        r'^\s*version\s*=\s*[\'\"]([^\'\"]+)[\'\"]',
        text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(
            f"Could not find version = \"...\" line in {pyproject_path}. "
            f"Expected a line like 'version = \"0.6.0\"'."
        )
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"

    try:
        pyproject_version = _read_pyproject_version(pyproject_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        from _version import FRAMEWORK_VERSION
    except ImportError as exc:
        print(f"ERROR: could not import _version: {exc}", file=sys.stderr)
        return 2

    if pyproject_version != FRAMEWORK_VERSION:
        print(
            f"VERSION MISMATCH:\n"
            f"  pyproject.toml:      {pyproject_version}\n"
            f"  _version.FRAMEWORK_VERSION: {FRAMEWORK_VERSION}\n"
            f"\n"
            f"These must match. Update whichever is stale. See "
            f"docs/maintenance-workflow.md section 1 for the release "
            f"procedure.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: pyproject.toml and _version.FRAMEWORK_VERSION both at {FRAMEWORK_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
