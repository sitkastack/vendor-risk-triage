"""Atomically bump the framework version in _version.py and pyproject.toml.

The framework keeps its version in two places: ``_version.FRAMEWORK_VERSION``
(read at runtime) and the ``version`` field in ``pyproject.toml`` (read
by the build system). ``scripts/check_version_sync.py`` verifies they
agree; this script is the write-counterpart that bumps both together so
they never drift.

Usage::

    python scripts/bump_version.py patch    # 0.9.0 -> 0.9.1
    python scripts/bump_version.py minor    # 0.9.0 -> 0.10.0
    python scripts/bump_version.py major    # 0.9.0 -> 1.0.0
    python scripts/bump_version.py 1.2.3    # set an explicit version

After bumping, the script reminds the maintainer to:

1. Add a History entry to the FRAMEWORK_VERSION docstring in
   _version.py describing the change.
2. Regenerate CHANGELOG.md (python scripts/extract_changelog.py).

The script does NOT write the History entry itself: that prose is
hand-curated and is the single highest-value artifact in the release
process. Auto-generating it from commit messages would produce lower-
quality output. The script only moves the version numbers; the human
writes the story.

Clean-tree guard: by default the script refuses to run when the git
working tree has uncommitted changes (staged or unstaged). This
prevents a version bump from being entangled with unrelated edits.
Pass ``--allow-dirty`` to override (useful when the bump is
intentionally part of a larger in-progress commit, as in the
framework's own sub-system workflow where the bump rides with the
feature).

Exit codes:

- ``0``: bump succeeded.
- ``1``: refused (dirty tree without --allow-dirty, or version would
  not increase).
- ``2``: setup error (bad bump argument, files missing, parse failure).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_semver(version: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' into an (int, int, int) tuple."""
    match = _SEMVER_RE.match(version)
    if not match:
        raise ValueError(
            f"Version {version!r} is not a valid X.Y.Z semver string."
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _compute_new_version(current: str, bump: str) -> str:
    """Compute the new version from the current one and a bump spec.

    ``bump`` is one of 'major', 'minor', 'patch', or an explicit
    'X.Y.Z' string. Explicit versions must be strictly greater than
    the current version.
    """
    major, minor, patch = _parse_semver(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    # Explicit version.
    new_major, new_minor, new_patch = _parse_semver(bump)
    if (new_major, new_minor, new_patch) <= (major, minor, patch):
        raise ValueError(
            f"Explicit version {bump} must be strictly greater than the "
            f"current version {current}."
        )
    return bump


def _read_current_version(version_path: Path) -> str:
    """Read FRAMEWORK_VERSION from _version.py via regex.

    Uses a regex rather than importing the module so the script works
    even if the module has import-time side effects or syntax issues
    elsewhere.
    """
    if not version_path.exists():
        raise FileNotFoundError(f"_version.py not found at {version_path}")
    text = version_path.read_text(encoding="utf-8")
    match = re.search(
        r'^FRAMEWORK_VERSION:\s*str\s*=\s*[\'"]([^\'"]+)[\'"]',
        text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(
            "Could not find a 'FRAMEWORK_VERSION: str = \"...\"' line "
            "in _version.py."
        )
    return match.group(1)


def _write_version_py(version_path: Path, old: str, new: str) -> None:
    """Replace the FRAMEWORK_VERSION assignment line in _version.py."""
    text = version_path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(^FRAMEWORK_VERSION:\s*str\s*=\s*[\'"])([^\'"]+)([\'"])',
        rf"\g<1>{new}\g<3>",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(
            f"Expected exactly one FRAMEWORK_VERSION assignment to "
            f"replace; found {count}."
        )
    version_path.write_text(new_text, encoding="utf-8")


def _write_pyproject(pyproject_path: Path, old: str, new: str) -> None:
    """Replace the version field in pyproject.toml."""
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")
    text = pyproject_path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(^\s*version\s*=\s*[\'"])([^\'"]+)([\'"])',
        rf"\g<1>{new}\g<3>",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(
            f"Expected exactly one version assignment in pyproject.toml "
            f"to replace; found {count}."
        )
    pyproject_path.write_text(new_text, encoding="utf-8")


def _git_tree_is_dirty() -> bool:
    """Return True if the git working tree has uncommitted changes.

    Uses 'git status --porcelain'; any output means the tree is dirty.
    If git is not available or this is not a repo, treat as clean
    (the caller's environment problem, not ours to block on).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return bool(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Atomically bump the framework version in _version.py and "
            "pyproject.toml."
        ),
    )
    parser.add_argument(
        "bump",
        help=(
            "Bump kind: 'major', 'minor', 'patch', or an explicit "
            "'X.Y.Z' version (which must be greater than the current)."
        ),
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Permit bumping when the git tree has uncommitted changes. "
            "Default is to refuse, so a bump is not entangled with "
            "unrelated edits."
        ),
    )
    args = parser.parse_args(argv)

    version_path = _REPO_ROOT / "_version.py"
    pyproject_path = _REPO_ROOT / "pyproject.toml"

    # Clean-tree guard.
    if not args.allow_dirty and _git_tree_is_dirty():
        print(
            "ERROR: git working tree has uncommitted changes. Commit or "
            "stash them first, or pass --allow-dirty to bump anyway "
            "(useful when the version bump is intentionally part of a "
            "larger in-progress commit).",
            file=sys.stderr,
        )
        return 1

    try:
        current = _read_current_version(version_path)
        new = _compute_new_version(current, args.bump)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        _write_version_py(version_path, current, new)
        _write_pyproject(pyproject_path, current, new)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Bumped version: {current} -> {new}")
    print("")
    print("Next steps:")
    print(f"  1. Add a History entry for {new} to the FRAMEWORK_VERSION")
    print("     docstring in _version.py describing the change.")
    print("  2. Regenerate the changelog:")
    print("       python scripts/extract_changelog.py")
    print("  3. Verify the release is ready:")
    print("       python scripts/prepare_release.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
