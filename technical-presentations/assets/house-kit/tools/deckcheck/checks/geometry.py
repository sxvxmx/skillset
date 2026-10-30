"""Geometry: does anything sit off-canvas, off-grid, or in the wrong band?"""

from __future__ import annotations

import statistics

from ..model import Finding, Rect, Severity


def check_offcanvas(deck, spec) -> list[Finding]:
    g = spec["grid"]
    out = []
    ml, mr = g["margin_left"], g["margin_right"]
    mt, mb = g["margin_top"], g["margin_bottom"]
    for s in deck.slides:
        c = s.rect
        for tb in s.text_boxes + s.images:
            r = tb.rect
            label = "text" if hasattr(tb, "runs") else "image"
            # a deliberate bleed touches the canvas edge on purpose
            bleed = (
                r.x0 <= c.x0 + 1
                or r.y0 <= c.y0 + 1
                or r.x1 >= c.x1 - 1
                or r.y1 >= c.y1 - 1
            )
            # table cells and framed content are positioned by their container
            in_container = getattr(tb, "region", "free") in ("table", "frame")
            if r.x0 < c.x0 - 0.5 or r.y0 < c.y0 - 0.5 or r.x1 > c.x1 + 0.5 or r.y1 > c.y1 + 0.5:
                out.append(
                    Finding(
                        "offcanvas",
                        Severity.ERROR,
                        f"{label} extends past the slide edge: {r}",
                        s.number,
                        str(r),
                        "pull the element back inside the canvas",
                    )
                )
                continue
            if bleed or in_container:
                continue
            if r.x0 < c.x0 + ml - 2 and r.width < c.width * 0.95:
                out.append(
                    Finding(
                        "margin.left",
                        Severity.WARN,
                        f"{label} starts at x={r.x0:.1f}, inside the {ml:.0f}pt left margin: {r}",
                        s.number,
                        str(r),
                        f"align to x={c.x0 + ml:.1f} or to a column edge",
                    )
                )
            if r.x1 > c.x1 - mr + 2 and r.width < c.width * 0.95:
                out.append(
                    Finding(
                        "margin.right",
                        Severity.WARN,
                        f"{label} ends at x={r.x1:.1f}, inside the {mr:.0f}pt right margin: {r}",
                        s.number,
                        str(r),
                        f"pull back to x={c.x1 - mr:.1f}",
                    )
                )
            if r.y1 > c.y1 - mb + 2 and r.height < c.height * 0.95:
                out.append(
                    Finding(
                        "margin.bottom",
                        Severity.WARN,
                        f"{label} ends at y={r.y1:.1f}, inside the {mb:.0f}pt bottom margin: {r}",
                        s.number,
                        str(r),
                        "shorten the text or split the slide",
                    )
                )
    return out


def check_content_band(deck, spec) -> list[Finding]:
    g = spec["grid"]
    top, bottom = g["content_top"], g["content_bottom"]
    top_tol = g.get("content_top_tolerance", 4.0)
    out = []
    for s in deck.slides:
        title = s.heading
        if title is not None and title.rect.y1 < top - 1:
            first_body = min((tb.rect.y0 for tb in s.body_boxes), default=bottom)
            if first_body < top - top_tol:
                out.append(
                    Finding(
                        "band.content_top",
                        Severity.WARN,
                        f"body text starts at y={first_body:.1f}, above the content top y={top}",
                        s.number,
                        f"y={first_body:.1f}",
                        f"start body content at y={top}",
                    )
                )
        for tb in s.body_boxes:
            if tb.rect.y1 > bottom + 3:
                out.append(
                    Finding(
                        "band.content_bottom",
                        Severity.ERROR,
                        f"text overflows the content band (bottom y={tb.rect.y1:.1f} > "
                        f"{bottom}): {tb.text[:32]!r}",
                        s.number,
                        str(tb.rect),
                        "cut words - the band is 68% of slide height by design",
                    )
                )
    return out


