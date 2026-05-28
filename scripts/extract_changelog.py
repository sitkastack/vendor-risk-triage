"""Generate (or verify) CHANGELOG.md from the _version.py history.

The framework's authoritative version history lives in the
``FRAMEWORK_VERSION`` docstring in ``_version.py`` as a hand-curated
"History:" section. That prose is higher-signal than any commit-
message-derived changelog could be: each entry explains what changed
and why at a level commit parsing cannot reach.

This script keeps ``_version.py`` as the single source of truth and
projects its history into a standard repo-root ``CHANGELOG.md`` that
follows Keep-a-Changelog conventions (https://keepachangelog.com).
External readers expect to find a CHANGELOG.md; this gives them one
without forcing a maintainer to write the history twice.

Two modes:

- **Generate** (default): write CHANGELOG.md from the current
  _version.py history. Run after a version bump to refresh the
  changelog.
- **Check** (``--check``): compare the committed CHANGELOG.md against
  what would be generated. Exit 1 if they differ. Used by
  ``prepare_release.py`` and CI to catch the "bumped the version but
  forgot to regenerate the changelog" failure mode.

The parser reads the "History:" section, splits it into per-version
entries (each starting with ``- X.Y.Z`` at the left margin, with
2-space-indented continuation lines), and converts the RST-style
double-backtick markup to markdown single-backtick. The
``- earlier: ...`` trailing entry (which has no version number) is
preserved as a free-form note.

Exit codes:

- ``0``: generate succeeded, or check found the changelog current.
- ``1``: check found the changelog stale (differs from generated).
- ``2``: setup error (cannot read _version.py, no History section).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_CHANGELOG_HEADER = """\
# Changelog

All notable changes to this framework are documented here.

