"""Shared output helpers for CLI subcommands.

Color, formatting, and human-readable summary rendering live here so
each subcommand presents output consistently.

Color choices follow ANSI 16-color codes (broadly supported, no
truecolor dependency). Colors auto-disable when:

- ``NO_COLOR`` environment variable is set (per https://no-color.org)
- Output is not a TTY (piping to a file or another command)

This keeps the JSON-piping workflow clean: ``vrt triage in.json | jq``
gets raw JSON without ANSI escape codes polluting the stream.
"""
from __future__ import annotations

import os
import sys
from typing import Any


__all__ = [
    "DISPOSITION_COLORS",
    "TIER_COLORS",
    "color",
    "is_color_enabled",
    "print_summary",
]


# ANSI 16-color codes used for disposition and tier coloring.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_COLORS: dict[str, str] = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "red": "\033[31m",
    "white": "\033[37m",
    "bright_green": "\033[92m",
    "bright_yellow": "\033[93m",
    "bright_red": "\033[91m",
    "bright_cyan": "\033[96m",
}


DISPOSITION_COLORS: dict[str, str] = {
    "approve": "green",
    "conditional_approve": "cyan",
    "escalate_senior_review": "yellow",
    "reject": "red",
}
"""Per-disposition color for the summary line. Matches the audit pack
banner accent colors (green/teal-ish/amber/burgundy) translated into
ANSI."""

TIER_COLORS: dict[str, str] = {
    "tier_1_low": "green",
    "tier_2_moderate": "cyan",
    "tier_3_elevated": "yellow",
    "tier_4_high": "red",
}
"""Per-tier color used in the summary line."""


def is_color_enabled() -> bool:
    """Decide whether to emit ANSI color codes.

    Honors the NO_COLOR convention (https://no-color.org) and disables
    color when stdout is not a TTY (e.g., when piped). The check is
    deliberately conservative; CLIs that emit color into non-TTY
    streams break downstream tooling.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def color(text: str, name: str, *, bold: bool = False) -> str:
    """Wrap text in an ANSI color code, if color is enabled.

    Args:
        text: The text to color.
        name: Color name from ``_COLORS``. Unknown names pass through
            uncolored (defensive; avoids raising on a typo in a CLI
            handler).
        bold: Apply bold attribute in addition to color.

    Returns:
        Text wrapped in ANSI escapes when color is enabled, plain text
        otherwise.
    """
    if not is_color_enabled():
        return text
    code = _COLORS.get(name, "")
    if not code:
        return text
    prefix = _BOLD + code if bold else code
    return f"{prefix}{text}{_RESET}"


def print_summary(
    record: dict[str, Any],
    *,
    elapsed_seconds: float | None = None,
    file=None,
) -> None:
    """Print a human-readable summary of a TriageRecord dict.

    Used by ``vrt triage`` to give a prospect/developer immediate
    visual feedback when they run the agent without ``--output``.
    The full JSON record is suppressed in favor of the highlights.

    Args:
        record: A TriageRecord serialized to a dict
            (``record.model_dump(mode="json")``).
        elapsed_seconds: Optional wall-clock duration for the run,
            displayed as a footer line.
        file: Output stream. Defaults to stdout.
    """
    out = file if file is not None else sys.stdout

    tier = record.get("risk_tier", "unknown")
    disposition = record.get("recommended_disposition", "unknown")
    confidence = record.get("confidence_signal", {})
    score = confidence.get("score", 0.0)
    interpretation = confidence.get("interpretation", "unknown")
    decision_id = record.get("decision_id", "<no decision_id>")
    rationale = record.get("classification_rationale", "")

    tier_label = _humanize_tier(tier)
    disp_label = _humanize_disposition(disposition)

    print(file=out)
    print(
        color("=" * 72, "white"),
        file=out,
    )
    print(
        color("Vendor risk triage decision", "white", bold=True),
        file=out,
    )
    print(
        color("=" * 72, "white"),
        file=out,
    )
    print(file=out)
    print(
        f"  Tier:        "
        f"{color(tier_label, TIER_COLORS.get(tier, 'white'), bold=True)}",
        file=out,
    )
    print(
        f"  Disposition: "
        f"{color(disp_label, DISPOSITION_COLORS.get(disposition, 'white'), bold=True)}",
        file=out,
    )
    print(
        f"  Confidence:  {score:.2f} ({interpretation})",
        file=out,
    )
    print(file=out)
    print(
        f"  Decision ID: "
        f"{color(decision_id, 'white')}",
        file=out,
    )

    accountable_owner = record.get("accountable_owner")
    if accountable_owner:
        print(f"  Owner:       {accountable_owner}", file=out)

    review_interval = record.get("review_interval_days")
    if review_interval is not None:
        print(f"  Next review: {review_interval} days", file=out)

    if rationale:
        print(file=out)
        print(color("  Rationale:", "white", bold=True), file=out)
        for line in _wrap(rationale, width=68):
            print(f"    {line}", file=out)

    mitigations = record.get("required_mitigations") or []
    if mitigations:
        print(file=out)
        print(color("  Required mitigations:", "white", bold=True), file=out)
        for i, mit in enumerate(mitigations, 1):
            for j, line in enumerate(_wrap(mit, width=66)):
                prefix = f"    {i}. " if j == 0 else "       "
                print(f"{prefix}{line}", file=out)

    if elapsed_seconds is not None:
        print(file=out)
        print(
            color(f"  Completed in {elapsed_seconds:.2f}s", "white"),
            file=out,
        )
    print(file=out)


def _humanize_tier(tier: str) -> str:
    """Render a tier enum value as 'Tier N (label)'."""
    mapping = {
        "tier_1_low": "Tier 1 (low)",
        "tier_2_moderate": "Tier 2 (moderate)",
        "tier_3_elevated": "Tier 3 (elevated)",
        "tier_4_high": "Tier 4 (high)",
    }
    return mapping.get(tier, tier)


def _humanize_disposition(disposition: str) -> str:
    """Render a disposition enum value as a readable phrase."""
    mapping = {
        "approve": "Approve",
        "conditional_approve": "Conditional approval",
        "escalate_senior_review": "Escalate to senior review",
        "reject": "Reject",
    }
    return mapping.get(disposition, disposition)


def _wrap(text: str, width: int) -> list[str]:
    """Word-wrap text to the given width. Newlines preserved.

    A pragmatic wrapper that avoids the textwrap module's quirks with
    long URLs and code-shaped tokens. Lines longer than width are
    truncated to a word boundary; very long tokens stay on their own
    line.
    """
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            if not current:
                current = word
                continue
            if len(current) + 1 + len(word) <= width:
                current = f"{current} {word}"
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if not paragraph:
            lines.append("")
    return lines
