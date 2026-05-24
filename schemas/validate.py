"""Validation utility for Vendor Risk Triage data contracts.

Provides functions to validate submissions and triage records against
the JSON Schema 2020-12 contracts published in this directory.

Usage from Python:
    from schemas.validate import validate_input, validate_output
    is_valid, errors = validate_input(submission_dict)
    is_valid, errors = validate_output(record_dict)

Usage from command line:
    python -m schemas.validate input examples/input-submission.example.json
    python -m schemas.validate output examples/triage-record.example.json
"""
import json
import sys
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as e:
    raise ImportError(
        "jsonschema library required. Install with: pip install jsonschema"
    ) from e


SCHEMAS_DIR = Path(__file__).parent


def _load_schema(filename: str) -> dict[str, Any]:
    """Load a schema from the schemas directory."""
    schema_path = SCHEMAS_DIR / filename
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {filename}")
    with open(schema_path) as f:
        return json.load(f)


def _validate(instance: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Validate an instance against a schema and return structured errors.

    Returns (is_valid, errors). The errors list is empty when is_valid
    is True. Each error is a dict with field_path, validator, message,
    and schema_path keys matching the shape in
    examples/validation-error.example.json.
    """
    validator = Draft202012Validator(schema)
    errors = []
    for error in validator.iter_errors(instance):
        errors.append({
            "field_path": "/".join(str(p) for p in error.absolute_path),
            "validator": error.validator,
            "message": error.message,
            "schema_path": "/".join(str(p) for p in error.absolute_schema_path),
        })
    return len(errors) == 0, errors


def validate_input(submission: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Validate a submission against the input contract (1.0.0)."""
    schema = _load_schema("input-contract-1.0.0.schema.json")
    return _validate(submission, schema)


def validate_output(record: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Validate a triage record against the output contract (1.0.0)."""
    schema = _load_schema("output-contract-1.0.0.schema.json")
    return _validate(record, schema)


def _cli() -> int:
    """Command-line interface for validation."""
    if len(sys.argv) < 3:
        print("Usage: python -m schemas.validate <input|output> <file.json>")
        return 2

    contract_type, file_path = sys.argv[1], sys.argv[2]

    with open(file_path) as f:
        instance = json.load(f)

    if contract_type == "input":
        is_valid, errors = validate_input(instance)
    elif contract_type == "output":
        is_valid, errors = validate_output(instance)
    else:
        print(f"Unknown contract type: {contract_type}. Use 'input' or 'output'.")
        return 2

    if is_valid:
        print(f"OK: {file_path} validates against {contract_type} contract")
        return 0

    print(f"FAIL: {file_path} does not validate against {contract_type} contract")
    for error in errors:
        print(f"  - {error['field_path']}: {error['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
