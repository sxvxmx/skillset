#!/usr/bin/env python3
"""Topic-independent presentation workflow. See PRESENTATION_GUIDE.md."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
from zipfile import ZipFile

import yaml
from PIL import Image as PILImage, ImageChops
import pymupdf

from deckgen import Deck, Slide, TextBlock, Image, Rect, para, to_pdf, to_pptx
from deckgen import layout as L
from deckcheck.cli import build_report, load_guideline, DEFAULT_GUIDELINE, _selftest
from deckcheck.loaders import load
from deckcheck.model import Severity

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS = {"cover", "prose", "compare", "procedure", "table", "split", "square", "wide", "conclusion", "sources"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_manifest(path):
    path = Path(path).resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), "deck.yaml must be a mapping")
    require(data.get("version") == 1, "deck.yaml version must be 1")
    allowed = {"version", "brief", "sources", "slides"}
    require(not (set(data)-allowed), f"unknown manifest fields: {set(data)-allowed}")
    brief = data.get("brief", {})
    for key in ("title", "audience", "takeaway", "language", "author"):
        require(isinstance(brief.get(key), str) and brief[key].strip(), f"brief.{key} is required")
    minutes = brief.get("minutes")
    require(isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
            and math.isfinite(minutes) and minutes > 0, "brief.minutes must be positive and finite")
    slides = data.get("slides")
    require(isinstance(slides, list) and slides, "at least one slide is required")
    sources = data.get("sources", [])
    require(isinstance(sources, list), "sources must be a list")
    source_ids = []
    for source in sources:
        require(isinstance(source, dict), "source must be a mapping")
        for key in ("id", "title", "location", "description"):
            require(isinstance(source.get(key), str) and source[key].strip(), f"source.{key} is required")
        source_ids.append(source["id"])
    require(len(source_ids) == len(set(source_ids)), "duplicate source IDs")
    slide_ids = []; elapsed = 0
    fields = {"id", "title", "layout", "purpose", "minutes", "body", "transition", "script", "sources",
              "columns", "takeaway", "steps", "table", "image", "video", "subtitle"}
    for n, slide in enumerate(slides, 1):
        require(isinstance(slide, dict), f"slide {n} must be a mapping")
        require(not (set(slide)-fields), f"slide {n}: unknown fields {set(slide)-fields}")
        for key in ("id", "title", "purpose"):
            require(isinstance(slide.get(key), str) and slide[key].strip(), f"slide {n}: {key} is required")
        slide_ids.append(slide["id"])
        require(re.fullmatch(r"[a-z0-9_-]+", slide["id"]), f"slide {n}: use a lowercase filename-safe ID")
        kind = slide.get("layout")
        require(kind in LAYOUTS, f"slide {n}: unknown layout {kind!r}")
        duration = slide.get("minutes")
        require(isinstance(duration, (int, float)) and not isinstance(duration, bool)
                and math.isfinite(duration) and duration > 0, f"slide {n}: positive minutes required")
        elapsed += duration
        if n < len(slides) and kind != "sources":
            require(isinstance(slide.get("transition"), str) and slide["transition"].strip(), f"slide {n}: transition required")
        script = slide.get("script", {})
        require(isinstance(script, dict), f"slide {n}: script must be a mapping")
        require(not (set(script)-{"see", "message", "speech", "action"}), f"slide {n}: unknown script field")
        for key in L.SPEC["speaker_script"]["required_fields"]:
            require(isinstance(script.get(key), str) and script[key].strip(), f"slide {n}: script.{key} required")
        refs = slide.get("sources", [])
        require(isinstance(refs, list) and all(isinstance(r, str) and r in source_ids for r in refs), f"slide {n}: unknown source ID")
        body = slide.get("body", [])
        require(isinstance(body, list) and all(isinstance(t, str) and t.strip() for t in body), f"slide {n}: body must be a list of paragraphs")
        if kind in {"prose", "conclusion"}:
            require(body, f"slide {n}: body is empty")
        if kind == "compare":
            cols = slide.get("columns", [])
            require(isinstance(cols, list) and len(cols) == 2, f"slide {n}: compare needs two columns")
            for col in cols:
                require(isinstance(col, dict) and isinstance(col.get("title"), str)
                        and isinstance(col.get("body"), list) and col["body"]
                        and all(isinstance(t, str) for t in col["body"]), f"slide {n}: invalid comparison column")
        if kind == "procedure":
            steps = slide.get("steps", [])
            require(isinstance(steps, list) and 1 <= len(steps) <= L.SPEC["authoring"]["procedure"]["max_steps"]
                    and all(isinstance(t, str) and t.strip() for t in steps), f"slide {n}: procedure needs 1–4 steps")
        if kind == "table":
            table = slide.get("table", {})
            require(isinstance(table, dict), f"slide {n}: table must be a mapping")
            header = table.get("header", []); rows = table.get("rows", []); widths = table.get("widths", [])
            require(isinstance(header, list) and len(header) >= 2 and all(isinstance(v, str) for v in header), f"slide {n}: table header required")
            require(isinstance(rows, list) and rows and all(isinstance(row, list) and len(row) == len(header)
                    and all(isinstance(v, str) for v in row) for row in rows), f"slide {n}: inconsistent table rows")
            require(isinstance(widths, list) and len(widths) == len(header) and all(isinstance(w, (int, float))
                    and not isinstance(w, bool) and math.isfinite(w) and w > 0 for w in widths), f"slide {n}: positive table widths required")
        if kind in {"split", "square", "wide"}:
            asset = slide.get("image", {})
            require(isinstance(asset, dict) and isinstance(asset.get("path"), str) and asset["path"]
                    and isinstance(asset.get("description"), str) and asset["description"], f"slide {n}: image path and description required")
            require((path.parent / asset["path"]).is_file(), f"slide {n}: image file missing")
            require(asset.get("source") in source_ids, f"slide {n}: image source required")
            if slide.get("video"):
                require(isinstance(slide["video"], str), f"slide {n}: video must be a path string")
                require((path.parent / slide["video"]).is_file(), f"slide {n}: video missing")
        else:
            require(not slide.get("video"), f"slide {n}: video requires split, square or wide layout")
    require(len(slide_ids) == len(set(slide_ids)), "duplicate slide IDs")
    require(abs(elapsed-minutes) < .001, f"slide timing totals {elapsed:g}, expected {minutes:g} minutes")
    return data


def rich(text, size=L.BODY_PT, bold=False):
    require(text.count("**") % 2 == 0, "unclosed ** emphasis")
    return para([(part, {"bold": bold or bool(i % 2)}) for i, part in enumerate(text.split("**"))],
                size=size, space_after=L.SPEC["spacing"]["paragraph_gap"],
                line_spacing=L.SPEC["authoring"]["line_spacing"])


def block(slide, x, y, width, texts, size=L.BODY_PT, role="body", bold=False):
    result = slide.add_block(TextBlock(x, y, width, [rich(t, size, bold) for t in texts], role=role))
    result.layout()
    # Fail before a backend can draw a missing glyph as a square.
    for p in result.paras:
        for run in p.runs:
            font = L._pymupdf_font(run.family, run.bold, run.italic)
            missing = {ch for ch in run.text if not ch.isspace() and not font.has_glyph(ord(ch))}
            require(not missing, f"{slide.title}: font lacks glyphs {sorted(missing)}; use supported notation")
    return result


def prepare_image(source, target, trim=True):
    with PILImage.open(source) as im:
        im = im.convert("RGBA")
        background = PILImage.new("RGBA", im.size, "white"); background.alpha_composite(im)
        im = background.convert("RGB")
        if trim:
            difference = ImageChops.difference(im, PILImage.new("RGB", im.size, "white"))
            mask = difference.convert("L").point(lambda value: 255 if value > 12 else 0)
            bbox = mask.getbbox()
            if bbox:
                im = im.crop(bbox)
        im.save(target)


def add_table(slide, record, width, top):
    cfg = L.SPEC["authoring"]["table"]
    header, rows = record["header"], record["rows"]
    ratios = [w/sum(record["widths"]) for w in record["widths"]]
    height = cfg["header_height"] + cfg["row_height"]*len(rows)
    slide.tables.append(L.NativeTable(L.ML, top, width, height, ratios, header, rows, cfg["header_height"], cfg["row_height"]))
    y = top
    for n, row in enumerate([header, *rows]):
        h = cfg["header_height"] if n == 0 else cfg["row_height"]
        x = L.ML
        for text, ratio in zip(row, ratios):
            w = width*ratio
            slide.rects.append(Rect(x, y, w, h, fill=cfg["header_fill"] if n == 0 else L.WHITE, stroke=L.GRID))
            cell = block(slide, x+cfg["padding"], y+5, w-2*cfg["padding"], [text], cfg["font_size"], "caption", n == 0)
            # Ignore paragraph space-after when checking cell text itself.
            actual = sum(line.height for line in cell.layout())
            require(actual <= h-6, f"{slide.title}: table cell needs more room; shorten or split table")
            x += w
        y += h


def compose(data, folder):
    cfg = L.SPEC["authoring"]; width = cfg["content_width"]
    deck = Deck(data["brief"]["title"], data["brief"]["author"]); media = []
    qa = folder/"qa"; qa.mkdir(exist_ok=True)
    sources = {s["id"]: s for s in data.get("sources", [])}
    for n, record in enumerate(data["slides"], 1):
        kind = record["layout"]; slide = Slide(title=record["title"])
        if kind == "cover":
            cover = cfg["cover"]
            block(slide, L.ML, cover["title_y"], width, [record["title"]], L.COVER_PT, "cover")
            if record.get("subtitle"):
                block(slide, L.ML, cover["subtitle_y"], width, [record["subtitle"]], L.COVER_SUB_PT, "cover")
            block(slide, L.ML, cover["author_y"], width, [data["brief"]["author"]], L.CAPTION_PT, "caption")
        else:
            title = block(slide, L.ML, L.TITLE_Y, width, [record["title"]], L.TITLE_PT, "title")
            require(title.h <= L.CONTENT_TOP-L.TITLE_Y, f"slide {n}: title is too long")
            if kind in {"prose", "conclusion"}:
                block(slide, L.ML, L.CONTENT_TOP, width, record["body"])
            elif kind == "compare":
                c = cfg["compare"]
                for i, col in enumerate(record["columns"]):
                    x = L.ML+i*c["column_step"]
                    block(slide, x, c["heading_y"], c["column_width"], [col["title"]], bold=True)
                    block(slide, x, c["body_y"], c["column_width"], col["body"])
                if record.get("takeaway"):
                    block(slide, L.ML, c["takeaway_y"], width, [record["takeaway"]])
            elif kind == "procedure":
                c = cfg["procedure"]
                for i, text in enumerate(record["steps"]):
                    y = L.CONTENT_TOP+i*c["row_step"]
                    block(slide, L.ML, y, c["number_width"], [str(i+1)], bold=True)
                    block(slide, c["text_x"], y, width-(c["text_x"]-L.ML), [text])
            elif kind == "table":
                intro = block(slide, L.ML, L.CONTENT_TOP, width, record.get("body", []))
                add_table(slide, record["table"], width, max(cfg["table"]["top"], intro.y+intro.h+12))
            elif kind == "sources":
                refs = record.get("sources", [])
                require(refs, f"slide {n}: sources layout needs source IDs")
                texts = [f"[{list(sources).index(ref)+1}] {sources[ref]['title']}. {sources[ref]['description']}" for ref in refs]
                block(slide, L.ML, L.CONTENT_TOP, width, texts, L.CAPTION_PT+1)
            else:
                region = L.SPEC["layouts"]["scientific_"+("split" if kind == "split" else kind)]
                intro = block(slide, L.ML, L.CONTENT_TOP, width if kind == "wide" else region["text_width"], record.get("body", []))
                top = max(region["image_y"], intro.y+intro.h+12) if kind == "wide" else region["image_y"]
                available = region["image_y"]+region["image_height"]-top
                require(available > 30, f"slide {n}: introduction leaves no room for figure")
                asset = record["image"]; poster = qa/f"{record['id']}-image.png"
                require(re.fullmatch(r"[a-z0-9_-]+", record["id"]), f"slide {n}: use a lowercase filename-safe ID")
                prepare_image(folder/asset["path"], poster, asset.get("trim", True))
                with PILImage.open(poster) as im:
                    ratio = im.width/im.height
                    w = min(region["image_width"], available*ratio, im.width*72/(L.SPEC["images"]["min_native_dpi"]+1))
                h = w/ratio; x = region["image_x"]+(region["image_width"]-w)/2; y = top+(available-h)/2
                slide.images.append(Image(x, y, w, h, str(poster)))
                if record.get("video"):
                    require(asset.get("trim", True) is False, f"slide {n}: video poster must use trim: false to preserve movie ratio")
                    media.append((n, folder/record["video"], poster, (x,y,w,h)))
        for b in slide.blocks:
            actual_bottom = max((line.y+line.height-line.pieces[0][1].size*.98 for line in b.layout() if line.pieces), default=b.y)
            require(actual_bottom <= cfg["content_bottom"], f"slide {n}: text exceeds content area; shorten or split")
        for t in slide.tables:
            require(t.y+t.h <= cfg["content_bottom"], f"slide {n}: table exceeds content area")
        footer = cfg["footer"]
        block(slide, footer["x"], footer["y"], footer["width"], [f"{n:02d} / {len(data['slides'])}"], footer["size"], "caption")
        deck.add(slide)
    return deck, media


def embed_media(pptx, media):
    from pptx import Presentation
    from pptx.util import Pt
    from pptx.oxml.ns import qn
    prs = Presentation(pptx)
    for n, clip, poster, (x,y,w,h) in media:
        shape = prs.slides[n-1].shapes.add_movie(str(clip), Pt(x), Pt(y), Pt(w), Pt(h), poster_frame_image=str(poster), mime_type="video/mp4")
        for video in prs.slides[n-1]._element.iter(qn("p:video")):
            if any(t.get("spid") == str(shape.shape_id) for t in video.iter(qn("p:spTgt"))):
                for condition in video.iter(qn("p:cond")):
                    condition.set("delay", "0")
                for node in video.iter(qn("p:cMediaNode")):
                    node.set("vol", "0")
    prs.save(pptx)


def render_pages(pdf, folder):
    folder.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        for n, page in enumerate(document, 1):
            page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(folder/f"slide-{n:02d}.png")


def input_digest(manifest, data):
    """Reject stale exports after a content, asset, style or builder edit."""
    manifest = Path(manifest).resolve()
    paths = {manifest, DEFAULT_GUIDELINE, Path(__file__).resolve(),
             ROOT/"tools"/"presentation_script.py", ROOT/"tools"/"deckgen"/"layout.py",
             ROOT/"tools"/"deckgen"/"backends.py"}
    for slide in data["slides"]:
        if slide.get("image"):
            paths.add((manifest.parent/slide["image"]["path"]).resolve())
        if slide.get("video"):
            paths.add((manifest.parent/slide["video"]).resolve())
    digest = hashlib.sha256()
    # Hash names relative to the project when possible, so moving the whole
    # toolkit does not invalidate a reproducible delivery.
    for path in sorted(paths):
        digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def check_delivery(manifest):
    data = read_manifest(manifest); folder = Path(manifest).resolve().parent
    health = _selftest(L.SPEC); require(health["ok"], str(health["problems"]))
    output = folder/"dist"; qa = folder/"qa"; qa.mkdir(exist_ok=True)
    state_path = qa/"build-state.json"
    require(state_path.is_file(), "build state missing; run build first")
    state = json.loads(state_path.read_text())
    require(state["input_sha256"] == input_digest(manifest,data), "inputs changed since export; rebuild")
    checks = {}; failed = False
    for extension in ("pptx", "pdf"):
        target = output/f"slides.{extension}"
        require(target.is_file(), f"missing output: {target}")
        deck = load(target); require(len(deck.slides) == len(data["slides"]), "output slide count differs from manifest")
        for n,(rendered,record) in enumerate(zip(deck.slides,data["slides"]),1):
            title = rendered.heading.text if rendered.heading else ""
            require(" ".join(title.split()) == " ".join(record["title"].split()), f"slide {n}: output title differs from manifest; rebuild")
        result = build_report(deck, L.SPEC)
        errors = result.count(Severity.ERROR); warnings = result.count(Severity.WARN)
        checks[extension] = {"errors": errors, "warnings": warnings,
                             "findings": [str(f) for f in result.findings]}
        failed |= bool(errors or warnings)
    with ZipFile(output/"slides.pptx") as archive:
        names = archive.namelist()
        require(not any(name.startswith("ppt/notesSlides/") for name in names), "PPTX contains embedded notes")
        actual_media = {hashlib.sha256(archive.read(name)).hexdigest() for name in names
                        if name.startswith("ppt/media/") and name.endswith(".mp4")}
        expected_media = {hashlib.sha256((folder/s["video"]).read_bytes()).hexdigest()
                          for s in data["slides"] if s.get("video")}
        require(actual_media == expected_media, "embedded MP4 files differ from manifest")
        from lxml import etree
        ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
        for n, slide in enumerate(data["slides"], 1):
            xml = etree.fromstring(archive.read(f"ppt/slides/slide{n}.xml"))
            videos = xml.xpath("//p:video", namespaces=ns)
            require(len(videos) == bool(slide.get("video")), f"slide {n}: embedded video mismatch")
            if videos:
                require(videos[0].xpath("p:cMediaNode/p:cTn/p:stCondLst/p:cond/@delay", namespaces=ns) == ["0"], f"slide {n}: video does not autoplay")
                require(xml.xpath("count(//p:pic)", namespaces=ns) >= 2, f"slide {n}: missing static poster")
    with pymupdf.open(output/"speaker-script.pdf") as script:
        require(len(script.get_toc()) >= len(data["slides"]), "script must have a bookmark for every slide")
        text = "\n".join(page.get_text() for page in script)
        from presentation_script import script_labels
        slide_label = script_labels(data["brief"]["language"])["slide"]
        for n in range(1, len(data["slides"])+1):
            require(f"{slide_label} {n} / {len(data['slides'])}." in text, f"script missing slide {n}")
        require("\ufffd" not in text and "\u25a0" not in text, "missing script glyphs")
    checks["slides"] = len(data["slides"]); checks["minutes"] = data["brief"]["minutes"]
    checks["status"] = "FAIL" if failed else "PASS"
    (qa/"delivery-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    for fmt in ("pptx", "pdf"):
        print(f"{fmt}: {checks[fmt]['errors']} errors, {checks[fmt]['warnings']} warnings")
        for finding in checks[fmt]["findings"]:
            if "[INFO " not in finding:
                print(finding)
    require(not failed, "delivery failed; see qa/delivery-checks.json")
    return checks


def build(manifest):
    data = read_manifest(manifest); folder = Path(manifest).resolve().parent
    deck, media = compose(data, folder)
    output = folder/"dist"; output.mkdir(exist_ok=True)
    to_pdf(deck, output/"slides.pdf"); to_pptx(deck, output/"slides.pptx")
    if media:
        embed_media(output/"slides.pptx", media)
    from presentation_script import build_script
    build_script(data, output/"slides.pdf", output/"speaker-script.pdf")
    render_pages(output/"slides.pdf", folder/"qa"/"slides")
    (folder/"qa"/"build-state.json").write_text(json.dumps({"input_sha256":input_digest(manifest,data)},indent=2))
    check_delivery(manifest)
    print(f"Built {len(deck.slides)} slides and separate speaker script in {output}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="operation", required=True)
    init = sub.add_parser("init", help="create a topic-independent starter directory")
    init.add_argument("directory"); init.add_argument("--title")
    for name in ("build", "check"):
        parser = sub.add_parser(name); parser.add_argument("manifest")
    render = sub.add_parser("render"); render.add_argument("pdf"); render.add_argument("directory")
    args = ap.parse_args(argv)
    try:
        if args.operation == "init":
            target = Path(args.directory).resolve()
            require(not target.exists(), "directory already exists; choose a new path")
            shutil.copytree(ROOT/"templates"/"presentation", target)
            if args.title:
                path = target/"deck.yaml"; data = yaml.safe_load(path.read_text())
                data["brief"]["title"] = data["slides"][0]["title"] = args.title
                path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
            print(f"Created {target}/deck.yaml. Replace the example content before use.")
        elif args.operation == "build":
            build(args.manifest)
        elif args.operation == "check":
            check_delivery(args.manifest)
        else:
            render_pages(args.pdf, Path(args.directory))
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
