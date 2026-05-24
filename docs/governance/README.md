# Governance Artifacts

This folder will hold the governance deliverables produced by the project: model cards, evaluation reports, audit log schemas, DPIA templates, risk registers, key risk indicators (KRIs), RACI matrices, and similar artifacts that a regulated organization expects to see when adopting an AI system.

These are intended as adaptable starting points, not finished compliance deliverables. Each artifact will land alongside the phase that produces it, with attribution to the source frameworks it draws from.

## Framework discipline

The sitkastack Framework maps every artifact to at least one specific control objective from five primary frameworks:

- **NIST AI RMF.** AI risk management functions (Govern, Map, Measure, Manage) used across all phases.
- **EU AI Act.** Particular attention to Annex III high-risk categories, with the cumulative classification analysis carried in Phase 0.
- **OSFI Guideline E-23.** Canadian model risk management for AI and ML, effective May 1, 2027. Phase 0 risk classification carries the institution-level mapping.
- **SOX/ICFR.** US public-company internal controls over financial reporting, including AI-affected controls. Surfaces in Phase 2 architecture decisions and Phase 4 audit log schemas.
- **ISO/IEC 42001:2023.** International AI management system standard. Annex A controls map to phases as documented below.

SOC 2 is included where the reference implementation context applies it. Sectoral frameworks (NAIC Model Bulletin on AI, SR 11-7, FCA, FINRA) are acknowledged in Phase 0 risk classification and surface in artifacts where their requirements bear on a specific decision.

## ISO/IEC 42001 mapping by phase

ISO/IEC 42001:2023 Annex A organizes AI management system controls into ten categories. The Framework's phases map to those categories as follows:

| Phase | Primary Annex A controls | What ships |
|---|---|---|
| Phase 0 (Discovery and Risk Classification) | A.5 (Assessing impacts of AI systems), A.10 (Third-party and customer relationships) | Problem definition, risk classification taxonomy, out-of-scope discipline |
| Phase 1 (Data Contracts and Privacy) | A.7 (Data for AI systems), A.10 | Input and output contracts, privacy and data handling spec, synthetic data spec, extension guide |
| Phase 2 (Architecture and Threat Model) | A.6 (AI system life cycle), A.10 | System architecture, trust boundaries, threat model, architecture decisions |
| Phase 3 (Build and Eval) | A.6, A.7 | Agent implementation, evaluation harness |
| Phase 4 (Governance Artifacts) | A.2 (Policies), A.3 (Internal organization), A.8 (Information for interested parties), A.9 (Use of AI systems) | Model cards, audit log schemas, DPIA templates, risk register, KRIs, RACI matrices |
| Phase 5 (Deploy and Monitor) | A.6, A.9 | Detection implementations, operational monitoring |
| Phase 6 (Sunset Planning) | A.6 | Decommissioning patterns |

Per-artifact control mappings at the individual-control level (not just category level) ship as part of Phase 4 governance deliverables alongside model cards and audit log schemas. The category-level mapping above is the architectural commitment the documentation phases support.

## Why COBIT is not in the primary framework set

COBIT 2019 is an enterprise IT governance framework owned by ISACA and adopted by institutions running broader IT governance disciplines. It is not in the sitkastack Framework's primary set for a deliberate reason: this Framework is opinionated about AI risk management for AI vendor triage, not about enterprise IT governance as a whole.

A deploying institution chooses its IT governance framework (COBIT 2019, ITIL 4, ISO/IEC 38500, or another). This Framework slots inside that choice rather than replacing it. The Framework provides AI-specific risk classification, contracts, threat modeling, and detection; the institution's IT governance framework provides the broader scaffolding (policies, organizational structure, performance measurement, conformance assurance) that this work depends on.

CGEIT-certified practitioners will recognize the decoupling. Where an institution's COBIT 2019 implementation requires AI-specific risk artifacts (typically under APO13 Managed Security, EDM03 Ensured Risk Optimization, or APO12 Managed Risk), this Framework provides them in a form that integrates with the institution's COBIT documentation rather than competing with it. The Framework's outputs (the contract artifacts, the threat model, the detection skeleton, the planned Phase 4 governance deliverables) are inputs to the institution's COBIT or equivalent governance process, not substitutes for it.

The same logic applies to other enterprise IT governance frameworks. ITIL 4 institutions slot this Framework's outputs into their service management discipline; ISO/IEC 38500 institutions slot them into their corporate IT governance. The Framework's opinionatedness lives at the AI-specific layer, and the institution's broader governance choice is preserved.

## Status

Phase 4 (Governance Artifacts) of the sitkastack Framework, planned. Roadmap: sitkastack.com/roadmap.
