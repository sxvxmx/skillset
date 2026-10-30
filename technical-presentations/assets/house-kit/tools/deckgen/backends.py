"""Renderers: the same `Deck` to PDF and to PPTX.

Both read absolute coordinates from `layout.Slide`. Neither invents a position.
The PDF embeds the real Arial TTFs so Cyrillic renders and text metrics match
the PPTX exactly; the PPTX keeps real text boxes so the deck stays editable.
"""

from __future__ import annotations

from pathlib import Path

from . import layout as L

_EMU = 12700


def _dash_str(dash) -> str | None:
    if not dash:
        return None
    return f"[{dash[0]} {dash[1]}] 0" if len(dash) >= 2 else f"[{dash[0]}] 0"


def _rgb(hex_color: str | None):
    if not hex_color:
        return None
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _pptx_color(hex_color: str):
    from pptx.dml.color import RGBColor

    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _emu(v: float) -> int:
    return int(round(v * _EMU))


# ---------------------------------------------------------------------- PDF
def to_pdf(deck: L.Deck, path: str | Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for slide in deck.slides:
        page = doc.new_page(width=L.W, height=L.H)
        page.draw_rect(pymupdf.Rect(0, 0, L.W, L.H), color=None, fill=(1, 1, 1), width=0)

        for r in (r for r in slide.rects if r.fill is not None or not r.dash):
            shape = page.new_shape()
            shape.draw_rect(pymupdf.Rect(r.x, r.y, r.x + r.w, r.y + r.h))
            shape.finish(
                color=_rgb(r.stroke) if r.stroke else None,
                fill=_rgb(r.fill) if r.fill else None,
                width=r.width if r.stroke else 0,
                dashes=_dash_str(r.dash),
            )
            shape.commit()

        for ln in slide.lines:
            shape = page.new_shape()
            shape.draw_line((ln.x1, ln.y1), (ln.x2, ln.y2))
            shape.finish(
                color=_rgb(ln.color),
                width=ln.width,
                dashes=_dash_str(ln.dash),
            )
            shape.commit()
            if ln.arrow:
                _arrow_head(page, ln)

        for im in slide.images:
            page.insert_image(
                pymupdf.Rect(im.x, im.y, im.x + im.w, im.y + im.h), filename=str(im.path)
            )

        # Highlight frames sit on top of the image edge, never behind the bitmap.
        for r in (r for r in slide.rects if r.fill is None and r.dash):
            shape = page.new_shape()
            shape.draw_rect(pymupdf.Rect(r.x, r.y, r.x + r.w, r.y + r.h))
            shape.finish(color=_rgb(r.stroke), fill=None, width=r.width,
                         dashes=_dash_str(r.dash))
            shape.commit()

        # One alias per distinct face. Re-binding a single alias per token
        # leaves the whole page using whichever face was registered last, which
        # silently drops every bit of bold emphasis in the deck.
        aliases: dict[tuple, str] = {}
        for _x, _y, _tok, run in slide.flattened_text():
            key = (run.family, run.bold, run.italic)
            if key not in aliases:
                alias = f"F{len(aliases)}"
                page.insert_font(fontname=alias, fontfile=L.font_file(*key))
                aliases[key] = alias
        for x, baseline, token, run in slide.flattened_text():
            page.insert_text(
                (x, baseline),
                token,
                fontname=aliases[(run.family, run.bold, run.italic)],
                fontsize=run.size,
                color=_rgb(run.color),
            )

    doc.set_metadata({"title": deck.title, "author": deck.author})
    p = Path(path)
    doc.save(str(p), deflate=True, garbage=3)
    doc.close()
    return p


def _arrow_head(page, ln: L.Line_) -> None:
    dx, dy = ln.x2 - ln.x1, ln.y2 - ln.y1
    d = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / d, dy / d
    size = 5.0
    px, py = -uy, ux
    page.draw_polyline(
        [
            (ln.x2, ln.y2),
            (ln.x2 - ux * size + px * size * 0.55, ln.y2 - uy * size + py * size * 0.55),
            (ln.x2 - ux * size - px * size * 0.55, ln.y2 - uy * size - py * size * 0.55),
        ],
        color=_rgb(ln.color),
        width=ln.width,
        fill=_rgb(ln.color),
    )


# --------------------------------------------------------------------- PPTX
def to_pptx(deck: L.Deck, path: str | Path) -> Path:
    from pptx import Presentation
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Emu, Pt

    prs = Presentation()
    prs.slide_width = Emu(_emu(L.W))
    prs.slide_height = Emu(_emu(L.H))

    for slide in deck.slides:
        s = prs.slides.add_slide(prs.slide_layouts[6])

        def inside_native_table(x: float, y: float, w: float = 0, h: float = 0) -> bool:
            return any(
                x >= t.x - 0.1 and y >= t.y - 0.1
                and x + w <= t.x + t.w + 0.1
                and y + h <= t.y + t.h + 0.1
                for t in slide.tables
            )

        for r in (r for r in slide.rects if r.fill is not None or not r.dash):
            if inside_native_table(r.x, r.y, r.w, r.h):
                continue
            sh = s.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Emu(_emu(r.x)),
                Emu(_emu(r.y)),
                Emu(_emu(r.w)),
                Emu(_emu(r.h)),
            )
            sh.shadow.inherit = False
            if r.fill:
                sh.fill.solid()
                sh.fill.fore_color.rgb = _pptx_color(r.fill)
            else:
                sh.fill.background()
            if r.stroke:
                sh.line.color.rgb = _pptx_color(r.stroke)
                sh.line.width = Pt(r.width)
                sh.line.dash_style = (
                    MSO_LINE_DASH_STYLE.DASH if r.dash else MSO_LINE_DASH_STYLE.SOLID
                )
            else:
                sh.line.fill.background()

        for ln in slide.lines:
            cx = s.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                Emu(_emu(ln.x1)),
                Emu(_emu(ln.y1)),
                Emu(_emu(ln.x2)),
                Emu(_emu(ln.y2)),
            )
            cx.line.color.rgb = _pptx_color(ln.color)
            cx.line.width = Pt(ln.width)
            if ln.dash:
                cx.line.dash_style = MSO_LINE_DASH_STYLE.DASH
            if ln.arrow:
                _add_arrowhead(cx)

        for im in slide.images:
            s.shapes.add_picture(
                str(im.path),
                Emu(_emu(im.x)),
                Emu(_emu(im.y)),
                Emu(_emu(im.w)),
                Emu(_emu(im.h)),
            )

        for r in (r for r in slide.rects if r.fill is None and r.dash):
            sh = s.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Emu(_emu(r.x)), Emu(_emu(r.y)),
                Emu(_emu(r.w)), Emu(_emu(r.h)),
            )
            sh.shadow.inherit = False
            sh.fill.background()
            sh.line.color.rgb = _pptx_color(r.stroke)
            sh.line.width = Pt(r.width)
            sh.line.dash_style = MSO_LINE_DASH_STYLE.DASH

        for t in slide.tables:
            graphic = s.shapes.add_table(
                len(t.rows) + 1, len(t.header),
                Emu(_emu(t.x)), Emu(_emu(t.y)), Emu(_emu(t.w)), Emu(_emu(t.h)),
            )
            native = graphic.table
            total = sum(t.widths)
            for i, fraction in enumerate(t.widths):
                native.columns[i].width = Emu(_emu(t.w * fraction / total))
            native.rows[0].height = Emu(_emu(t.head_h))
            for ri in range(1, len(t.rows) + 1):
                native.rows[ri].height = Emu(_emu(t.row_h))
            for ri, values in enumerate([t.header, *t.rows]):
                for ci, value in enumerate(values):
                    c = native.cell(ri, ci)
                    c.text = value
                    c.fill.solid()
                    cfg = L.SPEC.get("authoring", {}).get("table", {})
                    c.fill.fore_color.rgb = _pptx_color(cfg.get("header_fill", '#f0f0ff') if ri == 0 else L.WHITE)
                    c.vertical_anchor = MSO_ANCHOR.MIDDLE
                    tf = c.text_frame
                    tf.margin_left = tf.margin_right = Pt(cfg.get("padding", 8))
                    tf.margin_top = tf.margin_bottom = Pt(3)
                    tf.word_wrap = True
                    for paragraph in tf.paragraphs:
                        paragraph.alignment = PP_ALIGN_LEFT
                        for run in paragraph.runs:
                            run.font.name = L.FONT
                            run.font.size = Pt(cfg.get("font_size", 10.5))
                            run.font.bold = ri == 0 or ci == 0
                            run.font.color.rgb = _pptx_color(L.BLACK)
                    _set_cell_border(c, L.GRID)

        for b in slide.blocks:
            if inside_native_table(b.x, b.y):
                continue
            if not b.paras:
                continue
            lines = b.layout()
            if not lines:
                continue
            # Baselines already include ascent. Count it once, otherwise a
            # one-line footer gets an oversized box extending into the margin.
            height = max(ln.y - max((r.size for _, r, _ in ln.pieces), default=L.BODY_PT)*.98
                         + ln.height for ln in lines) - b.y + 2
            # The box top is the block top. Nudging it up by the leading makes
            # the *text* land on the right baseline but leaves the box in the
            # wrong place, which is what a geometry linter measures.
            box = s.shapes.add_textbox(
                Emu(_emu(b.x)), Emu(_emu(b.y)),
                Emu(_emu(b.w)), Emu(_emu(height)),
            )
            tf = box.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            for i, p in enumerate(b.paras):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                para.alignment = {
                    "left": PP_ALIGN_LEFT,
                    "center": PP_ALIGN_CENTER,
                    "right": PP_ALIGN_RIGHT,
                }[p.align]
                para.line_spacing = p.line_spacing
                if p.space_after:
                    para.space_after = Pt(p.space_after)
                for run in p.runs:
                    r = para.add_run()
                    r.text = run.text
                    r.font.name = run.family
                    r.font.size = Pt(run.size)
                    r.font.bold = run.bold
                    r.font.italic = run.italic
                    r.font.color.rgb = _pptx_color(run.color)

        if slide.notes:
            s.notes_slide.notes_text_frame.text = slide.notes

    p = Path(path)
    prs.save(str(p))
    return p


