# Cost tracking guide

This document explains how a deployment tracks LLM API spend through the vendor risk triage framework. It covers the cost data flowing into `TriageRecord` (what's there, what it means, what its limits are), the published price table (what it covers, how to read it, how to refresh it), the `--cost-budget` CLI flag (how to use it, what it does and doesn't protect against), and the patterns for answering customer pricing conversations.

Cost data is best-effort. It exists to support decisions, not to be authoritative billing. Deployments wanting precise spend tracking should consult their provider's invoicing system; the framework's figures are upper bounds with documented heuristics.

## How cost data appears

### On the `TriageRecord`

Every TriageRecord produced after framework version 0.8.0 carries an optional `cost_estimate` field. When populated, it looks like this:

```json
{
  "cost_estimate": {
    "input_tokens": 1247,
    "output_tokens": 412,
    "model_id": "anthropic:claude-sonnet-4-5",
    "estimated_cost_usd": 0.0186,
    "price_table_version": "2026-05-27"
  }
}
```

The five fields together let an auditor reconstruct exactly how the dollar figure was computed:

- `input_tokens` and `output_tokens` are the actual counts reported by PydanticAI's `result.usage` after the LLM call returns. They are exact, not estimates.
- `model_id` is the PydanticAI-style provider:model identifier the framework was configured with.
- `estimated_cost_usd` is `(input_tokens * input_price + output_tokens * output_price) / 1_000_000` against the price table indicated by `price_table_version`.
- `price_table_version` is a date string (YYYY-MM-DD) identifying which price table revision produced the dollar figure. The framework keeps prior table versions accessible so old records remain interpretable when prices change.

`cost_estimate` is absent (not null; absent) when the framework cannot resolve the configured model_id to a known price entry. This happens for test fixtures (`FunctionModel`, `TestModel`) and for any model not in the published price table. Deployments using custom Model adapters or models the framework doesn't know about will see records without cost data; this is the framework's contract ("cost is best-effort"), not an error.

### In audit packs

Audit pack rendering reads the `cost_estimate` field and displays it in the per-record HTML when populated. The deployment can format the dollar figure however suits their audience (currency conversion, internal cost-center allocation, etc.) by post-processing the rendered HTML.

### In observability signals

When observability is enabled, every LLM call emits:

- An `llm.call.cost_recorded` event with the same five fields as the record's `cost_estimate`, plus a `reason` attribute when the cost could not be computed (set to `model_id_not_in_price_table` for unknown models).
- A `vrt_llm_cost_usd_total{model, status}` counter incremented by the dollar figure when the model is known. Unknown models don't contribute.
- A `vrt_llm_tokens_total{kind, model}` histogram observed twice per call (once for `kind=input`, once for `kind=output`) regardless of whether the model is in the price table.

See `docs/observability-guide.md` for the full event and metric reference.

## The published price table

### What it covers

As of `PRICE_TABLE_VERSION = "2026-05-27"`, the framework ships pricing for 33 models across four providers:

