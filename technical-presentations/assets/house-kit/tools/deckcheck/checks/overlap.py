"""Overlap: the single most common real-world slide defect.

Covers text-on-text, text-on-image, and content spilling across a frame edge.
Table cells are excluded (they legitimately sit flush) and text *inside* a
dashed frame is fine - only *crossing* the frame is not.
"""

from __future__ import annotations

from ..model import Finding, Severity

# Ignore slivers: PDF glyph boxes legitimately kiss by a fraction of a point.
MIN_OVERLAP_PT2 = 1.0
# ...and ignore overlaps that are a whole-line artefact of justified text.
MIN_OVERLAP_FRAC = 0.004


def _pairwise(items):
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            yield a, b


def check_text_overlap(deck, spec) -> list[Finding]:
    out = []
    for s in deck.slides:
        boxes = [tb for tb in s.text_boxes if tb.text]
        for a, b in _pairwise(boxes):
            if a.region == "table" and b.region == "table":
                continue
            area = a.rect.overlap_area(b.rect)
            if area < MIN_OVERLAP_PT2:
                continue
            frac = area / min(a.rect.area, b.rect.area)
            if frac < MIN_OVERLAP_FRAC:
                continue
            # vertical neighbours in the same column: leading collision, not overlap
            if a.region == b.region and _stacked(a, b):
                continue
            sev = Severity.ERROR if frac > 0.02 else Severity.WARN
            out.append(
                Finding(
                    "overlap.text",
                    sev,
                    f"{a.text[:24]!r} overlaps {b.text[:24]!r} by {area:.1f}pt2 "
                    f"({100 * frac:.0f}% of the smaller box)",
                    s.number,
                    f"{a.rect} / {b.rect}",
                    "move one block, or shorten the text so the frames stop colliding",
                )
            )
    return out


def _stacked(a, b) -> bool:
    """True when a and b are vertically adjacent in the same column."""
    (top, bot) = (a, b) if a.rect.y0 <= b.rect.y0 else (b, a)
    gap = bot.rect.y0 - top.rect.y1
    if gap > 0:
        return False
    vx = min(a.rect.x1, b.rect.x1) - max(a.rect.x0, b.rect.x0)
    return vx > min(a.rect.width, b.rect.width) * 0.3


def check_text_image_overlap(deck, spec) -> list[Finding]:
    out = []
    for s in deck.slides:
        texts = [tb for tb in s.text_boxes if tb.text]
        for tb in texts:
            for im in s.images:
                if im.region == "table" or tb.region == "table":
                    continue
                area = tb.rect.overlap_area(im.rect)
                if area < 4.0:
                    continue
                frac = area / max(1e-9, tb.rect.area)
                if frac < 0.01:
                    continue
                out.append(
                    Finding(
                        "overlap.text_image",
                        Severity.ERROR,
                        f"text {tb.text[:28]!r} sits {100 * frac:.0f}% on top of an image",
                        s.number,
                        f"{tb.rect} / {im.rect}",
                        "give text and image their own column",
                    )
                )
    return out


def check_frame_crossing(deck, spec) -> list[Finding]:
    """Content must sit inside a frame, not straddle its border."""
    out = []
    for s in deck.slides:
        frames = [sh for sh in s.shapes if sh.region == "frame" and sh.is_frame_candidate]
        for fr in frames:
            r = fr.rect
            for e in [tb for tb in s.text_boxes if tb.text] + list(s.images):
                if e.rect == r or r.expand(0.5).contains(e.rect):
                    continue
                area = e.rect.overlap_area(r)
                if area < 4.0 or area / e.rect.area > 0.5:
                    continue  # a neighbour, not a spill
                out.append(
                    Finding(
                        "overlap.frame_edge",
                        Severity.WARN,
                        f"content crosses the frame border: {e.rect} vs frame {r}",
                        s.number,
                        str(r),
                        "text inside a dashed frame must clear the border on all sides",
                    )
                )
    return out


def check_image_overlap(deck, spec) -> list[Finding]:
    out = []
    for s in deck.slides:
        for a, b in _pairwise(s.images):
            area = a.rect.overlap_area(b.rect)
            if area < 4.0:
                continue
            if a.digest and a.digest == b.digest and area / min(a.rect.area, b.rect.area) > 0.9:
                continue  # same picture stacked; harmless
            out.append(
                Finding(
                    "overlap.image",
                    Severity.ERROR,
                    f"two images overlap by {area:.0f}pt2",
                    s.number,
                    f"{a.rect} / {b.rect}",
                    "stack images on a grid, do not overlap them",
                )
            )
    return out


def check_table_cell_overlap(deck, spec) -> list[Finding]:
    """Inside a table only real collisions matter, not flush neighbours."""
    out = []
    for s in deck.slides:
        cells = [tb for tb in s.text_boxes if tb.region == "table" and tb.text]
        for a, b in _pairwise(cells):
            area = a.rect.overlap_area(b.rect)
            if area < 2.0:
                continue
            if area / min(a.rect.area, b.rect.area) < 0.08:
                continue
            out.append(
                Finding(
                    "overlap.table_cell",
                    Severity.WARN,
                    f"table cells overlap by {area:.1f}pt2: "
                    f"{a.text[:18]!r} / {b.text[:18]!r}",
                    s.number,
                    f"{a.rect} / {b.rect}",
                    "a cell's text must not run into its neighbour",
                )
            )
    return out
