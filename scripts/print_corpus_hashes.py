"""Print the SHA-256 of each regulation corpus PDF, for pinning.

The integration test suite verifies each corpus PDF against a pinned
SHA-256 in ``retrieval/corpora.py``. Those pins ship as the all-zero
placeholder until someone fetches the real PDFs once and records their
hashes. This script does that: it downloads each corpus the same way
the framework does (same URL, same user agent), computes the SHA-256,
and prints it.

Run it once, copy the output, and update the pins (or hand the output
to whoever maintains the registry). It is safe to re-run: it only
reads from the network and prints; it changes nothing.

Usage::

    python scripts/print_corpus_hashes.py

Output is one line per corpus, either::

    osfi-e23        <64-hex-sha256>
    nist-ai-rmf     <64-hex-sha256>

or, when a download fails::

    eu-ai-act       ERROR: HTTP 403 fetching https://...

A download error is not fatal to the others; the script reports each
corpus independently and continues.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    from retrieval.corpora import CORPUS_REGISTRY
    # Reuse the framework's exact user agent so the bytes (and thus the
    # hash) match what the integration test will later download and
    # verify against the pin.
    from tests.integration.corpora_cache import _USER_AGENT, _FETCH_TIMEOUT_SECONDS

    # Bodies smaller than this are almost certainly not a real
    # regulation PDF (an empty 200, a challenge page, an error stub).
    # We refuse to emit a hash for them: a hash of garbage is worse
    # than no hash, because pinning it would "verify" the garbage. The
    # smallest real corpus here (NIST AI RMF) is well over 100 KB.
    min_plausible_bytes = 50_000

    print("Fetching each corpus and printing its size + SHA-256.")
    print("Copy these lines and send them back for pinning.\n")

    any_problem = False
    for name in sorted(CORPUS_REGISTRY.keys()):
        source = CORPUS_REGISTRY[name]
        try:
            request = urllib.request.Request(
                source.url, headers={"User-Agent": _USER_AGENT},
            )
            with urllib.request.urlopen(
                request, timeout=_FETCH_TIMEOUT_SECONDS,
            ) as response:
                payload = response.read()
            size = len(payload)
            if size < min_plausible_bytes:
                any_problem = True
                print(
                    f"{name:16} SUSPICIOUS: only {size} bytes "
                    f"(expected >{min_plausible_bytes}). NOT a usable "
                    f"hash, do not pin. Likely an empty or challenge "
                    f"response from {source.url}"
                )
                continue
            digest = hashlib.sha256(payload).hexdigest()
            print(f"{name:16} {size:>9} bytes  {digest}")
        except urllib.error.HTTPError as exc:
            any_problem = True
            print(f"{name:16} ERROR: HTTP {exc.code} fetching {source.url}")
        except urllib.error.URLError as exc:
            any_problem = True
            print(f"{name:16} ERROR: network error fetching {source.url}: {exc.reason}")
        except Exception as exc:  # noqa: BLE001 - report-and-continue tool
            any_problem = True
            print(f"{name:16} ERROR: {type(exc).__name__}: {exc}")

    if any_problem:
        print(
            "\nOne or more corpora did not return a usable PDF. Report "
            "which ones. A SUSPICIOUS or empty body usually means the "
            "host blocks scripted access (EUR-Lex does this); download "
            "that PDF in a browser and pass it to "
            "scripts/harvest_corpus_artifacts.py via --pdf. An HTTP error "
            "usually means the URL moved."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
