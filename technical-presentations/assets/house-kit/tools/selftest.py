#!/usr/bin/env python3
"""Self-test: build a clean deck and a deliberately broken one, then assert
that deckcheck passes the first and catches the second.

    python tools/selftest.py

Fixtures are generated, not committed, so this also exercises the PPTX loader.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Pt

from deckcheck.cli import build_report, load_guideline
from deckcheck.loaders import load_pptx
from deckcheck.model import Severity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = ROOT / ".selftest"
EMU = 12700  # per point

BLACK = RGBColor(0x00, 0x00, 0x00)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREY = RGBColor(0x59, 0x59, 0x59)
BLUE = RGBColor.from_string(load_guideline(ROOT / "guideline.yaml")["colors"]["accent"].lstrip("#"))
FONT = "Arial"
MONO = "Consolas"


def pt(v: float) -> Emu:
    return Emu(int(v * EMU))


def new_deck():
    prs = Presentation()
    prs.slide_width = pt(720)
    prs.slide_height = pt(405)
    return prs


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def textbox(slide, x, y, w, h, runs, size=12, color=BLACK, bold=False, font=FONT,
            align=PP_ALIGN.LEFT, space_after=0, line_spacing=None):
    """runs: a string, or a list of paragraphs (each a string or list of
    (text, {overrides}) tuples)."""
    box = slide.shapes.add_textbox(pt(x), pt(y), pt(w), pt(h))
    tf = box.text_frame
    tf.word_wrap = True
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if space_after:
            p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        chunks = para if isinstance(para, list) else [(para, {})]
        for text, over in chunks:
            r = p.add_run()
            r.text = text
            f = r.font
            f.name = over.get("font", font)
            f.size = Pt(over.get("size", size))
            f.bold = over.get("bold", bold)
            f.italic = over.get("italic", False)
            f.color.rgb = over.get("color", color)
    return box


def title(slide, text, y=46.0, x=31.3, size=25):
    return textbox(slide, x, y, 660, 40, text, size=size, color=BLACK, bold=False)


def dashed_frame(slide, x, y, w, h, width=0.75, color=BLUE):
    from pptx.enum.dml import MSO_LINE_DASH_STYLE

    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, pt(x), pt(y), pt(w), pt(h))
    sh.fill.background()
    sh.line.color.rgb = color
    sh.line.width = Pt(width)
    sh.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    sh.shadow.inherit = False
    return sh


# --------------------------------------------------------------------- clean
def _sample_png() -> Path:
    """A small placeholder diagram, so image checks have a real raster to read."""
    global _PNG
    if _PNG is not None:
        return _PNG
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1260, 776), "#f2f6fd")
    d = ImageDraw.Draw(img)
    for i in range(4):
        x = 60 + i * 300
        d.rectangle([x, 200 + (i % 2) * 120, x + 200, 420 + (i % 2) * 120],
                    fill="#4285f4", outline="#1a4a8a", width=4)
        d.line([x + 200, 310 + (i % 2) * 120, x + 300, 310], fill="#1a4a8a", width=6)
    _PNG = WORK / "sample_diagram.png"
    img.save(_PNG)
    return _PNG


_PNG: Path | None = None


def build_clean(path: Path) -> None:
    prs = new_deck()

    # 1. cover
    s = blank(prs)
    roles = load_guideline(ROOT / "guideline.yaml")["fonts"]["roles"]
    textbox(s, 0, 150, 720, 70, "Kafka Fundamentals", size=roles["cover_title"]["size"], align=PP_ALIGN.CENTER)
    textbox(s, 0, 235, 720, 40, "Докладчик", size=roles["cover_subtitle"]["size"], color=GREY, align=PP_ALIGN.CENTER)

    # 2. bullets, left aligned, on spec
    s = blank(prs)
    title(s, "Что решает Kafka")
    textbox(
        s, 31.3, 100.5, 630, 240,
        [
            [("Broker. ", {"bold": True}), ("Один узел хранит и раздаёт партиции темы.", {})],
            [("Topic. ", {"bold": True}), ("Именованный лог событий, реплицированный по брокерам.", {})],
            [("Partition. ", {"bold": True}), ("Единица параллелизма и минимальная единица репликации.", {})],
        ],
        size=12, space_after=12, line_spacing=1.375,
    )

    # 3. text left, image right
    s = blank(prs)
    title(s, "Архитектура")
    textbox(s, 31.3, 100.5, 320, 200,
            [[("Producer. ", {"bold": True}), ("Пишет события в топи.", {})],
             [("Consumer. ", {"bold": True}), ("Читает их по смещению.", {})]],
            size=12, space_after=12, line_spacing=1.375)
    dashed_frame(s, 371, 111, 321, 200)
    s.shapes.add_picture(str(_sample_png()), pt(374), pt(114), pt(315), pt(194))

    # 4. three code blocks in a dashed frame row
    s = blank(prs)
    title(s, "Consumer API")
    for x in (23, 250, 476):
        dashed_frame(s, x, 130, 214, 197)
    textbox(s, 26, 141, 205, 180,
            [[("auto.offset.reset", {})], [("  = earliest", {})]],
            size=14, font=MONO, line_spacing=1.3)
    textbox(s, 253, 141, 205, 180,
            [[("enable.auto.commit", {})], [("  = false", {})]],
            size=14, font=MONO, line_spacing=1.3)
    textbox(s, 479, 141, 205, 180,
            [[("group.id", {})], [("  = consumers-1", {})]],
            size=14, font=MONO, line_spacing=1.3)

    # 5. closing
    s = blank(prs)
    title(s, "Итог")
    textbox(s, 31.3, 100.5, 630, 200,
            [[("Kafka ", {"bold": True}), ("даёт декoupling producers и consumers.", {})],
             [("Итог. ", {"bold": True}), ("Храните состояние в компактных логах.", {})]],
            size=12, space_after=12, line_spacing=1.375)

    footer = load_guideline(ROOT / "guideline.yaml")["authoring"]["footer"]
    for n, slide in enumerate(prs.slides, 1):
        textbox(slide, footer["x"], footer["y"], footer["width"], 15,
                f"{n:02d} / {len(prs.slides)}", size=footer["size"])
    prs.save(path)


# -------------------------------------------------------------------- broken
def build_broken(path: Path) -> None:
    prs = new_deck()

    # 1. cover with no author line, wrong title size
    s = blank(prs)
    textbox(s, 200, 150, 500, 70, "Broken Deck", size=30, align=PP_ALIGN.CENTER)

    # 2. no title, banned font, too many words, bad bullet count
    s = blank(prs)
    textbox(s, 31.3, 100.5, 630, 280,
            [[(f"Пункт номер {i} ", {"bold": True}),
              ("с очень длинным объяснением, которое никто никогда не прочитает "
               "внимательно, потому что текста слишком много для одного слайда.", {})]
             for i in range(1, 10)],
            size=12, font="Times New Roman", space_after=12, line_spacing=1.05)

    # 3. overlapping text, off-margin element, tiny type, low contrast
    s = blank(prs)
    title(s, "Наложение", x=90.0, y=80.0)
    textbox(s, 31.3, 100.5, 300, 120,
            [[("Первый блок текста ", {}), ("перекрывается", {"bold": True}), (" со вторым.", {})]],
            size=12, line_spacing=1.375)
    textbox(s, 120, 110, 300, 120,
            [[("Второй блок начинается ", {}), ("прямо поверх", {"bold": True}), (" первого.", {})]],
            size=12, line_spacing=1.375)
    textbox(s, 660, 350, 120, 40, "микротекст", size=6)
    textbox(s, 400, 330, 200, 30, [[("жёлтый на белом", {"color": RGBColor(0xFF, 0xCC, 0x00)})]], size=12)

    # 4. a duplicate of slide 3 (build slide) plus a repeated title
    s = blank(prs)
    title(s, "Наложение", x=90.0, y=80.0)
    textbox(s, 31.3, 100.5, 300, 120,
            [[("Первый блок текста ", {}), ("перекрывается", {"bold": True}), (" со вторым.", {})]],
            size=12, line_spacing=1.375)
    textbox(s, 120, 110, 300, 120,
            [[("Второй блок начинается ", {}), ("прямо поверх", {"bold": True}), (" первого.", {})]],
            size=12, line_spacing=1.375)
    textbox(s, 660, 350, 120, 40, "микротекст", size=6)
    textbox(s, 400, 330, 200, 30, [[("жёлтый на белом", {"color": RGBColor(0xFF, 0xCC, 0x00)})]], size=12)

    # 5. off-palette fill, rounded corners, wrong border style
    s = blank(prs)
    title(s, "Оформление")
    sh = slide_shape = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, pt(31.3), pt(100.5), pt(300), pt(150))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor(0xFF, 0x00, 0x00)
    sh.line.color.rgb = RGBColor(0x00, 0xFF, 0x00)
    sh.line.width = Pt(3.5)
    textbox(s, 45, 115, 270, 120, [[("Заметная коробка с неправильной рамкой.", {})]], size=12)

    prs.save(path)


# ---------------------------------------------------------------------- main
EXPECTED_CLEAN_MAX_ERRORS = 0
EXPECTED_BROKEN = {
    "title.missing",
    "font.banned",
    "density.words",
    "density.bullets",
    "leading",
    "overlap.text",
    "offcanvas",
    "size.min",
    "color.offlist",
    "color.contrast",
    "build.duplicate",
    "shape.fill",
    "border.style",
    "title.x",
    "title.y",
    "cover.subtitle",
    "cover.title_size",
}


def main() -> int:
    WORK.mkdir(exist_ok=True)
    clean, broken = WORK / "clean.pptx", WORK / "broken.pptx"
    build_clean(clean)
    build_broken(broken)
    spec = load_guideline(ROOT / "guideline.yaml")

    failures: list[str] = []

    clean_deck = load_pptx(clean)
    rep_clean = build_report(clean_deck, spec)
    errs = rep_clean.count(Severity.ERROR)
    print(f"clean.pptx   {len(clean_deck.slides)} slides -> {errs} error, "
          f"{rep_clean.count(Severity.WARN)} warn, {rep_clean.count(Severity.INFO)} info")
    for f in rep_clean.sorted_findings():
        if f.severity in (Severity.ERROR, Severity.WARN):
            print("   ", f)
    if errs > EXPECTED_CLEAN_MAX_ERRORS:
        failures.append(f"clean deck should have {EXPECTED_CLEAN_MAX_ERRORS} errors, got {errs}")
    if rep_clean.count(Severity.WARN):
        failures.append("clean deck must have no warnings")

    broken_deck = load_pptx(broken)
    rep_broken = build_report(broken_deck, spec)
    found = {f.check for f in rep_broken.findings}
    print(f"\nbroken.pptx  {len(broken_deck.slides)} slides -> "
          f"{rep_broken.count(Severity.ERROR)} error, "
          f"{rep_broken.count(Severity.WARN)} warn, {rep_broken.count(Severity.INFO)} info")
    missed = EXPECTED_BROKEN - found
    for name in sorted(EXPECTED_BROKEN & found):
        print(f"    caught  {name}")
    if missed:
        failures.append(f"missed checks: {', '.join(sorted(missed))}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        return 1
    print("PASS  clean deck is clean; every planted defect was caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