This file is generated from the hand-curated version history in
`_version.py` by `scripts/extract_changelog.py`. Do not edit it by
hand; edit the `FRAMEWORK_VERSION` docstring in `_version.py` and
regenerate. The format follows [Keep a Changelog](https://keepachangelog.com/),
and the framework adheres to [Semantic Versioning](https://semver.org/)
(pre-1.0: breaking changes may ride in minor bumps).

"""


def _read_version_module_source(version_path: Path) -> str:
    """Return the source text of _version.py."""
    if not version_path.exists():
        raise FileNotFoundError(f"_version.py not found at {version_path}")
    return version_path.read_text(encoding="utf-8")


def _extract_history_block(source: str) -> str:
    """Pull the text between 'History:' and the closing docstring quotes.

    The history lives inside the FRAMEWORK_VERSION docstring. We find
    the 'History:' line and capture everything up to the triple-quote
    that closes the docstring.
    """
    history_match = re.search(r"History:\n(.*?)\n\"\"\"", source, re.DOTALL)
    if not history_match:
        raise ValueError(
            "Could not find a 'History:' section in _version.py's "
            "FRAMEWORK_VERSION docstring. The changelog extractor "
            "depends on that section. See docs/maintenance-workflow.md."
        )
    return history_match.group(1)


def _rst_to_markdown(text: str) -> str:
    """Convert RST-style ``code`` markup to markdown `code` markup."""
    return text.replace("``", "`")


def _parse_entries(history_block: str) -> list[tuple[str, str]]:
    """Parse the history block into (version, body) tuples.

    Each entry starts with '- X.Y.Z ...' at the left margin.
    Continuation lines are indented by 2 spaces and belong to the
    preceding entry. The trailing '- earlier: ...' entry has no
    semantic version; it is captured with version label 'earlier'.

    Returns entries in document order (newest first, matching the
    _version.py convention).
    """
    entries: list[tuple[str, str]] = []
    current_version: str | None = None
    current_lines: list[str] = []

    for line in history_block.split("\n"):
        # A new entry begins with '- ' at column 0.
        entry_match = re.match(r"^- (\S+)(.*)$", line)
        if entry_match:
            # Flush the previous entry.
            if current_version is not None:
                entries.append(
                    (current_version, "\n".join(current_lines).strip())
                )
            first_token = entry_match.group(1)
            remainder = entry_match.group(2)
            # Strip a trailing colon from a version token like '0.9.0'
            # only when it is the version (not the 'earlier' note where
            # the colon is part of the prose).
            version_candidate = first_token.rstrip(":")
            if re.match(r"^\d+\.\d+\.\d+$", version_candidate):
                current_version = version_candidate
                current_lines = [remainder.strip()]
            else:
                # Non-version entry such as 'earlier:'. Keep the whole
                # line's content as the body under an 'earlier' label.
                current_version = first_token.rstrip(":")
                current_lines = [remainder.strip()]
        else:
            # Continuation line (indented) for the current entry.
            if current_version is not None:
                current_lines.append(line.strip())

    # Flush the last entry.
    if current_version is not None:
        entries.append((current_version, "\n".join(current_lines).strip()))

    return entries


def _render_changelog(entries: list[tuple[str, str]]) -> str:
    """Render parsed entries into a Keep-a-Changelog markdown document."""
    out = [_CHANGELOG_HEADER]
    for version, body in entries:
        body_md = _rst_to_markdown(body)
        # Collapse internal newlines (the prose was line-wrapped in the
        # docstring) into spaces so each entry is one flowing paragraph.
        # Repair hyphenated line-wrap artifacts ('4-\nchars' became
        # '4- chars' after the naive collapse) by removing a space that
        # follows a hyphen between word characters.
        body_md = re.sub(r"\s+", " ", body_md).strip()
        body_md = re.sub(r"(\w)- (\w)", r"\1-\2", body_md)

        if not re.match(r"^\d+\.\d+\.\d+$", version):
            # The 'earlier' free-form note.
            out.append(f"## {version}\n\n{body_md}\n")
            continue

        # A version entry. The body starts with a parenthetical tag
        # like '(sub-system 8, Phase 6 SS4): summary...'. Split the
        # leading '(...): ' metadata from the description so the
        # rendered entry reads as a clean heading + prose rather than
        # a dangling parenthetical.
        tag_match = re.match(r"^\((.*?)\):\s*(.*)$", body_md, re.DOTALL)
        if tag_match:
            tag = tag_match.group(1)
            description = tag_match.group(2)
            out.append(
                f"## [{version}]\n\n_{tag}_\n\n{description}\n"
            )
        else:
            out.append(f"## [{version}]\n\n{body_md}\n")
    return "\n".join(out) + "\n"


def generate_changelog(version_path: Path) -> str:
    """Produce the CHANGELOG.md content from _version.py."""
    source = _read_version_module_source(version_path)
    history_block = _extract_history_block(source)
    entries = _parse_entries(history_block)
    return _render_changelog(entries)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate or verify CHANGELOG.md from the _version.py "
            "history."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify the committed CHANGELOG.md matches what would be "
            "generated. Exit 1 if stale. Does not write."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_REPO_ROOT / "CHANGELOG.md",
        help="Path to CHANGELOG.md (default: repo-root CHANGELOG.md).",
    )
    args = parser.parse_args(argv)

    version_path = _REPO_ROOT / "_version.py"

    try:
        generated = generate_changelog(version_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if not args.output.exists():
            print(
                f"ERROR: {args.output} does not exist. Run "
                f"'python scripts/extract_changelog.py' to generate it.",
                file=sys.stderr,
            )
            return 1
        committed = args.output.read_text(encoding="utf-8")
        if committed != generated:
            print(
                f"CHANGELOG STALE: {args.output} does not match the "
                f"current _version.py history.\n"
                f"Regenerate with: python scripts/extract_changelog.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.output} is current with _version.py history.")
        return 0

    args.output.write_text(generated, encoding="utf-8")
    print(f"Wrote {args.output} from _version.py history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
