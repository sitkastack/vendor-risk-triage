"""Tests for the Phase 4.5 reliability diagram SVG renderer.

The renderer is a pure function over CalibrationReport. Tests verify:

- The output is well-formed SVG (XML parseable, correct root element)
- Per-bin bars are present (and only for non-empty bins)
- Per-bin tooltip metadata is encoded
- Empty-bin (vacuous) reports render without bars but with the chart frame
- Both binning methods produce sensible output
- Size validation and edge cases
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from eval.calibration import (
    ConfidenceOutcome,
    compute_calibration,
)
from eval.calibration.diagram import render_reliability_diagram


# -- helpers ---------------------------------------------------------------


_NS = {"svg": "http://www.w3.org/2000/svg"}


def _parse(svg: str) -> ET.Element:
    """Parse the SVG string into an Element. Raises if malformed."""
    return ET.fromstring(svg)


def _rects(root: ET.Element) -> list[ET.Element]:
    return root.findall("svg:rect", _NS)


def _outcomes_full_range() -> list[ConfidenceOutcome]:
    """Outcomes covering most of [0, 1] for general-purpose testing."""
    return [
        ConfidenceOutcome(confidence_score=0.1, was_correct=False),
        ConfidenceOutcome(confidence_score=0.3, was_correct=True),
        ConfidenceOutcome(confidence_score=0.5, was_correct=True),
        ConfidenceOutcome(confidence_score=0.7, was_correct=False),
        ConfidenceOutcome(confidence_score=0.9, was_correct=True),
    ]


# -- basic structural tests ------------------------------------------------


def test_render_returns_string_starting_with_svg() -> None:
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report)
    assert isinstance(svg, str)
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")


def test_render_produces_well_formed_xml() -> None:
    """The output must parse as XML with svg as the root element."""
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    assert root.tag.endswith("svg"), f"Root should be svg, got {root.tag}"


def test_render_has_default_dimensions() -> None:
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    assert root.attrib["width"] == "600"
    assert root.attrib["height"] == "400"


def test_render_accepts_custom_dimensions() -> None:
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report, width=800, height=600)
    root = _parse(svg)
    assert root.attrib["width"] == "800"
    assert root.attrib["height"] == "600"


def test_render_rejects_tiny_dimensions() -> None:
    report = compute_calibration([])
    with pytest.raises(ValueError, match="at least 100"):
        render_reliability_diagram(report, width=50, height=50)


def test_render_rejects_dimensions_too_small_for_insets() -> None:
    """At width=100 (passing the >=100 check), plot area collapses below 0."""
    report = compute_calibration([])
    with pytest.raises(ValueError, match="too small for chart insets"):
        render_reliability_diagram(report, width=100, height=400)


# -- bars match non-empty bins --------------------------------------------


def test_render_produces_one_bar_per_non_empty_bin() -> None:
    """Each non-empty bin produces exactly one <rect>; empty bins are skipped."""
    outcomes = _outcomes_full_range()
    report = compute_calibration(outcomes, num_bins=10)
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    non_empty = sum(1 for b in report.bins if b.count > 0)
    assert len(_rects(root)) == non_empty


def test_render_skips_empty_bins() -> None:
    """A report with many empty bins produces only as many bars as non-empty bins."""
    # 2 outcomes in 10 equal-width bins -> only the bins containing them are non-empty
    outcomes = [
        ConfidenceOutcome(confidence_score=0.15, was_correct=True),
        ConfidenceOutcome(confidence_score=0.85, was_correct=False),
    ]
    report = compute_calibration(outcomes, num_bins=10)
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    # Exactly 2 bars: one in the 0.1-0.2 bin, one in the 0.8-0.9 bin
    assert len(_rects(root)) == 2


def test_render_vacuous_report_has_no_bars_but_renders() -> None:
    """A total_predictions=0 report still renders the axes/frame, just no bars."""
    report = compute_calibration([])
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    assert len(_rects(root)) == 0
    # The chart frame is still there: at minimum two axis lines + diagonal + gridlines
    lines = root.findall("svg:line", _NS)
    assert len(lines) > 0


def test_render_vacuous_subtitle_says_no_predictions() -> None:
    report = compute_calibration([])
    svg = render_reliability_diagram(report)
    assert "No predictions" in svg


# -- tooltips carry per-bin metadata --------------------------------------


def test_render_each_bar_has_a_title_tooltip() -> None:
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    rects = _rects(root)
    for r in rects:
        title = r.find("svg:title", _NS)
        assert title is not None
        assert title.text is not None


def test_render_tooltip_contains_count_and_accuracy() -> None:
    """Tooltip text encodes the per-bin audit data."""
    outcomes = [
        ConfidenceOutcome(confidence_score=0.75, was_correct=True),
        ConfidenceOutcome(confidence_score=0.75, was_correct=True),
        ConfidenceOutcome(confidence_score=0.75, was_correct=False),
    ]
    report = compute_calibration(outcomes, num_bins=10)
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    rects = _rects(root)
    assert len(rects) == 1
    title = rects[0].find("svg:title", _NS)
    assert title is not None
    assert "count: 3" in title.text
    # accuracy = 2/3
    assert "0.667" in title.text


# -- subtitle metrics -----------------------------------------------------


def test_render_subtitle_includes_ece_brier_n() -> None:
    """The subtitle exposes the key metrics for at-a-glance audit."""
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report)
    # Subtitle includes ECE, Brier, N (and MCE, dimension)
    assert "ECE:" in svg
    assert "MCE:" in svg
    assert "Brier:" in svg
    assert f"N={report.total_predictions}" in svg


def test_render_subtitle_shows_dimension() -> None:
    report = compute_calibration(_outcomes_full_range(), dimension="disposition")
    svg = render_reliability_diagram(report)
    assert "disposition" in svg


# -- custom title --------------------------------------------------------


def test_render_uses_default_title_with_binning_method() -> None:
    report = compute_calibration(_outcomes_full_range(), binning="equal_frequency")
    svg = render_reliability_diagram(report)
    assert "equal_frequency" in svg


def test_render_accepts_custom_title() -> None:
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report, title="Tier 3 Calibration")
    assert "Tier 3 Calibration" in svg
    # Default title should NOT also appear
    assert "Reliability Diagram (" not in svg


# -- binning method compatibility ----------------------------------------


def test_render_works_with_equal_width_binning() -> None:
    report = compute_calibration(_outcomes_full_range(), binning="equal_width")
    svg = render_reliability_diagram(report)
    _parse(svg)  # well-formed


def test_render_works_with_equal_frequency_binning() -> None:
    report = compute_calibration(_outcomes_full_range(), binning="equal_frequency")
    svg = render_reliability_diagram(report)
    _parse(svg)
    # Equal-frequency may have descriptive bounds; the renderer treats them
    # the same way as equal-width prescriptive bounds. Non-empty bins -> bars.
    root = _parse(svg)
    non_empty = sum(1 for b in report.bins if b.count > 0)
    assert len(_rects(root)) == non_empty


# -- bar geometry sanity --------------------------------------------------


def test_render_bar_x_position_reflects_bin_bounds() -> None:
    """A bar for a bin with lower_bound=0.5 should sit around x = midplot."""
    # 1 outcome at score=0.55 in a 10-bin equal-width report -> bin [0.5, 0.6) populated
    outcomes = [ConfidenceOutcome(confidence_score=0.55, was_correct=True)]
    report = compute_calibration(outcomes, num_bins=10, binning="equal_width")
    svg = render_reliability_diagram(report, width=600, height=400)
    root = _parse(svg)
    rects = _rects(root)
    assert len(rects) == 1
    # Plot area: x from 80 to 560 (width 480). bin [0.5, 0.6) -> bar x from
    # 80 + 0.5*480 = 320 to 80 + 0.6*480 = 368
    bar = rects[0]
    bar_x = float(bar.attrib["x"])
    bar_w = float(bar.attrib["width"])
    assert 319 < bar_x < 321, f"Expected bar x around 320, got {bar_x}"
    assert 47 < bar_w < 49, f"Expected bar width around 48, got {bar_w}"


def test_render_bar_height_reflects_accuracy() -> None:
    """A bar for accuracy=1.0 should be the full plot height; 0.5 should be half."""
    # Two outcomes both wrong at score=0.55 -> accuracy=0
    # Wait: accuracy=0 means the bar has zero height. Let's do accuracy=0.5 instead.
    outcomes = [
        ConfidenceOutcome(confidence_score=0.55, was_correct=True),
        ConfidenceOutcome(confidence_score=0.55, was_correct=False),
    ]
    report = compute_calibration(outcomes, num_bins=10)
    svg = render_reliability_diagram(report, width=600, height=400)
    root = _parse(svg)
    rects = _rects(root)
    bar_h = float(rects[0].attrib["height"])
    # Plot height = 400 - 60 (top inset) - 60 (bottom inset) = 280
    # Bar height for accuracy=0.5 should be 280 * 0.5 = 140
    assert 139 < bar_h < 141, f"Expected bar height ~140 for accuracy=0.5, got {bar_h}"


# -- accessibility -------------------------------------------------------


def test_render_includes_role_and_aria_label() -> None:
    """The SVG root carries accessibility attributes."""
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report)
    root = _parse(svg)
    assert root.attrib.get("role") == "img"
    assert "aria-label" in root.attrib


# -- XML safety ---------------------------------------------------------


def test_render_escapes_special_chars_in_custom_title() -> None:
    """A title with XML metacharacters does not break the output."""
    report = compute_calibration(_outcomes_full_range())
    svg = render_reliability_diagram(report, title='Title with <tag> & "quotes"')
    # Output should still parse cleanly
    root = _parse(svg)
    # Custom title text should be present (with escaping applied)
    full_text = "".join(elem.text or "" for elem in root.iter() if elem.text)
    assert "Title with <tag> & \"quotes\"" in full_text  # decoded by parser
