"""Graded example dataset model and loader for the eval harness.

A graded example pairs a vendor submission (conforming to the Phase 1 input
contract) with the tier and disposition a human expert reviewer agreed the
agent should produce. Running the agent against a dataset of graded
examples produces an EvalReport showing where the agent agrees and
disagrees with the expert grades.

Dataset format: JSONL (one example per line). The format choice is
deliberate:

- Each line is self-contained and parseable in isolation.
- ``git diff`` on a dataset file shows added or changed examples cleanly.
- ``grep`` filters work directly on the file (find every tier_4 example,
  count examples that process PII, etc.).
- Adding a new graded example is appending one line; no JSON-array
  bookkeeping is required.

Vendor identifier convention in shipped datasets:

The graded examples in ``datasets/tier-classification-baseline.jsonl``
use synthetic vendor ids of the form ``v-eval-{tier-marker}-{slug}``
(e.g., ``v-eval-tier1-analytics``, ``v-eval-tier4-credit``). The
``{tier-marker}`` segment is one of ``tier1``, ``tier2``, ``tier3``,
``tier4`` and indicates the expected tier as a human-readable hint.
This is a convention for synthetic eval data only; real vendor
submissions need not encode the expected tier in the id. The convention
makes the dataset's coverage visible from a ``grep`` and lets test
helpers do deterministic agent simulation without re-deriving the
expected tier from the submission body.

A graded example is intentionally minimal at MVP: id, submission, expected
tier, expected disposition, and reviewer notes. Fields that would let an
auditor reconstruct the reviewer's reasoning (multiple reviewer agreement,
disagreement notes, citation expectations) are tagged for follow-up work.

Deferred to follow-up commits within sub-system 3:

- [deferred-subsystem-3-followup] ``expected_min_evidence_count``: locking a
  lower bound on citations so the agent cannot drift to terse rationales
- [deferred-subsystem-3-followup] ``expected_framework_tags``: locking
  which regulatory framework tags the agent should produce
- [deferred-subsystem-3-followup] ``expected_required_mitigations``:
  ground-truth for conditional_approve mitigations
- [deferred-subsystem-3-followup] Multi-reviewer agreement and
  disagreement notes for examples where experts split

Deferred to Phase 4:

- [deferred-phase-4] Ground-truth confidence band per example (calibration
  measurement)
- [deferred-phase-4] LLM-as-judge fields for non-exact-match evaluation
- [deferred-phase-4] Bias attribute tags (vendor demographics, decision
  domain) for fairness analysis
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Optional

from pydantic import BaseModel, ConfigDict, Field

from agent.output_models import Disposition, RiskTier


__all__ = [
    "GradedExample",
    "Dataset",
    "load_dataset",
]


class GradedExample(BaseModel):
    """A single graded example: submission plus expected agent output.

    The ``submission`` field must be a dict conforming to the Phase 1 input
    contract at ``schemas/input-contract-1.0.0.schema.json``. This model
    does not validate against that schema (the agent does so at triage
    time, and forcing validation here would create a hard dependency from
    the eval harness on the schema's location). The loader for the
    canonical baseline dataset validates submissions explicitly at load
    time; callers building datasets in code should validate before
    constructing a GradedExample.

    Attributes:
        id: Stable identifier for this example. Required to be unique
            within a dataset (the loader enforces this). The id appears in
            the EvalReport and is the primary handle for talking about
            specific examples in audit and review.
        submission: The vendor submission dict. Passed to the agent as-is.
        expected_tier: The risk tier a human reviewer agreed the agent
            should produce.
        expected_disposition: The disposition a human reviewer agreed the
            agent should produce. Conditional on expected_tier per the v0.4
            taxonomy (for example, tier_2_moderate expects
            conditional_approve).
        reviewer_notes: Free-text from the human grader explaining why
            this tier and disposition are the right answer. Captured for
            audit reconstruction; not consumed by the runner.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    submission: dict[str, Any]
    expected_tier: RiskTier
    expected_disposition: Disposition
    reviewer_notes: str = Field(min_length=1, max_length=4000)


class Dataset(BaseModel):
    """A named collection of graded examples plus identity metadata.

    A Dataset is immutable once loaded. Its ``content_hash`` is a SHA-256
    over the canonicalized JSONL contents and is recorded in every
    EvalReport so an auditor can verify a given report was produced
    against a known dataset version.

    Attributes:
        name: Short identifier for the dataset (matches the filename
            without extension by convention).
        examples: Ordered list of graded examples. The loader rejects
            datasets with duplicate ids.
        content_hash: First 16 hex chars of SHA-256 over the canonical
            JSONL representation. Stable across loads of the same file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    examples: list[GradedExample] = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{16}$")

    def __iter__(self) -> Iterator[GradedExample]:  # type: ignore[override]
        """Iterate over examples for ergonomic ``for ex in dataset`` use."""
        return iter(self.examples)

    def __len__(self) -> int:
        """Number of graded examples in the dataset."""
        return len(self.examples)


def load_dataset(path: Path, *, name: Optional[str] = None) -> Dataset:
    """Load a JSONL dataset file into a Dataset.

    Each line in the file must be a JSON object parseable into a
    GradedExample. Empty lines and lines beginning with ``#`` (comments)
    are ignored. Duplicate example ids cause a ValueError.

    The content hash is computed over the canonical (sorted-key,
    no-whitespace) JSON serialization of every example, joined by
    newlines. This means re-ordering examples within the file does NOT
    change the hash, but changing any field of any example DOES. The
    intent is "what graded data was used", not "what file bytes were
    used"; reordering for readability should not invalidate prior eval
    reports.

    Args:
        path: Path to a JSONL file containing graded examples.
        name: Optional dataset name. If omitted, derived from the file
            stem (path.stem).

    Returns:
        A Dataset with examples in file order.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty, contains malformed JSON, or
            contains duplicate example ids.
        pydantic.ValidationError: If any example fails GradedExample
            construction.
    """
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    examples: list[GradedExample] = []
    seen_ids: set[str] = set()
    raw_text = path.read_text(encoding="utf-8")

    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}:{line_number}: malformed JSON: {exc}"
            ) from exc
        example = GradedExample.model_validate(data)
        if example.id in seen_ids:
            raise ValueError(
                f"{path}:{line_number}: duplicate example id {example.id!r}; "
                "every example id within a dataset must be unique"
            )
        seen_ids.add(example.id)
        examples.append(example)

    if not examples:
        raise ValueError(
            f"{path}: dataset contains no examples (only blank or commented lines)"
        )

    canonical = "\n".join(
        json.dumps(ex.model_dump(), sort_keys=True, separators=(",", ":"))
        for ex in examples
    )
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    return Dataset(
        name=name or path.stem,
        examples=examples,
        content_hash=content_hash,
    )