def check_title_lock(deck, spec) -> list[Finding]:
    """Every content slide's title must land in the same place."""
    g = spec["grid"]
    if not spec["structure"].get("title_position_locked", True):
        return []
    ref_x, ref_y = g["margin_left"], g.get("title_baseline_y", 46.0)
    tol = g.get("snap_tolerance", 3.0)
    out = []
    seen: list[tuple[int, Rect]] = []
    for s in deck.slides[1:]:
        t = s.heading
        if t is None:
            if spec["structure"].get("require_title", True) and s.words:
                out.append(
                    Finding(
                        "title.missing",
                        Severity.WARN,
                        "content slide has no title",
                        s.number,
                        fix=f"add a {spec['fonts']['roles']['title']['size']:.0f}pt title at "
                        f"({ref_x}, {ref_y})",
                    )
                )
            continue
        seen.append((s.number, t.rect))
        if abs(t.rect.x0 - ref_x) > tol:
            out.append(
                Finding(
                    "title.x",
                    Severity.WARN,
                    f"title x={t.rect.x0:.1f}, expected {ref_x} (off by {t.rect.x0 - ref_x:+.1f})",
                    s.number,
                    str(t.rect),
                    f"set title left = {ref_x}",
                )
            )
        if abs(t.rect.y0 - ref_y) > tol + 4:
            out.append(
                Finding(
                    "title.y",
                    Severity.WARN,
                    f"title y={t.rect.y0:.1f}, expected {ref_y} (off by {t.rect.y0 - ref_y:+.1f})",
                    s.number,
                    str(t.rect),
                    f"set title top = {ref_y}",
                )
            )
    if len(seen) >= 3:
        xs = [r.x0 for _, r in seen]
        ys = [r.y0 for _, r in seen]
        if max(xs) - min(xs) > tol:
            out.append(
                Finding(
                    "title.consistency",
                    Severity.WARN,
                    f"title x varies by {max(xs) - min(xs):.1f}pt across {len(xs)} slides "
                    f"(spread {min(xs):.1f}-{max(xs):.1f})",
                    fix="select the title placeholder once; do not nudge it per slide",
                )
            )
        if max(ys) - min(ys) > tol + 4:
            out.append(
                Finding(
                    "title.consistency",
                    Severity.WARN,
                    f"title y varies by {max(ys) - min(ys):.1f}pt across {len(ys)} slides",
                    fix="keep the title band fixed",
                )
            )
    return out


def check_alignment(deck, spec) -> list[Finding]:
    """Left edges should snap to a small set of x positions (column edges)."""
    tol = spec["grid"].get("snap_tolerance", 3.0)
    out = []
    for s in deck.slides:
        elements = [
            e
            for e in s.text_boxes + s.images
            if e.rect.width > 12
            and not getattr(e, "is_title", False)
            and getattr(e, "region", "free") not in ("table", "frame")
        ]
        if len(elements) < 3:
            continue  # a single column has nothing to snap to
        # only interesting when the slide really has more than one column
        if len({e.region for e in elements}) < 2:
            continue
        edges = sorted({round(e.rect.x0, 1) for e in elements})
        if len(edges) >= 3:
            steps = [b - a for a, b in zip(edges, edges[1:])]
            if max(steps) - min(steps) <= tol * 1.5:
                continue  # a regular column division
        edges = [round(e.rect.x0, 1) for e in elements]
        snapped = [e for e in edges if not _near_any(e, edges, tol, skip_self=True)]
        for e in sorted(set(snapped)):
            out.append(
                Finding(
                    "grid.snap",
                    Severity.INFO,
                    f"left edge x={e} matches no other element on this slide",
                    s.number,
                    f"x={e}",
                    "snap to a column edge to make the layout read as a grid",
                )
            )
    return out


def _near_any(value: float, pool: list[float], tol: float, skip_self: bool = False) -> bool:
    for other in pool:
        if skip_self and other == value:
            continue
        if abs(other - value) <= tol:
            return True
    return False
