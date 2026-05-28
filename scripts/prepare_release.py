"""Run the release-readiness checklist and emit a go/no-go report.

This script automates the checkable subset of the release checklist in
``docs/maintenance-workflow.md`` section 7. It runs each gate, reports
pass/fail per gate, and exits non-zero if any automatable gate fails.
Gates that cannot be checked programmatically (a human wrote the
migration doc, downstream consumers were notified) are listed as manual
reminders, not pass/fail gates.

The automated gates:

1. Version sync: _version.FRAMEWORK_VERSION == pyproject version.
2. CHANGELOG current: CHANGELOG.md matches the _version.py history.
3. Full test suite passes.
4. Coverage threshold met (95% minimum, enforced by the same flags CI
   uses).
5. Drift check passes.
6. No em-dashes in tracked markdown docs.

Each gate runs as a subprocess (reusing the existing scripts and the
same pytest invocation CI uses) so this script stays a thin
orchestrator over the project's real gates rather than reimplementing
them.

Usage::

    python scripts/prepare_release.py            # run all gates
    python scripts/prepare_release.py --fast      # skip the slow
                                                  # coverage gate

Exit codes:

- ``0``: all automated gates passed. The report still lists the manual
  steps the maintainer must confirm by hand.
- ``1``: one or more automated gates failed.
- ``2``: setup error (a gate could not run at all).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Coverage flags mirror the CI workflow so this gate checks exactly what
# CI checks. Kept as a module constant so a maintainer updating the
# package list updates it in one place.
_COVERAGE_PACKAGES = [
    "_version", "agent", "cli", "eval", "ingestion", "observability",
    "pricing", "resilience", "retrieval", "reporting", "tenancy", "migration",
]


@dataclass
class GateResult:
    """Outcome of a single release gate."""

    name: str
    passed: bool
    detail: str


def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    """Run a subprocess, returning (returncode, combined output)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return 1, f"command failed to run: {exc}"
    return result.returncode, (result.stdout + result.stderr)


def _gate_version_sync() -> GateResult:
    code, out = _run([sys.executable, "scripts/check_version_sync.py"])
    last = out.strip().splitlines()[-1] if out.strip() else ""
    return GateResult("version sync", code == 0, last)


def _gate_changelog_current() -> GateResult:
    code, out = _run(
        [sys.executable, "scripts/extract_changelog.py", "--check"]
    )
    last = out.strip().splitlines()[-1] if out.strip() else ""
    return GateResult("CHANGELOG current", code == 0, last)


def _gate_tests() -> GateResult:
    code, out = _run([sys.executable, "-m", "pytest", "-q"])
    last = out.strip().splitlines()[-1] if out.strip() else ""
    return GateResult("test suite", code == 0, last)


def _gate_coverage() -> GateResult:
    cov_flags = [f"--cov={pkg}" for pkg in _COVERAGE_PACKAGES]
    cmd = [sys.executable, "-m", "pytest", "-q", *cov_flags,
           "--cov-fail-under=95"]
    code, out = _run(cmd)
    # Find the coverage summary line if present.
    detail = ""
    for line in out.strip().splitlines():
        if "coverage" in line.lower() or line.startswith("TOTAL"):
            detail = line.strip()
    if not detail:
        detail = out.strip().splitlines()[-1] if out.strip() else ""
    return GateResult("coverage >= 95%", code == 0, detail)


def _gate_drift() -> GateResult:
    code, out = _run([sys.executable, "scripts/check_drift.py"])
    # The drift script prints a summary line; surface the meaningful one.
    detail = ""
    for line in out.strip().splitlines():
        if "drift" in line.lower():
            detail = line.strip()
    if not detail:
        detail = out.strip().splitlines()[-1] if out.strip() else ""
    return GateResult("drift check", code == 0, detail)


def _gate_no_em_dashes() -> GateResult:
    """Grep tracked markdown for em-dashes."""
    # Use git to enumerate tracked .md files, then grep them. Falls back
    # to a filesystem walk if git is unavailable.
    code, out = _run(["git", "ls-files", "*.md"])
    if code != 0 or not out.strip():
        # Fallback: walk the docs dir and repo-root markdown.
        md_files = list(_REPO_ROOT.glob("*.md")) + list(
            (_REPO_ROOT / "docs").glob("*.md")
        )
    else:
        md_files = [_REPO_ROOT / line.strip() for line in out.strip().splitlines()]

    offenders: list[str] = []
    for md in md_files:
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if "\u2014" in text:
            offenders.append(str(md.relative_to(_REPO_ROOT)))
    if offenders:
        return GateResult(
            "no em-dashes", False,
            f"em-dash found in: {', '.join(offenders)}",
        )
    return GateResult("no em-dashes", True, "no em-dashes in tracked markdown")


_MANUAL_REMINDERS = [
    "A History entry for this version is written in _version.py.",
    "Migration document written if the schema major version bumped.",
    "Customization guide updated if TriageAgentConfig signature changed.",
    "Maintenance workflow doc updated if any procedure changed.",
    "Editable install verified: pip install -e . and vrt --version.",
    "git tag v{version} created and pushed.",
    "GitHub release published with release notes.",
    "Downstream consumers notified for breaking changes.",
]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run the release-readiness checklist (go/no-go report).",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip the slow coverage gate (still runs the plain suite).",
    )
    args = parser.parse_args(argv)

    try:
        from _version import FRAMEWORK_VERSION
    except ImportError as exc:
        print(f"ERROR: could not import _version: {exc}", file=sys.stderr)
        return 2

    print(f"Release readiness for FRAMEWORK_VERSION {FRAMEWORK_VERSION}")
    print("=" * 60)

    gates: list[GateResult] = []
    gates.append(_gate_version_sync())
    gates.append(_gate_changelog_current())
    gates.append(_gate_tests())
    if not args.fast:
        gates.append(_gate_coverage())
    gates.append(_gate_drift())
    gates.append(_gate_no_em_dashes())

    print("\nAutomated gates:")
    all_passed = True
    for gate in gates:
        mark = "PASS" if gate.passed else "FAIL"
        if not gate.passed:
            all_passed = False
        print(f"  [{mark}] {gate.name}: {gate.detail}")

    print("\nManual steps to confirm by hand:")
    for reminder in _MANUAL_REMINDERS:
        print(f"  [ ] {reminder.replace('{version}', FRAMEWORK_VERSION)}")

    print("\n" + "=" * 60)
    if all_passed:
        print("GO: all automated gates passed. Confirm the manual steps "
              "above, then cut the release.")
        return 0
    print("NO-GO: one or more automated gates failed. Fix them before "
          "cutting the release.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
