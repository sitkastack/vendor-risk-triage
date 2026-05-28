"""Harvest demo and content artifacts from a regulation corpus.

The integration tests (tests/integration/) verify the framework works
against real regulation PDFs, but they only assert; they do not emit
anything you can show. This script runs the same end-to-end pipeline
and SAVES the tangible artifacts: a rendered audit pack, a retrieval
transcript, and the triage record JSON. Those are the raw material for
a demo or a content piece ("here is a real vendor triaged against the
actual OSFI E-23 guideline, with citations to real sections").

Pipeline (identical to the integration test, plus rendering):

1. Load the regulation PDF (from the integration cache by corpus name,
   or from an explicit --pdf path).
2. Chunk it with the section-aware loader.
3. Build a BM25 index and retrieve the top-k chunks for a query.
4. Triage a representative vendor submission with the retrieved chunks
   supplied as regulation context.
5. Render the audit pack HTML.
6. Save: <corpus>-audit-pack.html, <corpus>-retrieval-transcript.md,
   <corpus>-record.json.

By default the agent runs against a deterministic FunctionModel (no
cost, no key): the point is to produce real *retrieval* and *rendering*
artifacts against real regulatory text. Pass --real-llm (with
ANTHROPIC_API_KEY set) to use the production model for the reasoning.

Usage::

    # From the integration cache (after pinning hashes; see
    # tests/integration/README.md). Requires network on first fetch.
    python scripts/harvest_corpus_artifacts.py osfi-e23

    # From a local PDF you already have:
    python scripts/harvest_corpus_artifacts.py osfi-e23 \\
        --pdf ~/Downloads/osfi-e23.pdf

    # With the real LLM doing the reasoning:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/harvest_corpus_artifacts.py nist-ai-rmf --real-llm

Exit codes: 0 success; 1 pipeline failure (no chunks, no retrieval
hits); 2 setup error (unknown corpus, PDF not found/unfetchable).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# A representative submission. Uses a real example submission shape so
# the rendered pack is contract-faithful. Defaults to the tier-3
# document-OCR scenario, which thematically exercises regulation
# retrieval (PII flow, third-party model, data residency).
_DEFAULT_SUBMISSION = (
    _REPO_ROOT / "examples" / "submissions"
    / "03-tier3-document-ocr-loans.json"
)

_DEFAULT_QUERY = (
    "AI vendor risk management governance accountability "
    "data classification PII oversight third-party model"
)


def _double_agent(top_chunk_ids: list[str]):
    """A deterministic FunctionModel agent that cites the top chunk."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from agent.agent import TriageAgent, TriageAgentConfig

    first = top_chunk_ids[0] if top_chunk_ids else "<none>"
    payload: dict[str, Any] = {
        "risk_tier": "tier_3_elevated",
        "recommended_disposition": "conditional_approve",
        "classification_rationale": (
            "The vendor processes financial PII through a third-party "
            "model with cross-border data flow, warranting an elevated "
            "tier under the cited regulatory guidance. Conditional "
            "approval pending the listed mitigations."
        ),
        "evidence_cited": [
            {
                "input_field_reference": "$.data_residency",
                "reasoning": (
                    f"Cross-border residency triggers heightened scrutiny "
                    f"per retrieved guidance ({first})."
                ),
            },
        ],
        "confidence_signal": {"score": 0.74, "interpretation": "moderate"},
        "required_mitigations": [
            "Obtain a signed data-processing addendum before go-live.",
            "Quarterly third-party access and residency review.",
        ],
        "accountable_owner": "Senior Vendor Risk Manager",
    }

    def _call(_msgs, _info):
        return ModelResponse(parts=[
            ToolCallPart(tool_name="final_result", args=payload),
        ])

    return TriageAgent(TriageAgentConfig(model=FunctionModel(_call)))


def _resolve_pdf(corpus: str, pdf_arg: Optional[Path]) -> Path:
    """Return the PDF path: explicit --pdf, else the integration cache."""
    if pdf_arg is not None:
        if not pdf_arg.exists():
            raise FileNotFoundError(f"--pdf path not found: {pdf_arg}")
        return pdf_arg
    # Fall back to the integration cache fetch (network on first run).
    # verify=False: the harvest tool renders the current bytes of the
    # regulation; it is not the pin-verification path (that is the
    # integration test). This lets fetchable-but-unpinnable sources
    # like the OSFI print route be harvested by name.
    from tests.integration.corpora_cache import fetch_corpus, CorpusFetchError
    try:
        return fetch_corpus(corpus, verify=False)
    except CorpusFetchError as exc:
        raise FileNotFoundError(
            f"could not fetch {corpus}: {exc}. Either the host blocks "
            f"scripted access (e.g. EUR-Lex for eu-ai-act) or the URL "
            f"moved; download the PDF in a browser and pass --pdf."
        ) from exc


