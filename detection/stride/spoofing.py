"""Detection rules for STRIDE Spoofing threats (T-S1, T-S2, T-S3).

Phase 2 skeletons. Phase 5 implements operational logic.
Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_s1_submitter_identity_spoofing(context: DetectionContext) -> DetectionResult:
    """Detect T-S1: Submitter identity spoofing.

    Per docs/phase-2/03-threat-model.md:
    Detection through authentication failure rate anomalies at the API
    gateway and audit log analysis for repeated submissions from a single
    authenticated identity producing structurally similar but inconsistent
    content.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-S1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_s2_auditor_identity_spoofing(context: DetectionContext) -> DetectionResult:
    """Detect T-S2: Auditor identity spoofing.

    Per docs/phase-2/03-threat-model.md:
    Detection through the Audit Query API's query log analysis. Anomalous
    query volumes from a given authenticated identity, queries outside
    typical access patterns, or queries from identities not associated
    with active auditor roles.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-S2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_s3_llm_provider_endpoint_spoofing(context: DetectionContext) -> DetectionResult:
    """Detect T-S3: LLM provider endpoint spoofing.

    Per docs/phase-2/03-threat-model.md:
    Detection through TLS certificate fingerprint monitoring at the LLM
    Provider Adapter and provider endpoint anomaly detection (response
    latency patterns, response content patterns that deviate from
    established provider baselines).

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-S3 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
