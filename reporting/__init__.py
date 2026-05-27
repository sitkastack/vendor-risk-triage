"""Reporting outputs for the vendor risk triage framework.

Turns framework outputs into reader-facing artifacts that risk
committees, auditors, and ops teams can actually use.

Current contents:

- ``audit_pack``: Per-record HTML render of a single TriageRecord
- ``batch_index``: Multi-record HTML index linking to per-record packs
- ``styles``: Shared inline CSS used by both renderers
"""
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
    "BATCH_INDEX_CSS",
    "FRAMEWORK_VERSION",
    "render_audit_pack",
    "render_batch_index",
    "save_audit_pack",
    "save_batch_index",
]
