"""Detection rules for threats documented in docs/phase-2/03-threat-model.md.

This package provides one callable function per threat (27 total: 16
STRIDE, 8 AI-specific, 3 Privacy). The functions are Phase 2 skeletons:
signatures and docstrings are committed in Phase 2; the operational
detection logic is implemented in Phase 5 (Deploy and Monitor).

The point of the skeleton is governance-as-code. Every threat has a
callable, identifiable detection function. The signature commits the
contract for how detection is invoked and what it returns; Phase 5
fills in the logic.
"""
