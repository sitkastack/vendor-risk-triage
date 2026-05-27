# Corpus Manifest

This document tells deploying organizations where to obtain the regulation
texts the framework supports, the licensing terms under which those texts are
distributed, and the operational pattern for ingesting them into the
sitkastack vendor-risk-triage framework.

**The framework does not ship regulation texts.** It ships the loader,
the indexer, the agent, and the evaluation harness. Each deploying
organization fetches its own authorized copy of each regulation, stores
it locally, and points `CorpusLoader.load_pdf` at the bytes. The
separation is deliberate: redistribution terms vary by regulation, and
some (ISO 42001 in particular) prohibit redistribution outright.

Audit defensibility depends on this separation. A reviewer asking
"where did your AI agent get the OSFI E-23 text it cited?" should receive
the answer "we fetched it from osfi-bsif.gc.ca on 2026-04-15 and stored
the bytes in our internal corpus store; here is the SHA-256." That story
is cleaner than "we vendored a copy from a public AI framework
repository," which raises questions about version freshness, tampering,
and license compliance.

## Verification convention

Each entry below records the source URL, publisher, license, version
last verified, and verification date. Re-verify each entry at the
audit-defensibility check (annually at minimum, and before any
regulator-facing deployment that cites the regulation by chunk_id).

Verification dates in this document reflect a single point-in-time
snapshot. Re-fetching the published guidance and re-comparing the SHA-256
is the only authoritative way to confirm current status.

This manifest was last verified on **2026-05-26**.

## Regulations

### OSFI Guideline E-23: Model Risk Management (2027)

| Field | Value |
|---|---|
| Corpus name (suggested) | `osfi-e23` |
| Document name (suggested) | `guideline-2023-09-15` (or final version date you fetch) |
| Publisher | Office of the Superintendent of Financial Institutions Canada (OSFI) |
| Authoritative source | https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/guideline-e-23-model-risk-management-2027 |
| Final guideline published | September 11, 2025 |
| Effective date | May 1, 2027 (18-month transition from publication) |
| License | Crown copyright; permitted for non-commercial reproduction with attribution under the Government of Canada terms of use |
| Format | HTML and PDF on osfi-bsif.gc.ca |
| Notes | The final version supersedes the November 2023 draft. Applies to all federally regulated financial institutions (FRFIs) including foreign bank branches. Foreign insurance company branches are in scope. Federally regulated pension plans (FRPPs) are out of scope of the final guideline. |

Operational ingestion:

```python
from pathlib import Path
from retrieval import CorpusLoader

# After fetching the PDF from osfi-bsif.gc.ca and storing locally:
chunks = CorpusLoader().load_pdf(
    corpus_name="osfi-e23",
    document_name="guideline-2027",
    content=Path("/secure/corpora/osfi-e23-2027.pdf").read_bytes(),
    sectionize=True,  # OSFI's hierarchical numbering benefits from section-aware chunking
)
```

### NIST AI Risk Management Framework (AI RMF 1.0)

