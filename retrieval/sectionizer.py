"""Section heading detection for regulation text.

Regulations vary in heading style. OSFI E-23 uses hierarchical numbered
sections ("3.1 Roles and responsibilities"). EU AI Act uses keyword-
prefixed identifiers ("Article 1", "Annex III"). SOX uses "Section 302".
ISO standards use clauses like "6.1 Actions to address risks".

This module ships a default regex pattern set that recognizes the major
styles. Deploying organizations with idiosyncratic regulation formats
supply their own pattern set via the ``patterns`` parameter; the framework
remains corpus-format-agnostic.

The detection runs line-by-line on the input text. A line that matches
any pattern in the active set becomes the start of a section; the
section extends to the start of the next matched line (or end of input).

The defaults are conservative. False positives (treating body text as
headings) split chunks too aggressively and degrade retrieval. False
negatives (missing real headings) leave the text usable in the page-
based fallback. The defaults prefer false negatives. Patterns require
strong line-level signals (anchored to line start, capital first letter
or all-caps, no terminal sentence punctuation in body lines).
"""
from __future__ import annotations

import re
from typing import Optional, Pattern

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "DEFAULT_SECTION_PATTERNS",
    "Section",
    "detect_sections",
]


# Default pattern set. Each pattern matches a single stripped line.
# Patterns are checked in order; first match wins for a given line.
#
# Pattern 1: hierarchical numbered. Matches "3.1 Title", "4.2.1 Subtitle".
# Requires the title to start with a capital letter; avoids matching
# "3.1 the answer is..." or numeric body content.
_PATTERN_HIERARCHICAL_NUMBERED = re.compile(
    r"^\d+(?:\.\d+)+\s+[A-Z][^.!?]{2,80}$"
)

# Pattern 2: top-level numbered with all-caps title. Matches
# "4 OPERATIONAL FRAMEWORK", "1 SCOPE AND PURPOSE". Requires the title
# portion to be predominantly uppercase (signaling a section heading
# rather than a numbered list item).
_PATTERN_TOP_LEVEL_CAPS = re.compile(
    r"^\d+\s+[A-Z][A-Z\s]{4,80}$"
)

# Pattern 3: keyword + identifier. Matches "Article 1", "Section 302",
# "Chapter 4", "Annex III", "Appendix A". Optional trailing title text
# is included if present (but the heading is parsed from the keyword
# and identifier).
_PATTERN_KEYWORD_IDENTIFIER = re.compile(
    r"^(?:Article|Section|Chapter|Appendix|Annex|Part|Subpart)"
    r"\s+(?:[IVX]+|\d+[a-z]?|[A-Z])\b.{0,80}$"
)

# Pattern 4: all-caps line. Conservative: requires 9+ characters of caps
# (at least two words or one long word). Avoids matching short acronyms
# that appear mid-sentence.
_PATTERN_ALL_CAPS = re.compile(
    r"^[A-Z][A-Z\s]{8,80}$"
)


DEFAULT_SECTION_PATTERNS: tuple[Pattern[str], ...] = (
    _PATTERN_HIERARCHICAL_NUMBERED,
    _PATTERN_KEYWORD_IDENTIFIER,
    _PATTERN_TOP_LEVEL_CAPS,
    _PATTERN_ALL_CAPS,
)
"""Compiled regex patterns checked in order for each line.

The framework's default pattern set covers the four major regulation
heading styles: hierarchical numbered (OSFI, ISO), keyword-identifier
(EU AI Act, SOX), top-level numbered with all-caps title, and pure
all-caps lines.

Deploying organizations with idiosyncratic formats pass their own
patterns to ``detect_sections``. The patterns must be compiled
``re.Pattern`` objects; each pattern is matched against stripped lines.
"""


class Section(BaseModel):
    """A detected section: heading text plus character offsets in the source.

    Attributes:
        heading_text: The matched heading line, stripped of surrounding
            whitespace. Used as the ``section_heading`` field of any
            Chunks produced from this section.
        start_offset: Character offset into the source text where the
            section begins (inclusive). Points at the first character of
            the heading line.
        end_offset: Character offset where the section ends (exclusive).
            Equals the next section's start_offset, or ``len(text)``
            for the final section.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    heading_text: str = Field(min_length=1, max_length=256)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)


def detect_sections(
    text: str,
    patterns: Optional[tuple[Pattern[str], ...]] = None,
) -> list[Section]:
    """Detect section boundaries in a block of regulation text.

    The detection runs line-by-line. Each line is stripped and tested
    against the supplied patterns (or DEFAULT_SECTION_PATTERNS if none
    given). The first matching pattern marks the line as a section
    heading; the section's text spans from this heading to the start of
    the next detected heading (or end of input).

    Lines that match no pattern are body text and belong to the section
    they appear within. Text before the first detected heading is not
    part of any returned Section; callers handling preamble text do so
    explicitly.

    Args:
        text: The source text to scan. Typically a page of extracted
            regulation text.
        patterns: Optional override pattern set. Defaults to
            DEFAULT_SECTION_PATTERNS. Deploying organizations supplying
            custom patterns must pass a tuple of compiled re.Pattern
            objects; each is matched against stripped lines.

    Returns:
        A list of Sections in document order. Empty list if no headings
        are detected.
    """
    effective_patterns = patterns if patterns is not None else DEFAULT_SECTION_PATTERNS

    # First pass: find heading lines and their character offsets in the
    # original text. We track byte offsets via running sum of line
    # lengths (plus one for the newline separator we split on).
    heading_starts: list[tuple[int, str]] = []  # (start_offset, heading_text)
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            for pat in effective_patterns:
                if pat.match(stripped):
                    heading_starts.append((offset, stripped))
                    break
        # Advance offset: include the line's full length plus the \n
        # separator. The final line lacks a trailing \n, but the loop
        # also stops after processing it.
        offset += len(line) + 1

    # Second pass: compute end_offsets as the start of the next heading
    # (or end of text for the final section).
    sections: list[Section] = []
    for i, (start, heading_text) in enumerate(heading_starts):
        if i + 1 < len(heading_starts):
            end = heading_starts[i + 1][0]
        else:
            end = len(text)
        sections.append(Section(
            heading_text=heading_text,
            start_offset=start,
            end_offset=end,
        ))
    return sections
