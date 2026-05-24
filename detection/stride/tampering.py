"""Detection rules for STRIDE Tampering threats (T-T1, T-T2, T-T3).

Phase 2 skeletons. Phase 5 implements operational logic.
Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_t1_submission_tampering_in_transit(context: DetectionContext) -> DetectionResult:
    """Detect T-T1: Submission tampering in transit.

    Per docs/phase-2/03-threat-model.md:
    Detection through schema validation failure rate spikes. Tampered
    submissions typically produce structural anomalies before semantic
    ones; sustained spikes in validation errors from a given source
    warrant investigation.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-T1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_t2_inference_traffic_tampering_in_transit(context: DetectionContext) -> DetectionResult:
    """Detect T-T2: Inference traffic tampering in transit.

    Per docs/phase-2/03-threat-model.md:
    Detection through response anomaly monitoring. Provider responses
    that systematically deviate from established statistical patterns
    (response length distribution, confidence score distribution,
    rationale structure) may indicate tampering.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-T2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_t3_agent_code_tampering_at_source(context: DetectionContext) -> DetectionResult:
    """Detect T-T3: Agent code or prompt tampering at the source.

    Per docs/phase-2/03-threat-model.md:
    Detection through standard source control and build pipeline
    monitoring. Unsigned commits to main branch, build pipeline
    anomalies, deployment of unexpected code versions. The agent_version
    captured in records supports post-hoc reconciliation against
    expected versions.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-T3 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
