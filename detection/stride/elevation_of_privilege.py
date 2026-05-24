"""Detection rules for STRIDE Elevation of Privilege threats (T-E1, T-E2, T-E3).

Phase 2 skeletons. Phase 5 implements operational logic.
Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_e1_read_to_write_escalation(context: DetectionContext) -> DetectionResult:
    """Detect T-E1: Read-to-write privilege escalation via Audit Query API.

    Per docs/phase-2/03-threat-model.md:
    Detection through database role privilege audits. Regular review of
    role permissions confirms UPDATE and DELETE remain ungranted to the
    audit role. Database audit logs of permission changes capture
    attempts to grant them.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-E1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_e2_application_role_escalation(context: DetectionContext) -> DetectionResult:
    """Detect T-E2: Application role privilege escalation.

    Per docs/phase-2/03-threat-model.md:
    Detection through anomaly monitoring on the records table. INSERT
    volume spikes outside expected ranges or insertions from unexpected
    source addresses indicate possible application role compromise.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-E2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_e3_retention_role_scope_expansion(context: DetectionContext) -> DetectionResult:
    """Detect T-E3: Retention enforcement role scope expansion.

    Per docs/phase-2/03-threat-model.md:
    Detection through retention job audit logs. Comparison of actual
    deleted record counts against expected retention eligibility
    (computed from the row-level security policy) identifies retention
    job anomalies.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-E3 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
