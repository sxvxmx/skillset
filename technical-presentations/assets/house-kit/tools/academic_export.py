"""Populate a native Word TOC cache from headings and verify PDF page references.

The editable TOC and PAGEREF fields remain live in Word. The cached result is
computed from native heading styles and actual pagination, never typed by hand.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import shutil
import tempfile
from zipfile import ZipFile
from lxml import etree
import pymupdf
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
_BUNDLED = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice"
SOFFICE = os.environ.get("MATH_SOFFICE") or (str(_BUNDLED) if _BUNDLED.exists() else shutil.which("soffice")) or "soffice"
TEMP_DIR = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir())


def el(tag, **attrs):
    node = OxmlElement(tag)
    for key, value in attrs.items():
        node.set(qn("w:" + key), str(value))
    return node


def headings(doc):
    entries = []
    major = minor = 0
    for p in doc.paragraphs:
        if p.style.name == "Heading 1":
            major += 1; minor = 0; number = str(major); level = 1
        elif p.style.name == "Heading 2":
            minor += 1; number = f"{major}.{minor}"; level = 2
        else:
            continue
        entries.append(dict(title=p.text, number=number, level=level,
                            bookmark=f"_TocMath{len(entries)+1:03d}"))
    return entries


def convert(source, directory):
    env = os.environ.copy(); env["TMPDIR"] = str(TEMP_DIR)
    # The headless macOS build otherwise sees only its bundled substitutes.
    # Supply a task-local fontconfig file; never modify the user's office setup.
    if Path("/System/Library/Fonts/Supplemental/Arial.ttf").exists():
        config=ROOT/"qa"/"fonts.conf"
        config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/System/Library/Fonts/Supplemental</dir><cachedir>/private/tmp/math-font-cache</cachedir></fontconfig>')
        env["FONTCONFIG_FILE"]=str(config)
    with tempfile.TemporaryDirectory(prefix="math-office-", dir=TEMP_DIR) as profile:
        result = subprocess.run([str(SOFFICE), f"-env:UserInstallation={Path(profile).as_uri()}",
                                 "--headless", "--convert-to", "pdf", "--outdir", str(directory), str(source)],
                                env=env, capture_output=True, text=True, timeout=60, check=True)
    target = Path(directory) / source.with_suffix(".pdf").name
    if not target.exists():
        raise RuntimeError(result.stdout + result.stderr)
    return target


def normalized(text):
    return re.sub(r"[^\w]", "", text.casefold())


def measure(pdf, entries):
    pages = {}
    with pymupdf.open(pdf) as document:
        for entry in entries:
            found = []
            for page in document:
                blocks=page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
                # TeX may split a wrapped heading into separate text blocks.
                title_text=" ".join(span["text"] for block in blocks
                                    for line in block.get("lines", []) for span in line["spans"]
                                    if ("Arial" in span["font"] or "LiberationSans" in span["font"])
                                    and span["size"] >= 11.9)
                if normalized(entry["title"]) in normalized(title_text):
                    found.append(page.number+1)
            if len(set(found)) != 1:
                raise ValueError(f"Heading page not unique: {entry['title']}: {found}")
            pages[entry["bookmark"]] = found[0]
    return pages


def append_run(parent, text=None, child=None):
    run = el("w:r")
    if text is not None:
        t = el("w:t"); t.text = text; t.set(qn("xml:space"), "preserve"); run.append(t)
    if child is not None:
        run.append(child)
    parent.append(run)


def append_field(parent, instruction, cached=None):
    append_run(parent, child=el("w:fldChar", fldCharType="begin"))
    code = el("w:instrText"); code.text = " " + instruction + " "
    code.set(qn("xml:space"), "preserve"); append_run(parent, child=code)
    append_run(parent, child=el("w:fldChar", fldCharType="separate"))
    if cached is not None:
        append_run(parent, str(cached))
        append_run(parent, child=el("w:fldChar", fldCharType="end"))


def populate(source, entries, pages):
    doc = Document(source)
    for level in (1, 2):
        name = f"TOC {level}"
        style = doc.styles[name] if name in doc.styles else doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = "Times New Roman"; style.font.size = Pt(12)
        style.font.bold = False; style.font.italic = False
        pf = style.paragraph_format
        pf.first_line_indent = Cm(0); pf.left_indent = Cm(0 if level == 1 else .6)
        pf.line_spacing = 1.1; pf.space_before = Pt(0); pf.space_after = Pt(2)
        pf.keep_with_next = False
        pf.tab_stops.add_tab_stop(Cm(16.5), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    old_ids = set()
    for start in list(doc.element.iter(qn("w:bookmarkStart"))):
        if start.get(qn("w:name"), "").startswith("_TocMath"):
            old_ids.add(start.get(qn("w:id"))); start.getparent().remove(start)
    for end in list(doc.element.iter(qn("w:bookmarkEnd"))):
        if end.get(qn("w:id")) in old_ids:
            end.getparent().remove(end)
    native = [p for p in doc.paragraphs if p.style.name in ("Heading 1", "Heading 2")]
    for i, (p, entry) in enumerate(zip(native, entries), 100):
        p._p.insert(1, el("w:bookmarkStart", id=i, name=entry["bookmark"]))
        p._p.append(el("w:bookmarkEnd", id=i))
    body = doc.element.body
    existing = next(child for child in body if any("TOC " in (n.text or "") for n in child.iter(qn("w:instrText"))))
    sdt = el("w:sdt"); props = el("w:sdtPr"); obj = el("w:docPartObj")
    obj.append(el("w:docPartGallery", val="Table of Contents")); obj.append(el("w:docPartUnique"))
    props.append(obj); sdt.append(props); content = el("w:sdtContent"); sdt.append(content)
    p = el("w:p"); pp = el("w:pPr"); pp.append(el("w:spacing", before=0, after=0, line=20, lineRule="exact")); p.append(pp)
    append_field(p, 'TOC \\o "1-2" \\h \\z \\u'); content.append(p)
    for entry in entries:
        p = el("w:p"); pp = el("w:pPr"); pp.append(el("w:pStyle", val=f"TOC{entry['level']}")); p.append(pp)
        link = el("w:hyperlink", anchor=entry["bookmark"], history=1)
        append_run(link, f"{entry['number']}  {entry['title']}")
        append_run(link, child=el("w:tab"))
        append_field(link, f"PAGEREF {entry['bookmark']} \\h", pages[entry["bookmark"]])
        p.append(link); content.append(p)
    p = el("w:p"); append_run(p, child=el("w:fldChar", fldCharType="end")); content.append(p)
    body.replace(existing, sdt)
    doc.save(source)


def export(source, qa):
    global ROOT
    source=Path(source).resolve(); qa=Path(qa).resolve(); qa.mkdir(parents=True, exist_ok=True)
    ROOT=qa.parent
    entries = headings(Document(source))
    with tempfile.TemporaryDirectory(prefix="math-report-", dir=TEMP_DIR) as temp:
        pages = measure(convert(source, temp), entries)
    for attempt in range(4):
        populate(source, entries, pages)
        pdf = convert(source, source.parent)
        actual = measure(pdf, entries)
        if pages == actual:
            break
        pages = actual
    else:
        raise RuntimeError("TOC pagination did not converge")
    with ZipFile(source) as archive:
        xml = etree.fromstring(archive.read("word/document.xml"))
    codes = [node.text or "" for node in xml.iter(qn("w:instrText"))]
    assert sum("TOC " in c for c in codes) == 1
    assert sum("PAGEREF " in c for c in codes) == len(entries)
    (qa / "toc-pages.json").write_text(json.dumps({e["number"] + " " + e["title"]: pages[e["bookmark"]] for e in entries}, ensure_ascii=False, indent=2))
    print(f"Verified {len(entries)} native TOC entries: {pdf}")


    return pdf
