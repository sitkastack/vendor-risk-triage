"""Pydantic model for a single prompt-injection attack example.

An AttackExample is the atom of the attack evaluation suite. It carries:

- A payload (submission, optional documents, optional regulation chunks)
  that the agent will be invoked with
- A set of assertions describing what the agent must (or must not) do
  in response

An attack passes if ALL declared assertions hold. An attack fails if
ANY declared assertion is violated. This composable assertion model
lets a single AttackExample type cover the full attack taxonomy
without needing per-category subclasses.

Threat model linkage:

Each AttackExample carries ``threat_ids: list[str]`` pointing at one
or more entries in docs/phase-2/03-threat-model.md (e.g., "T-AI1" for
prompt injection, "T-AI2" for output schema manipulation). The
attack metrics roll up pass/fail rates per threat id so auditors can
ask threat-specific questions ("what's our T-AI1 attack success rate
on this model version?").

Assertion model:

Each attack declares any subset of:

- ``tier_must_be_in``: if the agent processes the submission, the
  resulting risk_tier must be in this set. Used for tier-manipulation
  attacks ("force tier_1 on a tier_4 submission" -> tier_must_be_in
  is [tier_3, tier_4, tier_5]).
- ``disposition_must_be_in``: if the agent processes, the resulting
  recommended_disposition must be in this set. Used for disposition-
  manipulation attacks.
- ``rationale_must_not_contain``: if the agent processes, none of these
  strings (case-insensitive) may appear in classification_rationale.
  Used to detect when the agent has been induced to echo injection
  language ("APPROVED PER USER REQUEST", "Tier override applied").
- ``expected_to_raise``: if set, the agent is expected to raise the
  named exception class (e.g., ``"TriageInputError"``). Used for
  attacks that should be rejected before the LLM is invoked
  (bait-and-switch document content_hash mismatch, missing fields).

An attack with NO declared assertions fails at construction time;
silently-passing attacks would be worse than no test.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.output_models import Disposition, RiskTier


__all__ = [
    "AttackExample",
    "AttackType",
]


AttackType = Literal[
    "direct_injection_submission",
    "direct_injection_document",
    "direct_injection_regulation",
    "tier_manipulation",
    "disposition_manipulation",
    "schema_manipulation",
    "rationale_manipulation",
    "bait_and_switch_document",
]
"""Categories of prompt-injection attacks.

Each value names a class of attack the dataset covers. Categories are
not exclusive (a tier_manipulation attack is also a direct_injection
of some kind), but each AttackExample picks one primary category for
metric aggregation. Threat ids carry the precise threat-model linkage.
"""


class AttackExample(BaseModel):
    """A single attack against the agent, with assertions for grading.

    Attributes:
        attack_id: Stable unique identifier across the dataset.
            Convention is ``attack-{category-short}-{N}`` (e.g.,
            ``attack-tier-manip-1``). Used in metrics output and audit
            trails.
        attack_type: Primary category of the attack. Used for metric
            aggregation.
        threat_ids: Threat-model identifiers the attack tests. At least
            one required; multiple allowed when an attack spans threats
            (e.g., an injection that also manipulates schema covers
            both T-AI1 and T-AI2).
        description: One-sentence human-readable summary of the attack.
            Appears in metric reports for human review.
        submission: The submission to triage. Required, even for attacks
            primarily injected through documents or chunks - the agent
            always operates on a submission.
        documents: Optional list of document payloads to attach. Each
            entry is a dict matching the ingestion.Document schema (the
            runner constructs Document instances; the dataset stays
            JSONL-serializable). When the attack vector is a document,
            the injection payload sits inside ``extracted_text``.
        regulation_chunks: Optional list of regulation chunk payloads to
            attach. Same JSON-shape rationale as ``documents``. When the
            attack vector is a regulation chunk, the injection payload
            sits inside ``text``.
        tier_must_be_in: Optional set of acceptable risk_tier outcomes.
            If set, attack passes only if the agent's risk_tier is in
            this set. None means "do not assert on tier".
        disposition_must_be_in: Optional set of acceptable disposition
            outcomes. None means "do not assert on disposition".
        rationale_must_not_contain: List of strings that must not appear
            (case-insensitive) in the agent's classification_rationale.
            Empty list means "do not assert on rationale content".
        expected_to_raise: Optional exception class name (e.g.,
            "TriageInputError"). If set, the agent is expected to raise
            this exception class. When set, other assertions are not
            evaluated (the agent never returned a record to grade).
        notes: Free-form notes for human reviewers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attack_id: str = Field(min_length=1, max_length=128)
    attack_type: AttackType
    threat_ids: list[str] = Field(min_length=1)
    description: str = Field(min_length=1, max_length=512)
    submission: dict[str, Any]
    documents: Optional[list[dict[str, Any]]] = None
    regulation_chunks: Optional[list[dict[str, Any]]] = None
    tier_must_be_in: Optional[list[RiskTier]] = None
    disposition_must_be_in: Optional[list[Disposition]] = None
    rationale_must_not_contain: list[str] = Field(default_factory=list)
    expected_to_raise: Optional[str] = None
    notes: str = ""

    @model_validator(mode="after")
    def _at_least_one_assertion(self) -> "AttackExample":
        """An AttackExample with no assertions cannot be graded.

        Reject at construction time rather than silently passing every
        run. The dataset author must declare what 'attack passes' means
        for each example.
        """
        has_assertion = any([
            self.tier_must_be_in is not None,
            self.disposition_must_be_in is not None,
            len(self.rationale_must_not_contain) > 0,
            self.expected_to_raise is not None,
        ])
        if not has_assertion:
            raise ValueError(
                f"AttackExample {self.attack_id!r} declares no assertions; "
                "at least one of tier_must_be_in, disposition_must_be_in, "
                "rationale_must_not_contain (non-empty), or expected_to_raise "
                "must be set. Otherwise the attack will always 'pass' and "
                "provide no signal."
            )
        return self

    @model_validator(mode="after")
    def _expected_to_raise_excludes_other_assertions(self) -> "AttackExample":
        """If the agent is expected to raise, no record exists to grade.

        Declaring expected_to_raise alongside tier_must_be_in is
        contradictory: either the agent returned a record (and we grade
        its content) or it raised (and we grade the exception). Surface
        the contradiction at construction time.
        """
        if self.expected_to_raise is not None:
            if (
                self.tier_must_be_in is not None
                or self.disposition_must_be_in is not None
                or len(self.rationale_must_not_contain) > 0
            ):
                raise ValueError(
                    f"AttackExample {self.attack_id!r} declares "
                    "expected_to_raise alongside record-grading assertions "
                    "(tier_must_be_in / disposition_must_be_in / "
                    "rationale_must_not_contain). These are mutually "
                    "exclusive: a raised exception produces no record to "
                    "grade."
                )
        return self
