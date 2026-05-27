"""``vrt render`` subcommand: render an audit pack HTML from a TriageRecord.

Usage::

    # Render to a file
    vrt render record.json --output audit-pack.html

    # Render to stdout (machine-pipeable)
    vrt render record.json

    # Override the attribution footer
    vrt render record.json --output out.html \\
        --footer "Internal use only. Confidential."

The input JSON must conform to the output contract (a
TriageRecord). The companion submission JSON is optional; when
omitted, the renderer uses placeholder vendor metadata. Supplying
the submission produces a richer rendered output (vendor name,
jurisdiction, etc.).

Exit codes:

- ``0``: render completed successfully
- ``1``: input validation failed (record JSON malformed or doesn't
  conform to the output contract)
- ``2``: setup error (record file not found, submission file not
  found, output directory unwritable)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


__all__ = ["add_arguments", "run"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``render`` arguments."""
    parser.add_argument(
        "record",
        type=Path,
        help="Path to the TriageRecord JSON file.",
    )
    parser.add_argument(
        "--submission", "-s",
        type=Path,
        default=None,
        help=(
            "Optional path to the original submission JSON. When "
            "supplied, the renderer uses vendor name, jurisdiction, "
            "and other context from the submission. Omitted: "
            "placeholder vendor metadata."
        ),
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help=(
            "Optional path to write the rendered HTML. Default: print "
            "to stdout."
        ),
    )
    parser.add_argument(
        "--footer",
        type=str,
        default=None,
        help=(
            "Override the framework's default attribution footer. "
            "Pass an empty string to suppress the footer entirely."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Render an audit pack."""
    from agent.output_models import TriageRecord
    from reporting import render_audit_pack

    if not args.record.exists():
        print(
            f"ERROR: record file not found: {args.record}",
            file=sys.stderr,
        )
        return 2

    try:
        record_dict = json.loads(args.record.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: record is not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 1

    # Parse decision_timestamp from ISO 8601 string if needed.
    if isinstance(record_dict.get("decision_timestamp"), str):
        try:
            record_dict["decision_timestamp"] = datetime.fromisoformat(
                record_dict["decision_timestamp"].replace("Z", "+00:00"),
            )
        except ValueError as exc:
            print(
                f"ERROR: decision_timestamp is not a valid RFC 3339 "
                f"datetime: {exc}",
                file=sys.stderr,
            )
            return 1
    if isinstance(record_dict.get("revoked_at"), str):
        try:
            record_dict["revoked_at"] = datetime.fromisoformat(
                record_dict["revoked_at"].replace("Z", "+00:00"),
            )
        except ValueError as exc:
            print(
                f"ERROR: revoked_at is not a valid RFC 3339 datetime: {exc}",
                file=sys.stderr,
            )
            return 1

    try:
        record = TriageRecord(**record_dict)
    except Exception as exc:
        print(
            f"ERROR: record does not validate as a TriageRecord: {exc}",
            file=sys.stderr,
        )
        return 1

    submission: dict[str, Any] = {}
    if args.submission is not None:
        if not args.submission.exists():
            print(
                f"ERROR: submission file not found: {args.submission}",
                file=sys.stderr,
            )
            return 2
        try:
            submission = json.loads(args.submission.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: submission is not valid JSON: {exc}",
                file=sys.stderr,
            )
            return 1
        if not isinstance(submission, dict):
            print(
                f"ERROR: submission must be a JSON object, got "
                f"{type(submission).__name__}",
                file=sys.stderr,
            )
            return 1

    render_kwargs: dict[str, Any] = {}
    if args.footer is not None:
        render_kwargs["attribution_footer"] = args.footer

    html_text = render_audit_pack(record, submission, **render_kwargs)

    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(html_text, encoding="utf-8")
        except OSError as exc:
            print(
                f"ERROR: could not write output: {exc}",
                file=sys.stderr,
            )
            return 2
        print(f"Audit pack written to: {args.output}")
    else:
        print(html_text)

    return 0
