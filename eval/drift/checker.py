"""Drift detection for vendor risk triage decisions.

Catches unexpected classification changes between framework versions.
Every time the SYSTEM_PROMPT changes, the framework version bumps,
or the eval logic shifts, the agent might produce different decisions
on the same inputs. Drift detection turns that "might" into a
verifiable check.

The check runs the deterministic FunctionModel-backed agent (the same
test double used in tests/test_demo_scenarios.py) against the five
demo scenarios, then compares each produced record to a checked-in
baseline. Any difference surfaces as drift.

This is a deterministic check. Two distinct categories of drift:

**Hard drift** (always a CI failure):

- ``risk_tier`` value changed
- ``recommended_disposition`` value changed
- ``accountable_owner`` presence changed (was None, now set, or vice versa)
- ``evidence_cited`` entry count changed
- ``regulatory_framework_tags`` set changed

Hard drift indicates a real classification change. The framework
recommended approve for vendor X yesterday and reject today; that is
not a stylistic edit, that is a workflow-relevant difference.

**Soft drift** (CI failure with bypass message):

- ``confidence_signal.score`` differs by more than ``soft_confidence_threshold``
  (default ±0.05)
- ``classification_rationale`` text differs
- ``required_mitigations`` text differs in any entry
- ``accountable_owner`` text differs
- Any ``evidence_cited`` entry's ``input_field_reference`` or
  ``reasoning`` text differs

Soft drift catches stylistic and tonal changes. A SYSTEM_PROMPT edit
that refines language without changing decisions surfaces here. The
bypass is ``scripts/check_drift.py --update-baseline``, which
regenerates the baseline file. The maintainer commits the new
baseline; the diff is reviewable.

**Always ignored** (never triggers drift):

- ``decision_timestamp`` (changes per run; not a meaningful signal)
- ``agent_version`` (changes when intentional; recorded but not diffed)
- ``decision_id`` (each run has its own)
- ``correlation_id`` (generated per-run for observability; not a
  classification signal)
- ``cost_estimate`` (per-run token usage and dollar figure; varies
  with prompt length and is not a classification signal)
- ``determinism_attestation`` data fields (effective_temperature,
  provider, effective_model_id, fallback, sampling_profile_hash,
  system_prompt_hash, corpus_bundle_hash, contract_version,
  migrated_from) — per-deployment configuration noise. The single
  field surfaced as drift is ``contract_honored``; a baseline
  that ran with ``contract_honored=True`` and a current run that
  produced ``False`` is reported as SOFT drift so an operator
  notices the contract exited.

The check does not exercise a real LLM. It uses the test-double
FunctionModel pattern from tests/test_demo_scenarios.py, with the
canned expected_record payload preserved through the framework's
pipeline. This means drift detection here catches framework changes
(record construction logic, schema validation, evidence handling),
not LLM behavior changes. Real-LLM drift is a Phase 6 deliverable
gated behind the existing ``real_llm`` marker.

Deferred:

- ``[deferred-phase-6]`` Real-LLM drift mode (``check_drift.py
  --real-llm``) that runs the actual configured LLM against the
  scenarios and compares. Costs money; requires API key; flakier
  due to LLM nondeterminism. The minimal check is the deterministic
  always-runnable version.
- ``[deferred-phase-6]`` Drift detection on a deployment's own
  scenario library (not just the framework's five demo scenarios).
  Customers would point the check at their own JSONL baseline.
- ``[deferred-phase-7]`` Continuous drift monitoring infrastructure
  (storage, scheduler, alerting). Out of scope; not framework code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from agent.output_models import TriageRecord


__all__ = [
    "DEFAULT_SOFT_CONFIDENCE_THRESHOLD",
    "DriftCategory",
    "DriftEntry",
    "DriftReport",
    "ScenarioDrift",
    "check_drift",
    "compare_records",
]


DEFAULT_SOFT_CONFIDENCE_THRESHOLD: float = 0.05
"""Confidence score delta below which differences are ignored.

The default is 0.05 (5 percentage points). A confidence shift from
0.78 to 0.81 is within threshold (soft = no drift). A shift from
0.78 to 0.85 exceeds threshold (soft drift).

