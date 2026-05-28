# Maintenance workflow

This document is for maintainers of the framework itself. It covers the procedures for evolving the framework's code and contracts: version bumps, SYSTEM_PROMPT updates, corpus refreshes, model dependency upgrades, schema evolution, security advisory response, and the release checklist.

This is not a contributor guide (see `CONTRIBUTING.md`) and not a deployment guide (see `docs/customization-guide.md`). It assumes you have commit access to the main repository and you are deciding what changes to merge and when to cut a release.

## 1. Release cadence and version semantics

The framework follows semantic versioning on `FRAMEWORK_VERSION`. The current value is `0.6.0`.

**Major bump (`X.0.0`)** is reserved for:

- Breaking changes to `schemas/input-contract-*.schema.json` or `schemas/output-contract-*.schema.json`
- Breaking changes to the `AuditLogEnvelope` wire format (any change to canonical-bytes rules, hash algorithm, required fields)
- Removal of a publicly-exported function or class
- Renames that downstream code would have to update for

**Minor bump (`0.X.0`)** is reserved for:

- New publicly-exported functionality (a new module, a new helper, a new flag)
- New optional schema fields (added via `extension_schema_version`, not by modifying the base)
- New SYSTEM_PROMPT content that materially changes classification behavior (even if technically backwards-compatible at the API surface)
- A new corpus added to the default manifest
- A new regulatory framework tag enumerated in the schema

**Patch bump (`0.0.X`)** is for:

- Bug fixes that do not change classification behavior
- Documentation-only changes
- Test additions
- Internal refactoring with no API change
- Dependency version pins that do not affect behavior

**Pre-1.0 note.** While the framework is pre-1.0, the major version stays at 0 and breaking changes ride in minor bumps. The 1.0 release will signal API stability commitments. Aim is mid-2027.

### Where FRAMEWORK_VERSION lives

The constant is defined in `_version.py` at the repository root as the single source of truth:

```python
FRAMEWORK_VERSION: str = "0.6.0"
```

Both `agent/agent.py` and `reporting/audit_pack.py` import the constant from `_version` rather than defining their own. To bump the version, edit `_version.py` and `pyproject.toml` together. CI verifies the two stay in sync via `scripts/check_version_sync.py`; the workflow step fails if they disagree.

### CLI command compatibility

The `vrt` console script and its five subcommands (`triage`, `render`, `drift`, `corpus`, `version`) are part of the framework's public surface as of `0.6.0`. Renaming or removing a subcommand is a breaking change requiring a major version bump. Adding a new subcommand or a new flag with sensible default is a minor bump. Adding a new positional argument to an existing subcommand is a breaking change unless the argument is optional with a backwards-compatible default.

The CLI is invoked through two paths: the installed `vrt` console script (registered in `pyproject.toml` under `[project.scripts]`) and `python -m cli`. Both must work for the framework to be considered installable; the CI test `test_cli_main_module_runnable` exercises the latter, and the install verification step (`pip install -e .` followed by `vrt --version`) is part of the release checklist.

### Observability surface compatibility

As of `0.7.0`, the framework emits a defined set of observability signals through the `observability` package. The surface has grown additively: `0.8.0` added `llm.call.cost_recorded` plus `vrt_llm_cost_usd_total` and `vrt_llm_tokens_total`; `0.9.0` added `llm.call.fallback_triggered`, `circuit_breaker.opened`, `circuit_breaker.half_opened`, `circuit_breaker.closed`, plus `vrt_llm_fallback_total` and `vrt_circuit_state_changes_total`:

- Seventeen event names (`agent.constructed`, `triage.started`, `triage.completed`, `llm.call.started`, `llm.call.completed`, `llm.call.cost_recorded`, `llm.call.fallback_triggered`, `retrieval.started`, `retrieval.completed`, `validation.started`, `validation.completed`, `drift.check.started`, `drift.check.completed`, `audit_pack.rendered`, `circuit_breaker.opened`, `circuit_breaker.half_opened`, `circuit_breaker.closed`)
- Fourteen metric names (the `vrt_*` family documented in `docs/observability-guide.md`)
- Five span names (`vrt.triage`, `vrt.llm_call`, `vrt.retrieval`, `vrt.validation`, `vrt.audit_pack.render`)
- The three Protocol interfaces (`EventLogger`, `Metrics`, `Tracer`)
- The `correlation_id` field on `TriageRecord` (optional, 16-character lowercase hex when populated)
- The `cost_estimate` field on `TriageRecord` (optional nested object; absent when the framework cannot resolve the configured model_id to a known price entry)
- The `resilience` package public surface (CircuitBreaker, CircuitBreakerConfig, CircuitState, ModelHealth, BreakerStateStore, InMemoryBreakerStateStore) and the `fallback_models` / `circuit_breaker` fields on TriageAgentConfig

