"""Paginated presenter PDF from a general deck manifest, with slide bookmarks."""
from io import BytesIO
import re
from xml.sax.saxutils import escape

import pymupdf
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from deckgen import layout as L


def markup(text):
    parts = escape(text).split("**")
    result = "".join(("<b>"+p+"</b>" if n % 2 else p) for n,p in enumerate(parts))
    superscripts = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789−+")
    result = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m:"<super>"+m[0].translate(superscripts)+"</super>", result)
    plain = re.sub(r"<[^>]+>", "", result)
    missing = {c for c in plain if not c.isspace() and ord(c) not in pdfmetrics.getFont("ScriptBody").face.charToGlyph}
    if missing:
        raise ValueError(f"speaker script: unsupported glyphs {sorted(missing)}")
    return result.replace("\n", "<br/>")


class ScriptDocument(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "slide_bookmark"):
            key, title = flowable.slide_bookmark
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key)


def timestamp(value):
    seconds = round(value*60)
    return f"{seconds//60:02}:{seconds%60:02}"



def script_labels(language):
    """Select built-in script labels; other languages require explicit adaptation."""
    value = language.strip().lower()
    russian = value.startswith(("ru", "рус"))
    return ({"slide": "Слайд", "script": "Сценарий выступления", "plan": "План",
             "minutes": "мин.", "interval": "Интервал", "see": "Что мы видим",
             "message": "Основной посыл", "speech": "Речь выступающего",
             "action": "Действие и пауза", "transition": "Переход к следующему слайду",
             "sources": "Источники", "source_note": "Полные описания — в конце сценария.", "page": "Стр."}
            if russian else
            {"slide": "Slide", "script": "Speaker script", "plan": "Plan",
             "minutes": "min", "interval": "Interval", "see": "What the audience sees",
             "message": "Main message", "speech": "Speaker's words",
             "action": "Action and pause", "transition": "Transition to the next slide",
             "sources": "Sources", "source_note": "Full descriptions are at the end of the script.", "page": "Page"})

def build_script(data, slides_pdf, target):
    cfg = L.SPEC["speaker_script"]; margin = cfg["margin"]; labels = script_labels(data["brief"]["language"])
    pdfmetrics.registerFont(TTFont("ScriptBody", L.font_file(L.FONT, False, False)))
    pdfmetrics.registerFont(TTFont("ScriptBold", L.font_file(L.FONT, True, False)))
    pdfmetrics.registerFontFamily("ScriptBody", normal="ScriptBody", bold="ScriptBold")
    styles = {
        "title": ParagraphStyle("script-title", fontName="ScriptBold", fontSize=16, leading=20, spaceAfter=10, keepWithNext=True),
        "heading": ParagraphStyle("script-heading", fontName="ScriptBold", fontSize=11, leading=14, spaceBefore=10, spaceAfter=5, keepWithNext=True, textColor=L.ACCENT),
        "body": ParagraphStyle("script-body", fontName="ScriptBody", fontSize=cfg["body_size"], leading=cfg["body_size"]*cfg["line_spacing"], spaceAfter=7),
        "meta": ParagraphStyle("script-meta", fontName="ScriptBody", fontSize=10, leading=13, spaceAfter=8, textColor=L.MUTED),
    }
    document = ScriptDocument(str(target), pagesize=A4, leftMargin=margin, rightMargin=margin,
                              topMargin=margin, bottomMargin=margin, title=data["brief"]["title"]+" — "+labels["script"],
                              author=data["brief"]["author"])
    flow = []; elapsed = 0; total = len(data["slides"])
    sources = {s["id"]: s for s in data.get("sources", [])}
    def add(text, style="body"):
        flow.append(Paragraph(markup(text), styles[style]))
    with pymupdf.open(slides_pdf) as pdf:
        for n, slide in enumerate(data["slides"], 1):
            if n > 1:
                flow.append(PageBreak())
            title = f"{labels['slide']} {n} / {total}. {slide['title']}"
            heading = Paragraph(markup(title), styles["title"])
            heading.slide_bookmark = (slide["id"], title); flow.append(heading)
            add(f"{labels['plan']}: {slide['minutes']:g} {labels['minutes']}. {labels['interval']}: {timestamp(elapsed)}–{timestamp(elapsed+slide['minutes'])}", "meta")
            pix = pdf[n-1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
            flow.append(Image(BytesIO(pix.tobytes("png")), width=260, height=260*L.H/L.W, hAlign="LEFT"))
            script = slide["script"]
            for label, key in ((labels["see"], "see"), (labels["message"], "message"), (labels["speech"], "speech")):
                add(label, "heading")
                for paragraph in script[key].split("\n\n"):
                    add(paragraph)
            if script.get("action"):
                add(labels["action"], "heading"); add(script["action"])
            if slide.get("transition"):
                add(labels["transition"], "heading"); add(slide["transition"])
            if slide.get("sources"):
                refs = ", ".join(f"[{list(sources).index(r)+1}]" for r in slide["sources"])
                add(labels["sources"]+": "+refs+". "+labels["source_note"], "meta")
            elapsed += slide["minutes"]
    if sources:
        flow.append(PageBreak()); add(labels["sources"], "title")
        for n, source in enumerate(sources.values(), 1):
            add(f"[{n}] {source['title']}", "heading")
            add(source["description"]); add(source["location"], "meta")
    def footer(canvas, doc):
        canvas.setFont("ScriptBody", 9); canvas.setFillColor(L.MUTED)
        canvas.drawString(margin, 25, labels["script"])
        canvas.drawRightString(A4[0]-margin, 25, f"{labels['page']} {doc.page}")
    document.build(flow, onFirstPage=footer, onLaterPages=footer)
