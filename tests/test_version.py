"""Tests for FRAMEWORK_VERSION single source of truth.

These tests verify that:

1. The canonical FRAMEWORK_VERSION constant lives in ``_version`` and
   has a semver-shaped value.
2. ``agent.agent`` and ``reporting.audit_pack`` both import the same
   object (not a copy of the string).
3. ``pyproject.toml`` declares the same version as
   ``_version.FRAMEWORK_VERSION``.

The CI script ``scripts/check_version_sync.py`` enforces (3) at
build time; this test catches the same failure at the unit-test
layer so a maintainer sees it before push.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def test_canonical_framework_version_is_semver() -> None:
    """_version.FRAMEWORK_VERSION matches MAJOR.MINOR.PATCH."""
    from _version import FRAMEWORK_VERSION
    assert re.match(r"^\d+\.\d+\.\d+$", FRAMEWORK_VERSION), (
        f"FRAMEWORK_VERSION {FRAMEWORK_VERSION!r} is not semver-shaped"
    )


def test_agent_imports_canonical_framework_version() -> None:
    """agent.agent.FRAMEWORK_VERSION is the same object as _version's."""
    from _version import FRAMEWORK_VERSION as canonical
    from agent.agent import FRAMEWORK_VERSION as agent_constant
    assert agent_constant is canonical, (
        "agent.agent.FRAMEWORK_VERSION should be the same object as "
        "_version.FRAMEWORK_VERSION (imported, not redefined)."
    )


def test_reporting_imports_canonical_framework_version() -> None:
    """reporting.audit_pack.FRAMEWORK_VERSION is the same object."""
    from _version import FRAMEWORK_VERSION as canonical
    from reporting.audit_pack import FRAMEWORK_VERSION as reporting_constant
    assert reporting_constant is canonical, (
        "reporting.audit_pack.FRAMEWORK_VERSION should be the same "
        "object as _version.FRAMEWORK_VERSION (imported, not "
        "redefined)."
    )


def test_pyproject_toml_version_matches_framework_version() -> None:
    """pyproject.toml's [project] version line matches FRAMEWORK_VERSION.

    This is the same check enforced by scripts/check_version_sync.py;
    here it runs as a unit test so a maintainer catches the drift
    locally before push.
    """
    from _version import FRAMEWORK_VERSION
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    match = re.search(
        r'^\s*version\s*=\s*[\'\"]([^\'\"]+)[\'\"]',
        text,
        re.MULTILINE,
    )
    assert match is not None, (
        "Could not find version = \"...\" line in pyproject.toml"
    )
    pyproject_version = match.group(1)
    assert pyproject_version == FRAMEWORK_VERSION, (
        f"pyproject.toml version {pyproject_version!r} does not match "
        f"FRAMEWORK_VERSION {FRAMEWORK_VERSION!r}. Sync them and "
        f"commit; see docs/maintenance-workflow.md section 1."
    )


def test_reporting_init_exports_framework_version() -> None:
    """reporting.__init__ re-exports FRAMEWORK_VERSION."""
    from _version import FRAMEWORK_VERSION as canonical
    from reporting import FRAMEWORK_VERSION as reporting_init
    assert reporting_init is canonical
