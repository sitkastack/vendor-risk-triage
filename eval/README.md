# Evaluation

This folder holds the eval harness and graded examples used to measure agent quality. The intent is that every meaningful change to the agent — a new prompt, a new model, a new risk category — is run against this set before it lands, and the results are committed alongside the change.

Phase 1 ships the initial hand-graded eval set. Later phases extend it (adversarial cases, prompt injection probes, regression cases drawn from real triage records). Empty during Phase 0.
