"""Render a TriageRecord as a self-contained HTML audit pack.

The framework's TriageRecord is JSON: machine-readable, audit-valid,
but unreadable as a board document. ``render_audit_pack`` turns a
record (plus its source submission and optional calibration data)
into an HTML artifact that a risk committee, external auditor, or
vendor management ops person can open in any browser and read as a
memo.

Design principles, in order of priority:

1. **Audience clarity**. The first thing a reader sees is the
   classification and recommended disposition; the rationale and
   evidence follow; the audit-trail metadata sits at the bottom.
   Readers skim from top to bottom; the structure matches that flow.

2. **Self-contained output**. The HTML has no external dependencies:
   inline CSS, system fonts, no JavaScript, no external images. A
   reviewer who archives the file or emails it gets the same render
   anywhere.

3. **White-label-friendly**. The framework's only branding is a
   small attribution footer naming the framework version. The
   ``attribution_footer`` parameter lets a deploying organisation
   override that text (typically replacing it with their own legal
   footer). No logo, no colours that signal a vendor brand.

4. **Print-clean**. The print stylesheet removes coloured
   backgrounds (ink conservation), preserves heading hierarchy,
   and avoids page-break artifacts. A browser's print-to-PDF on the
   rendered HTML produces a usable PDF without further tooling.

5. **Accessibility**. Semantic HTML structure (h1/h2/h3, dl/dt/dd
   for metadata), focus states preserved, contrast meets WCAG AA
   on body text and AAA on headings.

Deferred:

- ``[deferred-phase-6]`` Native PDF generation via WeasyPrint. The
  HTML output already prints cleanly; native PDF is a quality-of-
  life improvement, not a correctness one.
- ``[deferred-phase-6]`` Configurable colour theme (currently a
  single restrained palette; deploying organisations white-label
  via the attribution footer plus the option to wrap the HTML in
  their own outer styling).
- ``[deferred-phase-7]`` Regulator-specific filing format adapters
  (e.g., OSFI's SUP-OFI submission template, EU AI Act registration
  shape). The audit pack is intentionally regulator-neutral; filing
  adapters are a deployment concern.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from agent.output_models import TriageRecord
from reporting.styles import AUDIT_PACK_CSS, ATTRIBUTION_FOOTER_TEMPLATE

# FRAMEWORK_VERSION lives in the top-level ``_version`` module. Importing
# from there (rather than from ``agent.agent``) keeps reporting's
# dependency surface limited to ``agent.output_models``: the layering
# concern is avoided because ``_version`` has no other dependencies and
# is shared with ``pyproject.toml`` via the CI sync check.
from _version import FRAMEWORK_VERSION


__all__ = [
    "render_audit_pack",
    "save_audit_pack",
    "FRAMEWORK_VERSION",
]


# Disposition copy used in the banner.
_DISPOSITION_LABEL: dict[str, str] = {
    "approve": "Approve",
    "conditional_approve": "Conditional approval",
    "escalate_senior_review": "Escalate to senior review",
    "reject": "Reject",
}

_DISPOSITION_SUMMARY: dict[str, str] = {
    "approve": (
        "The vendor meets the deploying organisation's baseline "
        "expectations for this risk tier. No further conditions are "
        "required prior to contract execution."
    ),
    "conditional_approve": (
        "The vendor may proceed subject to the conditions listed "
        "below. The deploying organisation must verify each "
        "condition is satisfied before relying on the approval in "
        "production."
    ),
    "escalate_senior_review": (
        "Material risk warrants explicit decisioning by an accountable "
        "owner. The classification and rationale below summarise the "
        "framework's view; the named owner makes the final call."
    ),
    "reject": (
        "The submission as constructed does not meet the deploying "
        "organisation's expectations for this risk tier. The "
        "rationale below details the specific gaps. Rejection does "
        "not foreclose future engagement; resubmission addressing "
        "the gaps triggers a new triage."
    ),
}

# CSS class suffix per disposition for the banner accent.
_DISPOSITION_BANNER_CLASS: dict[str, str] = {
    "approve": "banner-approve",
    "conditional_approve": "banner-conditional",
    "escalate_senior_review": "banner-escalate",
    "reject": "banner-reject",
}

# Human-friendly tier labels.
_TIER_LABEL: dict[str, str] = {
    "tier_1_low": "Tier 1 (low)",
    "tier_2_moderate": "Tier 2 (moderate)",
    "tier_3_elevated": "Tier 3 (elevated)",
    "tier_4_high": "Tier 4 (high)",
}


def render_audit_pack(
    record: TriageRecord,
    submission: dict[str, Any],
    calibration_svg: Optional[str] = None,
    calibration_caption: Optional[str] = None,
    attribution_footer: Optional[str] = None,
) -> str:
    """Render a single TriageRecord as a self-contained HTML audit pack.

    Args:
        record: The TriageRecord to render. All fields are accessed
            through the model; no schema-shaped dicts.
        submission: The original submission dict the record was
            produced from. Used to surface vendor name, jurisdiction,
            and other context the record references but does not
            itself store.
        calibration_svg: Optional SVG string (typically produced by
            ``eval.calibration.render_reliability_diagram``). When
            supplied, the SVG is embedded inline under a Calibration
            section. When None, the section is omitted.
        calibration_caption: Optional human-readable caption for the
            calibration section (e.g., "Calibration measured against
            the framework's baseline dataset, n=247"). Ignored when
            calibration_svg is None.
        attribution_footer: Optional override for the framework
            attribution footer. Pass a deploying-organisation-
            specific legal footer to white-label the output. Pass
            an empty string to suppress the footer entirely.

    Returns:
        A complete HTML document as a string. The string starts with
        ``<!DOCTYPE html>`` and ends with ``</html>``. Ready to
        write to disk, embed in email, or open in a browser.
    """
    vendor_name = submission.get("vendor_name", "Unnamed Vendor")
    vendor_id = submission.get("vendor_id", record.input_submission_id)
    jurisdiction = submission.get("jurisdiction", "")
    classification = submission.get("vendor_classification", "")
    ai_usage_level = submission.get("ai_usage_level", "")

    disposition_value = (
        record.recommended_disposition.value
        if hasattr(record.recommended_disposition, "value")
        else str(record.recommended_disposition)
    )
    tier_value = (
        record.risk_tier.value
        if hasattr(record.risk_tier, "value")
        else str(record.risk_tier)
    )

    title_text = f"Vendor Risk Triage: {vendor_name}"

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    parts.append(
        f"<title>{html.escape(title_text)}</title>"
    )
    parts.append(f"<style>{AUDIT_PACK_CSS}</style>")
    parts.append("</head>")
    parts.append('<body>')
    parts.append('<main class="page">')

    # 1. Banner: disposition + headline summary.
    parts.append(_render_banner(
        vendor_name=vendor_name,
        tier_value=tier_value,
        disposition_value=disposition_value,
    ))

    # 2. Metadata strip.
    parts.append(_render_meta_strip(
        record=record,
        vendor_id=vendor_id,
        jurisdiction=jurisdiction,
        classification=classification,
        ai_usage_level=ai_usage_level,
    ))

    # 3. Classification rationale (prose).
    parts.append("<h2>Classification rationale</h2>")
    parts.append(
        f'<p>{html.escape(record.classification_rationale)}</p>'
    )

    # 4. Evidence cited (table).
    parts.append(_render_evidence_table(record))

    # 5. Required mitigations (if any).
    if record.required_mitigations:
        parts.append(_render_mitigations(record))

    # 6. Accountable owner (if any).
    if record.accountable_owner:
        parts.append("<h2>Accountable owner</h2>")
        parts.append(
            f'<p>{html.escape(record.accountable_owner)}</p>'
        )

    # 7. Confidence and (optional) calibration.
    parts.append(_render_confidence_section(
        record=record,
        calibration_svg=calibration_svg,
        calibration_caption=calibration_caption,
    ))

    # 8. Regulatory framework tags + review cadence.
    parts.append(_render_governance_metadata(record))

    # 9. Audit trail (decision_id, agent_version, timestamps, schemas).
    parts.append(_render_audit_trail(record))

    # 10. Footer.
    parts.append(_render_footer(attribution_footer))

    parts.append("</main>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def save_audit_pack(
    record: TriageRecord,
    submission: dict[str, Any],
    path: Union[str, Path],
    **kwargs: Any,
) -> Path:
    """Render an audit pack and write it to ``path``.

    Convenience wrapper around ``render_audit_pack`` that handles the
    file write. Returns the final path as a ``Path`` object for chaining.

    Args:
        record, submission: Same as ``render_audit_pack``.
        path: Destination path. The parent directory must exist; the
            caller is responsible for ``mkdir`` if needed.
        **kwargs: Forwarded to ``render_audit_pack``
            (calibration_svg, attribution_footer, etc.).

    Returns:
        The path written to, as a ``Path``.
    """
    output_path = Path(path)
    html_text = render_audit_pack(record, submission, **kwargs)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


# -- private rendering helpers ------------------------------------------


def _render_banner(
    vendor_name: str,
    tier_value: str,
    disposition_value: str,
) -> str:
    """Top-of-document banner with disposition + one-paragraph summary."""
    banner_class = _DISPOSITION_BANNER_CLASS.get(
        disposition_value, "banner-conditional",
    )
    disp_label = _DISPOSITION_LABEL.get(
        disposition_value, disposition_value,
    )
    tier_label = _TIER_LABEL.get(tier_value, tier_value)
    summary = _DISPOSITION_SUMMARY.get(disposition_value, "")
    return (
        f'<section class="banner {html.escape(banner_class)}">'
        f'<p class="eyebrow">Recommendation</p>'
        f'<h1>{html.escape(disp_label)}: {html.escape(tier_label)}</h1>'
        f'<p class="summary">'
        f'Vendor: <strong>{html.escape(vendor_name)}</strong>. '
        f'{html.escape(summary)}'
        f'</p>'
        f'</section>'
    )


def _render_meta_strip(
    record: TriageRecord,
    vendor_id: str,
    jurisdiction: str,
    classification: str,
    ai_usage_level: str,
) -> str:
    """Key-value metadata strip below the banner."""
    rows: list[tuple[str, str]] = [
        ("Vendor ID", vendor_id),
        ("Jurisdiction", jurisdiction or "Not specified"),
        ("Classification", classification or "Not specified"),
        ("AI usage level", _format_enum_value(ai_usage_level)),
        ("Decision ID", record.decision_id),
        ("Decision timestamp", _format_iso_datetime(record.decision_timestamp)),
    ]
    if record.review_interval_days is not None:
        rows.append(("Next review", f"{record.review_interval_days} days"))
    items = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
        for label, value in rows
    )
    return f'<dl class="meta-strip">{items}</dl>'


def _render_evidence_table(record: TriageRecord) -> str:
    """Evidence-cited section: input field references + reasoning."""
    rows = "".join(
        f"<tr><td>{html.escape(ev.input_field_reference)}</td>"
        f"<td>{html.escape(ev.reasoning)}</td></tr>"
        for ev in record.evidence_cited
    )
    return (
        '<h2>Evidence cited</h2>'
        '<table aria-label="Evidence cited in the classification">'
        '<thead><tr><th>Input field</th><th>Reasoning</th></tr></thead>'
        f'<tbody>{rows}</tbody>'
        '</table>'
    )


def _render_mitigations(record: TriageRecord) -> str:
    """Required-mitigations section: enumerated list."""
    items = "".join(
        f"<li>{html.escape(m)}</li>"
        for m in (record.required_mitigations or [])
    )
    return (
        '<h2>Required mitigations</h2>'
        f'<ol>{items}</ol>'
    )


def _render_confidence_section(
    record: TriageRecord,
    calibration_svg: Optional[str],
    calibration_caption: Optional[str],
) -> str:
    """Confidence signal plus optional embedded reliability diagram."""
    interp_value = (
        record.confidence_signal.interpretation.value
        if hasattr(record.confidence_signal.interpretation, "value")
        else str(record.confidence_signal.interpretation)
    )
    pill_html = (
        f'<span class="pill pill-accent">'
        f'Confidence: {record.confidence_signal.score:.2f} ({html.escape(interp_value)})'
        f'</span>'
    )
    body = f'<h2>Confidence</h2><p>{pill_html}</p>'

    if calibration_svg:
        caption_html = ""
        if calibration_caption:
            caption_html = (
                f'<p style="font-size:13px;color:var(--ink-muted);'
                f'margin:8px 0 0;">{html.escape(calibration_caption)}</p>'
            )
        body += (
            '<div class="calibration-block" '
            'aria-label="Reliability diagram for the agent\'s calibration">'
            f'{calibration_svg}'
            f'{caption_html}'
            '</div>'
        )
    return body


def _render_governance_metadata(record: TriageRecord) -> str:
    """Regulatory framework tags + review cadence (if either is set)."""
    if not record.regulatory_framework_tags:
        return ""
    pills = "".join(
        f'<span class="pill">{html.escape(_format_enum_value(tag))}</span>'
        for tag in record.regulatory_framework_tags
    )
    return (
        '<h2>Regulatory frameworks engaged</h2>'
        f'<p>{pills}</p>'
    )


def _render_audit_trail(record: TriageRecord) -> str:
    """Audit-trail section: identifiers, timestamps, schemas. The provenance."""
    rows: list[tuple[str, str]] = [
        ("Decision ID", record.decision_id),
        ("Decision timestamp", _format_iso_datetime(record.decision_timestamp)),
        ("Input submission ID", record.input_submission_id),
        ("Input schema version", record.input_schema_version),
        ("Output schema version", record.output_schema_version),
        ("Agent version", record.agent_version),
    ]
    if record.extension_schema_version:
        rows.append(("Extension schema", record.extension_schema_version))
    if record.supersedes:
        rows.append(("Supersedes record", record.supersedes))
    if record.revoked_at:
        rows.append(("Revoked at", _format_iso_datetime(record.revoked_at)))
    if record.revocation_reason:
        rows.append(("Revocation reason", record.revocation_reason))

    field_rows = "".join(
        f'<div class="field-row">'
        f'<span class="field-name">{html.escape(label)}</span>'
        f'<span class="field-value">{html.escape(str(value))}</span>'
        f'</div>'
        for label, value in rows
    )
    return (
        '<section class="audit-trail">'
        '<h3>Audit trail</h3>'
        f'{field_rows}'
        '</section>'
    )


def _render_footer(attribution_footer: Optional[str]) -> str:
    """Plain-language attribution footer. White-labelable via the parameter."""
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


# -- formatting helpers --------------------------------------------------


def _format_iso_datetime(dt: datetime) -> str:
    """Render a timezone-aware datetime as RFC 3339 with second precision.

    The TriageRecord validator already enforces timezone-aware datetimes;
    this helper renders them consistently in the audit pack (UTC if the
    record was UTC-tagged, original offset otherwise).
    """
    if dt.tzinfo is None:
        # Defensive: a record built outside the validator could carry
        # a naive datetime. Fall back to UTC tagging for display rather
        # than raising at render time.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def _format_enum_value(value: str) -> str:
    """Turn an enum-style ``snake_case`` value into a readable string.

    ``operational_decisions`` -> ``Operational decisions``.
    ``OSFI_E_23`` -> ``OSFI E 23`` (already readable; preserved).
    """
    if not value:
        return ""
    # Heuristic: if it's all-caps separator-delimited (a framework tag
    # like OSFI_E_23 or EU_AI_Act_Annex_III), preserve casing and just
    # replace underscores with spaces.
    if value.isupper() or "_" in value and any(c.isupper() for c in value):
        return value.replace("_", " ")
    return value.replace("_", " ").capitalize()
