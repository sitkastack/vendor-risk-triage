# Retrieval

This folder holds the BM25-based regulation text retrieval that grounds
the agent's classifications in actual regulatory text rather than the
LLM's training memory. The retrieval layer is intentionally separate
from the agent: the agent consumes retrieved Chunks via its
`regulation_chunks` parameter; the retriever has no LLM dependency.

## What ships now (Phase 3 sub-system 5)

The package:

- `chunk.py`: the `Chunk` Pydantic model (corpus name, document name,
  page number, text, content hash)
- `index.py`: the `BM25Index` class and `tokenize()` function
- `retriever.py`: the `Retriever` class wrapping an index
- `corpus.py`: the `CorpusLoader` class that turns PDFs into Chunks

Agent integration:

- `TriageAgent.triage(submission, documents=..., regulation_chunks=...)`
  accepts an optional list of retrieved chunks
- Each Chunk's content is included in the LLM prompt under
  `BEGIN_REGULATION_CONTEXT` / `END_REGULATION_CONTEXT` delimiters with
  `chunk_id`, `corpus`, `document`, and `page` in a header
- The system prompt instructs the LLM to treat chunks as authoritative
  framework context, to cite chunks by `chunk_id` in reasoning text,
  and to ignore chunks that do not bear on the submission's tier or
  disposition

## Design choices made for MVP

### BM25 lexical retrieval, not vector embeddings

Lexical retrieval was the deliberate choice for these reasons:

- **Vendor-agnostic**: no embedding model means no provider lock-in for
  retrieval. This matches the framework's stance for LLM calls
  (PydanticAI provider abstraction) and document parsing.
- **Deterministic**: BM25 scores are a pure function of the corpus and
  the query. Embeddings change across model updates, perturbing
  rankings in ways that complicate audit.
- **Auditable**: a reviewer can inspect which query tokens matched
  which chunks and why a chunk ranked where it did. Cosine similarity
  on embeddings is harder to explain.
- **Pure Python**: `rank-bm25` depends only on numpy. No GPU, no large
  model file, no inference cost per query.

Vector retrieval is tagged for Phase 4 work. The likely path: hybrid
lexical + vector with the lexical score remaining the primary audit
signal.

### One Chunk per page

The MVP chunking strategy uses one Chunk per PDF page. This is the
cheapest strategy (sub-system 4's `PDFReader` already produces per-page
text) and works because regulations are mostly text-dense without
massive single-paragraph pages. Section-aware chunking is tagged for
follow-up.

### In-memory index, not persisted

The BM25 index is built at `BM25Index` construction and lives in
memory. Persistence is deferred because:

- A typical corpus of five regulations is a few hundred to a few
  thousand chunks; indexing this in memory is fast (milliseconds)
- Persistence introduces format choices (parquet, pickle, custom JSON)
  that benefit from real-deployment learning
- Re-indexing on every retriever construction is the cheaper
  development path until persistence is proven needed

### No real regulation text in the repo

The framework ships the retrieval abstraction and synthetic test data
only. Real regulation corpora are user-provided because:

- **Copyright**: ISO 42001 is a commercial standard. COSO frameworks
  for ICFR are commercial. OSFI E-23, NIST AI RMF, and EU AI Act each
  have specific redistribution terms that an MVP cannot assume.
- **Versioning**: regulations are revised; tying the framework's
  release cycle to regulation revision cycles is wrong.
- **Selection**: different deploying organisations care about
  different regulation subsets.

The framework provides the loading machinery; deploying organisations
populate `corpora/` (or wherever they keep their authorised copies)
with the regulation PDFs they have the right to use.

## Limitations to know about

### BM25 on very small corpora

The Okapi BM25 inverse document frequency formula degenerates when the
corpus has very few documents:

- With 1 document, a query term in that document gets a negative IDF
  (treated as a stopword by the formula)
- With 2 documents, a query term in exactly 1 gets an IDF of zero
- With 3+ documents, IDF starts to be meaningfully positive

Real deployments (five regulations, hundreds to thousands of pages each)
have well-behaved IDF. This limitation is a deployment-time concern
only if a deploying org indexes a very thin corpus (one regulation, one
document, fewer than ~10 chunks).

### No stemming, no stopword removal

"Regulating", "regulation", "regulated" are distinct tokens. "The",
"a", "of" count as tokens. The tradeoff is transparency: the
`tokenize()` function is a single regex; what you see is what gets
indexed. If retrieval quality is poor in practice, this is the first
knob to revisit.

### No semantic matching

A query for "AI governance" will not match a chunk that talks about
"AI management systems" unless they share literal tokens. Mitigation:
the caller constructs the query, so the caller can include synonyms or
domain-specific paraphrases. The agent's caller in production should
construct queries from the salient submission fields (jurisdiction,
ai_usage_level, decision_role, ai_act_self_classification) using
known regulation vocabulary.

