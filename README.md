# vendor-risk-triage

A reference implementation of an AI agent that performs vendor and third-party AI risk triage, built in the open under Apache 2.0.

## What this is

Mid-market companies in regulated industries are now expected to assess the AI risk of every vendor they onboard. The list of obligations keeps growing: model provenance, data handling, prompt injection exposure, log retention, fine-tuning posture, and more, all driven by NIST AI RMF, the EU AI Act, sectoral regulators, and internal audit committees. Most teams answer this with a spreadsheet and a vibe check.

This repository is a working pattern for doing it deliberately: an agent that ingests a vendor's public documentation, security artifacts, and questionnaire responses, classifies the engagement against a defined risk taxonomy, and produces an audit-ready triage record. The code, the prompts, the evaluation harness, and the governance artifacts (model cards, eval reports, audit logs) all ship in this repo.

It is part of the [sitkastack Framework](https://sitkastack.com), a public body of work on shipping audit-ready AI inside regulated mid-market companies. Everything here is intended to be forked, adapted, and pressure-tested against your own regulatory context.

## Status

**Phase 0 and Phase 1 complete. Phase 2 in progress.**

Phase 0 (Discovery & Risk Classification) is live. Three artifacts in [docs/phase-0/](docs/phase-0/) define the problem the agent solves, the regulatory frameworks the classification maps to, and the boundaries of what is in and out of scope.

Phase 1 (Data Contracts & Privacy) is live. The problem definition, out-of-scope document, input data contract, output data contract, privacy and data handling spec, synthetic data specification, and extension guide live in [docs/phase-1/](docs/phase-1/). Runnable example records ship alongside them in [examples/](examples/).

No agent code has been written yet. The current focus is methodology and contract design. Later phases add code, evaluation, and governance artifacts.

## Roadmap

- **Phase 0**: Discovery & Risk Classification (live)
- **Phase 1**: Data Contracts & Privacy (live)
- **Phase 2**: Architecture & Threat Model (in progress)
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

- **v0.1 reference implementation, not production-grade audit defense.** Do not point this at a real vendor onboarding flow and assume the output will hold up under regulatory scrutiny. It is a starting point.
- **Artifacts are adaptable templates, not finished compliance deliverables.** The model card, audit log schema, and risk taxonomy are designed to be modified for your specific regulatory context (sector, jurisdiction, internal control framework). They will not survive a serious audit unchanged.
- **Solo work, no external peer review at this stage.** Everything here reflects one author's judgment. Issues and PRs from practitioners with real audit and procurement experience are explicitly welcome.
- **The five-question audit-ready framework referenced in the docs is a starter, not a comprehensive audit methodology.** It is a useful filter for early-stage triage, not a substitute for a real assurance program.

If you spot something that is wrong or oversimplified, opening an issue is the most useful thing you can do.

## Examples

The examples/ directory contains illustrative JSON files engineers can use to verify their integrations against the Phase 1 contracts:

- examples/input-submission.example.json: a valid input submission, validates against the Input Contract schema
- examples/triage-record.example.json: a valid triage record paired with the input example, validates against the Output Contract schema
- examples/validation-error.example.json: illustrative shape of a structured validation error response from the intake validator

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contact

Built by Robyn Toor. Contact: [robyn@sitkastack.com](mailto:robyn@sitkastack.com).
