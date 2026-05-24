# Detection

Callable detection rules for the 27 threats documented in docs/phase-2/03-threat-model.md. One function per threat. Every detection function is identified by its threat ID, has a stable signature, and carries the Detection prose from the threat model as its docstring.

## What this is

Governance-as-code for threat detection. The Phase 2 threat model identifies threats and their detection approaches in prose. This directory makes the detection approaches addressable in code: every threat has a Python function with the threat ID in its name, the detection prose in its docstring, and a stable input/output contract.

Phase 2 ships the skeletons. Every function raises NotImplementedError when called. Phase 5 (Deploy and Monitor) implements the operational detection logic. The skeleton-then-implementation pattern lets Phase 2 commit the contract for how detection is invoked without overcommitting to Phase 5 implementation specifics.

## Structure

```
detection/
├── types.py                              # DetectionContext, DetectionResult, etc.
├── stride/
│   ├── spoofing.py                       # T-S1, T-S2, T-S3
│   ├── tampering.py                      # T-T1, T-T2, T-T3
│   ├── repudiation.py                    # T-R1, T-R2
│   ├── information_disclosure.py         # T-I1, T-I2, T-I3
│   ├── denial_of_service.py              # T-D1, T-D2
│   └── elevation_of_privilege.py         # T-E1, T-E2, T-E3
├── ai/
│   └── ai_threats.py                     # T-AI1 through T-AI8
└── privacy/
    └── privacy_threats.py                # T-P1, T-P2, T-P3
```

## The signature contract

Every detection function follows this shape:

```python
def detect_<threat_id>_<short_name>(context: DetectionContext) -> DetectionResult:
    """Detect T-XX: Short name.

    Per docs/phase-2/03-threat-model.md:
    [Detection prose from the threat model]

    Raises:
        NotImplementedError: Phase 5 implements operational logic.
    """
    ...
```

The DetectionContext provides access to operational data sources (audit log, triage records, provider interactions, configuration). Phase 5 implements adapters between these types and the institution's actual data sources.

The DetectionResult carries the structured outcome: threat_id, detected (bool), severity, evidence list, and recommended action. Phase 5 implementations return populated DetectionResults; the Phase 2 skeletons raise NotImplementedError.

## Verification

tests/test_detection_signatures.py verifies that all 27 detection functions exist, take a DetectionContext, raise NotImplementedError when called, and reference their threat ID and the threat model document in their docstring. The signature contract is enforced on every push and PR by .github/workflows/validate.yml.

## Phase 5 implementation

When Phase 5 lands, each function's body is replaced with the operational detection logic. The signatures and docstrings stay; the NotImplementedError disappears. The tests in test_detection_signatures.py are updated at that point to exercise the real behavior rather than the skeleton.

The skeleton-then-implementation pattern is the framework's commitment that detection is an architectural concern, not just an operational add-on. The threat model identifies what needs to be detected; this directory identifies how the detection is called; Phase 5 implements the how.
