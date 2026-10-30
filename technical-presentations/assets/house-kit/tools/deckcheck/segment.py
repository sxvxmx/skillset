"""Structural segmentation: work out what each element *is* before judging it.

Checks like "text overlaps" are meaningless inside a table (cells sit flush) or
inside a dashed frame (text is meant to be inside). So before any check runs we
group a slide's elements into regions:

    table  - bounded by a grid of >=3 hairlines in 2+ axes
    frame  - a closed stroked rectangle with nothing but text/images inside
    colN   - a vertical band of the content area (text column / image column)
    free   - everything else
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Rect, Shape, Slide


@dataclass
class Region:
    kind: str  # "table" | "frame" | "col" | "free"
    rect: Rect
    members: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __contains__(self, other: Rect) -> bool:
        return self.rect.expand(1.5).contains(other)


def _is_hairline(sh: Shape) -> bool:
    return sh.visible and sh.stroke is not None and 0 < sh.width <= 1.5


def detect_tables(slide: Slide) -> list[Region]:
    """Group near-orthogonal hairlines into table regions."""
    hlines, vlines = [], []
    for sh in slide.shapes:
        r = sh.rect
        if not _is_hairline(sh):
            continue
        if r.height <= 1.5 and r.width > 20:
            hlines.append(r)
        elif r.width <= 1.5 and r.height > 20:
            vlines.append(r)
    if len(hlines) < 2 or len(vlines) < 2:
        return []

    # Group verticals by *x*, not by y-extent. A table drawn as one stroked
    # rectangle per row emits verticals at the same x with different heights,
    # and the old y-matching rule saw each row as its own unrelated line.
    by_x: dict[int, list[Rect]] = {}
    for v in vlines:
        key = int(round(v.x0 / 3.0))
        by_x.setdefault(key, []).append(v)
    if len(by_x) < 2 or len(hlines) < 2:
        return []

    # The region spans every column position, not one adjacent pair: a 4-column
    # table drawn with hairline verticals must be recognised as 4 columns, or
    # its outer columns are judged as stray off-margin text.
    col_x = [min(v.x0 for v in by_x[k]) for k in sorted(by_x)]
    col_r = [max(v.x1 for v in by_x[k]) for k in sorted(by_x)]
    x0, x1 = col_x[0], col_r[-1]
    band = [h for h in hlines if h.x0 <= x0 + 6 and h.x1 >= x1 - 6]
    if len(band) < 2:
        return []
    verts = [v for k in sorted(by_x) for v in by_x[k]]
    y0 = min(min(h.y0 for h in band), min(v.y0 for v in verts))
    y1 = max(max(h.y1 for h in band), max(v.y1 for v in verts))
    return [Region(kind="table", rect=Rect(x0, y0, x1, y1),
                   meta={"rules": len(band), "cols": len(col_x)})]


def detect_row_bands(slide: Slide) -> list[Region]:
    """A table drawn as one bordered rectangle per row.

    Common when a deck generator emits a box per row rather than a grid. The
    boxes share an x-extent and stack vertically - that is a table, and its
    contents are cells, not a bullet list.
    """
    boxes: dict[tuple[int, int], list[Rect]] = {}
    for sh in slide.shapes:
        r = sh.rect
        if not sh.visible or sh.stroke is None:
            continue
        if r.width < 60 or r.height < 10 or r.width > slide.rect.width * 0.98:
            continue
        key = (int(round(r.x0 / 4.0)), int(round(r.x1 / 4.0)))
        boxes.setdefault(key, []).append(r)
    out: list[Region] = []
    for rects in boxes.values():
        rects.sort(key=lambda r: r.y0)
        # keep a run of boxes that touch or nearly touch
        run: list[Rect] = [rects[0]]
        for r in rects[1:]:
            if r.y0 - max(x.y1 for x in run) <= 4.0:
                run.append(r)
            else:
                if len(run) >= 3:
                    out.append(_band_region(run))
                run = [r]
        if len(run) >= 3:
            out.append(_band_region(run))
    return out


def _band_region(run: list[Rect]) -> Region:
    return Region(
        kind="table",
        rect=Rect(
            min(r.x0 for r in run), min(r.y0 for r in run),
            max(r.x1 for r in run), max(r.y1 for r in run),
        ),
        meta={"rows": len(run), "cols": 0, "shape": "row-bands"},
    )


def detect_frames(slide: Slide, inside: list[Region] | None = None) -> list[Region]:
    """Containers drawn as a stroked rectangle.

    `inside` are regions already claimed as tables: a table's own row borders
    sit inside the table, and treating each one as a frame makes the linter
    report every cell as "content crossing a frame edge".
    """
    inside = inside or []
    frames: list[Region] = []
    for sh in slide.shapes:
        if not sh.is_frame_candidate:
            continue
        if any(r.kind == "table" and r.rect.expand(1.0).contains(sh.rect) for r in inside):
            continue
        r = sh.rect
        if r.width < 60 or r.height < 45:
            continue
        # a frame should hug its contents: allow generous but bounded slack
        inner = [tb for tb in slide.text_boxes if r.expand(6).contains(tb.rect)]
        inner += [im for im in slide.images if r.expand(6).contains(im.rect)]
        if not inner:
            continue
        frames.append(
            Region(
                kind="frame",
                rect=r,
                meta={"stroke": sh.stroke, "width": sh.width, "dash": sh.dash, "shape": sh},
            )
        )
    return frames


def detect_columns(slide: Slide, spec) -> list[Region]:
    """Vertical bands derived from the guideline's column split."""
    g = spec.get("grid", {})
    split = g.get("column_split_x")
    if not split:
        return []
    canvas = slide.rect
    scale = canvas.width / (spec.get("canvas", {}).get("width") or canvas.width)
    x = split * scale
    top = g.get("content_top", 0) * scale
    bottom = (g.get("content_bottom") or canvas.height) * scale
    return [
        Region(kind="col", rect=Rect(canvas.x0, top, x, bottom), meta={"index": 0}),
        Region(kind="col", rect=Rect(x, top, canvas.x1, bottom), meta={"index": 1}),
    ]


def segment(slide: Slide, spec: dict) -> list[Region]:
    regions: list[Region] = []
    regions += detect_tables(slide)
    regions += detect_row_bands(slide)
    regions += detect_frames(slide, inside=regions)
    regions += detect_columns(slide, spec)

    cols = [r for r in regions if r.kind == "col"]
    for tb in slide.text_boxes:
        for r in regions:
            if r.kind in ("table", "frame") and tb.rect in r:
                tb.region = r.kind
                r.members.append(tb)
                break
        else:
            for c in cols:
                if c.rect.x0 <= tb.rect.cx <= c.rect.x1:
                    tb.region = f"col{c.meta['index']}"
                    c.members.append(tb)
                    break
    for im in slide.images:
        for r in regions:
            if r.kind in ("table", "frame") and im.rect in r:
                im.region = r.kind
                r.members.append(im)
                break
        else:
            for c in cols:
                if c.rect.x0 <= im.rect.cx <= c.rect.x1:
                    im.region = f"col{c.meta['index']}"
                    c.members.append(im)
                    break
    for sh in slide.shapes:
        for r in regions:
            if r.kind == "frame" and sh is r.meta.get("shape"):
                sh.region = "frame"
    return regions


def segment_deck(deck, spec: dict) -> None:
    for slide in deck.slides:
        segment(slide, spec)