- **Anthropic** (7 models): Claude Opus 4.7, Opus 4.6, Opus 4.1 (legacy), Sonnet 4.6, Sonnet 4.5 (the framework's `DEFAULT_MODEL`), Haiku 4.5, Haiku 3 (legacy).
- **OpenAI** (10 models): GPT-5.5 (current flagship), GPT-5.4 family (GPT-5.4, Mini, Nano), GPT-4.1 family (GPT-4.1, Mini, Nano), GPT-4o family (GPT-4o, Mini), o3 reasoning.
- **Google** (6 models): Gemini 3 Pro, Gemini 3.1 Pro, Gemini 3.5 Flash, Gemini 2.5 Pro, Gemini 2.5 Flash-Lite, Gemini 2.0 Flash (deprecating June 1, 2026).
- **Mistral** (10 models): Mistral Large 3, Large 2, Medium 3.5, Medium 3, Small 4, Small 3.1, Small 3, Codestral, Ministral 8B, Ministral 3B.

Each entry records the model_id, provider, input price per million tokens (MTok), output price per MTok, source URL, last-verified date, and an optional notes field.

### What it does not cover

Standard rates only. The framework does NOT model these pricing variants:

- **Batch API discounts** (typically ~50% off). Providers like Anthropic, OpenAI, and Google offer batch endpoints with significant discounts; the framework's estimates do not account for this.
- **Prompt caching** (up to ~90% off cached input). Anthropic and OpenAI offer cache-aware pricing where repeated identical inputs cost a fraction of the standard rate.
- **Long-context surcharges**. Google Gemini 3 Pro charges $4/$18 above 200K context tokens (vs $2/$12 below); Anthropic Claude charges differently above 1M tokens. The framework uses the standard tier rate for all calls regardless of context length.
- **Regional data residency uplifts**. OpenAI applies a 10% uplift for regional endpoints on the GPT-5 family. Anthropic applies 10-25% uplifts on data-residency endpoints.
- **Fast mode** premium tiers. Anthropic Opus 4.6 Fast mode is $30/$150 (vs $5/$25 standard).
- **Tool use** and managed agent surcharges.
- **Negotiated enterprise rates**. Deployments with custom contracts override the published prices via `ModelPriceTable(prices=...)`.

In all of these cases, the framework's cost estimate is an upper bound on real-world spend at the deployment's negotiated rates. Deployments wanting precise spend should either configure a custom `ModelPriceTable` or post-process the token counts against their own pricing logic.

### Source conflicts

The Mistral Large 3 entry notes a source conflict: as of the 2026-05-27 verification, some sources report $0.50/$1.50 per MTok (margindash, cloudzero) and others report $2.00/$6.00 per MTok (devtk.ai, aipricing.guru, tokenmix). The framework uses $2.00/$6.00 based on the more widely cited figure. Deployments needing precise Mistral cost data should verify against the official Mistral pricing page before relying on this number.

When source conflicts surface for other models in future verifications, the resolution pattern is:

1. Document the conflict in the entry's `notes` field with both figures and the sources.
2. Choose the more widely cited figure.
3. Flag the entry for re-verification in 30-60 days.

### Refreshing the table

Provider pricing changes. The framework's commitment is to keep `PRICE_TABLE_VERSION` updated on a roughly quarterly cadence, with out-of-band updates when a major provider announces meaningful price changes (a new generation, a large discount, a deprecation).

The refresh workflow:

1. **Verify each provider's pricing page** against the entries in `pricing/pricing.py`. Cross-check with at least one reputable third-party tracker (CloudZero, Finout, PE Collective, pricepertoken, aipricing.guru, margindash, devtk.ai, tokenmix).
2. **Update entries that have changed**. Each entry records the new input/output prices, an updated `last_verified_date`, and any notes about deprecations or new pricing variants.
3. **Add new models** the provider has launched since the last refresh. Match the PydanticAI naming convention (`provider:model-version`).
4. **Remove deprecated models** the provider has fully sunset. Be conservative: a "deprecating soon" model stays in the table until the actual end-of-life date passes.
5. **Bump `PRICE_TABLE_VERSION`** to today's date in YYYY-MM-DD format.
6. **Update the maintenance workflow doc** if structural patterns change (new providers added, new pricing dimensions modeled).
7. **Bump `FRAMEWORK_VERSION` patch number** (e.g., 0.8.1 → 0.8.2). Price table refreshes are patch bumps because they do not change schema, behavior of existing call sites, or public API.
8. **Regenerate the demo scenarios baseline** if cost data appears in those records. (Currently it does not, because demo scenarios use FunctionModel.)
9. **Verify tests pass** including the specific assertions about flagship prices (e.g., `test_anthropic_current_flagship_pricing`). Update those tests when the flagship's price changes.

### Adding a custom price entry

A deployment with negotiated enterprise rates can override the published table:

```python
from pricing import ModelPrice, ModelPriceTable, PRICE_TABLE

# Start from the published table and override one entry
custom_prices = dict(PRICE_TABLE)
custom_prices["anthropic:claude-sonnet-4-5"] = ModelPrice(
    model_id="anthropic:claude-sonnet-4-5",
    provider="anthropic",
    input_price_per_mtok=2.10,   # 30% off standard $3.00
    output_price_per_mtok=10.50, # 30% off standard $15.00
    source_url="https://internal.deployment/contracts/anthropic-2026",
    last_verified_date="2026-05-27",
    notes="Negotiated rate, 30% off standard. Contract renews 2027-01-01.",
)

custom_table = ModelPriceTable(
    prices=custom_prices,
    version="2026-05-27-internal-v1",
)
```

The custom table is not currently wired into `TriageAgent` (the agent uses the module-level `compute_cost` against the published table). Deployments wanting custom pricing in their TriageRecords need to either fork the agent or post-process the records to substitute their own cost figures. A future framework version may add an `Optional[ModelPriceTable]` parameter to `TriageAgentConfig`.

## The `--cost-budget` CLI flag

### Basic usage

The `vrt triage` subcommand accepts a `--cost-budget DOLLARS` flag that refuses LLM calls projected to exceed a deployment-specified maximum. The flag must be paired with `--max-output-tokens N` so the gate can compute an upper-bound cost.

```bash
# Allow up to 50 cents per decision, with 8192 max output tokens
vrt triage submission.json --cost-budget 0.50 --max-output-tokens 8192

# Tighter budget for high-volume routing through a cheaper model
vrt triage submission.json --model anthropic:claude-haiku-4-5 \
    --cost-budget 0.01 --max-output-tokens 4096
```

### How the gate works

When `--cost-budget` is set, before invoking the LLM the CLI:

1. Constructs the prompt the agent will send (the same call site the agent uses internally).
2. Counts input tokens using a character-based heuristic (~4 chars per token for English text).
3. Computes upper-bound cost as `(input_tokens + max_output_tokens) at the model's standard rates`.
4. Compares to the budget. If estimate exceeds budget, refuses the call with exit code 1 and an explanatory error message.

The gate is **conservative by design**. The upper bound assumes the LLM produces its full `max_output_tokens` (almost never the case for classification tasks), so the gate refuses some calls that would have come in under budget. The alternative, guessing "typical" output length, creates a false sense of safety; an unusually verbose call would slip through and exceed the actual budget.

### What it does NOT protect against

- **Multiple calls within a session.** The gate is per-invocation. A loop calling `vrt triage` many times can collectively exceed any single-call budget.
- **Provider rate changes mid-flight.** If the provider raises prices between when the framework's table was last refreshed and now, the estimate may be low. Refresh the table regularly.
- **Pricing variants not in the table.** Long-context surcharges, fast-mode premiums, and regional uplifts are not modeled. A call that activates one of those variants may cost more than the gate estimated.
- **Variable token counts on retries.** PydanticAI may retry an LLM call if the response doesn't validate against the output schema; each retry counts as a separate call with its own tokens.

For deployments needing aggregate budget enforcement (total spend per day, per customer, etc.), implement budget tracking at the orchestration layer above `vrt triage`. The framework's per-call gate is one piece of the picture, not the whole.

### Error messages

When the gate refuses, the CLI prints a multi-line error to stderr:

```
ERROR: cost budget check failed.
  Estimated upper-bound cost $0.204855 exceeds budget $0.010000 by $0.194855.
  (1247 input tokens at 4 chars/token + 8192 max output tokens.)
```

The error names the estimated cost, the budget, the gap, and the token counts used. Exit code is `1` (budget refusal is a soft error, not a setup error).

When the model is unknown:

```
ERROR: cost budget check failed.
  Cannot enforce budget: model 'nonexistent:fake-model' is not in the framework's published price table.
  The budget gate refuses unknown models rather than letting the call through without verification.
  Either configure a known model or remove --cost-budget.
```

This is intentional. Letting unknown models bypass the gate would defeat its purpose.

## Customer pricing conversations

A deployment evaluating the framework typically asks three pricing questions early. Here are the right answers.

### "How much will this cost us per decision?"

Compute against the deployment's expected token volume:

```python
from pricing import compute_cost

# Typical classification call: ~1500 input + ~500 output tokens
# Sonnet 4.5: ~$0.011 per call
cost = compute_cost("anthropic:claude-sonnet-4-5", 1500, 500)
# $0.011

# Same call on Haiku 4.5: ~$0.004 per call (3x cheaper)
cost = compute_cost("anthropic:claude-haiku-4-5", 1500, 500)
# $0.004

# Same call on Opus 4.7: ~$0.017 per call (1.5x more expensive)
cost = compute_cost("anthropic:claude-opus-4-7", 1500, 500)
# $0.017
```

These are reasonable point estimates for the framework's typical workload (a few KB of submission JSON in, a structured classification out). For the deployment's real numbers, run a few representative submissions through the framework with observability enabled and read `cost_estimate.estimated_cost_usd` off the resulting records.

### "What if we have a high-volume use case?"

Multiply per-call cost by call volume:

```
10,000 decisions/month on Sonnet 4.5 = ~$110/month
100,000 decisions/month on Sonnet 4.5 = ~$1,100/month
1,000,000 decisions/month on Sonnet 4.5 = ~$11,000/month
```

At those volumes, model routing matters. Routing simple decisions to Haiku 4.5 (3x cheaper) and reserving Sonnet 4.5 for complex cases can cut spend by 50-70%. The framework's CLI accepts a `--model` flag to override per call; deployments wanting automatic routing should implement that at the orchestration layer.

Also flag batch API discounts (50% off) and prompt caching (90% off cached input) as available optimizations. Both are provider-managed; deployments enable them at the provider configuration level, and the framework's estimates do not account for them (so the framework's figures are upper bounds, and real spend will typically be lower).

