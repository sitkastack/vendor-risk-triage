"""Detection rules for STRIDE Denial of Service threats (T-D1, T-D2).

Phase 2 skeletons. Phase 5 implements operational logic.
Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_d1_resource_exhaustion(context: DetectionContext) -> DetectionResult:
    """Detect T-D1: Resource exhaustion via oversized or volume submissions.

    Per docs/phase-2/03-threat-model.md:
    Detection through API gateway metrics. Request rate spikes,
    submission size distribution shifts, and latency anomalies are
    leading indicators of resource exhaustion attacks.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-D1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_d2_llm_provider_outage(context: DetectionContext) -> DetectionResult:
    """Detect T-D2: LLM provider outage cascading to gate.

    Per docs/phase-2/03-threat-model.md:
    Detection through provider call latency and success rate monitoring.
    Sustained degradation patterns at the LLM Provider Adapter indicate
    provider-side issues regardless of provider acknowledgment.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-D2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
