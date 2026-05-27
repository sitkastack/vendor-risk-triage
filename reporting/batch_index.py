"""Render a batch of TriageRecords as an index page.

Where ``audit_pack`` renders one record as a per-record document,
``batch_index`` renders a list of records as an overview index. The
two are complementary:

- Use ``audit_pack`` for a single decision a CRO will read in detail.
- Use ``batch_index`` for a quarterly view of decisions an ops team
  will scan, or for an external auditor's spot-check across many
  records.

The index page presents:

- A summary block: total count, tier breakdown, disposition breakdown
- A sortable table of records with links to each per-record audit pack
- The same self-contained inline-CSS HTML structure as the per-record
  output, with shared visual language

Like the per-record audit pack, the output is white-label-friendly:
the only branding is the attribution footer, which the caller can
override.

Deferred:

- ``[deferred-phase-6]`` Filterable / searchable index (would require
  JavaScript; the framework's reporting output is intentionally
  no-JS for predictability and audit traceability)
- ``[deferred-phase-6]`` Trend charts across the batch (records-per-
  week, calibration-over-time)
- ``[deferred-phase-7]`` Drill-down dashboards (a deployment concern,
  not a framework concern)
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from agent.output_models import TriageRecord
from reporting.styles import BATCH_INDEX_CSS, ATTRIBUTION_FOOTER_TEMPLATE
from reporting.audit_pack import FRAMEWORK_VERSION


__all__ = [
    "render_batch_index",
    "save_batch_index",
]


# Display labels reused across batch and per-record outputs.
_TIER_LABEL: dict[str, str] = {
    "tier_1_low": "Tier 1",
    "tier_2_moderate": "Tier 2",
    "tier_3_elevated": "Tier 3",
    "tier_4_high": "Tier 4",
}

_DISPOSITION_LABEL: dict[str, str] = {
    "approve": "Approve",
    "conditional_approve": "Conditional",
    "escalate_senior_review": "Escalate",
    "reject": "Reject",
}


def render_batch_index(
    records: list[TriageRecord],
    submissions: dict[str, dict[str, Any]],
    record_links: Optional[dict[str, str]] = None,
    title: str = "Vendor Risk Triage: Decision Index",
    attribution_footer: Optional[str] = None,
) -> str:
    """Render a list of TriageRecords as a batch index HTML page.

    Args:
        records: The list of TriageRecords to index. May be empty
            (renders a recognisable empty-state page).
        submissions: Dict mapping ``vendor_id`` to the corresponding
            input submission dict. The renderer uses this to surface
            vendor names and jurisdictions in the index table.
            Records whose ``input_submission_id`` is not in the dict
            still render (with "Unnamed Vendor"); a missing entry
            is not an error.
        record_links: Optional dict mapping ``decision_id`` to a
            relative URL or path to that record's per-record audit
            pack. When supplied, the vendor name in each row becomes
            a link. When None, no links (useful for archives that
            ship the index alone without per-record packs).
        title: Page title and h1 text.
        attribution_footer: Same semantics as ``audit_pack``:
            override the framework attribution, or pass empty string
            to suppress.

    Returns:
        A complete HTML document as a string, ready to write or send.
    """
    summary = _compute_summary(records)

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    parts.append(f"<title>{html.escape(title)}</title>")
    parts.append(f"<style>{BATCH_INDEX_CSS}</style>")
    parts.append("</head>")
    parts.append('<body>')
    parts.append('<main class="page index-page">')

    # Title.
    parts.append(f'<h1>{html.escape(title)}</h1>')

    # Subtitle: count and date range.
    parts.append(_render_subtitle(records))

    # Summary stat cards (total, tier breakdown, disposition breakdown).
    parts.append(_render_summary_stats(summary))

    # The record table.
    parts.append(_render_record_table(
        records=records,
        submissions=submissions,
        record_links=record_links or {},
    ))

    # Footer.
    parts.append(_render_footer(attribution_footer))

    parts.append("</main>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def save_batch_index(
    records: list[TriageRecord],
    submissions: dict[str, dict[str, Any]],
    path: Union[str, Path],
    **kwargs: Any,
) -> Path:
    """Render a batch index and write it to ``path``.

    Convenience wrapper around ``render_batch_index``. Returns the
    written path as a Path for chaining.

    Args:
        records, submissions: Same as ``render_batch_index``.
        path: Destination path. Parent directory must exist.
        **kwargs: Forwarded to ``render_batch_index``.

    Returns:
        The destination Path.
    """
    output_path = Path(path)
    html_text = render_batch_index(records, submissions, **kwargs)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


# -- helpers ----------------------------------------------------------


def _compute_summary(records: list[TriageRecord]) -> dict[str, Any]:
    """Compute the summary stats shown above the record table."""
    tier_counts: dict[str, int] = {}
    disposition_counts: dict[str, int] = {}
    for r in records:
        tier_value = (
            r.risk_tier.value if hasattr(r.risk_tier, "value")
            else str(r.risk_tier)
        )
        disp_value = (
            r.recommended_disposition.value
            if hasattr(r.recommended_disposition, "value")
            else str(r.recommended_disposition)
        )
        tier_counts[tier_value] = tier_counts.get(tier_value, 0) + 1
        disposition_counts[disp_value] = (
            disposition_counts.get(disp_value, 0) + 1
        )
    return {
        "total": len(records),
        "tier_counts": tier_counts,
        "disposition_counts": disposition_counts,
    }


def _render_subtitle(records: list[TriageRecord]) -> str:
    """Render the count + date-range subtitle."""
    n = len(records)
    if n == 0:
        return (
            '<p style="color:var(--ink-muted);margin:8px 0 24px;">'
            "No decisions in this batch."
            '</p>'
        )
    timestamps = [r.decision_timestamp for r in records]
    earliest = min(timestamps)
    latest = max(timestamps)
    label = "decision" if n == 1 else "decisions"
    range_text = _format_date_range(earliest, latest)
    return (
        '<p style="color:var(--ink-muted);margin:8px 0 24px;">'
        f"{n} {label} {html.escape(range_text)}."
        '</p>'
    )


def _render_summary_stats(summary: dict[str, Any]) -> str:
    """Stat cards: total, tier mix, disposition mix."""
    cards: list[str] = []
    cards.append(_stat_card("Total", str(summary["total"])))
    # Tier breakdown.
    for tier_key in ("tier_1_low", "tier_2_moderate",
                     "tier_3_elevated", "tier_4_high"):
        count = summary["tier_counts"].get(tier_key, 0)
        cards.append(_stat_card(
            _TIER_LABEL.get(tier_key, tier_key),
            str(count),
        ))
    return f'<section class="summary-stats">{"".join(cards)}</section>'


def _stat_card(label: str, value: str) -> str:
    return (
        '<div class="stat-card">'
        f'<p class="stat-label">{html.escape(label)}</p>'
        f'<p class="stat-value">{html.escape(value)}</p>'
        '</div>'
    )


def _render_record_table(
    records: list[TriageRecord],
    submissions: dict[str, dict[str, Any]],
    record_links: dict[str, str],
) -> str:
    """The main record table with tier, disposition, vendor link columns."""
    if not records:
        return ""
    sorted_records = sorted(
        records,
        key=lambda r: r.decision_timestamp,
        reverse=True,
    )
    rows: list[str] = []
    for r in sorted_records:
        sub = submissions.get(r.input_submission_id, {})
        vendor_name = sub.get("vendor_name", "Unnamed Vendor")
        jurisdiction = sub.get("jurisdiction", "")
        tier_value = (
            r.risk_tier.value if hasattr(r.risk_tier, "value")
            else str(r.risk_tier)
        )
        disp_value = (
            r.recommended_disposition.value
            if hasattr(r.recommended_disposition, "value")
            else str(r.recommended_disposition)
        )
        tier_class_n = tier_value.split("_")[1] if "_" in tier_value else "1"
        link_url = record_links.get(r.decision_id)
        if link_url:
            vendor_cell = (
                f'<a class="record-link" href="{html.escape(link_url)}">'
                f'{html.escape(vendor_name)}'
                f'</a>'
            )
        else:
            vendor_cell = html.escape(vendor_name)
        rows.append(
            "<tr>"
            f'<td>{html.escape(_format_iso_date(r.decision_timestamp))}</td>'
            f'<td>{vendor_cell}'
            f' <span style="color:var(--ink-light);font-size:12px;">'
            f'{html.escape(jurisdiction)}'
            f'</span></td>'
            f'<td class="tier-cell tier-{html.escape(tier_class_n)}">'
            f'{html.escape(_TIER_LABEL.get(tier_value, tier_value))}'
            f'</td>'
            f'<td class="disp-cell disp-{html.escape(disp_value)}">'
            f'{html.escape(_DISPOSITION_LABEL.get(disp_value, disp_value))}'
            f'</td>'
            f'<td><span class="pill pill-accent">'
            f'{r.confidence_signal.score:.2f}'
            f'</span></td>'
            "</tr>"
        )
    return (
        '<section class="record-list">'
        '<table aria-label="Triage decision index">'
        '<thead><tr>'
        '<th>Date</th>'
        '<th>Vendor</th>'
        '<th>Tier</th>'
        '<th>Disposition</th>'
        '<th>Confidence</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</section>'
    )


def _render_footer(attribution_footer: Optional[str]) -> str:
    """Plain-language attribution footer (same as audit_pack)."""
    if attribution_footer == "":
        return ""
    text = (
        attribution_footer
        if attribution_footer is not None
        else ATTRIBUTION_FOOTER_TEMPLATE.format(
            framework_version=f"v{FRAMEWORK_VERSION}",
        )
    )
    return f'<footer class="footer">{html.escape(text)}</footer>'


# -- formatting helpers ----------------------------------------------


def _format_iso_date(dt: datetime) -> str:
    """Render a datetime as ``YYYY-MM-DD`` for the table column."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _format_date_range(earliest: datetime, latest: datetime) -> str:
    """Human-friendly date range for the subtitle."""
    e_date = _format_iso_date(earliest)
    l_date = _format_iso_date(latest)
    if e_date == l_date:
        return f"on {e_date}"
    return f"from {e_date} to {l_date}"
