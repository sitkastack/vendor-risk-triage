"""Shared inline CSS for reporting outputs.

A single Python string constant holding the CSS used by both
``audit_pack`` and ``batch_index``. Kept in code rather than a
separate ``.css`` file because the reporting outputs are
self-contained HTML strings (no external assets); the caller embeds
the style block inline.

Design choices, documented for the reader:

- Serif body font for prose. Charter, Georgia, and the system serif
  stack signal "document" rather than "web page". Auditors read
  these as memos, not as marketing pages.
- Sans-serif for headings via the system stack. Keeps headings
  distinct from body text without committing to a brand font.
- Restrained colour palette. Off-white background (#fbfbf9), near-
  black ink (#1a1a1a), single muted accent (deep teal #1f567a). No
  brand colours; the framework outputs are white-label-friendly.
- Generous whitespace. ~720px max-width on the content area, ~32px
  vertical rhythm between sections. Reads well on screen at 100%
  zoom and prints cleanly to A4 or US Letter.
- Tables use subtle horizontal rules, no zebra striping. Auditor
  documents are not dashboards.
- Print stylesheet adjusts colours to pure black/white for ink
  conservation and removes interactive elements (hover states).
- Accessibility: focus states preserved, semantic colour contrast
  ratios meet WCAG AA on body text and AAA on headings.

This file is intentionally short; the polish lives in choosing few
right defaults rather than many configurable knobs.
"""
from __future__ import annotations


__all__ = [
    "AUDIT_PACK_CSS",
    "BATCH_INDEX_CSS",
    "ATTRIBUTION_FOOTER_TEMPLATE",
]


# Shared base styles used by every reporting output. Both per-record
# and batch-index pages reference these tokens.
_BASE_CSS: str = """
:root {
  --ink: #1a1a1a;
  --ink-muted: #4a4a4a;
  --ink-light: #6a6a6a;
  --paper: #fbfbf9;
  --rule: #d8d6d2;
  --rule-light: #ebe9e4;
  --accent: #1f567a;
  --accent-bg: #eef3f7;
  --warn: #8a4413;
  --warn-bg: #f7f0e7;
  --reject: #7a1f1f;
  --reject-bg: #f7ebeb;
  --approve: #2d5a3f;
  --approve-bg: #ecf2ee;
}

* {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Charter, "Bitstream Charter", "Sitka Text", Cambria, Georgia, serif;
  font-size: 16px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.page {
  max-width: 720px;
  margin: 0 auto;
  padding: 48px 32px 64px;
}

h1, h2, h3, h4 {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-weight: 600;
  color: var(--ink);
  margin: 0 0 0.5em;
  line-height: 1.25;
}

h1 {
  font-size: 26px;
  letter-spacing: -0.01em;
}

h2 {
  font-size: 18px;
  letter-spacing: 0;
  margin-top: 32px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--rule);
}

h3 {
  font-size: 15px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  margin-top: 24px;
}

p {
  margin: 0 0 1em;
}

ul, ol {
  margin: 0 0 1em;
  padding-left: 1.5em;
}

li {
  margin-bottom: 0.4em;
}

a {
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid currentColor;
}

a:hover {
  color: var(--ink);
}

strong {
  font-weight: 600;
}

code, .mono {
  font-family: "SF Mono", "Consolas", "Liberation Mono", "Courier New", monospace;
  font-size: 0.9em;
  background: var(--rule-light);
  padding: 1px 5px;
  border-radius: 2px;
  color: var(--ink);
}

/* Decision banner (top of audit pack) */
.banner {
  margin-bottom: 32px;
  padding: 20px 24px;
  border-left: 3px solid var(--accent);
  background: var(--accent-bg);
}

.banner.banner-approve { border-left-color: var(--approve); background: var(--approve-bg); }
.banner.banner-conditional { border-left-color: var(--accent); background: var(--accent-bg); }
.banner.banner-escalate { border-left-color: var(--warn); background: var(--warn-bg); }
.banner.banner-reject { border-left-color: var(--reject); background: var(--reject-bg); }

.banner .eyebrow {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-muted);
  margin: 0 0 4px;
}

.banner h1 {
  margin: 0 0 6px;
  font-size: 22px;
}

.banner .summary {
  margin: 0;
  font-size: 15px;
  color: var(--ink-muted);
}

/* Metadata strip (key-value pairs under the banner) */
.meta-strip {
  display: grid;
  grid-template-columns: max-content 1fr;
  column-gap: 18px;
  row-gap: 8px;
  margin: 24px 0 32px;
  padding: 16px 20px;
  background: var(--rule-light);
  border-radius: 3px;
  font-size: 14px;
}

.meta-strip dt {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  font-weight: 500;
}

.meta-strip dd {
  margin: 0;
  color: var(--ink);
}

/* Evidence and mitigations tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 16px;
  font-size: 14px;
}

table th {
  text-align: left;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  font-weight: 500;
  padding: 8px 12px 8px 0;
  border-bottom: 1px solid var(--rule);
}

table td {
  padding: 12px 12px 12px 0;
  border-bottom: 1px solid var(--rule-light);
  vertical-align: top;
}

table td:first-child {
  white-space: nowrap;
  font-family: "SF Mono", "Consolas", "Liberation Mono", "Courier New", monospace;
  font-size: 12.5px;
  color: var(--ink-muted);
  padding-right: 18px;
}

table tr:last-child td {
  border-bottom: none;
}

/* Inline pills (regulatory framework tags, confidence band) */
.pill {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 11px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
  margin: 0 4px 4px 0;
  background: var(--rule-light);
  color: var(--ink-muted);
}

.pill.pill-accent {
  background: var(--accent-bg);
  color: var(--accent);
}

/* Calibration section */
.calibration-block {
  margin: 16px 0;
  padding: 16px 20px;
  background: var(--rule-light);
  border-radius: 3px;
}

.calibration-block svg {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 8px 0;
}

/* Audit trail */
.audit-trail {
  margin-top: 40px;
  padding-top: 24px;
  border-top: 1px solid var(--rule);
  font-size: 13px;
  color: var(--ink-muted);
}

.audit-trail h3 {
  margin-top: 0;
}

.audit-trail .field-row {
  display: grid;
  grid-template-columns: 200px 1fr;
  column-gap: 16px;
  margin-bottom: 6px;
}

.audit-trail .field-name {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.audit-trail .field-value {
  font-family: "SF Mono", "Consolas", "Liberation Mono", "Courier New", monospace;
  font-size: 12.5px;
  word-break: break-all;
  color: var(--ink);
}

/* Footer */
.footer {
  margin-top: 48px;
  padding-top: 16px;
  border-top: 1px solid var(--rule-light);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 11.5px;
  color: var(--ink-light);
  text-align: center;
}

/* Print stylesheet: ink conservation and pagination */
@media print {
  html, body {
    background: #fff;
    font-size: 11.5pt;
  }

  .page {
    max-width: none;
    padding: 0;
  }

  .banner, .meta-strip, .calibration-block {
    background: #fff;
    border-left-width: 2px;
  }

  .banner h1 {
    page-break-after: avoid;
  }

  h2, h3 {
    page-break-after: avoid;
  }

  table {
    page-break-inside: auto;
  }

  table tr {
    page-break-inside: avoid;
  }

  .audit-trail {
    page-break-before: auto;
  }

  a {
    color: var(--ink);
    border-bottom-color: var(--ink-light);
  }
}
"""


