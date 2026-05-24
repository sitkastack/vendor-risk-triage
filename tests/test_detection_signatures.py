"""Tests that all 27 detection skeletons have the expected signature contract.

Every threat in docs/phase-2/03-threat-model.md has a corresponding
detection function. These tests verify:

- All 27 functions exist and are importable
- Each function takes a single DetectionContext parameter
- Each function raises NotImplementedError (skeleton intent)
- Each docstring references its threat ID
- Each docstring references the threat model document

When Phase 5 implements detection logic, these tests are updated to
exercise real behavior; the signature contract remains stable.
"""
import inspect
from datetime import datetime, timezone

import pytest

from detection.types import (
    AuditLogWindow,
    ConfigurationSnapshot,
    DetectionContext,
    ProviderInteractionWindow,
    TriageRecordWindow,
)

# STRIDE Spoofing
from detection.stride.spoofing import (
    detect_t_s1_submitter_identity_spoofing,
    detect_t_s2_auditor_identity_spoofing,
    detect_t_s3_llm_provider_endpoint_spoofing,
)

# STRIDE Tampering
from detection.stride.tampering import (
    detect_t_t1_submission_tampering_in_transit,
    detect_t_t2_inference_traffic_tampering_in_transit,
    detect_t_t3_agent_code_tampering_at_source,
)

# STRIDE Repudiation
from detection.stride.repudiation import (
    detect_t_r1_reviewer_denying_override_or_revocation,
    detect_t_r2_llm_provider_repudiation,
)

# STRIDE Information Disclosure
from detection.stride.information_disclosure import (
    detect_t_i1_excessive_disclosure_to_llm_provider,
    detect_t_i2_system_prompt_extraction_via_responses,
    detect_t_i3_cross_vendor_information_leakage,
)

# STRIDE Denial of Service
from detection.stride.denial_of_service import (
    detect_t_d1_resource_exhaustion,
    detect_t_d2_llm_provider_outage,
)

# STRIDE Elevation of Privilege
from detection.stride.elevation_of_privilege import (
    detect_t_e1_read_to_write_escalation,
    detect_t_e2_application_role_escalation,
    detect_t_e3_retention_role_scope_expansion,
)

# AI-specific
from detection.ai.ai_threats import (
    detect_t_ai1_prompt_injection_via_vendor_documents,
    detect_t_ai2_data_exfiltration_via_prompt,
    detect_t_ai3_model_misuse_and_capability_extraction,
    detect_t_ai4_hallucination_accepted_without_verification,
    detect_t_ai5_confidence_score_manipulation,
    detect_t_ai6_discriminatory_output_bias,
    detect_t_ai7_fairness_drift,
    detect_t_ai8_classification_drift_through_provider_updates,
)

# Privacy
from detection.privacy.privacy_threats import (
    detect_t_p1_data_subject_access_request_conflict,
    detect_t_p2_right_to_erasure_conflict,
    detect_t_p3_cross_border_transfer_threat,
)


ALL_DETECTION_FUNCTIONS = [
    ("T-S1", detect_t_s1_submitter_identity_spoofing),
    ("T-S2", detect_t_s2_auditor_identity_spoofing),
    ("T-S3", detect_t_s3_llm_provider_endpoint_spoofing),
    ("T-T1", detect_t_t1_submission_tampering_in_transit),
    ("T-T2", detect_t_t2_inference_traffic_tampering_in_transit),
    ("T-T3", detect_t_t3_agent_code_tampering_at_source),
    ("T-R1", detect_t_r1_reviewer_denying_override_or_revocation),
    ("T-R2", detect_t_r2_llm_provider_repudiation),
    ("T-I1", detect_t_i1_excessive_disclosure_to_llm_provider),
    ("T-I2", detect_t_i2_system_prompt_extraction_via_responses),
    ("T-I3", detect_t_i3_cross_vendor_information_leakage),
    ("T-D1", detect_t_d1_resource_exhaustion),
    ("T-D2", detect_t_d2_llm_provider_outage),
    ("T-E1", detect_t_e1_read_to_write_escalation),
    ("T-E2", detect_t_e2_application_role_escalation),
    ("T-E3", detect_t_e3_retention_role_scope_expansion),
    ("T-AI1", detect_t_ai1_prompt_injection_via_vendor_documents),
    ("T-AI2", detect_t_ai2_data_exfiltration_via_prompt),
    ("T-AI3", detect_t_ai3_model_misuse_and_capability_extraction),
    ("T-AI4", detect_t_ai4_hallucination_accepted_without_verification),
    ("T-AI5", detect_t_ai5_confidence_score_manipulation),
    ("T-AI6", detect_t_ai6_discriminatory_output_bias),
    ("T-AI7", detect_t_ai7_fairness_drift),
    ("T-AI8", detect_t_ai8_classification_drift_through_provider_updates),
    ("T-P1", detect_t_p1_data_subject_access_request_conflict),
    ("T-P2", detect_t_p2_right_to_erasure_conflict),
    ("T-P3", detect_t_p3_cross_border_transfer_threat),
]


def _empty_context() -> DetectionContext:
    """Build a minimal DetectionContext for signature testing."""
    now = datetime.now(timezone.utc)
    return DetectionContext(
        audit_log=AuditLogWindow(start=now, end=now),
        triage_records=TriageRecordWindow(start=now, end=now),
        provider_interactions=ProviderInteractionWindow(start=now, end=now),
        configuration=ConfigurationSnapshot(timestamp=now),
    )


def test_all_27_detection_functions_present() -> None:
    """Framework defines exactly 27 detection functions (16 STRIDE, 8 AI, 3 Privacy)."""
    assert len(ALL_DETECTION_FUNCTIONS) == 27


@pytest.mark.parametrize("threat_id,fn", ALL_DETECTION_FUNCTIONS)
def test_signature_takes_detection_context(threat_id: str, fn) -> None:
    """Detection function takes exactly one DetectionContext parameter."""
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    assert len(params) == 1, f"{threat_id}: expected exactly one parameter"
    assert params[0].annotation is DetectionContext, (
        f"{threat_id}: parameter must be annotated DetectionContext, "
        f"got {params[0].annotation}"
    )


@pytest.mark.parametrize("threat_id,fn", ALL_DETECTION_FUNCTIONS)
def test_raises_not_implemented(threat_id: str, fn) -> None:
    """Phase 2 skeleton raises NotImplementedError (Phase 5 implements logic)."""
    context = _empty_context()
    with pytest.raises(NotImplementedError) as exc_info:
        fn(context)
    assert "Phase 5" in str(exc_info.value), (
        f"{threat_id}: NotImplementedError must mention Phase 5 deferral"
    )


@pytest.mark.parametrize("threat_id,fn", ALL_DETECTION_FUNCTIONS)
def test_docstring_mentions_threat_id(threat_id: str, fn) -> None:
    """Docstring includes the threat ID for traceability."""
    assert fn.__doc__ is not None, f"{threat_id}: function must have a docstring"
    assert threat_id in fn.__doc__, (
        f"{threat_id}: docstring must reference threat ID '{threat_id}'"
    )


@pytest.mark.parametrize("threat_id,fn", ALL_DETECTION_FUNCTIONS)
def test_docstring_references_threat_model(threat_id: str, fn) -> None:
    """Docstring references docs/phase-2/03-threat-model.md."""
    assert "03-threat-model.md" in fn.__doc__, (
        f"{threat_id}: docstring must reference docs/phase-2/03-threat-model.md"
    )
