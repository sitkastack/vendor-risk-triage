"""SVG reliability diagram rendering for calibration reports.

A CalibrationReport carries per-bin reliability data in its bins
field, plus aggregate metrics (Brier, ECE, MCE). The numerical data
is sufficient for programmatic analysis but inadequate for human
audit review: auditors read charts, not tables of BinStats.

This module renders a CalibrationReport as an SVG string. The chart
shows per-bin (mean_confidence, accuracy) bars against the y=x
reference line (perfect calibration). Gaps between bar tops and the
diagonal visualize miscalibration directly.

The output is pure SVG text:

- No external dependencies (no matplotlib, no plotly, no Chart.js).
  The framework's small dependency footprint is preserved.
- Diffable across commits. An auditor reviewing chart versions sees
  meaningful XML diffs, not opaque PNG blobs.
- Embeddable in HTML, included verbatim in PDF audit bundles, or
  written directly to a .svg file for standalone viewing.

The chart structure follows the standard reliability diagram
(Niculescu-Mizil & Caruana 2005). Per-bin bars span the bin's
lower_bound and upper_bound on the x axis (which is correct for both
equal-width binning, where bounds are prescriptive, and equal-
frequency binning, where bounds are descriptive).

Empty bins (count=0) are skipped in the main plot since they have no
mean_confidence to plot at. Per-bin count is encoded as a hover-
tooltip via the SVG <title> child of each bar, preserving audit
signal without a secondary plot.
"""
from __future__ import annotations

from typing import Optional

from eval.calibration.scorer import CalibrationReport


__all__ = [
    "render_reliability_diagram",
]


# Layout constants (in SVG user units, which default to pixels).
# Chosen so the chart is legible at typical embed sizes without
# being so large it overwhelms a page.

_DEFAULT_WIDTH: int = 600
_DEFAULT_HEIGHT: int = 400

# Plot-area inset within the SVG canvas. Leaves room for title, axis
# labels, and tick text.
_INSET_LEFT: int = 80
_INSET_RIGHT: int = 40
_INSET_TOP: int = 60
_INSET_BOTTOM: int = 60

# Visual styling. Conservative palette suitable for audit reports.
_BAR_FILL: str = "#4a90c2"
_BAR_STROKE: str = "#1f567a"
_REFERENCE_STROKE: str = "#999999"
_AXIS_STROKE: str = "#333333"
_GRID_STROKE: str = "#e5e5e5"
_TEXT_FILL: str = "#222222"
_SUBTITLE_FILL: str = "#666666"

