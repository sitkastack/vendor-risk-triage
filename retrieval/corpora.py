"""Registry of regulation corpus sources.

This module defines the data structures the framework uses to describe
fetchable regulation PDFs: the ``CorpusSource`` dataclass and the
``CORPUS_REGISTRY`` mapping from corpus short name to source record.

Two consumers depend on this module:

- ``scripts/build_corpus_bundles.py`` reads the registry to know which
  PDFs to chunk and embed into ``IndexBundle`` archives.
- ``cli/cmd_corpus.py`` reads the registry to print the inventory in
  ``vrt corpus list``.

Integration tests in ``tests/integration/corpora_cache.py`` separately
consume the registry to fetch PDFs over the network, verify them
against the pinned SHA-256, and cache the bytes on disk. The fetcher
logic stays in the tests directory; only the data structures live
here so the framework itself can be wheel-installed without depending
on the tests package.

The SHA-256 pins are intentional. If a regulator publishes an
amendment, the cached copy's hash will no longer match the pin and
the integration test fails loudly until a human reviews whether the
new version of the regulation still matches the framework's expected
behavior (citations, tier outputs, audit-trail format).

Pinning workflow is documented in ``docs/corpus-manifest.md``. The
verification log lists when each pin was last reviewed and against
which source URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


__all__ = ["CorpusSource", "CORPUS_REGISTRY"]


@dataclass(frozen=True)
class CorpusSource:
    """Provenance record for a fetchable corpus PDF.

    Attributes:
        name: Short identifier for the corpus. Used as the cache
            subdirectory name and as ``corpus_name`` when the test
            wraps the bytes in a CorpusLoader call.
        url: Authoritative source URL (the regulator's publication
            endpoint). Recorded in ``docs/corpus-manifest.md``.
        sha256_hex: Pinned SHA-256 of the expected PDF bytes, hex
            string (no ``sha256:`` prefix). When the regulator
            publishes an amendment, this hash will no longer match
            and tests will fail until the pin is updated by a human.
        filename: Filename for the cached copy on disk. Stable;
            renaming forces a refetch.
        document_name: ``document_name`` to use when wrapping the
            bytes in a Chunk via CorpusLoader. Recorded here so the
            chunk_id naming convention is consistent across test
            and production paths.
    """

    name: str
    url: str
    sha256_hex: str
    filename: str
    document_name: str


CORPUS_REGISTRY: Dict[str, CorpusSource] = {
    "osfi-e23": CorpusSource(
        name="osfi-e23",
        url=(
            # OSFI republishes the direct gd-mrm-*.pdf path on each
            # refresh, breaking it (404). The Drupal print-PDF route for
            # the E-23 (2027) guideline node is the live endpoint and
            # returns the guideline text. Confirmed live 2026-05.
            "https://www.osfi-bsif.gc.ca/en/print/pdf/node/1893"
        ),
        # NOT content-hash-pinnable: the print-PDF route is
        # non-deterministic. Two fetches of this URL on the same
        # machine, same user agent, no intervention, produced different
        # SHA-256 digests (an embedded generation timestamp/session
        # token in the PDF stream). The pin therefore stays the
        # placeholder. The route IS fetchable, though, and the
        # guideline TEXT it returns is stable, so OSFI is fetched with
        # fetch_corpus(verify=False): the integration test and the
        # harvest script both run against the current bytes without a
        # content-hash check. See tests/integration/README.md.
        sha256_hex="0" * 64,
        filename="osfi-e23-guideline-2027.pdf",
        document_name="guideline-2027",
    ),
    "nist-ai-rmf": CorpusSource(
        name="nist-ai-rmf",
        url="https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        # Pinned 2026-05. Verified by three independent fetches
        # producing byte-identical output (1,946,127 bytes). A static
        # NIST publication; the integration test verifies against this.
        sha256_hex="7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1",
        filename="nist-ai-rmf-100-1.pdf",
        document_name="100-1",
    ),
    "eu-ai-act": CorpusSource(
        name="eu-ai-act",
        url=(
            # Canonical EUR-Lex OJ PDF link (cited as the source by
            # published reproductions of the Act). The URL is correct;
            # the OJ and CELEX forms both return HTTP 200 with an EMPTY
            # body to scripted clients. This is EUR-Lex access control
            # (it serves an interstitial/JS consent flow to non-browser
            # agents), not a stale URL.
            "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/"
            "?uri=OJ:L_202401689"
        ),
        # NOT pinnable from this source: EUR-Lex does not serve the PDF
        # to urllib (empty body), so fetch_corpus cannot retrieve it
        # automatically. To use the EU AI Act, open the URL above in a
        # browser (EUR-Lex serves the real PDF to browsers, just not
        # scripts), save the file as
        # ``~/.cache/sitkastack-vrt/corpora/eu-ai-act/eu-ai-act-regulation-2024-1689-en.pdf``,
        # and then either: (a) run pytest -m integration and the EU
        # test will run against the cached copy (verify=False), or
        # (b) pass the file directly to
        # scripts/harvest_corpus_artifacts.py via --pdf. See
        # tests/integration/README.md.
        sha256_hex="0" * 64,
        filename="eu-ai-act-regulation-2024-1689-en.pdf",
        document_name="regulation-2024-1689",
    ),
    "sox-pl-107-204": CorpusSource(
        name="sox-pl-107-204",
        url="https://www.govinfo.gov/content/pkg/COMPS-1883/pdf/COMPS-1883.pdf",
        # Pinned 2026-05. Verified by three independent fetches
        # producing byte-identical output (250,730 bytes). A static
        # govinfo compilation; the integration test verifies against it.
        sha256_hex="048689e26cf64023fa38849e3d1d20f61315b3257b0d18e3717b91c6c6c672eb",
        filename="sox-pl-107-204.pdf",
        document_name="pl-107-204",
    ),
}
"""Registry of fetchable corpus sources.

The SHA-256 pins are placeholders (all-zero) on first commit. The first
``make integration-cache`` run downloads each PDF, computes the actual
hash, and prints an update snippet for this dict. The pins are then
committed by hand.

This deliberately requires a human-in-the-loop step. Pinning the hash
prevents silent corpus drift; bumping the pin is the moment a human
reviews whether the new corpus version still matches the integration
test's expected behavior (citations, tier outputs, audit-trail format).
"""