def _add_arrowhead(connector) -> None:
    from lxml import etree

    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ln = connector.line._get_or_add_ln()
    tail = etree.SubElement(ln, f"{{{ns}}}tailEnd")
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")


def _set_cell_border(cell, color: str) -> None:
    from lxml import etree
    from pptx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    for side in ('lnL', 'lnR', 'lnT', 'lnB'):
        old = tc_pr.find(qn(f'a:{side}'))
        if old is not None:
            tc_pr.remove(old)
        ln = etree.SubElement(tc_pr, qn(f'a:{side}'))
        ln.set('w', '9525')  # 0.75 pt
        fill = etree.SubElement(ln, qn('a:solidFill'))
        rgb = etree.SubElement(fill, qn('a:srgbClr'))
        rgb.set('val', color.lstrip('#').upper())


try:
    from pptx.enum.text import PP_ALIGN as _PPA

    PP_ALIGN_LEFT = _PPA.LEFT
    PP_ALIGN_CENTER = _PPA.CENTER
    PP_ALIGN_RIGHT = _PPA.RIGHT
except Exception:  # pragma: no cover
    from pptx.enum.text import PP_ALIGN  # type: ignore

    PP_ALIGN_LEFT, PP_ALIGN_CENTER, PP_ALIGN_RIGHT = (
        PP_ALIGN.LEFT,
        PP_ALIGN.CENTER,
        PP_ALIGN.RIGHT,
    )
