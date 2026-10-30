"""Turn a PDF or PPTX into the neutral `Deck` model.

The PDF path measures what the audience actually sees (glyph positions, baked
borders). The PPTX path reads the editable source. Both normalise to points.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .model import Deck, ImageBox, Rect, Shape, Slide, Span, TextBox

EMU_PER_PT = 12700

# Glyphs that are bullet markers, not content.
MARKERS = {"●", "•", "‣", "⁃", "◦", "▪", "▫", "·", "–", "—", "→", "-", "‒", "*"}
MARKER_RECOGNISED = {"●", "•", "‣", "⁃", "◦", "▪", "▫", "·", "–", "—", "→"}


def _hexc(c) -> str | None:
    if c is None:
        return None
    if isinstance(c, (int, float)):
        c = (c, c, c)
    if isinstance(c, str):
        return c.lower()
    if len(c) == 1:
        c = c * 3
    if len(c) != 3:
        return None
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in c)


_FONT_SUFFIXES = (
    "-BoldItalic",
    "-BoldOblique",
    "-SemiboldItalic",
    "-Bold",
    "-Semibold",
    "-Italic",
    "-Oblique",
    "-Regular",
    "-Light",
    "-Medium",
    "MT",
    "PS",
    "Std",
)


def _norm_family(name: str) -> str:
    """Strip PDF font suffixes: Arial-BoldMT -> Arial, HelveticaNeue-Bold -> HelveticaNeue."""
    base = name.split(",")[0].strip()
    changed = True
    while changed:
        changed = False
        for suffix in _FONT_SUFFIXES:
            if base.endswith(suffix) and len(base) > len(suffix):
                base = base[: -len(suffix)]
                changed = True
                break
    return base


def _dash_tuple(d) -> tuple[float, ...] | None:
    if not d:
        return None
    if isinstance(d, str):
        # PyMuPDF returns e.g. '[3 2.25] 0': the final number is phase,
        # not another dash length.
        match = re.search(r"\[([^\]]*)\]", d)
        d = match.group(1).split() if match else []
    try:
        vals = [round(float(v), 2) for v in d]
    except (TypeError, ValueError):
        return None
    if not vals or all(v == 0 for v in vals):
        return None
    return tuple(vals)


# --------------------------------------------------------------------- PDF
def load_pdf(path: str | Path) -> Deck:
    import pymupdf

    doc = pymupdf.open(str(path))
    slides: list[Slide] = []
    try:
        for pno in range(doc.page_count):
            page = doc[pno]
            pr = page.rect
            slide = Slide(number=pno + 1, rect=Rect(pr.x0, pr.y0, pr.x1, pr.y1))
            _pdf_background_probe(page, slide)
            probe = _pdf_probe(page)

            for blk in page.get_text("dict")["blocks"]:
                if blk.get("type") == 1:
                    continue  # images are collected via get_image_rects below
                tb = _pdf_text_box(blk)
                if tb is not None:
                    slide.text_boxes.append(tb)

            _pdf_images(page, doc, slide)

            for g in page.get_drawings():
                sh = _pdf_shape(g, probe)
                if sh is not None:
                    slide.shapes.append(sh)

            slide.text_boxes.sort(key=lambda b: (round(b.rect.y0), round(b.rect.x0)))
            slides.append(slide)
    finally:
        doc.close()
    return Deck(path=str(path), slides=slides, fmt="pdf")


def _pdf_background_probe(page, slide: Slide) -> None:
    """Mark full-page fills as the page background, not a shape."""
    for g in page.get_drawings():
        r = g["rect"]
        if (
            g.get("fill") is not None
            and r.width >= page.rect.width * 0.98
            and r.height >= page.rect.height * 0.98
        ):
            slide.shapes.append(
                Shape(
                    rect=Rect(r.x0, r.y0, r.x1, r.y1),
                    fill=_hexc(g["fill"]),
                    is_text_frame=True,
                    visible=False,
                )
            )
            return


def _pdf_text_box(blk: dict) -> TextBox | None:
    runs: list[Span] = []
    saw_marker = False
    for ln in blk.get("lines", []):
        for s in ln.get("spans", []):
            # PyMuPDF reports a discretionary break as U+00AD even when the line
            # is not split there. Keep the logical character, so a heading that
            # contains a hyphen still matches the manifest text.
            txt = s.get("text", "").replace("­", "-")
            if not txt.strip():
                continue
            if txt.strip() in MARKER_RECOGNISED and len(txt.strip()) <= 2:
                saw_marker = True
                continue
            x0, y0, x1, y1 = s["bbox"]
            font = s.get("font", "")
            flags = s.get("flags", 0)
            runs.append(
                Span(
                    text=txt,
                    font=_norm_family(font),
                    size=round(float(s.get("size", 0)), 2),
                    color="#" + f"{s.get('color', 0):06x}",
                    bold="Bold" in font or bool(flags & (1 << 4)),
                    italic="Italic" in font or "Oblique" in font or bool(flags & (1 << 0)),
                    rect=Rect(x0, y0, x1, y1),
                )
            )
    if not runs:
        return None
    bx = blk["bbox"]
    rect = Rect(bx[0], bx[1], bx[2], bx[3])
    top_size = max((r.size for r in runs), default=0)
    # A title is defined by *position*, not by size: a 30pt stat sitting in the
    # content band is not a slide title. Anything starting above the content
    # top (y=100) is in the title band.
    in_title_band = rect.y0 < 100.0
    is_title = top_size >= 20 and rect.height < 80 and in_title_band
    return TextBox(
        rect=rect,
        runs=runs,
        is_title=is_title,
        is_bullet_list=saw_marker,
        align="left",
    )


def _pdf_images(page, doc, slide: Slide) -> None:
    """Collect every placed image.

    `get_text("dict")` image blocks are clip-respecting (the visible extent),
    while `get_image_rects` reports the untransformed placement and can run off
    the page. So: take geometry from the blocks, and borrow native pixel size
    and content hash from the xref placements.
    """
    # (xref, raw placement, clipped-to-page placement, native px, digest)
    placements: list[tuple[int, Rect, Rect, tuple[int, int] | None, str]] = []
    for info in page.get_images(full=True):
        xref = info[0]
        native, digest = None, ""
        try:
            ext = doc.extract_image(xref)
            if ext:
                native = (ext["width"], ext["height"])
                digest = hashlib.sha1(ext["image"]).hexdigest()[:12]
        except Exception:
            pass
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        for r in rects:
            raw = Rect(r.x0, r.y0, r.x1, r.y1)
            clipped = Rect(
                max(r.x0, page.rect.x0),
                max(r.y0, page.rect.y0),
                min(r.x1, page.rect.x1),
                min(r.y1, page.rect.y1),
            )
            if clipped.width > 2 and clipped.height > 2:
                placements.append((xref, raw, clipped, native, digest))

    consumed: set[int] = set()
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 1:
            continue
        bx = blk["bbox"]
        r = Rect(
            max(bx[0], page.rect.x0),
            max(bx[1], page.rect.y0),
            min(bx[2], page.rect.x1),
            min(bx[3], page.rect.y1),
        )
        if r.width < 2 or r.height < 2:
            continue
        native, digest, name, placed = None, "", "img", None
        for idx, (_xref, praw, pclip, pnat, pdig) in enumerate(placements):
            inter = r.overlap_area(pclip)
            if inter >= 0.5 * min(r.area, pclip.area):
                native, digest, name = pnat, pdig, f"xref{_xref}"
                # the raw placement already carries the final transform, so its
                # aspect matches the source unless the image was really stretched.
                # The *visible* rect may be smaller - that is cropping, not stretching.
                placed = praw
                consumed.add(idx)
                break
        else:
            px, py = blk.get("width"), blk.get("height")
            if px and py:
                native = (int(px), int(py))
        slide.images.append(
            ImageBox(rect=r, placed_rect=placed, native_px=native, name=name, digest=digest)
        )

    for idx, (xref, praw, pclip, native, digest) in enumerate(placements):
        if idx in consumed:
            continue
        slide.images.append(
            ImageBox(
                rect=pclip,
                placed_rect=praw,
                native_px=native,
                name=f"xref{xref}",
                digest=digest,
            )
        )


class _Probe:
    """Pixel sampler used to decide whether a declared fill is actually painted.

    Google Slides (and most PDF exporters) emit a graphics state per text frame
    with a fill colour that is never painted. Trusting the fill would make every
    code block look like black-on-black, so sample the rendered page instead.
    """

    DENSITY = 40  # dpi - enough to see flat regions, cheap to render

    def __init__(self, page):
        self.ok = False
        try:
            pm = page.get_pixmap(dpi=self.DENSITY)
        except Exception:
            return
        self.pm = pm
        self.scale = self.DENSITY / 72.0
        counts: dict[tuple, int] = {}
        data = pm.samples
        for i in range(0, len(data), pm.n * 17):  # sparse sample for the background
            px = tuple(data[i : i + 3])
            counts[px] = counts.get(px, 0) + 1
        self.bg = max(counts, key=lambda k: counts[k]) if counts else (255, 255, 255)
        self.ok = True

    def at(self, x: float, y: float) -> tuple | None:
        if not self.ok:
            return None
        px, py = int(x * self.scale), int(y * self.scale)
        if not (0 <= px < self.pm.width and 0 <= py < self.pm.height):
            return None
        i = (py * self.pm.width + px) * self.pm.n
        return tuple(self.pm.samples[i : i + 3])

    def fill_is_painted(self, rect, hex_fill: str) -> bool:
        """True if `rect` is actually filled with `hex_fill`.

        Compares the region's mean colour against the declared fill and against
        the page background. Using the mean (not individual pixels) means
        overlaid text does not fool it, while a black-on-white text placeholder
        still reads as unpainted.
        """
        if not self.ok or not hex_fill:
            return True
        want = tuple(int(hex_fill.lstrip("#")[j : j + 2], 16) for j in (0, 2, 4))
        w, h = rect.width, rect.height
        if w < 4 or h < 4:
            return False
        n = 7
        acc = [0, 0, 0]
        count = 0
        for i in range(n):
            fx = (i + 0.5) / n
            for j in range(n):
                fy = (j + 0.5) / n
                px = self.at(rect.x0 + w * fx, rect.y0 + h * fy)
                if px is None:
                    continue
                acc[0] += px[0]
                acc[1] += px[1]
                acc[2] += px[2]
                count += 1
        if count < 4:
            return False
        mean = tuple(a / count for a in acc)
        d_fill = sum((mean[j] - want[j]) ** 2 for j in range(3)) ** 0.5
        d_bg = sum((mean[j] - self.bg[j]) ** 2 for j in range(3)) ** 0.5
        return d_fill < d_bg


def _pdf_probe(page) -> _Probe:
    return _Probe(page)


def _pdf_shape(g: dict, probe: _Probe | None = None) -> Shape | None:
    r = g["rect"]
    fill = _hexc(g.get("fill"))
    stroke = _hexc(g.get("color"))
    width = round(float(g.get("width") or 0), 3)
    if fill is None and stroke is None:
        return None

    rect = Rect(r.x0, r.y0, r.x1, r.y1)
    painted_fill = fill
    if fill is not None and probe is not None and not probe.fill_is_painted(rect, fill):
        painted_fill = None

    if painted_fill is None and stroke is None:
        # nothing is drawn: a layout placeholder
        return Shape(
            rect=rect,
            stroke=None,
            fill=None,
            width=0.0,
            is_text_frame=True,
            visible=False,
        )

    items = g.get("items", [])
    return Shape(
        rect=rect,
        stroke=stroke,
        fill=painted_fill,
        width=width,
        dash=_dash_tuple(g.get("dashes")),
        is_text_frame=False,
        visible=True,
        has_curves=any(it[0] == "c" for it in items),
        n_items=len(items),
    )


# -------------------------------------------------------------------- PPTX
def load_pptx(path: str | Path) -> Deck:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    cw = prs.slide_width / EMU_PER_PT
    ch = prs.slide_height / EMU_PER_PT
    slides: list[Slide] = []
    for idx, sld in enumerate(prs.slides):
        slide = Slide(number=idx + 1, rect=Rect(0, 0, cw, ch))
        slide.has_notes_part = sld.has_notes_slide
        for shp in sld.shapes:
            try:
                r = Rect(
                    shp.left / EMU_PER_PT,
                    shp.top / EMU_PER_PT,
                    (shp.left + shp.width) / EMU_PER_PT,
                    (shp.top + shp.height) / EMU_PER_PT,
                )
            except TypeError:
                continue

            if shp.shape_type == MSO_SHAPE_TYPE.PICTURE:
                native, digest = None, ""
                try:
                    img = shp.image
                    native = img.size
                    digest = hashlib.sha1(img.blob).hexdigest()[:12]
                except Exception:
                    pass
                slide.images.append(
                    ImageBox(rect=r, native_px=native, name=shp.name, digest=digest)
                )
                continue

            if shp.has_text_frame and shp.text_frame.text.strip():
                tb = _pptx_text_box(shp, r)
                if tb is not None:
                    slide.text_boxes.append(tb)
                line = shp.line
                slide.shapes.append(
                    Shape(
                        rect=r,
                        stroke=_pptx_line_color(line),
                        width=(line.width.pt if line.width is not None else 0.0),
                        dash=_pptx_line_dash(line),
                    )
                )
                continue

            line = getattr(shp, "line", None)
            fill_hex = None
            try:
                if shp.fill.type is not None and shp.fill.type == 1:  # solid
                    fill_hex = "#" + str(shp.fill.fore_color.rgb).lower()
            except Exception:
                pass
            radius = 0.0
            has_curves = False
            try:
                # MSO_SHAPE.ROUNDED_RECTANGLE == 5; adjustment[0] is the corner ratio
                if shp.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and shp.adjustments:
                    adj = shp.adjustments[0]
                    if adj:
                        radius = float(adj)
                        has_curves = True
            except Exception:
                pass
            slide.shapes.append(
                Shape(
                    rect=r,
                    stroke=_pptx_line_color(line),
                    fill=fill_hex,
                    width=(line.width.pt if line and line.width is not None else 0.0),
                    dash=_pptx_line_dash(line),
                    has_curves=has_curves,
                )
            )
        slides.append(slide)
    return Deck(path=str(path), slides=slides, fmt="pptx")


def _pptx_line_dash(line) -> tuple[float, ...] | None:
    """DrawingML predefined dash lengths are multiples of stroke width."""
    if line is None:
        return None
    from pptx.oxml.ns import qn
    element = line._get_or_add_ln()
    width = line.width.pt if line.width is not None else 0.75
    custom = element.find(qn("a:custDash"))
    if custom is not None:
        return tuple(float(pair.get(attr, "0")) * width / 100000
                     for pair in custom for attr in ("d", "sp")) or None
    preset = element.find(qn("a:prstDash"))
    pattern = {
        "dash": (4, 3), "lgDash": (8, 3), "dot": (1, 3),
        "dashDot": (4, 3, 1, 3), "lgDashDot": (8, 3, 1, 3),
        "lgDashDotDot": (8, 3, 1, 3, 1, 3),
        "sysDash": (3, 1), "sysDot": (1, 1),
        "sysDashDot": (3, 1, 1, 1), "sysDashDotDot": (3, 1, 1, 1, 1, 1),
    }.get(preset.get("val") if preset is not None else "solid")
    return tuple(x * width for x in pattern) if pattern else None


def _pptx_line_color(line) -> str | None:
    if line is None:
        return None
    try:
        if line.color and line.color.type is not None:
            return "#" + str(line.color.rgb).lower()
    except Exception:
        pass
    return None


# Mean glyph width as a fraction of the font size, for Arial-like sans faces.
# Good enough to estimate how many lines a paragraph wraps to.
MEAN_CHAR_W = 0.52


def _line_multiple(para, default: float = 1.2) -> float:
    from pptx.util import Length
    ls = para.line_spacing
    if ls is None:
        return default
    try:
        if isinstance(ls, Length):
            font_size = para.runs[0].font.size if para.runs else None
            return ls.pt / (font_size.pt if font_size is not None else 12.0)
        if isinstance(ls, (int, float)):
            return float(ls)
        return ls.pt / max(1.0, (para.runs[0].font.size.pt if para.runs else 12.0))
    except Exception:
        return default


def _space_after(para) -> float:
    try:
        return para.space_after.pt if para.space_after is not None else 0.0
    except Exception:
        return 0.0


def _space_before(para) -> float:
    try:
        return para.space_before.pt if para.space_before is not None else 0.0
    except Exception:
        return 0.0


def _pptx_text_box(shp, r: Rect) -> TextBox | None:
    """Build a TextBox from a PPTX shape, synthesising line geometry.

    PPTX stores no rendered geometry, but the checks that matter (leading,
    paragraph gaps, line counts, overlap) all need a plausible line stack.
    Estimate the wrap from the frame width and the mean glyph width, then lay
    the runs out row by row.
    """
    tf = shp.text_frame
    frame_w = max(1.0, r.width - tf.margin_left.pt - tf.margin_right.pt)
    out: list[Span] = []
    y = r.y0
    saw_marker = False
    align = "left"

    for para in shp.text_frame.paragraphs:
        src = [run for run in para.runs if run.text.strip()]
        if not src:
            y += 12
            continue
        try:
            if para.alignment is not None and "CENTER" in str(para.alignment):
                align = "center"
            elif para.alignment is not None and "RIGHT" in str(para.alignment):
                align = "right"
            elif para.alignment is not None and "JUSTIFY" in str(para.alignment):
                align = "justify"
        except Exception:
            pass
        if (para.text or "").strip()[:1] in MARKER_RECOGNISED:
            saw_marker = True

        spans: list[Span] = []
        for run in src:
            f = run.font
            size = f.size.pt if f.size is not None else 18.0
            color = "#000000"
            try:
                if f.color and f.color.type is not None:
                    color = "#" + str(f.color.rgb).lower()
            except Exception:
                pass
            spans.append(
                Span(
                    text=run.text,
                    font=_norm_family(f.name or "Arial"),
                    size=round(size, 2),
                    color=color,
                    bold=bool(f.bold),
                    italic=bool(f.italic),
                )
            )

        y += _space_before(para)
        line_mult = _line_multiple(para)
        total_chars = sum(len(s.text) for s in spans)
        total_w = sum(len(s.text) * s.size * MEAN_CHAR_W for s in spans)
        n_rows = max(1, int(total_w / frame_w) + (1 if total_w % frame_w else 0))
        per_row = max(1, -(-total_chars // n_rows))  # ceil division

        # slice the formatted runs into visual rows
        row_h = max(s.size for s in spans) * line_mult
        for row in range(n_rows):
            start, end = row * per_row, min(total_chars, (row + 1) * per_row)
            if start >= end:
                break
            pos = 0  # char offset within the paragraph, restated per row
            for s in spans:
                s0, s1 = pos, pos + len(s.text)
                pos = s1
                lo, hi = max(s0, start), min(s1, end)
                if lo >= hi:
                    continue
                piece = s.text[lo - s0 : hi - s0]
                if not piece.strip():
                    continue
                out.append(
                    Span(
                        text=piece,
                        font=s.font,
                        size=s.size,
                        color=s.color,
                        bold=s.bold,
                        italic=s.italic,
                        rect=Rect(r.x0, y, r.x0 + len(piece) * s.size * MEAN_CHAR_W, y + row_h),
                    )
                )
            y += row_h
        y += _space_after(para)

    if not out:
        return None
    max_size = max(s.size for s in out)
    return TextBox(
        rect=Rect(r.x0, r.y0, r.x1, min(y, r.y1)),
        runs=out,
        # match the PDF rule: a title starts above the content band (y=100)
        is_title=max_size >= 20 and r.y0 < 100.0,
        is_bullet_list=saw_marker,
        align=align,
    )


def load(path: str | Path) -> Deck:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(p)
    if suffix in (".pptx", ".pptm"):
        return load_pptx(p)
    raise ValueError(f"unsupported deck format: {p.suffix} (expected .pdf or .pptx)")