Renames or removals to any of these are breaking changes requiring a major version bump. Additions are minor bumps. Adding methods to the Protocol interfaces is a breaking change for any deployment with custom implementations.

The `[otel]` extra and the `OtelTracer` adapter are stable as of `0.7.0`. The OpenTelemetry dependency pin range (`opentelemetry-api>=1.20.0,<2`) is part of the framework's commitment; bumping the upper bound is a minor change when API-compatible, a major change when the upgrade breaks deployments.

## 2. SYSTEM_PROMPT update procedure

The `SYSTEM_PROMPT` constant in `agent/agent.py` shapes every classification the framework produces. Edits to it require disciplined process.

### Step-by-step

1. **Edit the prompt.** Make the change in `agent/agent.py`. The `SYSTEM_PROMPT_HASH` constant is computed from the prompt bytes; do not edit it manually.

2. **Run the test suite.** `python -m pytest`. The existing tests verify schema conformance, demo scenario classification, agent_version composition, and citation/calibration/judge behavior. They catch structural breakage; they do not catch classification drift on the demo scenarios.

3. **Run the drift check.** `python scripts/check_drift.py`. This compares current decisions against the checked-in baseline.

4. **Interpret the drift report.** Three outcomes:
   - No drift detected: ship the prompt edit as a documentation or stylistic change. No version bump needed unless the edit was substantive.
   - Soft drift only (rationale text, mitigation text, confidence within ±0.05): if the drift is intentional, regenerate the baseline (`python scripts/check_drift.py --update-baseline`) and commit the new baseline file alongside the prompt change. If the drift is unintentional, revise the prompt.
   - Hard drift (tier, disposition, evidence count, framework tags): investigate before accepting. A hard drift on a demo scenario means the prompt edit changed the framework's classification of a curated example. If intentional, regenerate the baseline and clearly document the reasoning in the commit message; consider whether this warrants a minor version bump rather than patch.

5. **Decide on version bump.** Editorial or clarifying prompt changes with no drift: patch bump optional. Prompt changes that produce intentional drift: minor bump required. A SYSTEM_PROMPT edit that materially changes classification behavior on hand-curated scenarios is a behavior change for downstream consumers.

6. **Commit.** Stage the prompt edit, the baseline (if regenerated), the version bumps (if any). Sign off per the DCO. Run `git push origin main`.

7. **CI verifies.** The CI pipeline runs the drift check; if you regenerated the baseline locally but didn't commit it, CI fails. If you bumped FRAMEWORK_VERSION in one location but not the other, CI does not currently catch it; double-check manually.

### What not to do

Do not auto-regenerate the baseline as part of every commit. The bypass mechanism exists to make accepting drift an intentional decision, not a silent one.

Do not bump SYSTEM_PROMPT_HASH manually. The constant is computed in `agent/agent.py`; touching it directly breaks the audit-traceability guarantee that the recorded `agent_version` corresponds to the prompt that produced the decision.

## 3. Corpus refresh procedure

When a regulation updates (OSFI releases a revised E-23, the EU AI Act gets an implementing act, NIST publishes a new AI RMF revision), the framework's corpus needs to refresh.

### Step-by-step

1. **Verify license.** Before ingesting a new or updated document, confirm the framework has the right to redistribute or, where it does not, that the deploying organization holds the license. ISO standards, certain industry frameworks, and paywalled publications are not redistributable. Document the licensing status in `docs/corpus-manifest.md`.

2. **Source the authoritative document.** Use the regulator's official publication URL where possible. For draft or non-final guidance, prefer the comment-period draft over informal summaries. Record the source URL and access date in the manifest entry.

3. **Compute the SHA-256.** Pin the document by content hash so subsequent runs verify against the same bytes. The hash goes in `tests/integration/corpora_cache.py`.

4. **Rebuild the IndexBundle.** Run the corpus build script for that regulation (see `scripts/build_corpus_bundles.py` for the pattern). The output is a `*.bundle.tgz` file containing chunks, manifest, and optional embeddings.

