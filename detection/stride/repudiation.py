"""Detection rules for STRIDE Repudiation threats (T-R1, T-R2).

Phase 2 skeletons. Phase 5 implements operational logic.
Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_r1_reviewer_denying_override_or_revocation(context: DetectionContext) -> DetectionResult:
    """Detect T-R1: Reviewer denying override or revocation action.

    Per docs/phase-2/03-threat-model.md:
    Detection is reactive. When a reviewer disputes an action, the
    audit log is consulted to confirm the authenticated identity,
    timestamp, and request content at the time of the action.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-R1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_r2_llm_provider_repudiation(context: DetectionContext) -> DetectionResult:
    """Detect T-R2: LLM provider repudiation of processing.

    Per docs/phase-2/03-threat-model.md:
    Detection through provider log reconciliation. Periodic comparison
    of the gate's claimed provider calls against the provider's billing
    or usage logs identifies discrepancies.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-R2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
