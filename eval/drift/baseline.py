"""Baseline file persistence for drift detection.

The drift checker compares current decisions against a baseline. The
baseline lives at ``eval/baselines/demo-scenarios.baseline.jsonl``,
checked into the repo, and is regenerated explicitly via
``scripts/check_drift.py --update-baseline`` when a maintainer
accepts a drift as intentional.

Baseline file format:

- JSONL: one line per scenario, plus optional ``#`` comment lines
- Each line is a JSON object with ``id`` (the scenario identifier)
  and ``record`` (the full TriageRecord that the framework produced
  for that scenario at baseline time)
- File header is a comment block recording when the baseline was last
  regenerated and the framework version at the time

This is intentionally a simple format. The drift check reads it,
compares per-scenario, and reports differences. The baseline is not
itself audit material; it is internal QA scaffolding.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.output_models import TriageRecord


__all__ = [
    "DEFAULT_BASELINE_PATH",
    "BaselineLoadError",
    "load_baselines",
    "save_baselines",
]


DEFAULT_BASELINE_PATH: Path = (
    Path(__file__).parent.parent / "baselines" / "demo-scenarios.baseline.jsonl"
)
"""Default location for the demo scenarios baseline file.

Resolves relative to the eval package, so this works regardless of
the caller's working directory.
"""


class BaselineLoadError(Exception):
    """Raised when a baseline file cannot be parsed.

    Causes:

    - File not found
    - Line is not valid JSON
    - JSON object does not have the expected ``id`` + ``record`` shape
    - The ``record`` payload does not validate as a TriageRecord
    """


def load_baselines(path: Path = DEFAULT_BASELINE_PATH) -> dict[str, TriageRecord]:
    """Load baseline records from a JSONL file.

    Args:
        path: Path to the baseline JSONL file. Defaults to the
            module-level ``DEFAULT_BASELINE_PATH``.

    Returns:
        Dict mapping scenario_id to TriageRecord.

    Raises:
        BaselineLoadError: For any failure listed on the exception class.
    """
    if not path.exists():
        raise BaselineLoadError(
            f"Baseline file not found: {path}. Run "
            f"'python scripts/check_drift.py --update-baseline' to "
            f"create one."
        )

    baselines: dict[str, TriageRecord] = {}
    for line_num, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BaselineLoadError(
                f"Line {line_num} of {path} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise BaselineLoadError(
                f"Line {line_num} of {path} is not a JSON object."
            )
        if "id" not in payload or "record" not in payload:
            raise BaselineLoadError(
                f"Line {line_num} of {path} missing 'id' or 'record' key."
            )

        scenario_id = payload["id"]
        record_dict = payload["record"]

        # Parse decision_timestamp from ISO 8601 string to aware datetime.
        if isinstance(record_dict.get("decision_timestamp"), str):
            record_dict["decision_timestamp"] = datetime.fromisoformat(
                record_dict["decision_timestamp"].replace("Z", "+00:00")
            )
        # Also handle revoked_at when present
        if isinstance(record_dict.get("revoked_at"), str):
            record_dict["revoked_at"] = datetime.fromisoformat(
                record_dict["revoked_at"].replace("Z", "+00:00")
            )

        try:
            record = TriageRecord(**record_dict)
        except Exception as exc:
            raise BaselineLoadError(
                f"Line {line_num} of {path}: record does not validate "
                f"as a TriageRecord: {exc}"
            ) from exc
        baselines[scenario_id] = record
    return baselines


def save_baselines(
    baselines: dict[str, TriageRecord],
    path: Path = DEFAULT_BASELINE_PATH,
    framework_version: Optional[str] = None,
) -> Path:
    """Write baseline records to a JSONL file.

    Generates a comment header block recording the regeneration timestamp
    and framework version, followed by one JSON line per scenario.

    Args:
        baselines: Map of scenario_id to TriageRecord.
        path: Destination path. The parent directory is created if needed.
        framework_version: Framework version string to record in the
            header. Defaults to the framework's current FRAMEWORK_VERSION
            (single source of truth in ``_version.py``).

    Returns:
        The path written to.
    """
    if framework_version is None:
        from _version import FRAMEWORK_VERSION
        framework_version = FRAMEWORK_VERSION

    path.parent.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header_lines = [
        "# demo-scenarios.baseline.jsonl",
        f"# Drift detection baseline. Last regenerated: {now_iso}.",
        f"# Framework version at regeneration: {framework_version}.",
        "#",
        "# Each line is a JSON object: {\"id\": \"<scenario-id>\",",
        "# \"record\": <TriageRecord dict>}. Regenerate via",
        "# 'python scripts/check_drift.py --update-baseline'.",
        "",
    ]

    record_lines: list[str] = []
    # Sort by scenario_id for deterministic file content
    for scenario_id in sorted(baselines.keys()):
        record = baselines[scenario_id]
        payload = {
            "id": scenario_id,
            "record": record.model_dump(mode="json", exclude_none=True),
        }
        record_lines.append(json.dumps(payload, sort_keys=True))

    content = "\n".join(header_lines + record_lines) + "\n"
    path.write_text(content)
    return path
