# Evaluation

This folder will hold the eval harness and graded examples used to measure agent quality. The intent is that every meaningful change to the agent (a new prompt, a new model, a new risk category) is run against this set before it lands, and the results are committed alongside the change.

The initial eval harness and graded examples ship in Phase 3 (Build and Eval) alongside the first agent code. Phase 3 also implements the bias evaluation suites and prompt injection resistance tests referenced in docs/phase-2/03-threat-model.md. Later phases extend the eval set with adversarial cases, regression cases drawn from real triage records, and additional bias and fairness probes.

Empty through Phases 0, 1, and 2 (documentation phases).
