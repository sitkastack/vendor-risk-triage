"""Detection rules for STRIDE Information Disclosure threats (T-I1, T-I2, T-I3).

Phase 2 skeletons. Phase 5 implements operational logic.
Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_i1_excessive_disclosure_to_llm_provider(context: DetectionContext) -> DetectionResult:
    """Detect T-I1: Excessive disclosure to LLM provider.

    Per docs/phase-2/03-threat-model.md:
    Detection through the PII detection step's incident logs. Spikes in
    incidental PII reaching the validator stage indicate either
    submission-side PII bleed-through or detection-side gaps.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-I1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_i2_system_prompt_extraction_via_responses(context: DetectionContext) -> DetectionResult:
    """Detect T-I2: System prompt extraction via responses.

    Per docs/phase-2/03-threat-model.md:
    Detection through response content analysis. Triage records
    containing rationale content that matches system prompt patterns or
    refers to operational instructions indicate possible prompt leakage.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-I2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_i3_cross_vendor_information_leakage(context: DetectionContext) -> DetectionResult:
    """Detect T-I3: Cross-vendor information leakage via prior records.

    Per docs/phase-2/03-threat-model.md:
    Detection through cross-record content matching. Triage records
    that reference other vendors' identifiers, names, or specific
    content in their rationale fields suggest cross-vendor leakage.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-I3 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
