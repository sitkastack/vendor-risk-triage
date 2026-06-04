"""CI gate: assert SYSTEM_PROMPT_HASH matches a committed baseline.

The framework's SYSTEM_PROMPT is the audit anchor referenced by every
record's ``agent_version`` (12-char prefix) and
``determinism_attestation.system_prompt_hash`` (full 64-char). Changing
the prompt without bumping the framework version would silently shift
the audit anchor: every new record carries a different hash from
records produced an hour ago, with no version change to explain why.

This gate runs in CI on every push. It compares the current
SYSTEM_PROMPT_HASH against the value committed to
``baselines/system_prompt_hash.txt``. A mismatch fails the build.

Acceptable workflows to update the prompt:

1. Edit the prompt + run ``scripts/check_system_prompt_hash.py
   --update-baseline`` + commit the new baseline file.
2. The commit includes the prompt edit AND the baseline regen in the
   same change set.
3. The version bump in ``_version.py`` documents the audit-anchor
   change (e.g. "system prompt revised to add Annex IV reference").

Exits 0 on match, 1 on mismatch, 2 on file-not-found or other error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
BASELINE_PATH = REPO_ROOT / "baselines" / "system_prompt_hash.txt"


def _load_baseline() -> str:
    if not BASELINE_PATH.exists():
        print(
            f"ERROR: baseline file not found at {BASELINE_PATH}. "
            "Run --update-baseline to create it.",
            file=sys.stderr,
        )
        sys.exit(2)
    return BASELINE_PATH.read_text(encoding="utf-8").strip()


def _write_baseline(value: str) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(value + "\n", encoding="utf-8")
    print(f"Wrote baseline to {BASELINE_PATH}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--update-baseline", action="store_true",
        help=(
            "Overwrite the committed baseline with the current "
            "SYSTEM_PROMPT_HASH. Use ONLY when the prompt was "
            "intentionally edited; commit the baseline change "
            "alongside the prompt change."
        ),
    )
    args = parser.parse_args(argv)

    # Import after argparse so a --help call doesn't pull in pydantic-ai
    # and the rest of the agent stack.
    from agent.agent import SYSTEM_PROMPT_HASH, SYSTEM_PROMPT_HASH_FULL

    current = SYSTEM_PROMPT_HASH_FULL
    if args.update_baseline:
        _write_baseline(current)
        return 0

    baseline = _load_baseline()
    if current != baseline:
        print(
            f"FAIL: SYSTEM_PROMPT_HASH mismatch.\n"
            f"  baseline: {baseline}\n"
            f"  current:  {current}\n"
            f"  prefix:   {SYSTEM_PROMPT_HASH}\n"
            "The committed prompt baseline does not match the running "
            "prompt's SHA-256. Either the prompt was edited (intended: "
            "re-run with --update-baseline and commit both changes "
            "together) or unintended drift exists (investigate the "
            "diff in agent/agent.py SYSTEM_PROMPT).",
            file=sys.stderr,
        )
        return 1

    print(f"OK: SYSTEM_PROMPT_HASH matches baseline ({current[:16]}...).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
