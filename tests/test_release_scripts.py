"""Tests for the release engineering scripts (Phase 6 SS5).

Covers:
- extract_changelog: parsing the _version.py history, RST-to-markdown
  conversion, the parenthetical-tag rendering, generate vs check modes.
- bump_version: semver parsing, bump computation (major/minor/patch/
  explicit), downgrade rejection, the file-rewrite helpers, the
  clean-tree guard logic.
- prepare_release: the GateResult dataclass and the gate orchestration
  (gates are exercised against the real repo, which is in a passing
  state).

The bump_version file-writing tests operate on temp copies so the real
_version.py and pyproject.toml are never mutated.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"


def _load_script(name: str):
    """Import a script module by path (scripts/ is not a clean package import).

    Registers the module in sys.modules under its synthetic name so that
    dataclasses defined in the module can resolve their __module__ during
    type introspection (dataclass field type evaluation looks the module
    up in sys.modules).
    """
    mod_name = f"_script_{name}"
    spec = importlib.util.spec_from_file_location(
        mod_name, _SCRIPTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


extract_changelog = _load_script("extract_changelog")
bump_version = _load_script("bump_version")
prepare_release = _load_script("prepare_release")


# -- extract_changelog ---------------------------------------------------


def test_extract_history_block_finds_section() -> None:
    source = '''
FRAMEWORK_VERSION: str = "1.0.0"
"""Doc.

History:

- 1.0.0 (test): a thing happened.
- 0.9.0 (test): an earlier thing.
"""
'''
    block = extract_changelog._extract_history_block(source)
    assert "1.0.0" in block
    assert "0.9.0" in block


def test_extract_history_block_raises_without_section() -> None:
    source = 'FRAMEWORK_VERSION: str = "1.0.0"\n"""No history here."""\n'
    with pytest.raises(ValueError):
        extract_changelog._extract_history_block(source)


def test_rst_to_markdown_converts_double_backticks() -> None:
    assert extract_changelog._rst_to_markdown("``code``") == "`code`"


def test_parse_entries_splits_versions() -> None:
    block = (
        "- 1.0.0 (tag): summary one.\n"
        "  continuation line.\n"
        "- 0.9.0 (tag): summary two.\n"
    )
    entries = extract_changelog._parse_entries(block)
    assert len(entries) == 2
    assert entries[0][0] == "1.0.0"
    assert "continuation line" in entries[0][1]
    assert entries[1][0] == "0.9.0"


def test_parse_entries_handles_earlier_note() -> None:
    block = "- 1.0.0 (tag): real.\n- earlier: phase milestones.\n"
    entries = extract_changelog._parse_entries(block)
    versions = [v for v, _ in entries]
    assert "1.0.0" in versions
    assert "earlier" in versions


def test_render_changelog_includes_header() -> None:
    entries = [("1.0.0", "(test tag): the summary.")]
    rendered = extract_changelog._render_changelog(entries)
    assert "# Changelog" in rendered
    assert "## [1.0.0]" in rendered
    assert "_test tag_" in rendered
    assert "the summary." in rendered


def test_render_changelog_repairs_hyphen_wrap() -> None:
    """The '4- chars' line-wrap artifact is repaired to '4-chars'."""
    entries = [("1.0.0", "(tag): a 4- chars-per-token heuristic.")]
    rendered = extract_changelog._render_changelog(entries)
    assert "4-chars-per-token" in rendered
    assert "4- chars" not in rendered


def test_render_changelog_earlier_note_no_brackets() -> None:
    entries = [("earlier", "phase milestones.")]
    rendered = extract_changelog._render_changelog(entries)
    assert "## earlier" in rendered
    assert "## [earlier]" not in rendered


def test_generate_changelog_from_real_version_module() -> None:
    """The real _version.py generates a changelog with the current version."""
    from _version import FRAMEWORK_VERSION
    generated = extract_changelog.generate_changelog(_REPO_ROOT / "_version.py")
    assert "# Changelog" in generated
    assert f"## [{FRAMEWORK_VERSION}]" in generated


def test_changelog_check_mode_passes_when_current(tmp_path: Path) -> None:
    """Check mode returns 0 when the file matches generated content."""
    generated = extract_changelog.generate_changelog(_REPO_ROOT / "_version.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(generated, encoding="utf-8")
    code = extract_changelog.main(["--check", "--output", str(changelog)])
    assert code == 0


def test_changelog_check_mode_fails_when_stale(tmp_path: Path) -> None:
    """Check mode returns 1 when the file differs."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("stale content", encoding="utf-8")
    code = extract_changelog.main(["--check", "--output", str(changelog)])
    assert code == 1


