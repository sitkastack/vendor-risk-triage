"""Tests for Phase 5 sub-system 3: demo vendor submissions.

These tests verify that the five hand-curated demo scenarios are:

1. Loaded correctly from the JSONL dataset
2. Schema-valid (inputs against the input contract, outputs against
   the output contract)
3. Runnable through a FunctionModel-backed TriageAgent that produces
   exactly the curated expected_record (modulo decision_id and
   decision_timestamp, which the agent generates fresh on each run)
4. Internally consistent: the expected_tier/expected_disposition
   convenience fields match the expected_record body

The tests double as documentation: each scenario's reviewer_notes
field explains what audit-readiness behavior the scenario is meant
to demonstrate.

Note: These are unit tests, not integration tests. They use the
FunctionModel pattern from test_eval.py to inject a deterministic
agent response and verify the pipeline plumbing carries the curated
expected_record through correctly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent.agent import TriageAgent, TriageAgentConfig


REPO_ROOT = Path(__file__).parent.parent
SUBMISSIONS_DIR = REPO_ROOT / "examples" / "submissions"
EXPECTED_DIR = REPO_ROOT / "examples" / "expected-records"
DATASET_PATH = REPO_ROOT / "eval" / "datasets" / "demo-scenarios.jsonl"
INPUT_SCHEMA_PATH = REPO_ROOT / "schemas" / "input-contract-1.0.0.schema.json"
OUTPUT_SCHEMA_PATH = REPO_ROOT / "schemas" / "output-contract-1.0.0.schema.json"


# -- dataset loading ------------------------------------------------------


def _load_demo_scenarios() -> list[dict[str, Any]]:
    """Parse the JSONL dataset, skipping comment lines."""
    scenarios: list[dict[str, Any]] = []
    for line in DATASET_PATH.read_text().splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        scenarios.append(json.loads(line))
    return scenarios


@pytest.fixture(scope="module")
def demo_scenarios() -> list[dict[str, Any]]:
    return _load_demo_scenarios()


@pytest.fixture(scope="module")
def input_validator() -> Draft202012Validator:
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def output_validator() -> Draft202012Validator:
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


# -- dataset shape -------------------------------------------------------


def test_dataset_has_five_scenarios(demo_scenarios: list[dict]) -> None:
    """Five scenarios as specified by Phase 5 sub-system 3 scope."""
    assert len(demo_scenarios) == 5


def test_scenarios_cover_all_four_tiers(demo_scenarios: list[dict]) -> None:
    """Tiers 1, 2, 3, 4 are each represented."""
    tiers = {s["expected_tier"] for s in demo_scenarios}
    assert tiers == {
        "tier_1_low", "tier_2_moderate",
        "tier_3_elevated", "tier_4_high",
    }


def test_scenarios_cover_all_four_dispositions(demo_scenarios: list[dict]) -> None:
    """All four dispositions appear across the five scenarios."""
    dispositions = {s["expected_disposition"] for s in demo_scenarios}
    assert dispositions == {
        "approve", "conditional_approve",
        "escalate_senior_review", "reject",
    }


def test_every_scenario_has_required_fields(demo_scenarios: list[dict]) -> None:
    """Each scenario has the documented top-level fields."""
    required = {
        "id", "description", "submission", "expected_record",
        "expected_tier", "expected_disposition", "reviewer_notes",
    }
    for s in demo_scenarios:
        assert required.issubset(s.keys()), (
            f"scenario {s.get('id', '?')} missing keys: "
            f"{required - set(s.keys())}"
        )


def test_scenario_ids_are_unique(demo_scenarios: list[dict]) -> None:
    """Every scenario has a stable unique id."""
    ids = [s["id"] for s in demo_scenarios]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


# -- internal consistency ------------------------------------------------


def test_expected_tier_matches_expected_record(demo_scenarios: list[dict]) -> None:
    """The convenience expected_tier field equals expected_record.risk_tier."""
    for s in demo_scenarios:
        assert s["expected_tier"] == s["expected_record"]["risk_tier"], (
            f"scenario {s['id']} expected_tier inconsistency"
        )


def test_expected_disposition_matches_expected_record(
    demo_scenarios: list[dict],
) -> None:
    """The convenience expected_disposition field equals the record's."""
    for s in demo_scenarios:
        assert (
            s["expected_disposition"]
            == s["expected_record"]["recommended_disposition"]
        ), f"scenario {s['id']} expected_disposition inconsistency"


def test_submission_vendor_id_matches_record_input_submission_id(
    demo_scenarios: list[dict],
) -> None:
    """The expected_record references the submission's vendor_id."""
    for s in demo_scenarios:
        assert (
            s["submission"]["vendor_id"]
            == s["expected_record"]["input_submission_id"]
        ), f"scenario {s['id']} vendor_id linkage broken"


# -- schema conformance --------------------------------------------------


def test_every_submission_validates_against_input_contract(
    demo_scenarios: list[dict],
    input_validator: Draft202012Validator,
) -> None:
    """All five submissions conform to the input contract."""
    for s in demo_scenarios:
        errors = list(input_validator.iter_errors(s["submission"]))
        assert not errors, (
            f"scenario {s['id']} input invalid: "
            f"{[(e.message, list(e.absolute_path)) for e in errors]}"
        )


def test_every_expected_record_validates_against_output_contract(
    demo_scenarios: list[dict],
    output_validator: Draft202012Validator,
) -> None:
    """All five expected_records conform to the output contract."""
    for s in demo_scenarios:
        errors = list(output_validator.iter_errors(s["expected_record"]))
        assert not errors, (
            f"scenario {s['id']} expected_record invalid: "
            f"{[(e.message, list(e.absolute_path)) for e in errors]}"
        )


