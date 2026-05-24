# Evaluation

This folder will hold the eval harness and graded examples used to measure agent quality. The intent is that every meaningful change to the agent (a new prompt, a new model, a new risk category) is run against this set before it lands, and the results are committed alongside the change.

The initial eval harness and graded examples ship in Phase 3 (Build and Eval) alongside the first agent code. Phase 3 evaluation suites map directly to threats documented in docs/phase-2/03-threat-model.md:

- Prompt injection resistance suites for T-AI1 (Prompt injection via vendor documents)
- Data exfiltration resistance suites for T-AI2 (Data exfiltration via prompt)
- Hallucination measurement suites for T-AI4 (Hallucination accepted without verification)
- Bias evaluation suites for T-AI6 (Discriminatory output bias) and T-AI7 (Fairness drift over vendor distribution)
- Classification stability suites for T-AI8 (Classification drift through provider model updates)

Later phases extend the eval set with adversarial cases, regression cases drawn from real triage records, and additional bias and fairness probes.

Empty through Phases 0, 1, and 2 (documentation phases).
