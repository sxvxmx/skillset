"""Symmetry: is the slide visually balanced, or does it lean?"""

from __future__ import annotations

from ..model import Finding, Severity

# Below this imbalance the eye will not notice.
BALANCE_TOL_PCT = 8.0
# Optical centring: a shape with a pointed/ascender profile reads as if it
# sits slightly above true centre, so nudge it down by this fraction of height.
OPTICAL_DROP = 0.02


def check_margin_balance(deck, spec) -> list[Finding]:
    """Left gap vs right gap for elements that are meant to be centred.

    A left-aligned title is *supposed* to hug the margin, so only wide or
    cover-slide elements are judged here.
    """
    out = []
    for s in deck.slides:
        is_cover = s.number == 1
        # a content-slide title is *meant* to hug the left margin
        cands: list = list(s.images)
        cover_align = spec["fonts"]["roles"]["cover_title"].get("align", "left")
        if is_cover and cover_align == "center" and s.heading is not None:
            cands.append(s.heading)
        for e in cands:
            r = e.rect
            # a deliberate bleed hugs the canvas edge
            if r.x0 <= s.rect.x0 + 1 or r.x1 >= s.rect.x1 - 1:
                continue
            # if the slide has other content on the opposite side, the element
            # sits in a column and its position is set by the grid, not by
            # centring
            mid = s.rect.cx
            partner = any(
                o is not e and ((o.rect.cx < mid) != (r.cx < mid))
                and o.rect.overlap_area(r) < 0.01
                for o in list(s.text_boxes) + list(s.images)
            )
            if partner:
                continue
            centred_by_design = is_cover or r.width > s.rect.width * 0.55
            if not centred_by_design:
                continue
            left, right = r.x0 - s.rect.x0, s.rect.x1 - r.x1
            if left + right <= 1:
                continue
            skew = abs(left - right)
            if skew > 4 and skew / (left + right) > 0.25:
                label = "title" if e is s.heading else "image"
                out.append(
                    Finding(
                        "symmetry.h",
                        Severity.WARN,
                        f"{label} is off-centre horizontally: {left:.1f}pt left vs "
                        f"{right:.1f}pt right",
                        s.number,
                        str(r),
                        "centre it on the canvas",
                    )
                )
    return out


def check_optical_centering(deck, spec) -> list[Finding]:
    """Vertically centred single-element slides (cover, section break)."""
    out = []
    for s in deck.slides:
        if len(s.text_boxes) + len(s.images) != 1:
            continue
        e = s.text_boxes[0] if s.text_boxes else s.images[0]
        r = e.rect
        if r.height > s.rect.height * 0.6:
            continue
        top, bottom = r.y0 - s.rect.y0, s.rect.y1 - r.y1
        if top + bottom <= 1:
            continue
        skew = abs(top - bottom)
        if skew > 3 and skew / (top + bottom) > 0.2:
            out.append(
                Finding(
                    "symmetry.v",
                    Severity.WARN,
                    f"single element sits {top:.1f}pt from top vs {bottom:.1f}pt from bottom",
                    s.number,
                    str(r),
                    "centre it, then drop it ~2% of height for optical alignment",
                )
            )
    return out


def check_weight_balance(deck, spec) -> list[Finding]:
    """Split slides: is ink distributed evenly left/right?"""
    out = []
    for s in deck.slides:
        c = s.rect
        mid = c.cx
        left = right = 0.0
        for e in list(s.text_boxes) + list(s.images):
            if e.rect.cx < mid:
                left += e.rect.area
            else:
                right += e.rect.area
        total = left + right
        if total < c.area * 0.04:
            continue
        # a genuine two-column slide has both sides substantially filled
        if min(left, right) < total * 0.18:
            continue
        skew = abs(left - right) / total * 100
        if skew > BALANCE_TOL_PCT + 8:
            out.append(
                Finding(
                    "symmetry.weight",
                    Severity.INFO,
                    f"visual weight is {skew:.0f}% lopsided (left {100 * left / total:.0f}% / "
                    f"right {100 * right / total:.0f}%)",
                    s.number,
                    fix="resize the image or rebalance the columns",
                )
            )
    return out


def check_column_symmetry(deck, spec) -> list[Finding]:
    """Equal-width columns with an equal outer margin."""
    out = []
    g = spec["grid"]
    for s in deck.slides:
        cols = {}
        for e in list(s.text_boxes) + list(s.images):
            if e.region.startswith("col"):
                cols.setdefault(e.region, []).append(e.rect)
        if len(cols) < 2:
            continue
        if any(e.region.startswith("col") and not hasattr(e, "lines") for e in s.images):
            continue  # a text column next to an image column is not a peer pair
        lefts = [r.x0 for rs in cols.values() for r in rs]
        rights = [r.x1 for rs in cols.values() for r in rs]
        if len(lefts) < 2 or len(rights) < 2:
            continue
        widths = []
        for rs in cols.values():
            widths.append(max(r.x1 for r in rs) - min(r.x0 for r in rs))
        if max(widths) - min(widths) > g.get("gutter", 30) * 1.5:
            out.append(
                Finding(
                    "symmetry.columns",
                    Severity.INFO,
                    f"column widths differ: {', '.join(f'{w:.0f}' for w in sorted(widths))}pt",
                    s.number,
                    fix="equal column widths read as deliberate; unequal ones read as accidental",
                )
            )
    return out


def check_centred_blocks(deck, spec) -> list[Finding]:
    """A block that looks centred should actually be centred."""
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            # only judge blocks that are actually centre-aligned; left-aligned
            # body text is never meant to be centred
            if tb.align != "center":
                continue
            left, right = tb.rect.x0 - s.rect.x0, s.rect.x1 - tb.rect.x1
            if abs(left - right) > 4:
                out.append(
                    Finding(
                        "symmetry.block",
                        Severity.INFO,
                        f"block is off-centre by {abs(left - right):.1f}pt "
                        f"(left {left:.0f} / right {right:.0f})",
                        s.number,
                        str(tb.rect),
                        "centre the text box on the canvas",
                    )
                )
    return out
