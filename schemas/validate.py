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


_OUTPUT_SCHEMA_FILES: dict[str, str] = {
    "1.0.0": "output-contract-1.0.0.schema.json",
    "1.1.0": "output-contract-1.1.0.schema.json",
    "1.2.0": "output-contract-1.2.0.schema.json",
}
"""Mapping from output_schema_version to the schema file that validates it.

Schema files are kept in the repo for every published version so that
records produced under prior versions remain validatable. The current
framework default is the highest version in this map; the agent stamps
that version into records it produces.
"""


def validate_output(record: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Validate a triage record against the appropriate output contract.

    Dispatches by the ``output_schema_version`` field in the record so
    older records (produced under prior framework versions) continue
    to validate. If the version is unknown, falls back to 1.0.0 and
    reports the unknown-version situation in the errors list.
    """
    version = record.get("output_schema_version", "1.0.0")
    schema_filename = _OUTPUT_SCHEMA_FILES.get(version)
    if schema_filename is None:
        return False, [{
            "message": (
                f"Unknown output_schema_version {version!r}. Supported "
                f"versions: {sorted(_OUTPUT_SCHEMA_FILES.keys())}."
            ),
            "path": "output_schema_version",
            "schema_path": "",
        }]
    schema = _load_schema(schema_filename)
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
