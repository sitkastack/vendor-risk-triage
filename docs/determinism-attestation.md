# Determinism attestation

The framework introduced a per-record determinism attestation in v1.0.5
(output contract 1.4.0). Every record produced by the agent now carries
a `determinism_attestation` object describing the producing
configuration's contract posture. A compliance lead checks one boolean
(`contract_honored`) to decide whether the record falls under the
framework's reproducibility commitment.

## The contract

When `determinism_attestation.contract_honored == true`, the framework
attests that re-running the same agent against the same submission with
the same configuration (provider, model, temperature, system prompt,
corpus bundle) will produce a record whose classification fields match
the original within the empirically-measured per-(provider, model)
variance band documented below. When `false`, the producing
configuration exited the contract; the record is still a valid audit
artifact but reproducibility is not asserted.

Classification fields covered:

- `risk_tier`
- `recommended_disposition`
- `regulatory_framework_tags` (set equality)
- `confidence_signal.score` (within band)
- `accountable_owner` presence (set vs. null)
- `required_mitigations` count

Fields explicitly NOT covered (per-run noise, by design):

- `decision_id`, `decision_timestamp`, `correlation_id` (unique per call)
- `classification_rationale`, `evidence_cited[*].reasoning` text (the
  LLM writes prose; identical reasoning, varying wording)