## Building a corpus

For each regulation you have the right to redistribute or use:

```python
from pathlib import Path
from retrieval import CorpusLoader, BM25Index, Retriever

loader = CorpusLoader()
all_chunks = []

for corpus_name, document_name, pdf_path in [
    ("osfi-e23", "guideline-2023-09-15", Path("corpora/osfi-e23.pdf")),
    ("nist-ai-rmf", "1.0", Path("corpora/nist-ai-rmf-1.0.pdf")),
    ("eu-ai-act", "regulation-2024-1689", Path("corpora/eu-ai-act.pdf")),
]:
    chunks = loader.load_pdf(
        corpus_name=corpus_name,
        document_name=document_name,
        content=pdf_path.read_bytes(),
    )
    all_chunks.extend(chunks)

retriever = Retriever(BM25Index(all_chunks))
```

The Retriever can be reused across many triage calls; the index does
not change unless the corpus does.

## Using retrieval in a triage

```python
from agent.agent import TriageAgent

agent = TriageAgent()

# Build a query from salient submission fields.
query = " ".join([
    submission.get("ai_usage_level", ""),
    submission.get("jurisdiction", ""),
    *(f.get("decision_role", "") for f in submission.get("ai_features_disclosed", [])),
])
chunks = retriever.query(query, top_k=5)

record = agent.triage(submission, regulation_chunks=chunks)
```

## Vector and hybrid retrieval (Phase 4 sub-system 5)

The framework supports three retrieval strategies that compose with
the same `Retriever` wrapper:

### VectorIndex - dense semantic retrieval

`VectorIndex` pre-computes L2-normalized embeddings for every chunk
and ranks by cosine similarity at query time. It captures semantic
similarity that BM25 misses: a query for "AI governance" finds
chunks discussing "AI management systems" even with no shared
tokens.

```python
from retrieval import VectorIndex, Retriever, SentenceTransformerEmbedder

embedder = SentenceTransformerEmbedder("all-MiniLM-L6-v2")
index = VectorIndex(chunks, embedder)
retriever = Retriever(index)
```

### HybridIndex - lexical + dense via RRF

`HybridIndex` builds both BM25 and Vector indexes over the same chunks
and combines per-query rankings via **Reciprocal Rank Fusion** (k=60).
RRF combines ranks rather than raw scores, so it's robust to the scale
mismatch between BM25 scores and cosine similarities.

```python
from retrieval import HybridIndex, Retriever, SentenceTransformerEmbedder

index = HybridIndex(chunks, embedder=SentenceTransformerEmbedder())
retriever = Retriever(index)
```

Hybrid is the recommended default for production retrieval. BM25 alone
captures exact-token matches and regulation-specific acronyms; vector
alone captures semantic similarity. Hybrid gets both signals.

### Embedder Protocol

`VectorIndex` accepts any class implementing the `Embedder` Protocol.
The framework ships two implementations:

- **`HashEmbedder`** (no external deps): deterministic hash-based
  pseudo-embeddings. Does NOT capture semantic similarity. Used in
  tests and as a fallback when sentence-transformers is not installed.
- **`SentenceTransformerEmbedder`** (opt-in via `[vector]` extra):
  production semantic embeddings via the sentence-transformers
  library. Default model `all-MiniLM-L6-v2` (384-dim, ~80MB).

Adding a Voyage, OpenAI, Cohere, or local-Llama embedder requires only
implementing the Protocol's `dimension` property and `embed()` method.
No framework changes.

### Optional installation

The `[vector]` extra installs sentence-transformers:

```
pip install 'sitkastack-vrt[vector]'
```

Without the extra, `HashEmbedder` works but semantic retrieval does
not.

## Deferred

Tagged for follow-up commits within sub-system 5:

- `[deferred-subsystem-5-followup]` Persistent BM25 indexes (parquet
  format, lazy-loaded)
- `[deferred-subsystem-5-followup]` Section-aware chunking (detect
  headings, group by section)
- `[deferred-subsystem-5-followup]` Real corpus manifest (URLs and
  fetch instructions for the five primary regulations, when
  redistribution terms allow)

Tagged for Phase 4 follow-up:

- `[deferred-phase-4-followup]` Cross-encoder reranking
- `[deferred-phase-4-followup]` Query expansion via thesaurus or LLM

Tagged for Phase 5:

- `[deferred-phase-5]` Voyage / OpenAI / Cohere built-in Embedders
- `[deferred-phase-5]` Persistent vector indexes (FAISS, ChromaDB)
- `[deferred-phase-5]` Multi-tenant corpora (different deploying orgs
  index different regulation selections; the framework remains
  selection-agnostic)