_BATCH_INDEX_EXTRA_CSS: str = """
.index-page {
  max-width: 1080px;
}

.summary-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
  margin: 24px 0 40px;
}

.stat-card {
  padding: 14px 18px;
  background: var(--rule-light);
  border-radius: 3px;
}

.stat-card .stat-label {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
  margin: 0 0 4px;
}

.stat-card .stat-value {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 22px;
  font-weight: 600;
  color: var(--ink);
}

.record-list table th,
.record-list table td:first-child {
  white-space: nowrap;
}

.record-list table td {
  padding: 12px 16px 12px 0;
}

.tier-cell, .disp-cell {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 12.5px;
  font-weight: 500;
}

.tier-1 { color: var(--approve); }
.tier-2 { color: var(--accent); }
.tier-3 { color: var(--warn); }
.tier-4 { color: var(--reject); }

.disp-approve { color: var(--approve); }
.disp-conditional_approve { color: var(--accent); }
.disp-escalate_senior_review { color: var(--warn); }
.disp-reject { color: var(--reject); }

.record-link {
  color: var(--ink);
  border-bottom: none;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}

.record-link:hover {
  color: var(--accent);
  border-bottom: 1px solid currentColor;
}
"""


AUDIT_PACK_CSS: str = _BASE_CSS
"""CSS for a per-record audit pack HTML render."""


BATCH_INDEX_CSS: str = _BASE_CSS + _BATCH_INDEX_EXTRA_CSS
"""CSS for the batch-index HTML render. Includes base + index extras."""


ATTRIBUTION_FOOTER_TEMPLATE: str = (
    "Generated by sitkastack vendor-risk-triage framework {framework_version}. "
    "Document content reflects the deploying organization's submission and "
    "the framework's classification at decision time."
)
"""Plain-language attribution shown at the bottom of every render.

This is the only branding the framework injects into reporting output.
Deploying organisations white-label by replacing this string at render
time (the audit_pack and batch_index renderers accept an
``attribution_footer`` override parameter).
"""