- `cost_estimate` (token counts vary with the model's tokenization)
- `extension_schema_version` (deployment-specific, not framework-controlled)

## Three populations of records

After v1.0.5, three populations of records coexist in the wild:

1. **Pre-1.0.5 records** (`output_schema_version == "1.3.0"` or earlier).
   Produced before the contract existed. They carry no attestation. They
   cannot be retroactively attested because no measurement of the
   producing agent's temperature, system prompt, or corpus bundle was
   taken at the time. These records remain valid audit artifacts under
   their version-of-record schemas.

2. **Migrated-forward records** (`output_schema_version == "1.4.0"`,
   `determinism_attestation.migrated_from == "1.3.0"`). Produced by
   `vrt migrate` running against a pre-1.0.5 record. The attestation is
   present but every data field is null and `contract_honored == false`.
   The `migrated_from` field is the discriminator: an operator scanning
   the population sees these records as "lifted to current contract but
   not measured."

3. **Fresh post-1.0.5 records** (`output_schema_version == "1.4.0"`,
   `determinism_attestation.migrated_from == null`). The full
   attestation populated. `contract_honored` reflects the producing
   configuration.

The pattern operators check:

```
SELECT
  COUNT(*) FILTER (WHERE determinism_attestation IS NULL)            AS pre_contract,
  COUNT(*) FILTER (WHERE determinism_attestation.migrated_from IS NOT NULL) AS migrated,
  COUNT(*) FILTER (
    WHERE determinism_attestation.migrated_from IS NULL
    AND determinism_attestation.contract_honored = TRUE
  )                                                                   AS contract_honored,
  COUNT(*) FILTER (
    WHERE determinism_attestation.migrated_from IS NULL
    AND determinism_attestation.contract_honored = FALSE
  )                                                                   AS contract_exited
FROM triage_records;
```

## When `contract_honored` is `true`

The framework sets `contract_honored = true` only when ALL of:

- `effective_temperature == 0.0`. Non-zero temperature exits the contract.
- `provider` is in the known-attested set: `anthropic`, `openai`,
  `google-gla`, `google-vertex`. Test fixtures (`test`, `unknown`) and
  models behind providers outside this set are not in scope.
- `system_prompt_hash` matches the framework default
  (`SYSTEM_PROMPT_HASH_FULL`). A custom system prompt exits the
  contract because per-(provider, model) variance is measured against
  the default prompt.
- `fallback` is `null`. A fallback firing produced the record from a
  model other than the configured primary; the per-(primary-model)
  contract does not transit through fallback.

If any of these conditions fails, `contract_honored = false` and the
specific exit condition is identifiable from the other attestation
fields.

## Audit anchors

- `system_prompt_hash`: full 64-char SHA-256 of the SYSTEM_PROMPT bytes
  the agent actually loaded. NOT read from the 12-char
  `SYSTEM_PROMPT_HASH` framework-identity constant; computed from the
  loaded bytes at construction so a custom prompt override flows
  through faithfully. When this matches the default's hash,
  `contract_honored` may be true.

- `corpus_bundle_hash`: full 64-char SHA-256 of the canonical-JSON
  serialization of the regulation chunks actually loaded for this
  triage call. NOT a registry lookup. Null when no corpus was loaded
  (e.g. `vrt triage` without `--corpus`).

- `sampling_profile_hash`: 12-char SHA-256 prefix over the
  (provider, effective_model_id, effective_temperature) triple. A
  stable join key for downstream consumers that need to bucket records
  by sampling config without parsing strings.

- `contract_version`: the determinism contract's own semver. Independent
  of the framework version (a patch bump of the framework does not
  change the contract version unless the contract text changes). Today
  the contract is at `1.0.0`.

## Variance band (empirical)

The contract attests reproducibility WITHIN an empirically-measured
band specific to each (provider, model) pair. The band is not zero:
temperature=0 reduces but does not eliminate model-internal sampling
variation. Numbers below are measured by
`scripts/measure_determinism_variance.py` running ten triages of the
same submission with identical configuration.

| Provider     | Model                       | Tier agreement | Disposition agreement | Confidence range |
|--------------|-----------------------------|----------------|-----------------------|-------------------|
| anthropic    | claude-sonnet-4-5           | 10/10 (tier_4_high) | 10/10 (escalate_senior_review) | 0.75 to 0.85      |

Numbers are populated by the maintainer at each release using the
measurement harness; older numbers remain in this document as a
trail. The band values quoted are not guarantees against ALL future
runs; provider model versions and infrastructure shift over time, and
the band may widen or narrow. The framework's commitment is that
records are reproducible WITHIN THE BAND MEASURED AT PRODUCTION TIME,
captured in the agent_version string and the contract_version field.

To regenerate the numbers locally:

```
python scripts/measure_determinism_variance.py \
  --model anthropic:claude-sonnet-4-5 \
  --runs 10 \
  --submission examples/submissions/02-tier2-customer-service-chatbot.json \
  --output /tmp/variance.json
```

The output JSON contains `fields.risk_tier.majority_ratio`,
`fields.confidence_signal.score.range`, etc.

## Exiting the contract intentionally

To opt out for exploration or eval use:

```python
agent = TriageAgent(TriageAgentConfig(
    model="anthropic:claude-sonnet-4-5",
    temperature=0.7,
    allow_nondeterministic_legacy=True,  # required to construct
))
```

The framework emits a DeprecationWarning at construction and every
produced record carries `contract_honored = false`. The
`allow_nondeterministic_legacy` flag is transitional and is removed in
v1.1.0; the long-term path is to mark non-contract-honored deployments
explicitly in operational dashboards and accept that records from those
deployments are not contract-attested.

## Migration

A pre-1.0.5 record can be lifted to the 1.4.0 contract via
`vrt migrate`:

```
vrt migrate path/to/legacy-1.3.0-record.json --to 1.4.0
```

The migration adds a `determinism_attestation` with
`migrated_from = "1.3.0"`, every data field null, and
`contract_honored = false`. This faithfully records that the contract
was not in force at production time; the migration does not retroactively
attest.

To attest a record produced today, re-triage the underlying submission
with the current framework: that produces a fresh 1.4.0 record with
the full attestation. The migrated record and the re-triaged record
share the submission's `vendor_id` but have distinct `decision_id`
values.

## CI gates

The framework's CI runs `scripts/check_system_prompt_hash.py` on every
push. A mismatch between the current `SYSTEM_PROMPT_HASH_FULL` and the
committed baseline at `baselines/system_prompt_hash.txt` fails the
build. The acceptable workflow:

1. Edit the system prompt.
2. Run `python scripts/check_system_prompt_hash.py --update-baseline`.
3. Commit BOTH the prompt edit AND the baseline change together.

This keeps the audit anchor visible in version-control history: a
reviewer sees "the prompt changed" and "the baseline moved" as one
atomic commit.

## Per-record dispatch

When unwrapping a record, consumers route on the three-population
discriminator:

```python
from agent.output_models import TriageRecord

def classify(record: TriageRecord) -> str:
    if record.determinism_attestation is None:
        return "pre_contract"  # 1.0.0 - 1.3.0 record
    if record.determinism_attestation.migrated_from is not None:
        return "migrated"  # 1.4.0 record lifted from older contract
    if record.determinism_attestation.contract_honored:
        return "contract_honored"  # fresh 1.4.0, in contract
    return "contract_exited"  # fresh 1.4.0, configuration exited contract
```

A four-bin dashboard built on this discriminator surfaces the
deployment's contract posture at a glance.

## What the contract does NOT promise

- **Identical text output.** The LLM writes
  `classification_rationale` and `evidence_cited[*].reasoning` text
  freely; two runs may produce different prose with identical
  classifications. The contract is structural, not stylistic.
- **Identical cost.** `cost_estimate.input_tokens` and
  `output_tokens` depend on the tokenizer and on output length,
  both of which vary even at temperature=0.
- **Reproducibility forever.** Provider model versions are
  themselves subject to silent provider-side rotation. The agent_version
  string records WHICH model version was used; reproducing a six-month-old
  record may require requesting the legacy model from the provider.
- **Reproducibility across providers.** The contract is
  per-(provider, model). Switching from `anthropic:claude-sonnet-4-5` to
  `openai:gpt-5.0` is outside the contract by design (the records
  carry `provider` and `effective_model_id` so consumers can bucket).
