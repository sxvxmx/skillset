"""Spacing: line leading, paragraph rhythm, column gutters, frame padding."""

from __future__ import annotations

import statistics

from ..model import Finding, Line, Severity

# A new bullet/paragraph begins when the gap exceeds this multiple of the
# tightest leading observed inside the same text frame.
PARA_BREAK_RATIO = 1.35


def para_breaks(tb) -> list[tuple[Line, Line, float]]:
    """(prev, next, gap) for every paragraph boundary inside a text frame."""
    return para_breaks_in(tb.lines, tb.dominant_size or 12.0)


def para_breaks_in(lines: list[Line], size: float) -> list[tuple[Line, Line, float]]:
    """Same, but over an already-materialised line list.

    `TextBox.lines` rebuilds its Line objects on every access, so comparing them
    by identity across two calls silently fails. Materialise once, pass it in.
    """
    if len(lines) < 2:
        return []
    out = []
    for a, b in zip(lines, lines[1:]):
        pitch = b.rect.y0 - a.rect.y0
        if pitch <= 0:
            continue
        gap = b.rect.y0 - a.rect.y1
        if gap > size * 0.3 and pitch > _min_pitch(lines, size) * PARA_BREAK_RATIO:
            out.append((a, b, gap))
    return out


def _min_pitch(lines: list[Line], size: float) -> float:
    pitches = [
        b.rect.y0 - a.rect.y0
        for a, b in zip(lines, lines[1:])
        if 0 < b.rect.y0 - a.rect.y0 < size * 1.8
    ]
    return min(pitches) if pitches else size * 1.2


def para_items(tb) -> int:
    """How many bullets/paragraphs a frame actually contains.

    Wrapped lines carry no paragraph gap, so they belong to the item above
    them. A frame is one item, plus one more for every gap that opens a new
    one. (In these exports each bullet is usually its own text frame, so this
    also means "count the frames".)
    """
    return 1 + len(para_breaks(tb)) if tb.lines else 0


def check_line_spacing(deck, spec) -> list[Finding]:
    lo, hi = spec["spacing"]["line_height_ratio"]
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            if len(tb.lines) < 2:
                continue
            size = tb.dominant_size
            if size <= 0:
                continue
            lines = tb.lines
            breaks = {(id(a), id(b)) for a, b, _ in para_breaks_in(lines, size)}
            for a, b in zip(lines, lines[1:]):
                if (id(a), id(b)) in breaks:
                    continue
                pitch = b.rect.y0 - a.rect.y0
                if pitch <= 0:
                    continue
                # compare against the type actually on these two lines: a 30pt
                # display number above a 10pt caption is not tight leading
                ref = max(a.size, b.size, 1.0)
                ratio = pitch / ref
                if lo - 0.06 <= ratio <= hi + 0.06:
                    continue
                # A large gap with a loose pitch is paragraph spacing, not
                # leading - `para.gap` reports that. Only call it leading when
                # the lines are actually sitting on top of each other.
                if b.rect.y0 - a.rect.y1 >= ref * 0.25:
                    continue
                if True:
                    out.append(
                        Finding(
                            "leading",
                            Severity.WARN,
                            f"line pitch {pitch:.1f}pt = {ratio:.2f}x{size:.0f}pt "
                            f"(spec {lo}-{hi}x): {a.text[:28]!r} -> {b.text[:28]!r}",
                            s.number,
                            str(tb.rect),
                            f"set line spacing to {statistics.mean([lo, hi]):.2f}",
                        )
                    )
    return out


def check_paragraph_gaps(deck, spec) -> list[Finding]:
    """Gaps between bullets should be uniform within a list."""
    want = spec["spacing"]["paragraph_gap"]
    tol = max(2.5, want * 0.45)
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            if len(tb.lines) < 3:
                continue
            size = tb.dominant_size
            brk = para_breaks_in(tb.lines, size)
            if len(brk) < 2:
                continue
            vals = [g for _, _, g in brk]
            med = statistics.median(vals)
            if med > size * 1.6:
                out.append(
                    Finding(
                        "para.gap",
                        Severity.WARN,
                        f"paragraph gap {med:.1f}pt is {med / size:.1f}x the font size "
                        f"(spec ~{want}pt)",
                        s.number,
                        str(tb.rect),
                        f"set space-after = {want}pt",
                    )
                )
            for a, b, g in brk:
                if abs(g - med) > tol:
                    out.append(
                        Finding(
                            "para.gap_uniform",
                            Severity.INFO,
                            f"gap {g:.1f}pt differs from the list median {med:.1f}pt "
                            f"({a.text[:20]!r} -> {b.text[:20]!r})",
                            s.number,
                            str(tb.rect),
                            "make every inter-bullet gap identical",
                        )
                    )
    return out