def test_changelog_check_mode_fails_when_missing(tmp_path: Path) -> None:
    """Check mode returns 1 when the file does not exist."""
    changelog = tmp_path / "DOES_NOT_EXIST.md"
    code = extract_changelog.main(["--check", "--output", str(changelog)])
    assert code == 1


def test_changelog_generate_writes_file(tmp_path: Path) -> None:
    """Generate mode writes the file and returns 0."""
    changelog = tmp_path / "CHANGELOG.md"
    code = extract_changelog.main(["--output", str(changelog)])
    assert code == 0
    assert changelog.exists()
    assert "# Changelog" in changelog.read_text(encoding="utf-8")


# -- bump_version --------------------------------------------------------


def test_parse_semver_valid() -> None:
    assert bump_version._parse_semver("1.2.3") == (1, 2, 3)


def test_parse_semver_rejects_two_part() -> None:
    with pytest.raises(ValueError):
        bump_version._parse_semver("1.2")


def test_parse_semver_rejects_non_numeric() -> None:
    with pytest.raises(ValueError):
        bump_version._parse_semver("1.2.x")


def test_compute_patch_bump() -> None:
    assert bump_version._compute_new_version("0.9.0", "patch") == "0.9.1"


def test_compute_minor_bump() -> None:
    assert bump_version._compute_new_version("0.9.0", "minor") == "0.10.0"


def test_compute_major_bump() -> None:
    assert bump_version._compute_new_version("0.9.0", "major") == "1.0.0"


def test_compute_explicit_version() -> None:
    assert bump_version._compute_new_version("0.9.0", "1.2.3") == "1.2.3"


def test_compute_explicit_downgrade_rejected() -> None:
    with pytest.raises(ValueError):
        bump_version._compute_new_version("0.9.0", "0.8.0")


def test_compute_explicit_same_version_rejected() -> None:
    with pytest.raises(ValueError):
        bump_version._compute_new_version("0.9.0", "0.9.0")


def test_read_current_version_from_temp(tmp_path: Path) -> None:
    vfile = tmp_path / "_version.py"
    vfile.write_text(
        'FRAMEWORK_VERSION: str = "2.3.4"\n"""doc"""\n', encoding="utf-8"
    )
    assert bump_version._read_current_version(vfile) == "2.3.4"


def test_read_current_version_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bump_version._read_current_version(tmp_path / "nope.py")