5. **Update the corpus manifest.** Edit `docs/corpus-manifest.md` to record: the document name, source URL, access date, version (where the regulator versions explicitly), SHA-256, and license status.

6. **Run the test suite.** A corpus refresh changes retrieval results, which can change classifications. Run the full test suite (`pytest`) and the drift check (`scripts/check_drift.py`).

7. **Interpret drift.** If the refresh produces hard drift on demo scenarios, that's usually a real signal - the new regulation says something different about a category the demo scenario was classified under. Investigate per-scenario; the right answer is sometimes "the demo scenario's expected classification needs to update because the regulatory expectation changed."

8. **Decide version bump.** A corpus refresh is at minimum a patch bump (the framework now retrieves from a newer source). If the refresh changes classifications materially, minor bump.

9. **Commit and push.** Include the manifest update, the corpus build script changes if any, the regenerated baseline (if drift was accepted), and the version bump.

### Notes on government corpora

OSFI documents are Crown copyright; redistribution is restricted. The framework does not ship OSFI E-23 bundles; deployments source these locally. Document this in your engagement intake (see `docs/customization-guide.md` section 1.5).

NIST documents are US public domain; safe to redistribute.

EU AI Act text is published by the European Union; redistribution is permitted with attribution.

Industry standards (ISO, IEEE) are licensed; only the deploying organization with a valid license can use them. The framework does not ingest these directly.

## 3a. Price table refresh procedure

The framework ships an LLM pricing table at `pricing/pricing.py` covering all four major providers' lineups (33 models as of 0.8.0). Providers change prices, launch new models, and deprecate old ones; the maintainer commits to a roughly quarterly refresh cadence, with out-of-band updates when a major provider announces meaningful changes (a new generation, a large discount, a deprecation).

### When to refresh

Trigger a refresh in any of these cases:

- A provider has announced a new model that deployments will plausibly route through (judgment call; usually means the model is at least covering 30 days post-launch and has public pricing).
- A provider has announced a meaningful price change (>20% in either direction, or a structural change like adding a long-context tier).
- A provider has announced an end-of-life date for a model in the table.
- The last `last_verified_date` on any entry is more than 90 days old.
- A deployment reports a discrepancy between the table and their actual invoice.

### Step-by-step

