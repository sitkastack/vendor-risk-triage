"""Pre-built rubrics for the LLM judge.

Each rubric names a single evaluation criterion the framework
considers important enough to ship out of the box. Deploying
organizations are encouraged to add their own rubrics for criteria
specific to their domain or audit policy; these three are starting
points, not an exhaustive list.

A rubric is a `Rubric` instance with:

- A snake_case name used in metrics aggregation
- A description embedded in the judge's user prompt verbatim
- An optional edge_case_handler that short-circuits LLM calls in cases
  where the score is determined without semantic judgement (e.g., no
  chunks cited to evaluate, no mitigations required by the disposition)

The descriptions are hand-tuned. Generic prompts produce noisy scores;
specific descriptions with explicit anchors ("a defensible chain
references concrete fields") tighten the signal.
"""
from __future__ import annotations

from typing import Any, Optional

import re

from agent.output_models import TriageRecord
from eval.judge.judge import Rubric


__all__ = [
    "CITATION_GROUNDING",
    "MITIGATION_APPROPRIATENESS",
    "RATIONALE_COHERENCE",
]


# Chunk-id regex (mirrors eval.citations.citation_verifier).
# Local copy to avoid a cross-package dependency that the citation
# verifier doesn't otherwise need from the judge.
_CHUNK_ID_PATTERN = re.compile(
    r"\b([a-z0-9][a-z0-9.\-_]*:[a-z0-9][a-z0-9.\-_]*:page-\d+)\b",
    re.IGNORECASE,
)


# -- Rationale coherence ----------------------------------------------------


_RATIONALE_COHERENCE_DESCRIPTION = """\
Does the agent's classification_rationale provide a defensible chain of reasoning from the specific facts in the submission to the assigned risk_tier and recommended_disposition?

A defensible chain references concrete fields or facts from the submission (PII categories, AI usage level, jurisdiction, vendor classification, documentation artifacts, ai_act_self_classification, training_data_sources, etc.) and explains how each contributes to the tier and disposition.

A NOT-defensible rationale relies on:
- Generic claims ("this vendor is high risk") without grounding in specific submission fields
- Restating the tier/disposition without explaining why
- Reasoning that contradicts the submission's facts
- Reasoning that ignores material risks visible in the submission

Score 1.0: every claim in the rationale is anchored to specific submission facts; the tier and disposition follow from the cited facts.
Score 0.5: partial grounding; the rationale identifies the right facts but the chain to tier/disposition has gaps.
Score 0.0: the rationale is generic, contradictory, or ignores the submission's specific content.

Score continuously between these anchors.
"""

RATIONALE_COHERENCE = Rubric(
    name="rationale_coherence",
    description=_RATIONALE_COHERENCE_DESCRIPTION,
)


# -- Citation grounding ----------------------------------------------------


_CITATION_GROUNDING_DESCRIPTION = """\
For each chunk citation in the agent's evidence_cited (referenced by chunk_id in the reasoning text), does the cited regulation chunk actually support the claim the agent makes about it?

A well-grounded chunk citation: the chunk's text directly supports the specific claim the agent's reasoning makes when invoking that chunk_id. The agent does not invent regulatory requirements that the chunk does not contain.

A POORLY-grounded chunk citation: the cited chunk does not contain the requirement, fact, or guidance the agent claims. The agent uses the chunk_id as a citation prop without basis in the chunk's actual text.

Score 1.0: every chunk citation in the reasoning is grounded in the chunk's actual text; no fabricated requirements; no chunk_ids invented.
Score 0.5: some citations are grounded, others paraphrase too loosely or invent requirements not in the chunk.
Score 0.0: any citation invents regulatory content the chunk does not contain.

Score continuously between these anchors. Be specific: when scoring below 1.0, quote the agent's claim and the chunk's actual relevant text.
"""


def _citation_grounding_edge_case(
    record: TriageRecord,
    submission: dict[str, Any],
    documents: list[Any],
    regulation_chunks: list[Any],
) -> Optional[tuple[float, str]]:
    """Short-circuit citation grounding when there are no chunks to grade.

    If no chunks were supplied to the agent AND no chunk_ids are
    mentioned in any reasoning text, citation grounding is vacuously
    satisfied. Returns (1.0, explanation) to skip the LLM call.

    If chunks were supplied but the agent did not cite any, that is
    NOT an edge case - the LLM should judge whether non-citation is
    appropriate for this record (the agent may have correctly decided
    no chunk applied).
    """
    if regulation_chunks:
        return None  # LLM should grade
    # No chunks supplied. Check if reasoning mentions any chunk_ids.
    for ec in record.evidence_cited:
        if _CHUNK_ID_PATTERN.search(ec.reasoning):
            return None  # Agent fabricated a citation; LLM should grade
    return (
        1.0,
        "No regulation chunks were supplied to the agent and the agent's "
        "evidence_cited contains no chunk_id references; citation grounding "
        "is vacuously satisfied.",
    )


CITATION_GROUNDING = Rubric(
    name="citation_grounding",
    description=_CITATION_GROUNDING_DESCRIPTION,
    edge_case_handler=_citation_grounding_edge_case,
)


# -- Mitigation appropriateness -------------------------------------------


_MITIGATION_APPROPRIATENESS_DESCRIPTION = """\
When the recommended_disposition is 'conditional_approve', do the required_mitigations actually address the specific risks identified in the classification_rationale?

Appropriate mitigations: each mitigation names a specific risk (drawn from the rationale) and provides concrete oversight or control language. The mitigation set as a whole covers the major risks the rationale identifies.

INAPPROPRIATE mitigations:
- Generic ("monitor regularly", "ensure compliance") without specific risk linkage
- Boilerplate disconnected from the rationale's specific concerns
- Missing coverage for material risks the rationale identifies

Score 1.0: every mitigation maps to a specific risk in the rationale; the mitigation set covers the major risks identified.
Score 0.5: some mitigations are specific, others generic; partial coverage of the rationale's risks.
Score 0.0: mitigations are entirely boilerplate, or do not address any risks the rationale identifies.

Score continuously between these anchors.
"""


def _mitigation_appropriateness_edge_case(
    record: TriageRecord,
    submission: dict[str, Any],
    documents: list[Any],
    regulation_chunks: list[Any],
) -> Optional[tuple[float, str]]:
    """Short-circuit mitigation appropriateness when disposition is not conditional_approve.

    The output contract allows required_mitigations only when the
    disposition is conditional_approve. For any other disposition,
    mitigations are inapplicable; the rubric is vacuously satisfied.
    """
    if record.recommended_disposition != "conditional_approve":
        return (
            1.0,
            f"Disposition is {record.recommended_disposition!r}, not "
            "'conditional_approve'; mitigations do not apply for this "
            "disposition. Rubric is vacuously satisfied.",
        )
    return None  # disposition is conditional_approve; LLM should grade


MITIGATION_APPROPRIATENESS = Rubric(
    name="mitigation_appropriateness",
    description=_MITIGATION_APPROPRIATENESS_DESCRIPTION,
    edge_case_handler=_mitigation_appropriateness_edge_case,
)
