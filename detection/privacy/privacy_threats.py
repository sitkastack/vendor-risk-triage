"""Detection rules for Privacy threats (T-P1, T-P2, T-P3).

These threats target privacy obligations and their interaction with the
gate's architecture. Their detection profile is institutional process
(privacy office workflows) rather than purely technical, but the
skeleton commits a callable interface for institutional tooling to
implement against. Phase 2 skeletons; Phase 5 implements operational
logic. Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_p1_data_subject_access_request_conflict(context: DetectionContext) -> DetectionResult:
    """Detect T-P1: Data subject access request conflict with audit trail retention.

    Per docs/phase-2/03-threat-model.md:
    Detection through standard privacy office workflow. Access requests
    are received and routed; the institution tracks request volume and
    response time as part of privacy compliance metrics.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-P1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_p2_right_to_erasure_conflict(context: DetectionContext) -> DetectionResult:
    """Detect T-P2: Right to erasure conflict with append-only storage.

    Per docs/phase-2/03-threat-model.md:
    Detection through standard privacy office workflow. Erasure request
    volume and outcome (granted or denied with documented exemption) is
    tracked as part of privacy compliance reporting.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-P2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_p3_cross_border_transfer_threat(context: DetectionContext) -> DetectionResult:
    """Detect T-P3: Cross-border transfer threat at Crossing 2.

    Per docs/phase-2/03-threat-model.md:
    Detection through region configuration audit (periodic verification
    that the deployed configuration matches the legal mechanism) and
    provider audit of actual processing region (institutions verify
    processing region for AWS Bedrock and similar at the inference path
    level, per ADR-002).

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-P3 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
