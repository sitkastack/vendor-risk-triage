# reporting

Reader-facing artifacts from framework outputs. Turns a `TriageRecord` (or a batch of them) into HTML documents a risk committee, external auditor, or vendor management ops team can actually read.

## What's here

- `audit_pack.py` - per-record HTML render of a single `TriageRecord`
- `batch_index.py` - multi-record HTML index linking to per-record packs
- `styles.py` - shared inline CSS used by both renderers

## Quick start

### Per-record audit pack

```python
from reporting import render_audit_pack

html_text = render_audit_pack(record, submission)
# Or save directly:
from reporting import save_audit_pack
save_audit_pack(record, submission, "vendor-textlens-2026-q2.html")
```

The output is a complete, self-contained HTML document ready to open in a browser, attach to email, or check into a vendor management system. No external dependencies - inline CSS, system fonts, no JavaScript.

### Batch index

```python
from reporting import render_batch_index

# records: list[TriageRecord]
# submissions: dict mapping vendor_id to submission dict
# (optional) record_links: dict mapping decision_id to a URL/path for that record's pack

html_text = render_batch_index(
    records=records,
    submissions=submissions,
    record_links={r.decision_id: f"records/{r.decision_id}.html" for r in records},
)
```

The batch index shows summary stat cards (total + per-tier counts), a record table sorted by decision timestamp descending, and (when `record_links` is supplied) clickable vendor names linking to each record's per-record audit pack.

### Optional calibration embed

When you have a calibration report (from `eval.calibration`), you can embed the reliability diagram inline in the per-record audit pack:

```python
from eval.calibration import render_reliability_diagram

svg = render_reliability_diagram(calibration_report)
html_text = render_audit_pack(
    record, submission,
    calibration_svg=svg,
    calibration_caption="Calibration measured on baseline dataset (n=247).",
)
```

When `calibration_svg` is not supplied, the calibration section is omitted entirely.

## Design choices

### Polish-as-craft, not polish-as-marketing

The framework outputs an artifact the deploying organization owns. Branding belongs in the deploying organization's wrapper (or in sitkastack.com's marketing pages), not in framework output.

What that means concretely:

- No vendor logo
- No vendor color palette in the rendered document
- Restrained type and color choices that feel "document" rather than "web page"
- A small attribution footer naming the framework version, replaceable via the `attribution_footer` parameter

If you need full white-labeling, pass `attribution_footer=""` to suppress the default footer entirely, or pass your own footer string.

### Aesthetic

- **Body font**: Charter (system serif fallback) - signals "document"
- **Heading font**: System sans-serif (-apple-system, BlinkMacSystemFont, Segoe UI)
- **Palette**: Off-white background (#fbfbf9), near-black ink (#1a1a1a), single deep teal accent (#1f567a) for conditional approval, warm amber for escalation, restrained red-burgundy for rejection, muted green for approval
- **Layout**: ~720px max content width, generous vertical rhythm, single-column for per-record output
- **Print stylesheet**: Adjusts colors for ink conservation, preserves heading hierarchy, avoids page-break artifacts. A browser's "print to PDF" produces a clean PDF without additional tooling.

### Accessibility

- Semantic HTML structure (`h1`/`h2`/`h3`, `dl`/`dt`/`dd` for metadata, `table` with `thead`/`tbody`)
- `aria-label` on data tables and the calibration block
- Focus states preserved in the print stylesheet (the document is keyboard-navigable in browser)
- Contrast ratios meet WCAG AA on body text and AAA on headings
- No JavaScript dependency - the document is fully readable with JS disabled

## White-labeling pattern

If a deploying organization wants the audit pack to appear under their brand, the recommended pattern is to keep the framework's clean output as the authoritative record and wrap it in an organization-specific outer template at publishing time:

```python
framework_html = render_audit_pack(record, submission, attribution_footer="")
branded_html = your_org_template.replace("{{audit_pack}}", framework_html)
```

This keeps audit-trail content unbranded (so the document reads as an audit record, not a marketing artifact) while satisfying internal style requirements.

## Deferred

- `[deferred-phase-6]` Native PDF generation (e.g., WeasyPrint). The HTML output prints cleanly today; native PDF is a quality-of-life improvement, not a correctness one. WeasyPrint adds ~80MB of Cairo/Pango dependencies that aren't justified at v1.
- `[deferred-phase-6]` Configurable color theme via parameter. Currently a single restrained palette; full theming is a low-priority addition since organizations white-label by wrapping rather than reconfiguring.
- `[deferred-phase-6]` Filterable / searchable batch index. Would require JavaScript; the framework's reporting output is intentionally no-JS for predictability and audit traceability.
- `[deferred-phase-6]` Trend charts on the batch index (records-per-week, calibration-over-time).
- `[deferred-phase-7]` Regulator-specific filing format adapters (e.g., OSFI's SUP-OFI submission template, EU AI Act registration shape). The audit pack is intentionally regulator-neutral.

## Testing

`tests/test_reporting.py` covers:

- HTML well-formedness (document structure, inline CSS, print media query)
- Content presence (every record field appears in output)
- Conditional rendering (optional fields omitted when absent, present when set)
- Disposition banner styling per disposition
- Calibration SVG embed (presence, caption, absence)
- Attribution footer (default, override, suppress)
- Edge cases (missing vendor name, naive datetime, empty record batch)
- Save helpers (file write, path types, kwarg forwarding)
- Batch sorting and date-range formatting
- Styles module sanity (print media query, CSS layering)

62 tests total. 100% coverage on the reporting package.