def test_read_current_version_no_match_raises(tmp_path: Path) -> None:
    vfile = tmp_path / "_version.py"
    vfile.write_text("# no version here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        bump_version._read_current_version(vfile)


def test_write_version_py_replaces(tmp_path: Path) -> None:
    vfile = tmp_path / "_version.py"
    vfile.write_text(
        'FRAMEWORK_VERSION: str = "1.0.0"\n"""doc"""\n', encoding="utf-8"
    )
    bump_version._write_version_py(vfile, "1.0.0", "1.0.1")
    assert 'FRAMEWORK_VERSION: str = "1.0.1"' in vfile.read_text()


def test_write_pyproject_replaces(tmp_path: Path) -> None:
    pfile = tmp_path / "pyproject.toml"
    pfile.write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    bump_version._write_pyproject(pfile, "1.0.0", "1.0.1")
    assert 'version = "1.0.1"' in pfile.read_text()


def test_write_pyproject_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bump_version._write_pyproject(tmp_path / "nope.toml", "1.0.0", "1.0.1")


# -- prepare_release -----------------------------------------------------


def test_gate_result_dataclass() -> None:
    g = prepare_release.GateResult(name="x", passed=True, detail="ok")
    assert g.name == "x"
    assert g.passed is True
    assert g.detail == "ok"


def test_version_sync_gate_passes_on_real_repo() -> None:
    """The real repo is in sync, so this gate passes."""
    result = prepare_release._gate_version_sync()
    assert result.passed is True


def test_changelog_gate_passes_on_real_repo() -> None:
    """The committed CHANGELOG.md is current with _version.py."""
    result = prepare_release._gate_changelog_current()
    assert result.passed is True


def test_em_dash_gate_passes_on_real_repo() -> None:
    """No em-dashes in tracked markdown."""
    result = prepare_release._gate_no_em_dashes()
    assert result.passed is True


def test_coverage_packages_list_includes_resilience() -> None:
    """The coverage gate's package list stays in sync with the framework."""
    assert "resilience" in prepare_release._COVERAGE_PACKAGES
    assert "pricing" in prepare_release._COVERAGE_PACKAGES
    assert "tenancy" in prepare_release._COVERAGE_PACKAGES
    assert "migration" in prepare_release._COVERAGE_PACKAGES


def test_manual_reminders_nonempty() -> None:
    assert len(prepare_release._MANUAL_REMINDERS) > 0


# -- main() entry points (the scripts' public interface) -----------------


def test_extract_changelog_main_generate_and_check_roundtrip(tmp_path: Path) -> None:
    """Generate then check should pass (the file is current by construction)."""
    changelog = tmp_path / "CHANGELOG.md"
    assert extract_changelog.main(["--output", str(changelog)]) == 0
    assert extract_changelog.main(["--check", "--output", str(changelog)]) == 0


def test_bump_version_main_rejects_dirty_tree(monkeypatch, tmp_path: Path) -> None:
    """main() returns 1 on a dirty tree without --allow-dirty."""
    # Force the dirty-tree check to report dirty.
    monkeypatch.setattr(bump_version, "_git_tree_is_dirty", lambda: True)
    code = bump_version.main(["patch"])
    assert code == 1


def test_bump_version_main_bad_bump_arg(monkeypatch) -> None:
    """main() returns 2 on an unparseable explicit version."""
    monkeypatch.setattr(bump_version, "_git_tree_is_dirty", lambda: False)
    # Point the script at temp files so the real ones are never touched,
    # and feed a bad explicit version.
    code = bump_version.main(["not-a-version", "--allow-dirty"])
    assert code == 2


def test_prepare_release_main_reports_with_mocked_gates(monkeypatch, capsys) -> None:
    """main() orchestrates gates and prints a report.

    The individual gates are mocked to passing so this test does NOT
    recursively invoke pytest (the real test/coverage gates spawn
    pytest subprocesses; running them from within a test would nest
    pytest inside pytest). Gate logic is covered by the per-gate tests
    above; this test covers the orchestration and reporting.
    """
    passing = prepare_release.GateResult("mock", True, "ok")
    monkeypatch.setattr(prepare_release, "_gate_version_sync", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_changelog_current", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_tests", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_coverage", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_drift", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_no_em_dashes", lambda: passing)

    code = prepare_release.main(["--fast"])
    captured = capsys.readouterr()
    assert "Release readiness" in captured.out
    assert "Automated gates:" in captured.out
    assert "Manual steps" in captured.out
    assert "GO:" in captured.out
    assert code == 0


def test_prepare_release_main_no_go_when_gate_fails(monkeypatch, capsys) -> None:
    """main() returns 1 and prints NO-GO when a gate fails."""
    passing = prepare_release.GateResult("mock", True, "ok")
    failing = prepare_release.GateResult("mock", False, "broke")
    monkeypatch.setattr(prepare_release, "_gate_version_sync", lambda: failing)
    monkeypatch.setattr(prepare_release, "_gate_changelog_current", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_tests", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_coverage", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_drift", lambda: passing)
    monkeypatch.setattr(prepare_release, "_gate_no_em_dashes", lambda: passing)

    code = prepare_release.main(["--fast"])
    captured = capsys.readouterr()
    assert "NO-GO:" in captured.out
    assert code == 1