| Field | Value |
|---|---|
| Corpus name (suggested) | `nist-ai-rmf` |
| Document name (suggested) | `100-1` (the publication identifier) |
| Publisher | National Institute of Standards and Technology, U.S. Department of Commerce |
| Authoritative source | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf (DOI: https://doi.org/10.6028/NIST.AI.100-1) |
| Published | January 26, 2023 |
| License | U.S. government work; not subject to U.S. copyright protection (17 U.S.C. § 105). Free to use, copy, modify, and distribute. |
| Format | PDF on nvlpubs.nist.gov |
| Companion documents | AI RMF Playbook (online, https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook); Generative AI Profile (NIST AI 600-1, July 2024) |
| Notes | Voluntary, sector-agnostic, use-case agnostic. Four core functions: Govern, Map, Measure, Manage. The Generative AI Profile (NIST AI 600-1) is a complementary document with the same license; ingest it as a separate document within the `nist-ai-rmf` corpus if generative-AI vendor risk is in scope. |

Operational ingestion:

```python
chunks = CorpusLoader().load_pdf(
    corpus_name="nist-ai-rmf",
    document_name="100-1",
    content=Path("/secure/corpora/NIST.AI.100-1.pdf").read_bytes(),
    sectionize=True,  # NIST uses hierarchical numbering
)
```

### ISO/IEC 42001:2023 AI Management Systems

| Field | Value |
|---|---|
| Corpus name (suggested) | `iso-42001` |
| Document name (suggested) | `2023` (publication year) |
| Publisher | International Organization for Standardization (ISO) and International Electrotechnical Commission (IEC) |
| Authoritative source | https://www.iso.org/standard/42001 (purchase required) |
| Published | December 2023 |
| License | **Commercial license. Redistribution prohibited.** Pricing varies by country and ISO member body. Typical individual purchase price is around CHF 198 (ISO direct); national member bodies (ANSI in the US, BSI in the UK, SCC in Canada, DIN in Germany) sell at similar prices in local currency. Site licenses and corporate licenses available at higher tiers. |
| Format | PDF (purchased copy) |
| Notes | **Each licensee must hold their own copy.** Sharing a single purchased PDF across multiple corporate workstations may violate the ISO license; consult the specific license terms on your purchase. ISO member bodies sometimes offer free read-only previews of the first few pages; these are insufficient for retrieval indexing. |

Operational ingestion:

```python
# After your organization has purchased the standard and stored
# the licensed PDF in your internal corpus store:
chunks = CorpusLoader().load_pdf(
    corpus_name="iso-42001",
    document_name="2023",
    content=Path("/secure/corpora/iso-iec-42001-2023.pdf").read_bytes(),
    sectionize=True,  # ISO uses hierarchical clause numbering (4.1, 6.2.3, etc.)
)
```

Audit consideration: the ISO purchase record itself is part of the
audit trail. A reviewer asking "where did your indexed copy of ISO
42001 come from?" needs to receive a purchase invoice or license
record alongside the SHA-256 of the indexed bytes. Keep the
purchase record in the same governance system that tracks the
content_hash.

### EU AI Act: Regulation (EU) 2024/1689

| Field | Value |
|---|---|
| Corpus name (suggested) | `eu-ai-act` |
| Document name (suggested) | `regulation-2024-1689` |
| Publisher | European Parliament and Council of the European Union |
| Authoritative source | https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng (HTML) and https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689 (PDF) |
| Published in Official Journal | July 12, 2024 |
| Effective date | August 1, 2024 (entered into force); most provisions applicable two years later (August 2, 2026); prohibited-AI provisions applicable six months earlier (February 2, 2025) |
| License | Commission Decision 2011/833/EU on the reuse of Commission documents permits free reuse of EU legal texts for commercial and non-commercial purposes, with attribution. EUR-Lex content is reusable under these terms. |
| Format | HTML and PDF on eur-lex.europa.eu, in 24 EU languages |
| Notes | The English authentic version is recommended for retrieval. Other language versions are equally authoritative under EU law but introduce translation variance that can affect retrieval. If your regulated entity operates across multiple EU member states, consider indexing the local-language version per member state as a separate document within the corpus. |

Operational ingestion:

```python
chunks = CorpusLoader().load_pdf(
    corpus_name="eu-ai-act",
    document_name="regulation-2024-1689",
    content=Path("/secure/corpora/eu-ai-act-en.pdf").read_bytes(),
    sectionize=True,  # EU regulations use Article / Annex / Recital structure
)
```

The default section patterns recognize `Article N`, `Annex N`, and
`Chapter N` headings used throughout the EU AI Act text. Recitals
(numbered preambular paragraphs before the operative provisions) do
not match the default patterns; if your retrieval needs include
recital references, supply a custom pattern set including a recital
matcher.

### SOX / ICFR: Sarbanes-Oxley Act and PCAOB AS 2201

The SOX/ICFR wedge requires two source documents: the statute itself
and the audit standard that implements ICFR obligations.

#### Sarbanes-Oxley Act of 2002

| Field | Value |
|---|---|
| Corpus name (suggested) | `sox` |
| Document name (suggested) | `pl-107-204` (Public Law identifier) |
| Publisher | U.S. Congress (Public Law 107-204) |
| Authoritative source | https://www.govinfo.gov/content/pkg/COMPS-1883/pdf/COMPS-1883.pdf |
| Enacted | July 30, 2002 |
| License | U.S. government work; public domain (17 U.S.C. § 105). Free to use, copy, modify, and distribute. |
| Format | PDF on govinfo.gov |
| Notes | Sections 302 (corporate responsibility for financial reports) and 404 (management assessment of internal controls) are the primary AI-vendor-relevant provisions. The full statute is short (roughly 66 pages); ingesting the whole text is reasonable. |

#### PCAOB Auditing Standard AS 2201

| Field | Value |
|---|---|
| Corpus name (suggested) | `pcaob-as2201` (within the same `sox` corpus, or separate; deploying-org choice) |
| Document name (suggested) | `as-2201-effective-2024-12-15` or `as-2201-amended-2026-12-15` |
| Publisher | Public Company Accounting Oversight Board (PCAOB) |
| Authoritative source | https://pcaobus.org/oversight/standards/auditing-standards/details/AS2201 |
| Current effective version | For fiscal years beginning on or after December 15, 2024 |
| Amended version | Amendments effective December 15, 2026 (PCAOB Release No. 2024-005, SEC Release No. 34-100968) |
| License | PCAOB standards are publicly available; SEC-approved auditing standards are quasi-regulatory and reproducible with attribution. Verify PCAOB's specific reuse terms on the standards page for your use case. |
| Format | HTML on pcaobus.org; PDF compilations available |
| Notes | **Two versions are currently relevant.** For audits of fiscal years beginning on or after December 15, 2024 but before December 15, 2026: the pre-amendment standard. For audits on or after December 15, 2026: the amended standard. Both versions should be indexed during the transition period; chunk_ids should disambiguate via document_name (e.g., `as-2201-2024` and `as-2201-2026`). |

Operational ingestion:

```python
sox_chunks = CorpusLoader().load_pdf(
    corpus_name="sox",
    document_name="pl-107-204",
    content=Path("/secure/corpora/sox-2002.pdf").read_bytes(),
    sectionize=True,  # SOX uses Section N keyword headings
)

# AS 2201 may need to be fetched as HTML and converted to PDF, or
# obtained from a PCAOB-issued PDF compilation.
as2201_chunks = CorpusLoader().load_pdf(
    corpus_name="pcaob-as2201",
    document_name="effective-2024-12-15",
    content=Path("/secure/corpora/pcaob-as-2201-2024.pdf").read_bytes(),
    sectionize=True,
)
```

## Operational guidance

### Storage convention

The framework imposes no storage convention. A reasonable institutional
pattern:

```
/secure/corpora/
  osfi-e23/
    guideline-2027.pdf                  # the bytes
    guideline-2027.fetch.json           # url, fetch date, sha256
  nist-ai-rmf/
    100-1.pdf
    100-1.fetch.json
    600-1.pdf                           # Generative AI Profile
    600-1.fetch.json
  iso-42001/
    2023.pdf                            # licensed copy
    2023.fetch.json                     # includes ISO purchase reference
  eu-ai-act/
    regulation-2024-1689-en.pdf
    regulation-2024-1689-en.fetch.json
  sox/
    pl-107-204.pdf
    pl-107-204.fetch.json
  pcaob-as2201/
    effective-2024-12-15.pdf
    effective-2024-12-15.fetch.json
    amended-2026-12-15.pdf
    amended-2026-12-15.fetch.json
```

Each `*.fetch.json` records the source URL, fetch timestamp, and the
SHA-256 of the bytes. This is the audit-trail anchor: when the agent
cites `osfi-e23:guideline-2027:page-15:section-3` in a triage record,
the reviewer can verify that the indexed bytes match the published
bytes by re-fetching from osfi-bsif.gc.ca and recomputing the hash.

### Re-fetch cadence

Regulations are not static documents. Re-fetch on a defined cadence:

- **Annually at minimum** for stable regulations (SOX, NIST AI RMF).
- **Quarterly** for regulations in transition (OSFI E-23 through May 2027;
  PCAOB AS 2201 around December 2026 amendment).
- **On notification** for any regulation that publishes a change notice.

Each re-fetch produces a new SHA-256. If the hash changed, the corpus
index must be rebuilt and any cached triage records flagged for
re-review against the new text.

### Version anchoring in chunk_ids

The `chunk_id` convention `{corpus}:{document_name}:page-N:section-N`
makes the document version explicit. When a regulation publishes a
new version, the `document_name` changes (`guideline-2023-09-15` becomes
`guideline-2027`); old triage records continue to reference the old
chunk_ids, which trace back to the bytes that were indexed at the time
of the decision. The audit trail is preserved across version changes.

## Not on this list

Other regulations and standards are supported via the
"engagement-supported (no dedicated framework page)" path documented
in sitkastack's positioning. The framework's loader is corpus-agnostic;
any PDF or HTML-to-PDF source can be ingested as a corpus. Notable
adjacent texts deploying organizations may want to index:

- SOC 1 / SOC 2 (AICPA Trust Services Criteria). Purchased from AICPA.
- ISO 27001 / 27002. Purchased from ISO (same terms as ISO 42001).
- NAIC Model Bulletin on AI Systems. Free at naic.org.
- Federal Reserve SR 11-7 (Model Risk Management). Free at federalreserve.gov.
- PCI DSS v4.0.1. Free at pcisecuritystandards.org (account required).
- Sectoral guidance (FDA AI/ML SaMD, FINRA Reg Notice 21-29, etc.). Free at the respective regulator sites.

Each of these follows the same pattern: fetch authoritative bytes,
record source URL and SHA-256, load via `CorpusLoader.load_pdf`.

## Verification log template

Append entries here as your deployment re-verifies the manifest:

```
Date: 2026-05-26
Verifier: <name or initials>
OSFI E-23: confirmed final version effective 2027-05-01; URL unchanged
NIST AI RMF: confirmed 1.0 unchanged; AI 600-1 GenAI profile noted
ISO 42001: pricing checked, license terms unchanged
EU AI Act: confirmed Regulation 2024/1689; phased applicability noted
SOX: confirmed PL 107-204 unchanged
PCAOB AS 2201: confirmed amendment effective 2026-12-15 (pending)
```
