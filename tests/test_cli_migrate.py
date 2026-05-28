"""Tests for the ``vrt migrate`` CLI subcommand (Phase 7 SS3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.dispatcher import main


def _record(version: str, decision_id: str = "d-001") -> dict:
    return {
        "decision_id": decision_id,
        "decision_timestamp": "2026-05-28T12:00:00Z",
        "input_submission_id": "v-x",
        "input_schema_version": "1.0.0",
        "agent_version": "vrt-1.0.0+test+abc123def456",
        "risk_tier": "tier_1_low",
        "recommended_disposition": "approve",
        "classification_rationale": "A rationale for the CLI migration test.",
        "evidence_cited": [
            {"input_field_reference": "$.x", "reasoning": "y."},
        ],
        "confidence_signal": {"score": 0.9, "interpretation": "high"},
        "output_schema_version": version,
    }


def _write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


# -- single record -------------------------------------------------------


def test_migrate_single_record_to_stdout(tmp_path, capsys) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    code = main(["migrate", str(f), "--to", "1.3.0", "--tenant-id", "acme-bank"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["output_schema_version"] == "1.3.0"
    assert out["tenant_id"] == "acme-bank"


def test_migrate_additive_hop_no_tenant_needed(tmp_path, capsys) -> None:
    f = _write(tmp_path / "r.json", _record("1.0.0"))
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["output_schema_version"] == "1.2.0"


def test_migrate_to_output_file(tmp_path, capsys) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    out_path = tmp_path / "out.json"
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "acme-bank", "--output", str(out_path),
    ])
    assert code == 0
    written = json.loads(out_path.read_text())
    assert written["tenant_id"] == "acme-bank"


# -- batch ---------------------------------------------------------------


def test_migrate_jsonl_batch_with_map(tmp_path, capsys) -> None:
    batch = tmp_path / "b.jsonl"
    batch.write_text(
        json.dumps(_record("1.2.0", "d-001")) + "\n"
        + json.dumps(_record("1.2.0", "d-002")) + "\n",
        encoding="utf-8",
    )
    tmap = _write(tmp_path / "m.json", {"d-001": "acme-bank", "d-002": "globex"})
    code = main([
        "migrate", str(batch), "--to", "1.3.0", "--tenant-map", str(tmap),
    ])
    assert code == 0
    lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    by_id = {r["decision_id"]: r["tenant_id"] for r in lines}
    assert by_id == {"d-001": "acme-bank", "d-002": "globex"}


def test_migrate_json_array_batch(tmp_path, capsys) -> None:
    f = _write(tmp_path / "arr.json", [_record("1.2.0", "d-001"), _record("1.2.0", "d-002")])
    code = main(["migrate", str(f), "--to", "1.3.0", "--tenant-id", "acme-bank"])
    assert code == 0
    lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2


# -- registry ------------------------------------------------------------


def test_migrate_with_registry_accepts_known(tmp_path, capsys) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    reg = _write(tmp_path / "reg.json", {
        "tenants": [{"tenant_id": "acme-bank", "display_name": "Acme"}],
    })
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "acme-bank", "--tenants", str(reg),
    ])
    assert code == 0


def test_migrate_with_registry_rejects_unknown(tmp_path, capsys) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    reg = _write(tmp_path / "reg.json", {
        "tenants": [{"tenant_id": "acme-bank", "display_name": "Acme"}],
    })
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "unknown-co", "--tenants", str(reg),
    ])
    assert code == 2


# -- error paths ---------------------------------------------------------


def test_migrate_missing_tenant_source_exits_1(tmp_path, capsys) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    code = main(["migrate", str(f), "--to", "1.3.0"])
    assert code == 1


def test_migrate_both_tenant_flags_exits_2(tmp_path) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    tmap = _write(tmp_path / "m.json", {"d-001": "x"})
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "x", "--tenant-map", str(tmap),
    ])
    assert code == 2


def test_migrate_unknown_target_exits_2(tmp_path) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    code = main(["migrate", str(f), "--to", "9.9.9", "--tenant-id", "x"])
    assert code == 2


def test_migrate_missing_input_exits_2(tmp_path) -> None:
    code = main([
        "migrate", str(tmp_path / "nope.json"), "--to", "1.3.0",
        "--tenant-id", "x",
    ])
    assert code == 2


def test_migrate_missing_map_file_exits_2(tmp_path) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-map", str(tmp_path / "nomap.json"),
    ])
    assert code == 2


def test_migrate_missing_registry_file_exits_2(tmp_path) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "x", "--tenants", str(tmp_path / "noreg.json"),
    ])
    assert code == 2


def test_migrate_bad_json_exits_1(tmp_path) -> None:
    f = tmp_path / "bad.json"
    f.write_text("{not valid json and not jsonl either", encoding="utf-8")
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_empty_input_exits_1(tmp_path) -> None:
    f = tmp_path / "empty.json"
    f.write_text("   \n", encoding="utf-8")
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_downward_exits_1(tmp_path) -> None:
    rec = _record("1.3.0")
    rec["tenant_id"] = "acme-bank"
    f = _write(tmp_path / "r.json", rec)
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_invalid_registry_exits_2(tmp_path) -> None:
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    reg = tmp_path / "reg.json"
    reg.write_text("{not valid json", encoding="utf-8")
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "acme-bank", "--tenants", str(reg),
    ])
    assert code == 2


def test_migrate_mapping_miss_exits_1(tmp_path) -> None:
    """A record with no map entry fails migration (exit 1)."""
    f = _write(tmp_path / "r.json", _record("1.2.0", "d-999"))
    tmap = _write(tmp_path / "m.json", {"d-001": "acme-bank"})
    code = main([
        "migrate", str(f), "--to", "1.3.0", "--tenant-map", str(tmap),
    ])
    assert code == 1


def test_migrate_malformed_map_exits_2(tmp_path) -> None:
    """A tenant-map file that is valid JSON but not an object exits 2."""
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    tmap = tmp_path / "m.json"
    tmap.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    code = main([
        "migrate", str(f), "--to", "1.3.0", "--tenant-map", str(tmap),
    ])
    assert code == 2


def test_migrate_json_array_with_non_dict_exits_1(tmp_path) -> None:
    """A JSON array containing a non-object entry is rejected (exit 1)."""
    f = tmp_path / "arr.json"
    f.write_text(json.dumps([_record("1.2.0"), "not-an-object"]), encoding="utf-8")
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_scalar_json_exits_1(tmp_path) -> None:
    """A bare JSON scalar (not object or array) is rejected (exit 1)."""
    f = tmp_path / "scalar.json"
    f.write_text("42", encoding="utf-8")
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_jsonl_with_comments_and_blanks(tmp_path, capsys) -> None:
    """JSONL parsing skips comment and blank lines."""
    f = tmp_path / "b.jsonl"
    f.write_text(
        "# a comment\n\n"
        + json.dumps(_record("1.2.0", "d-001")) + "\n"
        + "  \n",
        encoding="utf-8",
    )
    code = main(["migrate", str(f), "--to", "1.3.0", "--tenant-id", "acme-bank"])
    assert code == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 1


def test_migrate_jsonl_non_object_line_exits_1(tmp_path) -> None:
    """A JSONL line that is valid JSON but not an object is rejected."""
    f = tmp_path / "b.jsonl"
    f.write_text(
        json.dumps(_record("1.2.0")) + "\n42\n",
        encoding="utf-8",
    )
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_jsonl_all_comments_exits_1(tmp_path) -> None:
    """A JSONL file with only comments has no records (exit 1)."""
    f = tmp_path / "b.jsonl"
    f.write_text("# only\n# comments\n", encoding="utf-8")
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_jsonl_bad_line_exits_1(tmp_path) -> None:
    """A JSONL file whose second line is malformed JSON exits 1."""
    f = tmp_path / "b.jsonl"
    f.write_text(
        json.dumps(_record("1.2.0")) + "\n{broken\n",
        encoding="utf-8",
    )
    code = main(["migrate", str(f), "--to", "1.2.0"])
    assert code == 1


def test_migrate_batch_record_failure_reports_id(tmp_path, capsys) -> None:
    """A failing record in a batch is reported with its decision_id (exit 1)."""
    batch = tmp_path / "b.jsonl"
    good = _record("1.2.0", "d-001")
    bad = _record("1.2.0", "d-002")
    bad["risk_tier"] = "not_a_real_tier"  # fails target validation
    batch.write_text(
        json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8",
    )
    code = main(["migrate", str(batch), "--to", "1.2.0"])
    assert code == 1
    err = capsys.readouterr().err
    assert "d-002" in err


def test_migrate_output_unwritable_exits_2(tmp_path) -> None:
    """An unwritable --output path exits 2."""
    f = _write(tmp_path / "r.json", _record("1.2.0"))
    # A path whose parent does not exist is unwritable.
    bad_out = tmp_path / "nonexistent-dir" / "out.json"
    code = main([
        "migrate", str(f), "--to", "1.3.0",
        "--tenant-id", "acme-bank", "--output", str(bad_out),
    ])
    assert code == 2
