# Ingestion

This folder holds the readers that turn vendor-submitted documentation
artifact bytes into ``Document`` objects the agent can include in its
prompt. The input contract states that it "records the reference; it
does not parse the artifact"; this module is the separate concern that
parses the artifact.

## What ships now (Phase 3 sub-system 4)

The package:

- `document.py`: the `Document` Pydantic model with `ArtifactType` enum
- `readers.py`: the `DocumentReader` Protocol, the `DocumentReadError`
  exception, and the `PDFReader` implementation

Agent integration:

- `TriageAgent.triage(submission, documents=...)` accepts an optional
  list of `Document`. Each document is matched to a
  `documentation_artifacts[i]` entry on the submission by
  `source_reference` and verified against any claimed `content_hash` on
  the matched entry. Verification failures raise `TriageInputError`
  before the LLM call.
- The system prompt instructs the LLM to treat document content as data
  (T-AI1 defense) and to cite documents in `evidence_cited` using
  `$.documentation_artifacts[N]` references.

## What does not ship in sub-system 4 (and why)

The full vision for vendor document ingestion includes readers for every
common artifact format, OCR for scanned PDFs, table and form-field
extraction, and a registry that dispatches to the right reader by URI
scheme or artifact type. The honest MVP scope ships one reader (PDF)
and the abstraction every future reader must satisfy. Adding a new
reader is implementing the `DocumentReader` Protocol; no consumer change
is required.

Deferred readers (each a future commit):

| Format | Common artifact types | Why deferred |
|---|---|---|
| XLSX | security_questionnaire | Different parser (openpyxl); structured tabular reading is its own design problem. Tagged [deferred-subsystem-4-followup]. |
| HTML | privacy_policy, architecture_document | Often available as HTML on vendor sites; needs sanitization and link-following decisions. Tagged [deferred-phase-4]. |
| Plain text | various | Trivial; deferred only because no current artifact type targets it. Tagged [deferred-phase-4]. |
| Markdown | model_card | Some model cards are markdown. Tagged [deferred-phase-4]. |

Deferred reader capabilities:

- **OCR fallback for scanned PDFs**: Tesseract or similar. Heavy
  dependency; defer until needed. The MVP `PDFReader` records a warning
  on pages that produce no text so callers can detect the case. Tagged
  [deferred-phase-4].
- **Table extraction**: SOC 2 control activity tables lose structure
  under plain-text extraction. Tools like `pdfplumber` recover tables
  but add complexity. Tagged [deferred-phase-4].
- **Form-field extraction**: security questionnaires often have form
  fields; `pypdf` can read them but the semantics are vendor-specific.
  Tagged [deferred-phase-4].

Deferred document store connectors (Phase 5):

- `internal://` resolver against an institutional document store
- `s3://` resolver
- `https://` resolver with auth
- `file://` resolver for local development

The agent and the readers are designed so connectors are an entirely
separate concern: the caller fetches bytes from wherever and passes them
to the reader. The framework does not impose a document store.

## Reading a PDF

```python
from pathlib import Path
from ingestion import PDFReader

reader = PDFReader()
content = Path("vendor-soc2.pdf").read_bytes()
doc = reader.read(
    source_reference="internal://docstore/vendor-soc2.pdf",
    artifact_type="soc2_report",
    content=content,
)
print(f"Pages: {doc.page_count}")
print(f"Hash: {doc.content_hash}")
print(doc.extracted_text)
```

## Including ingested documents in a triage

```python
from agent.agent import TriageAgent
from ingestion import PDFReader

reader = PDFReader()
agent = TriageAgent()

# Vendor submission has documentation_artifacts pointing at one SOC 2.
submission = load_submission(...)
soc2_ref = submission["documentation_artifacts"][0]["reference"]
soc2_bytes = fetch_from_docstore(soc2_ref)  # institutional concern

soc2_doc = reader.read(
    source_reference=soc2_ref,
    artifact_type="soc2_report",
    content=soc2_bytes,
)

record = agent.triage(submission, documents=[soc2_doc])
```

The agent verifies that `soc2_doc.source_reference` appears in
`submission["documentation_artifacts"]`. If the submission's matching
entry declares a `content_hash`, the agent verifies the Document's hash
matches it. Either check failing raises `TriageInputError` before the
LLM call.

## Adding a new reader

1. Implement the `DocumentReader` Protocol: a class with a `read` method
   matching the signature in `readers.py`.
2. Return a `Document` populated with extracted text, per-page text,
   `content_hash` of the input bytes, and any extraction warnings.
3. Raise `DocumentReadError` on any unrecoverable failure.
4. Add tests in `tests/test_ingestion.py` covering the happy path and
   error paths (malformed input, format-specific failure modes).
5. Update this README with the new reader and remove the corresponding
   row from the "Deferred readers" table.