1. **Open `pricing/pricing.py`** and identify entries that need updating. For each provider, visit their official pricing page (URLs are in the `_<PROVIDER>_SOURCE` constants at module level). Cross-check against at least one reputable third-party tracker (CloudZero, Finout, PE Collective, pricepertoken, aipricing.guru, margindash, devtk.ai, tokenmix).
2. **Update existing entries** whose prices have changed. Each modified entry records the new `input_price_per_mtok` and/or `output_price_per_mtok`, an updated `last_verified_date` (today's date in YYYY-MM-DD format), and any `notes` about new pricing variants or deprecation timelines.
3. **Add new model entries** the provider has launched since the last refresh. Match the PydanticAI naming convention (`provider:model-version`, e.g., `anthropic:claude-sonnet-4-6`). Include `notes` flagging if the model is the current flagship, a legacy variant, or has a pricing variant the framework does not model (long-context, batch-only, etc.).
4. **Remove deprecated model entries** the provider has fully sunset. Be conservative: a "deprecating soon" model stays in the table until the actual end-of-life date passes. When removed, also remove or update any tests asserting on the entry (typically in `tests/test_pricing.py`).
5. **Resolve source conflicts** if two reputable sources disagree on a price. Document the conflict in the entry's `notes` field with both figures and the sources. Choose the more widely cited figure or the value closer to the legacy entry from the same provider. Flag the entry for re-verification in 30-60 days.
6. **Bump `PRICE_TABLE_VERSION`** in `pricing/pricing.py` to today's date in YYYY-MM-DD format. This is the constant that every TriageRecord's `cost_estimate.price_table_version` field will record from now on.
7. **Update `docs/cost-tracking-guide.md`** if the structural pricing patterns have changed (a new provider added, a new pricing dimension modeled, the source-conflict policy refined).
8. **Bump `FRAMEWORK_VERSION` patch number** (e.g., 0.8.1 → 0.8.2). Price table refreshes are patch bumps because they do not change schema, behavior of existing call sites, or public API. Bump pyproject.toml to match.
9. **Run the test suite**. The tests in `tests/test_pricing.py` include specific assertions about flagship prices (e.g., `test_anthropic_current_flagship_pricing`); update those if the flagship's price has changed. The total model count assertion (`test_price_table_has_thirty_three_models`) needs updating if models were added or removed.
10. **Regenerate the demo scenarios baseline** if any cost data has changed in those records. Currently the demo scenarios use FunctionModel which is unknown to the price table, so the baseline records carry no cost data, and no regeneration is needed for table-only changes.
11. **Verify drift check passes**. Cost data lives in the drift checker's "always ignored" list as of 0.8.0, so price table changes do not trigger drift. If they ever do, the maintenance doc's schema evolution section is the right place to look first.
12. **Commit with a clear message** following the existing pattern: `chore(pricing): refresh price table for YYYY-MM-DD verification`. List the providers updated, the models added/removed, and any structural pricing changes (new tiers, new pricing variants) in the body.

### What not to do

Do not bump `PRICE_TABLE_VERSION` without re-verifying every entry. The version date is the maintainer's commitment to having done the work; bumping without verifying breaks the audit chain.

Do not model batch API discounts, prompt caching, long-context surcharges, or regional uplifts without a formal proposal. The framework's "standard rates only" policy is explicit in the `pricing/pricing.py` docstring and in the cost tracking guide; changing it is a behavior change that warrants discussion across multiple deployments first.

Do not silently change the table's structure. Adding fields to `ModelPrice` (e.g., a batch_input_price_per_mtok) is a backwards-compatible change but still warrants a minor version bump and updates to the cost tracking guide.

## 4. Model dependency upgrade

The framework's runtime depends on PydanticAI, which itself depends on provider SDKs (Anthropic, OpenAI, Google, etc.). Upgrades happen for security patches, new model versions, and new features.

### Step-by-step

1. **Read the upstream changelog.** PydanticAI's release notes name breaking changes. Provider SDKs (especially Anthropic and OpenAI) sometimes ship breaking changes in their Python clients.

2. **Bump the dependency pin.** Edit `pyproject.toml`. The framework pins minor-version-range dependencies (e.g., `pydantic-ai>=0.0.X,<0.1.0`) to avoid surprise breakage on transitive updates. Tighten the pin if the upstream is in flux.

3. **Run the test suite.** The agent's core test path (`tests/test_agent_core.py`) exercises TriageAgent construction with TestModel and FunctionModel. PydanticAI API changes surface here.

4. **Run the drift check.** A model-SDK upgrade should not change classifications on the deterministic test double, but if PydanticAI changes how it serializes ToolCallPart payloads or how it composes the agent prompt, drift can surface.

5. **Run the real-LLM integration tests if you have an API key.** The `real_llm` marker gates these; they cost money per run. Use them when:
   - The upgrade is a model version change (Claude Sonnet 4 → 4.5)
   - The upgrade changes how the agent constructs its tool calls
   - You're about to cut a release that customers will adopt

6. **Update the customization guide if needed.** If the upgrade changes the recommended `TriageAgentConfig` shape (new provider parameter, deprecated argument), section 2.6 of `docs/customization-guide.md` needs to update.

7. **Decide version bump.** Internal dependency upgrades with no API change: patch. Dependency upgrades that change `TriageAgentConfig` signature or default behavior: minor.

### Model version upgrades specifically

When Anthropic releases a new Claude model (or any provider releases a new model), update `DEFAULT_MODEL` in `agent/agent.py` thoughtfully:

- Test the new model against the framework's classification quality (run the real-LLM integration tests against your demo scenarios; compare classifications and confidence).
- Decide whether the change is "default upgrade" (every new deployment gets the new model) or "opt-in" (existing deployments keep the old default; new deployments choose).
- Bump FRAMEWORK_VERSION. A model default change is a minor bump because deployments running on defaults experience the change.

The `agent_version` string baked into every TriageRecord captures the model identifier, so an auditor can grep records produced by a specific model version. This is the safety net for model-default changes.

## 5. Schema evolution

The framework has three versioned schemas: input contract (`schemas/input-contract-1.0.0.schema.json`), output contract (`schemas/output-contract-1.0.0.schema.json`), and audit log envelope (`ENVELOPE_SCHEMA_VERSION` constant in `reporting/audit_log.py`). All are pinned at `1.0.0`. No v2 is planned.

### When to bump major

- A previously-required field becomes optional or vice versa
- A field's type changes (string → object, integer → string)
- A field is renamed
- A required field is added (existing records produced under the prior schema would not validate against the new one)
- The canonical-bytes serialization rules for the envelope change

### When to bump minor

- A new optional field is added at the base level
- An enumerated value is added to a field that previously had a closed enum
- A constraint is relaxed (max length increases, regex broadens)

### Migration story

When a major bump becomes necessary, the framework ships a migration document at `docs/schema-migration-X-to-Y.md` describing field-by-field changes and supplying a transformation function. The transformation lives in `schemas/migrations/` (does not exist today; create it on first migration).

The output schema is the harder migration: existing TriageRecords in customer archives must remain valid under their original schema version. The framework keeps prior schema versions in `schemas/output-contract-1.0.0.schema.json`, `schemas/output-contract-1.1.0.schema.json`, and so on. `schemas/validate.py` reads the record's `output_schema_version` field and dispatches to the corresponding schema file. The agent only produces records under the latest schema (currently 1.1.0).

The audit log envelope is the simpler case: a major bump signals to consumers that they must upgrade before parsing newer envelopes; consumers already check `envelope_schema_version` and refuse incompatible majors with a clear error (`parse_jsonl_line` raises `AuditLogParseError` with a "incompatible" message).

### Worked example: 1.0.0 -> 1.1.0 (Phase 6 SS2)

The 0.7.0 release added the optional `correlation_id` field to TriageRecord for observability correlation across logs, metrics, and traces. The migration:

1. New schema file `schemas/output-contract-1.1.0.schema.json` was added alongside the existing `output-contract-1.0.0.schema.json`. The 1.0.0 file was not modified.
2. The new file added `correlation_id` to `properties` with `type: string`, `minLength: 1`, `maxLength: 128`, and a regex pattern restricting it to URL-safe characters. The field is NOT in `required`, preserving backwards compatibility.
3. The new file updated `output_schema_version` from `pattern: "^\\d+\\.\\d+\\.\\d+$"` to `const: "1.1.0"`. Records explicitly declare which schema they conform to.
4. `schemas/validate.py` gained a `_OUTPUT_SCHEMA_FILES` dispatch mapping; `validate_output()` reads `output_schema_version` from the record and selects the matching schema file.
5. `agent/agent.py` bumped `OUTPUT_SCHEMA_VERSION` to `"1.1.0"`. New records declare 1.1.0; old records in customer archives still declare 1.0.0 and validate against the 1.0.0 schema.
6. The Pydantic `TriageRecord` model in `agent/output_models.py` gained an optional `correlation_id: Optional[str]` field with matching validation.
7. The drift detection baseline was regenerated (the new records have correlation_id and declare 1.1.0); the drift checker's "always ignored" list was extended to include `correlation_id`.

No migration code was needed because the change is purely additive: every 1.0.0 record is a valid 1.1.0 record except for the schema version stamp itself, and consumers reading older records validate them against the older schema.

### Worked example: 1.1.0 -> 1.2.0 (Phase 6 SS3-A)

The 0.8.0 release added the optional nested `cost_estimate` field to TriageRecord for LLM cost tracking. The migration:

1. New schema file `schemas/output-contract-1.2.0.schema.json` was added alongside `output-contract-1.1.0.schema.json` and `output-contract-1.0.0.schema.json`. Earlier files were not modified.
2. The new file added `cost_estimate` to `properties` as a `$ref` to a new `$defs/cost_estimate` definition. The cost_estimate object has five required inner fields (input_tokens, output_tokens, model_id, estimated_cost_usd, price_table_version) with `additionalProperties: false` to lock the inner shape. The outer `cost_estimate` is NOT in `required`, preserving backwards compatibility.
3. The new file updated `output_schema_version` from `const: "1.1.0"` to `const: "1.2.0"`.
4. `schemas/validate.py` `_OUTPUT_SCHEMA_FILES` dispatch was extended with `"1.2.0": "output-contract-1.2.0.schema.json"`. Three schemas are now in the dispatch (1.0.0, 1.1.0, 1.2.0).
5. `agent/agent.py` bumped `OUTPUT_SCHEMA_VERSION` to `"1.2.0"`.
6. The Pydantic `TriageRecord` model in `agent/output_models.py` gained an optional `cost_estimate: Optional[CostEstimate]` field. A new `CostEstimate` BaseModel was added with matching Pydantic validation (non-negative tokens, date-pattern on price_table_version, etc.).
7. A new `pricing/` package was added with `ModelPriceTable`, `ModelPrice`, `PRICE_TABLE`, `PRICE_TABLE_VERSION`, `compute_cost`, and `lookup_price`. The agent's `_capture_cost_estimate` helper reads `result.usage` from the LLM call, looks up the model in the price table, and builds the CostEstimate (or returns None for unknown models, leaving cost_estimate absent on the record).
8. The drift detection baseline was regenerated for 0.8.0; the drift checker's "always ignored" list was extended to include `cost_estimate` (per-run token usage and dollar figure, varies with prompt length, not a classification signal).

The pattern is identical to the 1.0.0 -> 1.1.0 migration: additive nested optional field, new schema file alongside the old, new version stamp, validator dispatch extended. The pricing package is the substantive new infrastructure; the schema bump is the contract-level expression of it.

### Worked example: 1.2.0 -> 1.3.0 (Phase 7 SS2) - the first breaking change

Every prior schema change was additive-optional: a record produced under an older version was already a valid newer-version record except for the version stamp. The 1.3.0 change is the framework's first breaking one: it adds a `tenant_id` field that is *required*, so a pre-1.3.0 record (which has no tenant_id) genuinely fails 1.3.0 validation. The migration:

1. New schema file `schemas/output-contract-1.3.0.schema.json` was added alongside the 1.0.0, 1.1.0, and 1.2.0 files (which were not modified). It adds `tenant_id` to both `properties` and `required` on the base definition, with the field constrained to either the tenant slug pattern or the reserved sentinel `__default__` (expressed as an `anyOf`). The `output_schema_version` const was set to `1.3.0`.
2. `schemas/validate.py` `_OUTPUT_SCHEMA_FILES` dispatch was extended with `"1.3.0"`. All four schemas (1.0.0, 1.1.0, 1.2.0, 1.3.0) are now in the dispatch. This is the decision that preserves backward compatibility: a record declaring 1.2.0 still validates against the 1.2.0 schema (which never required tenant_id), so archived records are never retroactively invalidated. Only records declaring 1.3.0 or later are held to the new requirement.
3. `agent/agent.py` bumped `OUTPUT_SCHEMA_VERSION` to `1.3.0`. The agent now stamps `tenant_id` into every record it produces.
4. The Pydantic `TriageRecord` model gained an `Optional[str]` `tenant_id` field whose presence is enforced *conditionally by declared output_schema_version*: the model validator requires it when `output_schema_version >= 1.3.0` and permits its absence otherwise. This mirrors the JSON-schema dispatch in a single model class: the model can still represent a historical 1.2.0 record (tenant_id absent) and a current 1.3.0 record (tenant_id required), exactly as the dispatch does. A field-level validator enforces the slug-or-sentinel rule when a value is present.

The key lesson: even a breaking schema change does not have to break the validator for old records. By keeping every published schema file frozen and dispatching by the record's declared version, the framework lets a 2026 record validate against 2026's contract forever, while new records adopt the new requirement. The "breaking" nature is real (new records must carry tenant_id; a consumer expecting every record to have one must handle the migration of old records) but it is contained to records that opt into the new version.

Because pre-1.3.0 records cannot be made valid 1.3.0 records by a version restamp alone (they lack a tenant identity), this is the first schema change that needs a real migration engine rather than a restamp. That engine (SS3) assigns a tenant to pre-tenancy records as it up-migrates them.

### What not to do

Do not modify a `1.0.0` schema file in place. Once `1.0.0` is published, it is frozen. Modifications go in a new file with a new version. The framework code dispatches by the version string in the record.

Do not skip the migration document for a major bump. The framework's customers depend on being able to read records they produced last year.

## 6. Security advisory response

When a dependency CVE lands or a vulnerability is reported against the framework directly, the response procedure is:

### For dependency CVEs

1. **Assess scope.** Does the CVE affect a code path the framework actually exercises? Many CVEs in transitive dependencies are theoretical for this framework's usage pattern. Read the advisory; check the affected module.

2. **Check for a patched version.** Most CVEs have a fix in a subsequent minor or patch release. Bump the dependency pin to the patched version.

3. **Run the test suite and drift check.** The dependency upgrade procedure in section 4 applies.

4. **Cut a patch release.** Security-only patches get a patch version bump and a `SECURITY-ADVISORY.md` note in the release.

5. **Notify downstream.** Add a `SECURITY.md` advisory if one does not exist; update it with the CVE reference and the patched version range.

### For framework vulnerabilities

If someone reports a vulnerability in the framework itself (via `SECURITY.md` reporting path or a private channel):

1. **Acknowledge within 48 hours.** Respond to the reporter with confirmation of receipt and a CVSS estimate.

2. **Privately develop the fix.** Use a private branch or fork. The vulnerability should not be discussed in public until a patched release is available.

3. **Coordinate disclosure.** If the vulnerability has CVE-level severity (CVSS 7.0+), file a CVE through GitHub's advisory mechanism. The reporter typically gets credit unless they request anonymity.

4. **Release the patched version.** Patch bump, with the CVE referenced in the release notes.

5. **Publish the advisory.** After the patched version is released, publish the public advisory naming the affected versions, the CVSS score, and the fix.

### What not to do

Do not silently fix a vulnerability without a disclosure. Customers running affected versions need to know to upgrade.

Do not delay a security patch to bundle it with feature work. Security patches ship on their own.

## 7. Release checklist

Most of the automatable gates below are checked by `python scripts/prepare_release.py`, which runs version sync, changelog-current, the full suite, the coverage gate, drift, and the em-dash check, then emits a go/no-go report plus the manual steps. Run it before cutting any release. The version bump itself is performed by `python scripts/bump_version.py {major|minor|patch}` (atomic across `_version.py` and `pyproject.toml`, refuses on a dirty tree unless `--allow-dirty`), and the changelog is regenerated by `python scripts/extract_changelog.py` after the History entry is written.

When cutting a versioned release:

- [ ] All tests pass on main (`python -m pytest`)
- [ ] Coverage threshold met (currently 95% minimum, currently at 100%)
- [ ] Drift check passes (`python scripts/check_drift.py`)
- [ ] 3-run test stability verified (`for i in 1 2 3; do python -m pytest 2>&1 | tail -1; done`)
- [ ] No em-dashes in markdown documentation (CI-enforced)
- [ ] `FRAMEWORK_VERSION` in `_version.py` matches `pyproject.toml` `version` (CI-enforced via `scripts/check_version_sync.py`)
- [ ] `CHANGELOG.md` regenerated and current (`python scripts/extract_changelog.py --check`)
- [ ] Editable install works: `pip install -e .` succeeds, `vrt --version` prints the expected framework version
- [ ] CHANGELOG entry written naming user-visible changes (via the `_version.py` History section)
- [ ] Migration document written if schema major version bumps
- [ ] Customization guide updated if `TriageAgentConfig` signature changed
- [ ] Maintenance workflow doc updated if any procedure here changed
- [ ] `git tag v{FRAMEWORK_VERSION}` and pushed
- [ ] GitHub release published with release notes
- [ ] Downstream consumers notified for breaking changes (via release notes, mailing list, or direct contact for known deployments)

### Release cadence guidance

Patch releases ship as needed (security, bugs, doc fixes). No minimum cadence.

Minor releases ship roughly monthly during active development, more often when shipping a coordinated set of customer-facing changes.

Major releases ship rarely. The 1.0 target is mid-2027; until then, minor bumps carry breaking changes with clear migration notes.

### What goes in a release

- All commits since the prior release tag
- A release notes file naming user-visible changes, grouped by category (added, changed, fixed, deprecated, removed, security)
- The baseline file as it currently exists on main (the drift check passes against it)
- Updated corpus bundles if applicable
- Updated schema files if a new major version is being introduced (prior versions stay in the repo for backwards compatibility)

### What stays out of a release

- Speculative features behind feature flags
- Internal refactoring not yet exposed in the public API
- Pre-release model upgrades that haven't been validated against the integration test suite
- Documentation drafts not yet ready for external consumption

## Notes on known issues to fix during routine maintenance

- The drift check uses the deterministic FunctionModel; real-LLM drift is a Phase 6 deferral. When Phase 6 ships, this maintenance procedure gains a step for running the real-LLM drift mode on prompt changes.
- The continuous monitoring infrastructure (separate sitkastack consulting tooling) is out of scope for this framework's maintenance procedures. Maintainers of that tooling work from their own runbook.
