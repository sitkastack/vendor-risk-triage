"""Reporting outputs for the vendor risk triage framework.

Turns framework outputs into reader-facing artifacts that risk
committees, auditors, and ops teams can actually use.

Current contents:

- ``audit_pack``: Per-record HTML render of a single TriageRecord
- ``batch_index``: Multi-record HTML index linking to per-record packs
- ``audit_log``: Wire-format envelope for shipping TriageRecords to
  SIEMs, archives, and event buses
- ``styles``: Shared inline CSS used by both HTML renderers
"""
from reporting.audit_log import (
    ENVELOPE_SCHEMA_VERSION,
    AuditLogEnvelope,
    AuditLogParseError,
    build_envelope,
    parse_jsonl_line,
)
from reporting.audit_pack import (
    FRAMEWORK_VERSION,
    render_audit_pack,
    save_audit_pack,
)
from reporting.batch_index import (
    render_batch_index,
    save_batch_index,
)
from reporting.styles import (
    ATTRIBUTION_FOOTER_TEMPLATE,
    AUDIT_PACK_CSS,
    BATCH_INDEX_CSS,
)


__all__ = [
    "ATTRIBUTION_FOOTER_TEMPLATE",
    "AUDIT_PACK_CSS",
    "AuditLogEnvelope",
    "AuditLogParseError",
    "BATCH_INDEX_CSS",
    "ENVELOPE_SCHEMA_VERSION",
    "FRAMEWORK_VERSION",
    "build_envelope",
    "parse_jsonl_line",
    "render_audit_pack",
    "render_batch_index",
    "save_audit_pack",
    "save_batch_index",
]
