# vendor-risk-triage

A reference implementation of an AI agent that performs vendor and third-party AI risk triage, built in the open under Apache 2.0.

## What this is

Mid-market companies in regulated industries are now expected to assess the AI risk of every vendor they onboard — model provenance, data handling, prompt injection exposure, log retention, fine-tuning posture, and a growing list of obligations driven by NIST AI RMF, the EU AI Act, sectoral regulators, and internal audit committees. Most teams answer this with a spreadsheet and a vibe check.

This repository is a working pattern for doing it deliberately: an agent that ingests a vendor's public documentation, security artifacts, and questionnaire responses, classifies the engagement against a defined risk taxonomy, and produces an audit-ready triage record. The code, the prompts, the evaluation harness, and the governance artifacts (model cards, eval reports, audit logs) all ship in this repo.

It is part of the [sitkastack Framework](https://sitkastack.com) — a public body of work on shipping audit-ready AI inside regulated mid-market companies. Everything here is intended to be forked, adapted, and pressure-tested against your own regulatory context.

## Status

**Phase 0: Discovery & Risk Classification.** The current focus is defining the problem precisely — what a "vendor AI risk triage" actually decides, what risks the taxonomy needs to discriminate between, and what is explicitly out of scope for v0.1. No agent code has been written yet. The Phase 0 artifacts live in [docs/phase-0/](docs/phase-0/) and are the substrate every later phase will build on.

## Roadmap

- **Phase 0** — Discovery & Risk Classification (current)
- **Phase 1** — Minimal triage agent, hand-graded eval set
- **Phase 2** — Audit log schema, decision traceability
- **Phase 3** — Prompt injection and jailbreak hardening
- **Phase 4** — Human-in-the-loop review workflow
- **Phase 5** — Governance artifacts: model card, eval report, DPIA template
- **Phase 6** — Production hardening notes and known-limit catalog

A new phase ships roughly every 3–4 weeks. Each phase lands as its own set of PRs with the design doc, the code, the tests, and the eval results in the same commit history.

## How to follow along

- Watch this repo for new phases as they land
- Read the Phase 0 docs in [docs/phase-0/](docs/phase-0/) — they're numbered and intended to be read in order
- Follow [sitkastack.com](https://sitkastack.com) for the broader framework context
- Open an issue if something is unclear, wrong, or contradicts your real-world experience

## Limitations and known gaps

This is intentionally honest:

- **v0.1 reference implementation, not production-grade audit defense.** Do not point this at a real vendor onboarding flow and assume the output will hold up under regulatory scrutiny. It is a starting point.
- **Artifacts are adaptable templates, not finished compliance deliverables.** The model card, audit log schema, and risk taxonomy are designed to be modified for your specific regulatory context (sector, jurisdiction, internal control framework). They will not survive a serious audit unchanged.
- **Solo work, no external peer review at this stage.** Everything here reflects one author's judgment. Issues and PRs from practitioners with real audit and procurement experience are explicitly welcome.
- **The five-question audit-ready framework referenced in the docs is a starter, not a comprehensive audit methodology.** It is a useful filter for early-stage triage, not a substitute for a real assurance program.

If you spot something that is wrong or oversimplified, opening an issue is the most useful thing you can do.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contact

Built by Robyn Toor — [robyn@sitkastack.com](mailto:robyn@sitkastack.com).
