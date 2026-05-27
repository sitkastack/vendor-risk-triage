"""Tests for Phase 5 sub-system 4: reporting/audit_pack and batch_index.

Coverage targets the pure-Python rendering helpers and the public
API. The HTML output is validated for:

- Well-formedness (parses as HTML)
- All record fields appear in output
- Optional fields are gracefully omitted when absent
- Disposition banner uses the correct accent
- Calibration SVG embeds correctly when supplied
- Attribution footer behavior (default, override, suppress)
- Print stylesheet present
- Accessibility markers (semantic HTML, aria-labels)

Tests use the existing demo scenarios as fixtures: real TriageRecord
+ submission pairs that exercise every code path. Where the demo
scenarios don't cover a path (e.g., revoked records, missing
optional fields), tests construct minimal records inline.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.output_models import TriageRecord
from reporting import (
    ATTRIBUTION_FOOTER_TEMPLATE,
    AUDIT_PACK_CSS,
    BATCH_INDEX_CSS,
    FRAMEWORK_VERSION,
    render_audit_pack,
    render_batch_index,
    save_audit_pack,
    save_batch_index,
)


REPO_ROOT = Path(__file__).parent.parent
SUBMISSIONS_DIR = REPO_ROOT / "examples" / "submissions"
EXPECTED_DIR = REPO_ROOT / "examples" / "expected-records"


# -- fixtures ----------------------------------------------------------


def _load_record_and_submission(scenario_index: int) -> tuple[TriageRecord, dict]:
    """Load scenario N from the demo examples, parsing timestamps to aware datetimes."""
    sub_glob = list(SUBMISSIONS_DIR.glob(f"0{scenario_index}-*.json"))
    rec_glob = list(EXPECTED_DIR.glob(f"0{scenario_index}-*.expected.json"))
    submission = json.loads(sub_glob[0].read_text())
    record_dict = json.loads(rec_glob[0].read_text())
    record_dict["decision_timestamp"] = datetime.fromisoformat(
        record_dict["decision_timestamp"].replace("Z", "+00:00")
    )
    return TriageRecord(**record_dict), submission


@pytest.fixture(scope="module")
def tier1_record() -> tuple[TriageRecord, dict]:
    return _load_record_and_submission(1)


@pytest.fixture(scope="module")
def tier2_record() -> tuple[TriageRecord, dict]:
    return _load_record_and_submission(2)


@pytest.fixture(scope="module")
def tier3_record() -> tuple[TriageRecord, dict]:
    return _load_record_and_submission(3)


@pytest.fixture(scope="module")
def tier4_record() -> tuple[TriageRecord, dict]:
    return _load_record_and_submission(4)


@pytest.fixture(scope="module")
def edge_record() -> tuple[TriageRecord, dict]:
    return _load_record_and_submission(5)


@pytest.fixture(scope="module")
def all_records() -> list[tuple[TriageRecord, dict]]:
    return [_load_record_and_submission(i) for i in range(1, 6)]


# -- audit_pack: well-formedness ---------------------------------------


def test_audit_pack_returns_complete_html_document(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert html_text.startswith("<!DOCTYPE html>")
    assert html_text.endswith("</html>")
    assert "<html lang=" in html_text
    assert "<head>" in html_text and "</head>" in html_text
    assert "<body>" in html_text and "</body>" in html_text


def test_audit_pack_includes_inline_css(tier3_record) -> None:
    """The CSS is inline; no external stylesheet references."""
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert "<style>" in html_text
    assert "</style>" in html_text
    # No external link tags pointing at CSS
    assert 'rel="stylesheet"' not in html_text
    assert AUDIT_PACK_CSS[:50] in html_text  # CSS body actually embedded


def test_audit_pack_has_print_media_query(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert "@media print" in html_text


# -- audit_pack: content presence --------------------------------------


def test_audit_pack_contains_vendor_name(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert submission["vendor_name"] in html_text


def test_audit_pack_contains_classification_rationale(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    # Full rationale text appears, with HTML escaping applied
    import html as html_module
    assert html_module.escape(record.classification_rationale) in html_text


def test_audit_pack_contains_all_evidence_citations(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    for ev in record.evidence_cited:
        assert ev.input_field_reference in html_text


def test_audit_pack_contains_decision_id(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert record.decision_id in html_text


def test_audit_pack_contains_agent_version(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert record.agent_version in html_text


def test_audit_pack_contains_confidence_score(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert f"{record.confidence_signal.score:.2f}" in html_text


# -- audit_pack: optional fields ---------------------------------------


def test_audit_pack_omits_mitigations_when_absent(tier1_record) -> None:
    """Tier 1 approve has no required_mitigations."""
    record, submission = tier1_record
    html_text = render_audit_pack(record, submission)
    assert record.required_mitigations is None
    assert "Required mitigations" not in html_text


def test_audit_pack_renders_mitigations_when_present(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert record.required_mitigations is not None
    assert "Required mitigations" in html_text
    for m in record.required_mitigations:
        # Each mitigation should appear (HTML-escaped)
        import html as html_module
        assert html_module.escape(m) in html_text


def test_audit_pack_omits_accountable_owner_when_absent(tier1_record) -> None:
    record, submission = tier1_record
    html_text = render_audit_pack(record, submission)
    assert record.accountable_owner is None
    assert "Accountable owner" not in html_text


def test_audit_pack_renders_accountable_owner_when_present(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert record.accountable_owner is not None
    assert "Accountable owner" in html_text
    assert record.accountable_owner in html_text


def test_audit_pack_renders_regulatory_framework_tags(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert "Regulatory frameworks engaged" in html_text


# -- audit_pack: disposition banner -----------------------------------


def test_audit_pack_banner_class_matches_approve(tier1_record) -> None:
    record, submission = tier1_record
    html_text = render_audit_pack(record, submission)
    assert "banner-approve" in html_text


def test_audit_pack_banner_class_matches_conditional(tier2_record) -> None:
    record, submission = tier2_record
    html_text = render_audit_pack(record, submission)
    assert "banner-conditional" in html_text


def test_audit_pack_banner_class_matches_escalate(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert "banner-escalate" in html_text


def test_audit_pack_banner_class_matches_reject(tier4_record) -> None:
    record, submission = tier4_record
    html_text = render_audit_pack(record, submission)
    assert "banner-reject" in html_text


# -- audit_pack: calibration embed -------------------------------------


def test_audit_pack_omits_calibration_section_when_no_svg(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    # The CSS defines .calibration-block class definitions; check for the actual
    # div with that class being rendered into the body.
    assert '<div class="calibration-block"' not in html_text


def test_audit_pack_embeds_calibration_svg_when_supplied(tier3_record) -> None:
    record, submission = tier3_record
    fake_svg = '<svg width="100" height="100"><rect width="50" height="50"/></svg>'
    html_text = render_audit_pack(
        record, submission,
        calibration_svg=fake_svg,
    )
    assert "calibration-block" in html_text
    assert fake_svg in html_text


def test_audit_pack_renders_calibration_caption_when_supplied(tier3_record) -> None:
    record, submission = tier3_record
    fake_svg = '<svg width="100" height="100"/>'
    html_text = render_audit_pack(
        record, submission,
        calibration_svg=fake_svg,
        calibration_caption="Calibration on baseline n=247",
    )
    assert "Calibration on baseline n=247" in html_text


def test_audit_pack_ignores_caption_without_svg(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(
        record, submission,
        calibration_caption="This should not appear",
    )
    assert "This should not appear" not in html_text


# -- audit_pack: attribution footer ------------------------------------


def test_audit_pack_default_attribution_present(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(record, submission)
    assert "Generated by sitkastack" in html_text
    assert FRAMEWORK_VERSION in html_text


def test_audit_pack_custom_attribution_replaces_default(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(
        record, submission,
        attribution_footer="Internal use only. Confidential.",
    )
    assert "Internal use only. Confidential." in html_text
    assert "Generated by sitkastack" not in html_text


def test_audit_pack_empty_attribution_suppresses_footer(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_audit_pack(
        record, submission,
        attribution_footer="",
    )
    assert "Generated by sitkastack" not in html_text
    assert '<footer class="footer">' not in html_text


# -- audit_pack: edge cases -------------------------------------------


def test_audit_pack_handles_missing_vendor_name(tier3_record) -> None:
    """A submission without vendor_name falls back to a placeholder."""
    record, submission = tier3_record
    no_name = dict(submission)
    no_name.pop("vendor_name")
    html_text = render_audit_pack(record, no_name)
    assert "Unnamed Vendor" in html_text


def test_audit_pack_handles_naive_datetime_defensively(tier3_record) -> None:
    """A record with a naive datetime (defensive code path) still renders.

    Pydantic validators prevent this in normal use, but the renderer
    has a defensive UTC-tag fallback for any downstream code paths
    that bypass validation. We test by calling the renderer's helper
    directly rather than constructing an invalid TriageRecord.
    """
    from reporting.audit_pack import _format_iso_datetime
    naive_dt = datetime(2026, 5, 22, 9, 33, 0)  # no tzinfo
    formatted = _format_iso_datetime(naive_dt)
    # Defensive UTC fallback applied
    assert "2026-05-22 09:33:00" in formatted


def test_batch_index_format_iso_date_handles_naive_datetime() -> None:
    """Defensive UTC fallback in the batch_index date formatter."""
    from reporting.batch_index import _format_iso_date
    naive_dt = datetime(2026, 5, 22, 9, 33, 0)
    assert _format_iso_date(naive_dt) == "2026-05-22"


def test_audit_pack_renders_all_five_demo_scenarios(all_records) -> None:
    """Sanity: every demo scenario renders without error."""
    for record, submission in all_records:
        html_text = render_audit_pack(record, submission)
        assert html_text.startswith("<!DOCTYPE html>")
        assert html_text.endswith("</html>")
        assert submission["vendor_name"] in html_text


# -- save_audit_pack ---------------------------------------------------


def test_save_audit_pack_writes_file(tier3_record, tmp_path: Path) -> None:
    record, submission = tier3_record
    target = tmp_path / "test_audit.html"
    returned = save_audit_pack(record, submission, target)
    assert returned == target
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    assert submission["vendor_name"] in content


def test_save_audit_pack_accepts_string_path(tier3_record, tmp_path: Path) -> None:
    record, submission = tier3_record
    target = tmp_path / "as_string.html"
    returned = save_audit_pack(record, submission, str(target))
    assert returned == target
    assert returned.exists()


def test_save_audit_pack_forwards_kwargs(tier3_record, tmp_path: Path) -> None:
    record, submission = tier3_record
    target = tmp_path / "with_attribution.html"
    save_audit_pack(
        record, submission, target,
        attribution_footer="Custom footer text",
    )
    content = target.read_text()
    assert "Custom footer text" in content


# -- batch_index: well-formedness --------------------------------------


def test_batch_index_returns_complete_html_document(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    assert html_text.startswith("<!DOCTYPE html>")
    assert html_text.endswith("</html>")


def test_batch_index_includes_inline_css(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    assert "<style>" in html_text
    assert BATCH_INDEX_CSS[:50] in html_text


# -- batch_index: content ----------------------------------------------


def test_batch_index_shows_total_count(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    # "5 decisions" appears in the subtitle
    assert "5 decisions" in html_text


def test_batch_index_singular_count_for_one_record(tier3_record) -> None:
    record, submission = tier3_record
    html_text = render_batch_index(
        [record],
        {submission["vendor_id"]: submission},
    )
    assert "1 decision " in html_text


def test_batch_index_shows_all_vendor_names(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    for _, sub in all_records:
        assert sub["vendor_name"] in html_text


def test_batch_index_shows_tier_breakdown(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    # Stat cards for each tier
    assert "Tier 1" in html_text
    assert "Tier 2" in html_text
    assert "Tier 3" in html_text
    assert "Tier 4" in html_text


def test_batch_index_with_record_links(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    links = {r.decision_id: f"records/{r.decision_id}.html" for r in records}
    html_text = render_batch_index(records, submissions, record_links=links)
    # Every link target appears
    for url in links.values():
        assert url in html_text
    # And the link CSS class is applied
    assert "record-link" in html_text


def test_batch_index_without_record_links(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    # The CSS defines a .record-link class; check that no actual anchor with
    # that class is rendered.
    assert 'class="record-link"' not in html_text


def test_batch_index_unknown_submission_falls_back(tier3_record) -> None:
    """A record whose submission isn't in the dict renders with placeholder."""
    record, _ = tier3_record
    # Empty submissions dict
    html_text = render_batch_index([record], submissions={})
    assert "Unnamed Vendor" in html_text