def check_column_gutter(deck, spec) -> list[Finding]:
    """Measure the gutter between the two content columns, per slide and per deck.

    The measurement is between the *column extents*, not between arbitrary
    neighbouring boxes - a short heading in the left column and a long
    paragraph in the right one are not a gutter.
    """
    lo, hi = spec["spacing"]["column_gutter"]
    out = []
    measured: list[tuple[int, float]] = []
    for s in deck.slides:
        # classify by geometry: a framed diagram is still part of its column,
        # and the title spans both halves so it is not a gutter participant
        mid = s.rect.cx
        content = [
            e
            for e in list(s.text_boxes) + list(s.images)
            if not getattr(e, "is_title", False) and e.rect.width < s.rect.width * 0.8
        ]
        left = [e for e in content if e.rect.cx < mid]
        right = [e for e in content if e.rect.cx >= mid]
        if not left or not right:
            continue
        # only a text column beside a text column has a gutter that means
        # something; next to an image it is just where the image starts
        text_vs_text = not any(hasattr(e, "digest") for e in left + right)
        if not text_vs_text:
            continue
        gutter = min(e.rect.x0 for e in right) - max(e.rect.x1 for e in left)
        if gutter <= 0:
            continue
        if text_vs_text:
            measured.append((s.number, gutter))
        # a text column beside an image column is a different archetype: the
        # gutter there is a design choice, not a spacing error
        if text_vs_text and (gutter < lo - 1 or gutter > hi + 1):
            out.append(
                Finding(
                    "gutter",
                    Severity.INFO,
                    f"{gutter:.0f}pt gutter between the columns (spec {lo:.0f}-{hi:.0f}pt)",
                    s.number,
                    f"x {max(e.rect.x1 for e in left):.0f}->"
                    f"{min(e.rect.x0 for e in right):.0f}",
                )
            )
    tol = spec["spacing"].get("gutter_consistency_tolerance", 25.0)
    if len(measured) >= 3:
        vals = [g for _, g in measured]
        spread = max(vals) - min(vals)
        if spread > tol:
            pages = ", ".join(f"p{n}:{g:.0f}" for n, g in measured)
            out.append(
                Finding(
                    "gutter.consistency",
                    Severity.INFO,
                    f"column gutter varies by {spread:.0f}pt across the deck "
                    f"({min(vals):.0f}-{max(vals):.0f}pt) - {pages}",
                    fix="one gutter value for the whole deck",
                )
            )
    return out


def check_frame_padding(deck, spec) -> list[Finding]:
    lo, hi = spec["spacing"]["padding_in_frame"]
    out = []
    for s in deck.slides:
        frames = [sh for sh in s.shapes if sh.region == "frame" and sh.is_frame_candidate]
        for fr in frames:
            r = fr.rect
            # only text frames have padding; a frame hugging its image exactly
            # is a picture placeholder border
            inside = [
                tb.rect
                for tb in s.text_boxes
                if r.expand(0.5).contains(tb.rect) and tb.rect != r
            ]
            if not inside:
                continue
            pads = [
                min(e.x0 for e in inside) - r.x0,
                r.x1 - max(e.x1 for e in inside),
                min(e.y0 for e in inside) - r.y0,
                r.y1 - max(e.y1 for e in inside),
            ]
            left = pads[0]
            if left < lo - 1.5 or left > hi + 6:
                out.append(
                    Finding(
                        "frame.padding",
                        Severity.INFO,
                        f"frame left padding {left:.1f}pt (spec {lo:.0f}-{hi:.0f}pt); "
                        f"pads L{pads[0]:.0f} R{pads[1]:.0f} T{pads[2]:.0f} B{pads[3]:.0f}",
                        s.number,
                        str(r),
                        "give every frame identical padding",
                    )
                )
    return out


def check_vertical_rhythm(deck, spec) -> list[Finding]:
    """Side-by-side blocks should start on the same baseline."""
    out = []
    for s in deck.slides:
        blocks = [tb for tb in s.body_boxes if tb.rect.height > 20]
        for i, a in enumerate(blocks):
            for b in blocks[i + 1 :]:
                if a.region == b.region:
                    continue
                # only compare blocks that actually sit alongside each other:
                # a paired column overlaps horizontally but spans just its own
                # side, whereas a full-width block merely crosses both columns
                vx = min(a.rect.x1, b.rect.x1) - max(a.rect.x0, b.rect.x0)
                if vx <= 0:
                    continue
                if vx > 0.6 * min(a.rect.width, b.rect.width):
                    continue
                # a block spanning the content width is a paragraph, not a
                # column: it will always "misalign" against something
                if a.rect.width > s.rect.width * 0.8 or b.rect.width > s.rect.width * 0.8:
                    continue
                # stacked, not side by side
                if min(a.rect.y1, b.rect.y1) - max(a.rect.y0, b.rect.y0) > 0:
                    continue
                dy = abs(a.rect.y0 - b.rect.y0)
                if dy > 4:
                    out.append(
                        Finding(
                            "vertical.alignment",
                            Severity.WARN,
                            f"side-by-side blocks start {dy:.1f}pt apart: "
                            f"{a.text[:20]!r} y={a.rect.y0:.0f} vs {b.text[:20]!r} "
                            f"y={b.rect.y0:.0f}",
                            s.number,
                            f"y {a.rect.y0:.0f} vs {b.rect.y0:.0f}",
                            "top-align columns to the same y",
                        )
                    )
    return out