### "Can you guarantee a maximum cost?"

No, and you should be honest about why:

- The `--cost-budget` flag enforces a hard per-call ceiling. That part is guaranteed.
- Aggregate spend across many calls is not bounded by the framework. The deployment's orchestration layer needs to handle that.
- The framework cannot guarantee its price table reflects current provider pricing; the deployment should refresh the table at least quarterly and post-validate against actual invoices.

A useful framing: the framework gives you the data to track and gate cost. It does not replace your accounting system.

## Deferred and out-of-scope

- **`TriageAgentConfig(pricing_table=...)` parameter.** Deployments with custom pricing currently override at the call site (`compute_cost(...)` directly) or by forking the agent. Adding the parameter to the config is non-controversial but waits for a deployment actually needing it. Tagged `[deferred-future]` in the maintenance doc.
- **Aggregate budget tracking.** Per-call gating is the framework's scope; per-session, per-day, per-customer budgets are the orchestration layer's. The framework documents the pattern but does not implement it.
- **Provider-specific tokenizers.** The 4-chars-per-token heuristic is good enough for budget gating. Real tokenizers (`tiktoken`, etc.) would improve precision at the cost of provider-specific dependencies. Deployments wanting precision can call `count_input_tokens_heuristic` with a pre-tokenized count.
- **Modeling batch API, prompt caching, long-context tiers.** These are real pricing variants but each adds complexity to the price table and to the estimator. Deferred until deployment feedback indicates which variants matter most.
- **Currency conversion.** The framework prices in USD only. Deployments operating in other currencies handle conversion at their accounting layer.
