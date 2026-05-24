# Schemas

Machine-readable JSON Schema 2020-12 artifacts for the Vendor Risk Triage data contracts. These are the executable form of the contracts described in docs/phase-1/02-input-contract.md and docs/phase-1/03-output-contract.md.

## Files

- input-contract-1.0.0.schema.json: Input contract for submissions to the triage agent
- output-contract-1.0.0.schema.json: Output contract for triage records produced by the agent
- validate.py: Python validation utility

## Authoritative source

The standalone files in this directory are the authoritative executable form. The markdown contracts in docs/phase-1/ describe the same schemas in prose and include the JSON for reference, but the standalone files here are what tools consume.

## Usage in Python

```python
from schemas.validate import validate_input, validate_output

is_valid, errors = validate_input(submission_dict)
if not is_valid:
    for error in errors:
        print(f"{error['field_path']}: {error['message']}")
```

## Usage from command line

```bash
python -m schemas.validate input examples/input-submission.example.json
python -m schemas.validate output examples/triage-record.example.json
```

## Usage in other ecosystems

The schemas conform to JSON Schema 2020-12 with full closure properties (unevaluatedProperties and additionalProperties both set false). Use any validator that supports the full 2020-12 specification:

- JavaScript and TypeScript: ajv with Draft 2020-12 config
- Go: gojsonschema or github.com/santhosh-tekuri/jsonschema
- Rust: jsonschema crate
- Java: everit-json-schema or networknt json-schema-validator

ADR-004 (docs/phase-2/04-architecture-decisions.md) documents why closure properties are non-negotiable for these contracts.

## Schema versioning

Schemas use semantic versioning. The filename encodes the version: input-contract-MAJOR.MINOR.PATCH.schema.json. Each version is immutable once published. New versions add new files rather than modifying existing ones, per ADR-006 (Schema Evolution and Migration Policy).

## Verification

Every example in examples/ validates against its corresponding contract. This is enforced by tests/test_examples_validate.py, run automatically by the CI workflow on every push and pull request.