# Gridline positions on the [0, 1] axes.
_GRIDLINES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def render_reliability_diagram(
    report: CalibrationReport,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    title: Optional[str] = None,
) -> str:
    """Render a CalibrationReport as an SVG reliability diagram.

    The diagram shows per-bin accuracy bars positioned at each bin's
    confidence range, against the y=x reference line that represents
    perfect calibration. The vertical gap between each bar's top and
    the diagonal at that x position is the per-bin calibration error.

    Empty bins (count=0) are not rendered in the main plot; per-bin
    count is exposed via SVG <title> tooltips on the bars.

    Args:
        report: A CalibrationReport from compute_calibration() or one
            of its convenience entry points.
        width: SVG canvas width in user units. Default 600.
        height: SVG canvas height in user units. Default 400.
        title: Optional chart title overriding the default. The default
            is "Reliability Diagram" with the binning method appended
            in parentheses.

    Returns:
        A complete SVG document as a string. The string starts with
        the <svg ...> opening tag and ends with </svg>; no XML
        declaration is included so the result embeds cleanly in HTML.

    Notes:
        Vacuous reports (total_predictions=0) render a chart with no
        bars and a subtitle explaining the lack of data. The axes and
        reference line still appear so the chart shape is recognizable.
    """
    if width < 100 or height < 100:
        raise ValueError(
            f"width and height must each be at least 100, got "
            f"width={width}, height={height}"
        )

    plot_x0 = _INSET_LEFT
    plot_y0 = _INSET_TOP
    plot_x1 = width - _INSET_RIGHT
    plot_y1 = height - _INSET_BOTTOM
    plot_w = plot_x1 - plot_x0
    plot_h = plot_y1 - plot_y0

    if plot_w <= 0 or plot_h <= 0:
        raise ValueError(
            f"width/height too small for chart insets; got plot area "
            f"{plot_w}x{plot_h}"
        )

    pieces: list[str] = []
    pieces.append(
        f'<svg width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Reliability diagram">'
    )

    # Title and subtitle
    effective_title = title or f"Reliability Diagram ({report.binning_method})"
    pieces.append(
        f'<text x="{width // 2}" y="22" text-anchor="middle" '
        f'font-family="sans-serif" font-size="14" font-weight="bold" '
        f'fill="{_TEXT_FILL}">{_xml_escape(effective_title)}</text>'
    )
    subtitle = _format_subtitle(report)
    pieces.append(
        f'<text x="{width // 2}" y="40" text-anchor="middle" '
        f'font-family="sans-serif" font-size="11" '
        f'fill="{_SUBTITLE_FILL}">{_xml_escape(subtitle)}</text>'
    )

    # Gridlines (drawn before axes so axes overlay them)
    for value in _GRIDLINES:
        # Vertical gridline at x=value
        gx = plot_x0 + value * plot_w
        pieces.append(
            f'<line x1="{gx:.2f}" y1="{plot_y0}" '
            f'x2="{gx:.2f}" y2="{plot_y1}" '
            f'stroke="{_GRID_STROKE}" stroke-width="1" />'
        )
        # Horizontal gridline at y=value
        gy = plot_y1 - value * plot_h
        pieces.append(
            f'<line x1="{plot_x0}" y1="{gy:.2f}" '
            f'x2="{plot_x1}" y2="{gy:.2f}" '
            f'stroke="{_GRID_STROKE}" stroke-width="1" />'
        )

    # Axes
    pieces.append(
        f'<line x1="{plot_x0}" y1="{plot_y1}" '
        f'x2="{plot_x1}" y2="{plot_y1}" '
        f'stroke="{_AXIS_STROKE}" stroke-width="1.5" />'
    )
    pieces.append(
        f'<line x1="{plot_x0}" y1="{plot_y0}" '
        f'x2="{plot_x0}" y2="{plot_y1}" '
        f'stroke="{_AXIS_STROKE}" stroke-width="1.5" />'
    )

    # Diagonal reference line (perfect calibration: y = x)
    pieces.append(
        f'<line x1="{plot_x0}" y1="{plot_y1}" '
        f'x2="{plot_x1}" y2="{plot_y0}" '
        f'stroke="{_REFERENCE_STROKE}" stroke-width="1" '
        f'stroke-dasharray="4,3" />'
    )

    # Per-bin bars (non-empty only)
    for b in report.bins:
        if b.count == 0:
            continue
        # b.lower_bound, b.upper_bound, b.accuracy are guaranteed non-None
        # when count > 0.
        bar_x_left = plot_x0 + b.lower_bound * plot_w
        bar_x_right = plot_x0 + b.upper_bound * plot_w
        bar_width = max(bar_x_right - bar_x_left, 1.0)  # minimum 1px to be visible
        # accuracy is in [0, 1]; bar height proportional to plot_h
        accuracy = b.accuracy if b.accuracy is not None else 0.0
        bar_y_top = plot_y1 - accuracy * plot_h
        bar_height = plot_y1 - bar_y_top
        tooltip = (
            f"bin: [{b.lower_bound:.3f}, {b.upper_bound:.3f}] | "
            f"count: {b.count} | "
            f"mean_confidence: {b.mean_confidence:.3f} | "
            f"accuracy: {accuracy:.3f}"
        )
        pieces.append(
            f'<rect x="{bar_x_left:.2f}" y="{bar_y_top:.2f}" '
            f'width="{bar_width:.2f}" height="{bar_height:.2f}" '
            f'fill="{_BAR_FILL}" stroke="{_BAR_STROKE}" '
            f'stroke-width="0.5" fill-opacity="0.8">'
            f'<title>{_xml_escape(tooltip)}</title>'
            f'</rect>'
        )

    # Tick labels on the axes
    for value in _GRIDLINES:
        tx = plot_x0 + value * plot_w
        ty = plot_y1 + 16
        pieces.append(
            f'<text x="{tx:.2f}" y="{ty}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="10" '
            f'fill="{_TEXT_FILL}">{value:.1f}</text>'
        )
        lx = plot_x0 - 8
        ly = plot_y1 - value * plot_h + 4
        pieces.append(
            f'<text x="{lx}" y="{ly:.2f}" text-anchor="end" '
            f'font-family="sans-serif" font-size="10" '
            f'fill="{_TEXT_FILL}">{value:.1f}</text>'
        )

    # Axis labels
    pieces.append(
        f'<text x="{plot_x0 + plot_w // 2}" y="{height - 18}" '
        f'text-anchor="middle" font-family="sans-serif" font-size="12" '
        f'fill="{_TEXT_FILL}">Predicted confidence</text>'
    )
    # Y-axis label is rotated 90 degrees counterclockwise.
    label_x = 22
    label_y = plot_y0 + plot_h // 2
    pieces.append(
        f'<text x="{label_x}" y="{label_y}" '
        f'transform="rotate(-90, {label_x}, {label_y})" '
        f'text-anchor="middle" font-family="sans-serif" font-size="12" '
        f'fill="{_TEXT_FILL}">Empirical accuracy</text>'
    )

    # Reference-line legend annotation (small text along the diagonal)
    legend_x = plot_x0 + plot_w - 4
    legend_y = plot_y0 + 12
    pieces.append(
        f'<text x="{legend_x}" y="{legend_y}" text-anchor="end" '
        f'font-family="sans-serif" font-size="10" '
        f'fill="{_SUBTITLE_FILL}">perfect calibration (y=x)</text>'
    )

    pieces.append('</svg>')
    return "".join(pieces)


# -- private helpers -------------------------------------------------------


def _format_subtitle(report: CalibrationReport) -> str:
    """Build the subtitle line with key metrics.

    Vacuous reports (total_predictions=0) get a "no data" subtitle.
    """
    if report.total_predictions == 0:
        return f"No predictions (dimension: {report.dimension})"
    return (
        f"ECE: {report.expected_calibration_error:.3f}"
        f" | MCE: {report.maximum_calibration_error:.3f}"
        f" | Brier: {report.brier_score:.3f}"
        f" | N={report.total_predictions}"
        f" | dimension: {report.dimension}"
    )


def _xml_escape(text: str) -> str:
    """Escape a string for inclusion as XML text content.

    Pure stdlib (no html.escape import to keep the module focused).
    Escapes the five XML special characters; sufficient for the
    bounded strings this module emits (titles, tooltips, labels).
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
