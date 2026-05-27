# Integration tests

End-to-end tests against real regulation corpora (OSFI E-23, NIST AI RMF,
EU AI Act, SOX). These tests:

- Fetch regulation PDFs from authoritative sources (cached locally, SHA-256
  verified)
- Build chunks, IndexBundles, BM25 indexes
- Run retrieval queries
- Triage a representative vendor submission through the framework

They are **excluded from the default `pytest` run** because they touch
the network and require disk cache space. They are gated by the
`integration` marker.

## Running

### Default (excludes integration tests)

```bash
pytest                          # the default suite; fast, no network
```

### Run integration tests

```bash
pytest -m integration           # all integration tests, FunctionModel agent
```

### Run integration tests with a real LLM (costs money)

Real-LLM tests require both the `real_llm` marker AND the
`ANTHROPIC_API_KEY` environment variable. Tests skip cleanly when either
is missing.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pytest -m "integration and real_llm"
```

### Everything (default + integration + real-LLM)

```bash
pytest -m ""                    # empty marker filter = include all
```

## Cache layout

The first integration-test run fetches each regulation PDF, verifies the
SHA-256, and caches the bytes at:

```
~/.cache/sitkastack-vrt/corpora/
├── osfi-e23/
│   └── osfi-e23-guideline-2027.pdf
├── nist-ai-rmf/
│   └── nist-ai-rmf-100-1.pdf
├── eu-ai-act/
│   └── eu-ai-act-regulation-2024-1689-en.pdf
└── sox-pl-107-204/
    └── sox-pl-107-204.pdf
```

To override the cache root, set the `SITKASTACK_VRT_CACHE` environment
variable.

## SHA-256 pins and first-run setup

The corpus registry in `corpora_cache.py` ships with placeholder SHA-256
pins (all-zero). The first run for each corpus will:

1. Download the PDF.
2. Compare the downloaded SHA-256 against the placeholder.
3. Fail with a clear message printing the **actual** downloaded SHA-256
   and instructions to update the registry.

This is the right one-time setup: a human commits the real hash after
verifying the downloaded bytes match the regulator's published version.

### Updating pins after first run

When `fetch_corpus()` raises a placeholder-mismatch error, copy the
printed hash into `tests/integration/corpora_cache.py`:

```python
"nist-ai-rmf": CorpusSource(
    name="nist-ai-rmf",
    url="https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
    sha256_hex="a1b2c3...",  # <-- update from the error message
    filename="nist-ai-rmf-100-1.pdf",
    document_name="100-1",
),
```

Commit the change. Subsequent runs verify against the new pin.

### When a regulator publishes an amendment

The cached PDF's hash will no longer match the pin. `fetch_corpus()`
re-downloads, the new copy's hash will not match either, and the test
fails with a message recommending review.

This is intentional. Amendments warrant human review of whether the
integration test's expected behavior (citations, tier outputs, term
matching) still holds against the new corpus text.

## Skipping behavior

Integration tests use `pytest.skip()` when:

- The PDF is not in the cache AND the network is unavailable
- The pinned SHA-256 has not been set (placeholder) on first run
- The pinned SHA-256 disagrees with the downloaded bytes (likely an
  amendment; needs human review)
- `ANTHROPIC_API_KEY` is missing (for `real_llm` tests only)

Skips are clean (test exit code remains 0). Failures only fire when the
framework itself misbehaves on real corpus bytes.

## Adding a new corpus

1. Add an entry to `CORPUS_REGISTRY` in `corpora_cache.py` with the
   authoritative URL, placeholder SHA-256, filename, and document_name
   matching `docs/corpus-manifest.md`.
2. Add a fixture in `conftest.py` following the existing pattern.
3. Add a `test_<corpus>_integration` test in `test_real_corpora.py`
   that calls `_run_pipeline_for_corpus` and asserts a corpus-specific
   sanity term list.
4. On first run, update the SHA-256 pin as described above.

## Why integration tests are separate

Unit tests verify the framework's logic in isolation; integration tests
verify the framework against the real world. The two cadences are
different:

- Unit tests run on every push, in CI, sub-second.
- Integration tests run before releases, when corpora change, or when
  a contributor specifically wants to verify the end-to-end pipeline.

Mixing them slows down the default development feedback loop without
adding signal for most changes.

## What these tests do NOT cover

- **Retrieval quality.** BM25 lexical-only retrieval is used here for
  speed and dep-light testing. Real deployments using the `[vector]`
  extra and `SentenceTransformerEmbedder` get better recall. Retrieval
  quality eval lives in `eval/` with dedicated datasets.
- **LLM reasoning quality.** The FunctionModel-backed agent's output
  is a fixed canned payload; this tests the pipeline plumbing, not the
  LLM's actual reasoning. Real-LLM tests (gated) exercise the LLM, but
  smoke-test only. Full LLM eval lives in `eval/` and `eval/judge/`.
- **Performance.** Integration tests do not benchmark. Performance
  regression testing is a separate workstream.
