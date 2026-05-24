"""Tests that example JSON files validate against the contracts.

Every example in examples/ must validate against the corresponding
contract schema. These tests are the contract proof: if an example
breaks, either the example is wrong or the schema is wrong, and the
failure surfaces immediately rather than at runtime.
"""
import json
from pathlib import Path

from schemas.validate import validate_input, validate_output


REPO_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


def _load_example(filename: str) -> dict:
    """Load an example JSON file from examples/."""
    path = EXAMPLES_DIR / filename
    with open(path) as f:
        return json.load(f)


def test_input_submission_example_validates() -> None:
    """examples/input-submission.example.json validates against input contract."""
    submission = _load_example("input-submission.example.json")
    is_valid, errors = validate_input(submission)
    assert is_valid, f"Example does not validate: {errors}"


def test_triage_record_example_validates() -> None:
    """examples/triage-record.example.json validates against output contract."""
    record = _load_example("triage-record.example.json")
    is_valid, errors = validate_output(record)
    assert is_valid, f"Example does not validate: {errors}"


def test_validation_error_example_loads_as_json() -> None:
    """examples/validation-error.example.json is well-formed JSON.

    This example documents the shape returned by the validator on
    failure. It is not validated against a schema (it is the schema's
    output, not its input), but it must be loadable JSON.
    """
    error_example = _load_example("validation-error.example.json")
    assert isinstance(error_example, dict)


def test_invalid_submission_produces_errors() -> None:
    """A submission missing required fields produces structured errors."""
    invalid_submission = {"vendor_id": "test"}  # missing all other required fields
    is_valid, errors = validate_input(invalid_submission)
    assert not is_valid
    assert len(errors) > 0
    for error in errors:
        assert "field_path" in error
        assert "message" in error
        assert "validator" in error