Hard drift on tier/disposition is independent of this threshold;
those fields trigger regardless of any numeric tolerance.
"""


class DriftCategory(str, Enum):
    """Severity of a single drift entry."""

    HARD = "hard"
    """Real classification change: tier, disposition, presence of
    accountable_owner, evidence count, or regulatory framework tag set.
    Always a CI failure."""

    SOFT = "soft"
    """Text or numeric drift within the same classification:
    confidence delta beyond threshold, rationale text, mitigation
    text, evidence reasoning text, accountable_owner text. CI
    failure with a 'regenerate baseline if intentional' message."""


@dataclass(frozen=True)
class DriftEntry:
    """A single observed difference between baseline and current record.

    Attributes:
        category: Hard or soft.
        field_path: Dotted path to the differing field
            (e.g., ``risk_tier``, ``confidence_signal.score``,
            ``evidence_cited[0].reasoning``).
        baseline_value: The value recorded in the baseline.
        current_value: The value produced in the current run.
        message: Human-readable explanation of the drift.
    """

    category: DriftCategory
    field_path: str
    baseline_value: Any
    current_value: Any
    message: str


@dataclass(frozen=True)
class ScenarioDrift:
    """Drift entries for one scenario.

    Attributes:
        scenario_id: The scenario's stable identifier (matches the
            ``id`` field in the JSONL dataset).
        entries: All drift entries (hard and soft) for this scenario.
            Empty list means no drift detected.
    """

    scenario_id: str
    entries: list[DriftEntry] = field(default_factory=list)

    @property
    def has_hard_drift(self) -> bool:
        return any(e.category == DriftCategory.HARD for e in self.entries)

    @property
    def has_soft_drift(self) -> bool:
        return any(e.category == DriftCategory.SOFT for e in self.entries)

    @property
    def has_any_drift(self) -> bool:
        return len(self.entries) > 0


@dataclass(frozen=True)
class DriftReport:
    """Drift detection report across all scenarios.

    Attributes:
        scenarios: Per-scenario drift results. Always one entry per
            checked scenario; entries with empty drift lists mean
            "no drift on this scenario."
        soft_confidence_threshold: The threshold used for this run.
            Recorded for traceability.
    """

    scenarios: list[ScenarioDrift]
    soft_confidence_threshold: float

    @property
    def total_scenarios(self) -> int:
        return len(self.scenarios)

    @property
    def scenarios_with_hard_drift(self) -> int:
        return sum(1 for s in self.scenarios if s.has_hard_drift)

    @property
    def scenarios_with_soft_drift(self) -> int:
        return sum(1 for s in self.scenarios if s.has_soft_drift)

    @property
    def total_entries(self) -> int:
        return sum(len(s.entries) for s in self.scenarios)

    @property
    def has_hard_drift(self) -> bool:
        return any(s.has_hard_drift for s in self.scenarios)

    @property
    def has_any_drift(self) -> bool:
        return any(s.has_any_drift for s in self.scenarios)


def compare_records(
    baseline: TriageRecord,
    current: TriageRecord,
    soft_confidence_threshold: float = DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
) -> list[DriftEntry]:
    """Compare two TriageRecords field by field.

    Args:
        baseline: The recorded "expected" record.
        current: The record produced by the current framework run.
        soft_confidence_threshold: Confidence-score delta below which
            differences are ignored. Defaults to
            ``DEFAULT_SOFT_CONFIDENCE_THRESHOLD`` (0.05).

    Returns:
        A list of DriftEntry objects, one per observed difference.
        Empty list means no drift. Each entry is categorized as HARD
        or SOFT per the module docstring's rules.

    The function does NOT diff:

    - ``decision_id`` (each run has its own)
    - ``decision_timestamp`` (changes per run)
    - ``agent_version`` (changes when intentional; not a drift signal)
    - ``correlation_id`` (generated per-run for observability; not a
      classification signal)
    - ``cost_estimate`` (per-run token usage and dollar figure; varies
      with prompt length and is not a classification signal)
    - ``input_submission_id`` (input-dependent, not framework drift)
    - ``input_schema_version`` (would be a schema migration, not drift)
    - ``output_schema_version`` (same)
    - ``extension_schema_version`` (deployment-specific)
    - ``supersedes`` (deployment-specific)
    - ``revoked_at`` / ``revocation_reason`` (deployment events, not framework)
    - ``review_interval_days`` (treated as policy-derived, not framework drift)
    """
    entries: list[DriftEntry] = []

    # Hard drift: risk_tier
    if _enum_value(baseline.risk_tier) != _enum_value(current.risk_tier):
        entries.append(DriftEntry(
            category=DriftCategory.HARD,
            field_path="risk_tier",
            baseline_value=_enum_value(baseline.risk_tier),
            current_value=_enum_value(current.risk_tier),
            message="Risk tier changed.",
        ))

    # Hard drift: recommended_disposition
    if (
        _enum_value(baseline.recommended_disposition)
        != _enum_value(current.recommended_disposition)
    ):
        entries.append(DriftEntry(
            category=DriftCategory.HARD,
            field_path="recommended_disposition",
            baseline_value=_enum_value(baseline.recommended_disposition),
            current_value=_enum_value(current.recommended_disposition),
            message="Recommended disposition changed.",
        ))

    # Hard drift: accountable_owner presence (None vs set)
    baseline_has_owner = baseline.accountable_owner is not None
    current_has_owner = current.accountable_owner is not None
    if baseline_has_owner != current_has_owner:
        entries.append(DriftEntry(
            category=DriftCategory.HARD,
            field_path="accountable_owner",
            baseline_value="<set>" if baseline_has_owner else None,
            current_value="<set>" if current_has_owner else None,
            message=(
                "Accountable owner presence changed (a record gained "
                "or lost its owner). This indicates a workflow change."
            ),
        ))
    elif (
        baseline_has_owner
        and current_has_owner
        and baseline.accountable_owner != current.accountable_owner
    ):
        # Both set, but text differs: soft drift
        entries.append(DriftEntry(
            category=DriftCategory.SOFT,
            field_path="accountable_owner",
            baseline_value=baseline.accountable_owner,
            current_value=current.accountable_owner,
            message="Accountable owner text differs.",
        ))

    # Hard drift: evidence_cited count
    baseline_evidence_count = len(baseline.evidence_cited)
    current_evidence_count = len(current.evidence_cited)
    if baseline_evidence_count != current_evidence_count:
        entries.append(DriftEntry(
            category=DriftCategory.HARD,
            field_path="evidence_cited",
            baseline_value=f"{baseline_evidence_count} citations",
            current_value=f"{current_evidence_count} citations",
            message=(
                "Evidence citation count changed. A citation was added "
                "or removed; this materially changes the audit trail."
            ),
        ))
    else:
        # Same count: check per-entry text for soft drift
        for i, (b_ev, c_ev) in enumerate(
            zip(baseline.evidence_cited, current.evidence_cited)
        ):
            if b_ev.input_field_reference != c_ev.input_field_reference:
                entries.append(DriftEntry(
                    category=DriftCategory.SOFT,
                    field_path=f"evidence_cited[{i}].input_field_reference",
                    baseline_value=b_ev.input_field_reference,
                    current_value=c_ev.input_field_reference,
                    message=(
                        "Evidence citation field reference changed. "
                        "Same number of citations but pointing at "
                        "different fields."
                    ),
                ))
            if b_ev.reasoning != c_ev.reasoning:
                entries.append(DriftEntry(
                    category=DriftCategory.SOFT,
                    field_path=f"evidence_cited[{i}].reasoning",
                    baseline_value=b_ev.reasoning,
                    current_value=c_ev.reasoning,
                    message="Evidence citation reasoning text differs.",
                ))

    # Hard drift: regulatory_framework_tags set
    baseline_tags = set(baseline.regulatory_framework_tags or [])
    current_tags = set(current.regulatory_framework_tags or [])
    if baseline_tags != current_tags:
        entries.append(DriftEntry(
            category=DriftCategory.HARD,
            field_path="regulatory_framework_tags",
            baseline_value=sorted(baseline_tags),
            current_value=sorted(current_tags),
            message=(
                "Regulatory framework tag set changed. The framework "
                "engaged a different set of regulations on this "
                "scenario than the baseline recorded."
            ),
        ))

    # Soft drift: confidence_signal.score delta
    # Use a small absolute tolerance to avoid float-arithmetic edge cases
    # (e.g., abs(0.80 - 0.75) computes as ~0.050000000000000044). The
    # tolerance is 1e-9, far below any meaningful drift threshold.
    baseline_score = float(baseline.confidence_signal.score)
    current_score = float(current.confidence_signal.score)
    score_delta = abs(current_score - baseline_score)
    if score_delta > soft_confidence_threshold + 1e-9:
        entries.append(DriftEntry(
            category=DriftCategory.SOFT,
            field_path="confidence_signal.score",
            baseline_value=baseline_score,
            current_value=current_score,
            message=(
                f"Confidence score shifted by {score_delta:.3f} "
                f"(threshold {soft_confidence_threshold:.3f})."
            ),
        ))

    # Soft drift: classification_rationale
    if baseline.classification_rationale != current.classification_rationale:
        entries.append(DriftEntry(
            category=DriftCategory.SOFT,
            field_path="classification_rationale",
            baseline_value=_truncate(baseline.classification_rationale),
            current_value=_truncate(current.classification_rationale),
            message="Classification rationale text differs.",
        ))

    # Soft drift: required_mitigations
    baseline_mitigations = list(baseline.required_mitigations or [])
    current_mitigations = list(current.required_mitigations or [])
    # If counts differ AND both are non-empty, soft drift (count differences
    # within the mitigations set itself; presence-vs-absence is a hard signal
    # implicitly tied to disposition, which we already check).
    if baseline_mitigations != current_mitigations:
        # Detect: are both present but different, or did one go from
        # empty/None to non-empty?
        if not baseline_mitigations and current_mitigations:
            entries.append(DriftEntry(
                category=DriftCategory.SOFT,
                field_path="required_mitigations",
                baseline_value=None,
                current_value=f"{len(current_mitigations)} mitigations",
                message="Required mitigations added where none were before.",
            ))
        elif baseline_mitigations and not current_mitigations:
            entries.append(DriftEntry(
                category=DriftCategory.SOFT,
                field_path="required_mitigations",
                baseline_value=f"{len(baseline_mitigations)} mitigations",
                current_value=None,
                message="Required mitigations removed.",
            ))
        else:
            entries.append(DriftEntry(
                category=DriftCategory.SOFT,
                field_path="required_mitigations",
                baseline_value=f"{len(baseline_mitigations)} mitigations",
                current_value=f"{len(current_mitigations)} mitigations",
                message=(
                    "Required mitigations text differs. Count or "
                    "content changed."
                ),
            ))

    # Soft drift: determinism_attestation.contract_honored
    # Only this single field is diffed (the rest of the attestation is
    # per-deployment instance noise). A False-to-True or True-to-False
    # flip means the deployment's contract posture changed; operators
    # need to notice this even if the classification stayed the same.
    baseline_attestation = getattr(baseline, "determinism_attestation", None)
    current_attestation = getattr(current, "determinism_attestation", None)
    if baseline_attestation is not None and current_attestation is not None:
        baseline_honored = baseline_attestation.contract_honored
        current_honored = current_attestation.contract_honored
        if baseline_honored != current_honored:
            entries.append(DriftEntry(
                category=DriftCategory.SOFT,
                field_path="determinism_attestation.contract_honored",
                baseline_value=baseline_honored,
                current_value=current_honored,
                message=(
                    "Determinism contract_honored flipped. The "
                    "deployment's contract posture changed between "
                    "baseline and current. Review the attestation's "
                    "fallback / temperature / system_prompt_hash to "
                    "identify which exit condition triggered."
                ),
            ))

    return entries


def check_drift(
    baselines: dict[str, TriageRecord],
    currents: dict[str, TriageRecord],
    soft_confidence_threshold: float = DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
) -> DriftReport:
    """Run drift comparison across a set of scenarios.

    Args:
        baselines: Map of scenario_id to baseline TriageRecord. The
            "expected" decisions.
        currents: Map of scenario_id to current TriageRecord. The
            decisions just produced by the framework.
        soft_confidence_threshold: As in ``compare_records``.

    Returns:
        A DriftReport with one ScenarioDrift entry per scenario in
        ``baselines``.

    Behavior on missing scenarios:

    - A scenario in ``baselines`` but not ``currents``: recorded as
      hard drift with a "scenario missing from current run" entry.
    - A scenario in ``currents`` but not ``baselines``: ignored (the
      baseline is the source of truth for what should be checked).
      Add to the baseline explicitly to start checking it.
    """
    scenarios: list[ScenarioDrift] = []
    for scenario_id, baseline in baselines.items():
        if scenario_id not in currents:
            scenarios.append(ScenarioDrift(
                scenario_id=scenario_id,
                entries=[DriftEntry(
                    category=DriftCategory.HARD,
                    field_path="<scenario>",
                    baseline_value="<present in baseline>",
                    current_value="<missing from current run>",
                    message=(
                        "Scenario is in the baseline but not in the "
                        "current run. The drift runner did not produce "
                        "a record for this scenario."
                    ),
                )],
            ))
            continue
        entries = compare_records(
            baseline=baseline,
            current=currents[scenario_id],
            soft_confidence_threshold=soft_confidence_threshold,
        )
        scenarios.append(ScenarioDrift(
            scenario_id=scenario_id,
            entries=entries,
        ))
    return DriftReport(
        scenarios=scenarios,
        soft_confidence_threshold=soft_confidence_threshold,
    )


# -- helpers --------------------------------------------------------------


def _enum_value(value: Any) -> str:
    """Extract the .value from an enum, or pass through a string."""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate long text for display in drift entries."""
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."