# -- on-disk file consistency -------------------------------------------


def test_examples_submissions_match_dataset(demo_scenarios: list[dict]) -> None:
    """The submission files on disk match what the dataset contains."""
    submission_files = sorted(SUBMISSIONS_DIR.glob("*.json"))
    assert len(submission_files) == len(demo_scenarios), (
        f"submission files: {len(submission_files)}, "
        f"dataset scenarios: {len(demo_scenarios)}"
    )
    by_vendor_id = {
        json.loads(p.read_text())["vendor_id"]: json.loads(p.read_text())
        for p in submission_files
    }
    for s in demo_scenarios:
        vendor_id = s["submission"]["vendor_id"]
        assert vendor_id in by_vendor_id, f"missing file for {vendor_id}"
        assert by_vendor_id[vendor_id] == s["submission"], (
            f"submission file content disagrees with dataset for {vendor_id}"
        )


def test_examples_expected_records_match_dataset(
    demo_scenarios: list[dict],
) -> None:
    """The expected-record files on disk match the dataset's expected_record."""
    expected_files = sorted(EXPECTED_DIR.glob("*.expected.json"))
    assert len(expected_files) == len(demo_scenarios)
    by_decision_id = {
        json.loads(p.read_text())["decision_id"]: json.loads(p.read_text())
        for p in expected_files
    }
    for s in demo_scenarios:
        decision_id = s["expected_record"]["decision_id"]
        assert decision_id in by_decision_id
        assert by_decision_id[decision_id] == s["expected_record"], (
            f"expected-record file disagrees with dataset for {decision_id}"
        )


# -- agent runthrough ---------------------------------------------------


def _classification_payload_from_expected(
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    """Extract the agent's classification payload from an expected_record.

    The agent's tool-call payload is a subset of the full record:
    risk_tier, recommended_disposition, classification_rationale,
    evidence_cited, confidence_signal, and any conditional fields
    (required_mitigations, accountable_owner). The framework wraps
    this with decision_id, timestamps, agent_version, etc.
    """
    payload: dict[str, Any] = {
        "risk_tier": expected_record["risk_tier"],
        "recommended_disposition": expected_record["recommended_disposition"],
        "classification_rationale": expected_record["classification_rationale"],
        "evidence_cited": expected_record["evidence_cited"],
        "confidence_signal": expected_record["confidence_signal"],
    }
    for optional in ("required_mitigations", "accountable_owner",
                     "review_interval_days", "regulatory_framework_tags"):
        if optional in expected_record:
            payload[optional] = expected_record[optional]
    return payload


def _agent_returning_expected(expected_record: dict[str, Any]) -> TriageAgent:
    """Build a TriageAgent that returns the canned expected_record payload."""
    payload = _classification_payload_from_expected(expected_record)

    def _call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=payload),
        ])

    return TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))


@pytest.mark.parametrize(
    "scenario_index", range(5), ids=[
        "tier1-internal-productivity",
        "tier2-customer-service-chatbot",
        "tier3-document-ocr-loans",
        "tier4-autonomous-credit-decisioning",
        "edge-embedded-ai-via-subprocessors",
    ],
)
def test_agent_produces_expected_record_for_scenario(
    demo_scenarios: list[dict],
    scenario_index: int,
) -> None:
    """Run each scenario's submission through a canned agent and verify the
    record matches the curated expected_record, modulo runtime fields.
    """
    scenario = demo_scenarios[scenario_index]
    agent = _agent_returning_expected(scenario["expected_record"])
    record = agent.triage(submission=scenario["submission"])

    # Classification fields must match the curated values exactly.
    assert record.risk_tier == scenario["expected_record"]["risk_tier"]
    assert (
        record.recommended_disposition
        == scenario["expected_record"]["recommended_disposition"]
    )
    assert (
        record.classification_rationale
        == scenario["expected_record"]["classification_rationale"]
    )
    assert (
        record.confidence_signal.score
        == scenario["expected_record"]["confidence_signal"]["score"]
    )
    # The submission's vendor_id flows through to the input_submission_id.
    assert record.input_submission_id == scenario["submission"]["vendor_id"]


# -- count and coverage --------------------------------------------------


def test_dataset_jurisdictions_cover_intended_mix(
    demo_scenarios: list[dict],
) -> None:
    """The intended mix per design: OSFI lead + 1 SOX + 1 EU AI Act + 1 cross."""
    jurisdictions = [s["submission"]["jurisdiction"] for s in demo_scenarios]
    # Three Canadian-jurisdiction scenarios (OSFI lead)
    canadian = [j for j in jurisdictions if j.startswith("CA")]
    # One US-jurisdiction scenario (SOX lens)
    us = [j for j in jurisdictions if j == "US"]
    # One EU-jurisdiction scenario
    eu = [j for j in jurisdictions if j in {"EU", "EEA"}]
    assert len(canadian) >= 2, (
        f"expected at least 2 Canadian scenarios for OSFI lead, "
        f"got {jurisdictions}"
    )
    assert len(us) >= 1, f"expected a US scenario for SOX lens, got {jurisdictions}"
    assert len(eu) >= 1, f"expected an EU scenario, got {jurisdictions}"


def test_dataset_reviewer_notes_are_substantial(
    demo_scenarios: list[dict],
) -> None:
    """reviewer_notes is the audience-facing explanation; should not be empty."""
    for s in demo_scenarios:
        assert len(s["reviewer_notes"]) >= 80, (
            f"scenario {s['id']} reviewer_notes too short: "
            f"{len(s['reviewer_notes'])} chars"
        )