def test_batch_index_empty_records(tmp_path: Path) -> None:
    """An empty record list renders an empty-state page."""
    html_text = render_batch_index([], submissions={})
    assert html_text.startswith("<!DOCTYPE html>")
    assert "No decisions" in html_text


def test_batch_index_custom_title(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(
        records, submissions,
        title="Q2 Vendor Review",
    )
    assert "Q2 Vendor Review" in html_text


def test_batch_index_records_sorted_by_decision_timestamp_desc(all_records) -> None:
    """Records appear in reverse chronological order."""
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    # Find each decision_id's position in the HTML; latest should come first
    sorted_records = sorted(records, key=lambda r: r.decision_timestamp, reverse=True)
    positions = [html_text.index(r.decision_id) for r in sorted_records
                 if r.decision_id in html_text]
    if len(positions) >= 2:
        # Note: decision_id might not be in HTML if vendor name is the link
        # text. We check via record_links instead.
        links = {r.decision_id: f"records/{r.decision_id}.html" for r in records}
        html_with_links = render_batch_index(
            records, submissions, record_links=links,
        )
        positions = [html_with_links.index(f"records/{r.decision_id}.html")
                     for r in sorted_records]
        assert positions == sorted(positions), (
            "Records should be sorted by decision_timestamp descending"
        )


def test_batch_index_includes_attribution_by_default(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    assert "Generated by sitkastack" in html_text


def test_batch_index_attribution_override(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(
        records, submissions,
        attribution_footer="Quarterly compliance review, internal use",
    )
    assert "Quarterly compliance review, internal use" in html_text
    assert "Generated by sitkastack" not in html_text


def test_batch_index_attribution_suppressed_when_empty_string(all_records) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(
        records, submissions,
        attribution_footer="",
    )
    assert "Generated by sitkastack" not in html_text
    assert '<footer class="footer">' not in html_text


# -- save_batch_index --------------------------------------------------


def test_save_batch_index_writes_file(all_records, tmp_path: Path) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    target = tmp_path / "index.html"
    returned = save_batch_index(records, submissions, target)
    assert returned == target
    assert target.exists()
    content = target.read_text()
    assert content.startswith("<!DOCTYPE html>")


def test_save_batch_index_accepts_string_path(
    all_records, tmp_path: Path,
) -> None:
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    target = tmp_path / "as_string.html"
    returned = save_batch_index(records, submissions, str(target))
    assert returned == target
    assert target.exists()


# -- date range subtitle --------------------------------------------------


def test_batch_index_date_range_uses_on_for_same_day(tier3_record) -> None:
    """Single date -> 'on YYYY-MM-DD' phrasing."""
    record, submission = tier3_record
    html_text = render_batch_index(
        [record],
        {submission["vendor_id"]: submission},
    )
    assert "on 2026-05-22" in html_text


def test_batch_index_date_range_uses_from_to_for_multiple_days(
    all_records,
) -> None:
    """Multiple dates -> 'from earliest to latest' phrasing."""
    records = [r for r, _ in all_records]
    submissions = {s["vendor_id"]: s for _, s in all_records}
    html_text = render_batch_index(records, submissions)
    assert "from 2026-05-20" in html_text
    assert "to 2026-05-24" in html_text


# -- styles module ----------------------------------------------------


def test_audit_pack_css_includes_print_media(monkeypatch) -> None:
    """Sanity: the styles module ships a print stylesheet."""
    assert "@media print" in AUDIT_PACK_CSS


def test_batch_index_css_extends_audit_pack_css() -> None:
    """Batch index CSS includes everything in audit pack CSS plus more."""
    assert AUDIT_PACK_CSS in BATCH_INDEX_CSS
    assert len(BATCH_INDEX_CSS) > len(AUDIT_PACK_CSS)


def test_attribution_footer_template_formats() -> None:
    """The footer template accepts framework_version and produces a string."""
    out = ATTRIBUTION_FOOTER_TEMPLATE.format(framework_version="v0.6.0")
    assert "sitkastack" in out
    assert "v0.6.0" in out


# -- coverage for formatting helpers ----------------------------------


def test_format_enum_value_for_uppercase_tag() -> None:
    """OSFI_E_23 style tags preserve casing and replace underscores."""
    from reporting.audit_pack import _format_enum_value
    assert _format_enum_value("OSFI_E_23") == "OSFI E 23"
    assert _format_enum_value("EU_AI_Act_Annex_III") == "EU AI Act Annex III"


def test_format_enum_value_for_lowercase_snake() -> None:
    """operational_decisions -> Operational decisions."""
    from reporting.audit_pack import _format_enum_value
    assert _format_enum_value("operational_decisions") == "Operational decisions"


def test_format_enum_value_for_empty_string() -> None:
    from reporting.audit_pack import _format_enum_value
    assert _format_enum_value("") == ""


def test_audit_pack_renders_supersedes_when_present(tier3_record) -> None:
    """Supersedes field appears in audit trail when set."""
    record, submission = tier3_record
    updated = record.model_copy(update={"supersedes": "prior-decision-abc"})
    html_text = render_audit_pack(updated, submission)
    assert "Supersedes record" in html_text
    assert "prior-decision-abc" in html_text


def test_audit_pack_renders_revocation_when_present(tier3_record) -> None:
    """Revoked records show revocation timestamp and reason."""
    record, submission = tier3_record
    revoked_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    updated = record.model_copy(update={
        "revoked_at": revoked_at,
        "revocation_reason": "Vendor failed re-attestation.",
    })
    html_text = render_audit_pack(updated, submission)
    assert "Revoked at" in html_text
    assert "Revocation reason" in html_text
    assert "Vendor failed re-attestation." in html_text


def test_audit_pack_renders_extension_schema_when_present(tier3_record) -> None:
    """Extension schema version appears in audit trail when set."""
    record, submission = tier3_record
    updated = record.model_copy(update={
        "extension_schema_version": "1.2.0",
    })
    html_text = render_audit_pack(updated, submission)
    assert "Extension schema" in html_text
    assert "1.2.0" in html_text


def test_audit_pack_omits_framework_tags_when_absent(tier3_record) -> None:
    """Records without regulatory_framework_tags omit the frameworks section."""
    record, submission = tier3_record
    updated = record.model_copy(update={"regulatory_framework_tags": None})
    html_text = render_audit_pack(updated, submission)
    assert "Regulatory frameworks engaged" not in html_text


def test_audit_pack_meta_strip_omits_review_when_unset(tier3_record) -> None:
    """The review-interval row is conditional on review_interval_days."""
    record, submission = tier3_record
    updated = record.model_copy(update={"review_interval_days": None})
    html_text = render_audit_pack(updated, submission)
    assert "Next review" not in html_text