def _write_transcript(
    path: Path, corpus: str, query: str, top_chunks: list[Any], total: int,
) -> None:
    """Write a human-readable retrieval transcript."""
    lines = [
        f"# Retrieval transcript: {corpus}",
        "",
        f"Query: {query}",
        "",
        f"Corpus chunks: {total}. Showing top {len(top_chunks)} by BM25.",
        "",
    ]
    for rank, chunk in enumerate(top_chunks, start=1):
        excerpt = " ".join(chunk.text.split())[:400]
        lines.append(f"## Rank {rank}: {chunk.chunk_id}")
        section = getattr(chunk, "section_path", None) or getattr(
            chunk, "section", None
        )
        if section:
            lines.append(f"Section: {section}")
        lines.append("")
        lines.append(excerpt + ("..." if len(excerpt) == 400 else ""))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Harvest demo/content artifacts from a regulation corpus.",
    )
    parser.add_argument("corpus", help="Corpus name (e.g. osfi-e23).")
    parser.add_argument("--pdf", type=Path, default=None,
                        help="Local PDF path (skips the cache fetch).")
    parser.add_argument("--output-dir", type=Path,
                        default=_REPO_ROOT / "corpus-artifacts",
                        help="Where to write artifacts.")
    parser.add_argument("--query", type=str, default=_DEFAULT_QUERY,
                        help="Retrieval query.")
    parser.add_argument("--submission", type=Path, default=_DEFAULT_SUBMISSION,
                        help="Vendor submission JSON.")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Number of chunks to retrieve.")
    parser.add_argument("--real-llm", action="store_true",
                        help="Use the production LLM (needs ANTHROPIC_API_KEY).")
    args = parser.parse_args(argv)

    from retrieval.corpora import CORPUS_REGISTRY
    if args.corpus not in CORPUS_REGISTRY:
        print(f"ERROR: unknown corpus {args.corpus!r}. Known: "
              f"{sorted(CORPUS_REGISTRY.keys())}", file=sys.stderr)
        return 2

    try:
        pdf_path = _resolve_pdf(args.corpus, args.pdf)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.submission.exists():
        print(f"ERROR: submission not found: {args.submission}", file=sys.stderr)
        return 2
    submission = json.loads(args.submission.read_text(encoding="utf-8"))

    from retrieval import BM25Index, CorpusLoader, Retriever
    from reporting import render_audit_pack

    document_name = CORPUS_REGISTRY[args.corpus].document_name

    # 1-2. Chunk.
    chunks = CorpusLoader().load_pdf(
        corpus_name=args.corpus, document_name=document_name,
        content=pdf_path.read_bytes(), sectionize=True,
    )
    if not chunks:
        print(f"ERROR: no chunks produced from {pdf_path} (image-only PDF?)",
              file=sys.stderr)
        return 1

    # 3. Retrieve.
    retriever = Retriever(BM25Index(chunks))
    top_chunks = retriever.query(args.query, top_k=args.top_k)
    if not top_chunks:
        print("ERROR: retrieval returned no chunks for the query.",
              file=sys.stderr)
        return 1

    # 4. Triage.
    if args.real_llm:
        from agent.agent import TriageAgent, TriageAgentConfig
        agent = TriageAgent(TriageAgentConfig())
    else:
        agent = _double_agent([c.chunk_id for c in top_chunks])
    record = agent.triage(submission=submission, regulation_chunks=top_chunks)

    # 5. Render.
    html = render_audit_pack(record, submission)

    # 6. Save.
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    pack_path = out / f"{args.corpus}-audit-pack.html"
    transcript_path = out / f"{args.corpus}-retrieval-transcript.md"
    record_path = out / f"{args.corpus}-record.json"
    pack_path.write_text(html, encoding="utf-8")
    _write_transcript(transcript_path, args.corpus, args.query,
                      top_chunks, len(chunks))
    record_path.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8")

    print(f"Harvested {args.corpus} artifacts ({len(chunks)} chunks, "
          f"top {len(top_chunks)} retrieved):")
    print(f"  audit pack:  {pack_path}")
    print(f"  transcript:  {transcript_path}")
    print(f"  record:      {record_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
