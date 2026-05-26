"""JSONL dataset of AttackExamples with content-hash provenance.

Parallel to ``eval/dataset.py`` (the graded-example dataset for tier
classification), the AttackDataset loads one attack per JSONL line,
records a content_hash for audit traceability, and surfaces helpful
errors on malformed input.

Usage::

    from eval.attacks import load_attack_dataset

    dataset = load_attack_dataset("eval/datasets/prompt-injection-baseline.jsonl")
    print(f"loaded {len(dataset.attacks)} attacks, hash={dataset.content_hash}")
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.attacks.attack_example import AttackExample


__all__ = [
    "AttackDataset",
    "AttackDatasetError",
    "load_attack_dataset",
]


class AttackDatasetError(Exception):
    """Raised when an attack dataset file cannot be parsed.

    Carries the file path and line number where parsing failed so the
    dataset author can fix the offending entry directly.
    """


class AttackDataset(BaseModel):
    """An in-memory attack dataset with content-hash provenance.

    Attributes:
        path: Filesystem path the dataset was loaded from.
        attacks: The parsed AttackExample list, in JSONL line order.
        content_hash: SHA-256 of the raw JSONL bytes, formatted
            ``sha256:<hex>``. Lets a report reference the exact dataset
            version used at run time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    path: str
    attacks: list[AttackExample]
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


def load_attack_dataset(path: Union[str, Path]) -> AttackDataset:
    """Load an attack dataset from a JSONL file.

    One attack per line. Blank lines and lines starting with '#' are
    permitted (skipped) so dataset authors can group attacks with
    comments. The content_hash is computed over the raw file bytes
    (including comments and blank lines) so a comment change registers
    as a dataset change.

    Args:
        path: Filesystem path to the JSONL file.

    Returns:
        An AttackDataset with the parsed attacks and a content_hash.

    Raises:
        AttackDatasetError: If the file does not exist, cannot be read,
            contains malformed JSON on any data line, or has an entry
            that fails AttackExample validation. The error message
            includes the file path and 1-indexed line number of the
            offending entry.
    """
    path_obj = Path(path)
    if not path_obj.is_file():
        raise AttackDatasetError(
            f"attack dataset not found: {path_obj}"
        )

    raw_bytes = path_obj.read_bytes()
    content_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    attacks: list[AttackExample] = []
    text = raw_bytes.decode("utf-8")
    for line_num, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AttackDatasetError(
                f"{path_obj}:{line_num}: invalid JSON ({exc.msg})"
            ) from exc
        try:
            attacks.append(AttackExample.model_validate(payload))
        except ValidationError as exc:
            raise AttackDatasetError(
                f"{path_obj}:{line_num}: AttackExample validation failed:\n{exc}"
            ) from exc

    if not attacks:
        raise AttackDatasetError(
            f"{path_obj}: no attack entries found "
            "(file is empty or contains only comments and blanks)"
        )

    return AttackDataset(
        path=str(path_obj),
        attacks=attacks,
        content_hash=content_hash,
    )
