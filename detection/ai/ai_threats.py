"""Detection rules for AI-specific threats (T-AI1 through T-AI8).

These threats target the AI system's behavior specifically; STRIDE alone
does not address them. Phase 2 skeletons; Phase 5 implements operational
logic. Reference: docs/phase-2/03-threat-model.md
"""
from detection.types import DetectionContext, DetectionResult


def detect_t_ai1_prompt_injection_via_vendor_documents(context: DetectionContext) -> DetectionResult:
    """Detect T-AI1: Prompt injection via vendor documents.

    Per docs/phase-2/03-threat-model.md:
    Detection through input pattern analysis. Submissions containing
    common prompt injection markers (instruction overrides, role
    escalation phrases, system prompt extraction requests) and output
    structural anomalies suggesting the LLM diverged from its expected
    behavior pattern.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI1 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai2_data_exfiltration_via_prompt(context: DetectionContext) -> DetectionResult:
    """Detect T-AI2: Data exfiltration via prompt.

    Per docs/phase-2/03-threat-model.md:
    Detection through response content analysis. Triage records
    containing content resembling system prompt structures, training
    data fragments, or other indicators of extraction success.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI2 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai3_model_misuse_and_capability_extraction(context: DetectionContext) -> DetectionResult:
    """Detect T-AI3: Model misuse and capability extraction.

    Per docs/phase-2/03-threat-model.md:
    Detection through volume and pattern analysis. High submission
    rates from the same source with subtle systematic variations
    consistent with probing behavior; unusual diversity in submission
    content from a single source.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI3 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai4_hallucination_accepted_without_verification(context: DetectionContext) -> DetectionResult:
    """Detect T-AI4: Hallucination accepted without verification.

    Per docs/phase-2/03-threat-model.md:
    Detection is reactive (reviewer flags fabrication) and proactive
    (sampling audits, automated fact-checking against known facts for
    regulatory citation patterns, periodic evaluation against held-out
    test sets to measure hallucination rates).

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI4 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai5_confidence_score_manipulation(context: DetectionContext) -> DetectionResult:
    """Detect T-AI5: Confidence-score manipulation.

    Per docs/phase-2/03-threat-model.md:
    Detection through confidence score distribution monitoring. Sudden
    shifts in the distribution of confidence scores across submissions,
    or anomalous correlations between confidence and submission
    characteristics (such as consistently high confidence on borderline
    cases), indicate manipulation.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI5 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai6_discriminatory_output_bias(context: DetectionContext) -> DetectionResult:
    """Detect T-AI6: Discriminatory output bias.

    Per docs/phase-2/03-threat-model.md:
    Detection through output distribution analysis across vendor
    categories. Periodic bias audits comparing classification rates,
    dispositions, and rationale patterns across vendor types of
    concern. Reviewer escalation when systematic patterns emerge.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI6 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai7_fairness_drift(context: DetectionContext) -> DetectionResult:
    """Detect T-AI7: Fairness drift over vendor distribution.

    Per docs/phase-2/03-threat-model.md:
    Detection through periodic classification distribution analysis.
    Shifts in tier and disposition distributions over time, especially
    when correlated with shifts in vendor characteristic distributions,
    indicate fairness drift.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI7 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )


def detect_t_ai8_classification_drift_through_provider_updates(context: DetectionContext) -> DetectionResult:
    """Detect T-AI8: Classification drift through provider model updates.

    Per docs/phase-2/03-threat-model.md:
    Detection through provider change notifications (institutional
    subscription to provider release notes), periodic re-evaluation
    against held-out test sets (classification rates that drift on
    stable inputs indicate upstream changes), and statistical
    monitoring of confidence distributions and rationale patterns over
    time.

    Raises:
        NotImplementedError: Phase 5 (Deploy and Monitor) implements the logic.
    """
    raise NotImplementedError(
        "T-AI8 detection is a Phase 2 skeleton; Phase 5 implements operational logic."
    )
