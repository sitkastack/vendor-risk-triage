# vendor-risk-triage

A reference implementation of an AI agent that performs vendor and third-party AI risk triage, built in the open under Apache 2.0.

## What this is

Mid-market companies in regulated industries are now expected to assess the AI risk of every vendor they onboard. The list of obligations keeps growing: model provenance, data handling, prompt injection exposure, log retention, fine-tuning posture, and more, all driven by frameworks like NIST AI RMF, the EU AI Act, OSFI Guideline E-23, SOX/ICFR, and ISO/IEC 42001, plus sectoral regulators and internal audit committees. Most teams answer this with a spreadsheet and a vibe check.

This repository is a working pattern for doing it deliberately: an agent that ingests a vendor's public documentation, security artifacts, and questionnaire responses, classifies the engagement against a defined risk taxonomy, and produces an audit-ready triage record. The framework ships in phases: Phase 0 through Phase 2 (documentation phases) are live; Phase 3 (Build and Eval) adds the agent code, prompts, and evaluation harness; Phase 4 adds governance artifacts (model cards, eval reports, audit log schemas); Phase 5 adds deployment and monitoring; Phase 6 adds sunset planning. The governance-as-code foundation (machine-readable schemas, validation utility, detection skeletons, CI enforcement) ships ahead of Phase 3 so consumers can validate against the contracts today.

It is part of the [sitkastack Framework](https://sitkastack.com), a public body of work on shipping audit-ready AI inside regulated mid-market companies. Everything here is intended to be forked, adapted, and pressure-tested against your own regulatory context.

## Status

**Phase 0, Phase 1, and Phase 2 complete. Phase 3 upcoming.**

Phase 0 (Discovery & Risk Classification) is live. Three artifacts in [docs/phase-0/](docs/phase-0/) define the problem the agent solves, the regulatory frameworks the classification maps to, and the boundaries of what is in and out of scope.

Phase 1 (Data Contracts & Privacy) is live. The problem definition, out-of-scope document, input data contract, output data contract, privacy and data handling spec, synthetic data specification, and extension guide live in [docs/phase-1/](docs/phase-1/). Runnable example records ship alongside them in [examples/](examples/).

Phase 2 (Architecture & Threat Model) is live. Five artifacts in [docs/phase-2/](docs/phase-2/) cover the problem definition, the system architecture, the trust boundaries, the threat model, and the architecture decision records for the triage gate.

No agent code has been written yet. With the architecture and threat model now documented, the next focus is Phase 3 (Build & Eval): the agent implementation and its evaluation harness. Later phases add governance artifacts, deployment, and sunset planning. Ahead of Phase 3, the governance-as-code foundation already ships in this repo: standalone JSON Schemas in schemas/, a validation utility, threat detection skeletons in detection/, and CI enforcement. See the "Governance as code" section below.

## Governance as code

The framework's governance is partially executable, not just documented:

- **Data contracts** are JSON Schema 2020-12 artifacts in schemas/. The Python utility in schemas/validate.py validates submissions and records against them; consumers in other languages use any 2020-12 validator. ADR-004 documents the closure properties (unevaluatedProperties: false, additionalProperties: false) the schemas enforce.
- **Examples** in examples/ are verified against the schemas by tests/test_examples_validate.py, enforced on every push and PR by .github/workflows/validate.yml.
- **Threat detection skeletons** in detection/ provide a callable function for each of the 27 threats documented in docs/phase-2/03-threat-model.md. The functions raise NotImplementedError until Phase 5 implements the detection logic, but the signatures and detection approach are committed in Phase 2. tests/test_detection_signatures.py enforces the signature contract.
- **Style discipline** (no em dashes) is enforced in CI.

What is documented but not yet executable: most Phase 4 governance artifacts (model cards, DPIA templates, audit log schemas) ship in Phase 4; Phase 3 evaluation suites (bias, prompt injection resistance, hallucination) ship in Phase 3; Phase 5 implements the threat detection logic. The framework's commitment is that wherever governance can be machine-readable, it will be.

## Roadmap

- **Phase 0**: Discovery & Risk Classification (live)
- **Phase 1**: Data Contracts & Privacy (live)
- **Phase 2**: Architecture & Threat Model (live)
- **Phase 3**: Build & Eval (upcoming)
- **Phase 4**: Governance Artifacts (upcoming)
- **Phase 5**: Deploy & Monitor (upcoming)
- **Phase 6**: Sunset Planning (upcoming)

Phases ship when ready. Each phase lands as its own set of PRs with the design docs, code where applicable, tests, and eval results in the same commit history.

## How to follow along

- Watch this repo for new phases as they land
- Read the Phase 0 docs in [docs/phase-0/](docs/phase-0/), which are numbered and intended to be read in order
- Follow [sitkastack.com](https://sitkastack.com) for the broader framework context
- Open an issue if something is unclear, wrong, or contradicts your real-world experience

## Limitations and known gaps

This is intentionally honest:

- **v0.3 reference, not production-grade audit defense.** The framework documents the discipline; Phase 3 ships the agent code and evaluation suites that turn discipline into running software. Do not point this at a real vendor onboarding flow and assume the output will hold up under regulatory scrutiny. It is a starting point.
- **Artifacts are adaptable templates, not finished compliance deliverables.** The model card, audit log schema, and risk taxonomy are designed to be modified for your specific regulatory context (sector, jurisdiction, internal control framework). They will not survive a serious audit unchanged.
- **Solo work, no external peer review at this stage.** Everything here reflects one author's judgment. Issues and PRs from practitioners with real audit and procurement experience are explicitly welcome.
- **The five-question audit-ready framework referenced in the docs is a starter, not a comprehensive audit methodology.** It is a useful filter for early-stage triage, not a substitute for a real assurance program.

If you spot something that is wrong or oversimplified, opening an issue is the most useful thing you can do.

## Examples

The examples/ directory contains illustrative JSON files engineers use to verify their integrations against the Phase 1 contracts. Every example is verified to validate against its schema by tests/test_examples_validate.py, enforced in CI on every push and PR.

- examples/input-submission.example.json: a valid input submission, validates against the Input Contract schema
- examples/triage-record.example.json: a valid triage record paired with the input example, validates against the Output Contract schema
- examples/validation-error.example.json: illustrative shape of a structured validation error response from the intake validator

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contact

Built by Robyn Toor. Contact: [robyn@sitkastack.com](mailto:robyn@sitkastack.com).
