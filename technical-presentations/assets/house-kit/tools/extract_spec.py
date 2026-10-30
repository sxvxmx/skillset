#!/usr/bin/env python3
"""Reverse-engineer a style guideline from an existing deck.

Point it at a deck you like and it writes a `guideline.yaml` that `deckcheck`
can lint other decks against.

    python tools/extract_spec.py reference.pdf -o guideline.yaml
    python tools/extract_spec.py ref.pptx --merge guideline.yaml

Every number it reports is measured, not assumed - but it reports the *shape* of
the distribution, so read the output before trusting it. A guideline fitted to
one deck encodes that deck's accidents as much as its intentions.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from deckcheck import loaders, segment  # noqa: E402
from deckcheck.model import Severity  # noqa: E402

BODY_ROLES = ("title", "body", "caption", "code")


def _norm(name: str) -> str:
    from deckcheck.loaders import _norm_family

    return _norm_family(name)


def _is_grey(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return True
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) <= 12


def _mode(values, default=None):
    vals = [v for v in values if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else default


def _median(values, default=0.0):
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 2) if vals else default


def _range(values, lo_q=0.1, hi_q=0.9):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return [0.0, 0.0]
    i, j = int(len(vals) * lo_q), max(int(len(vals) * hi_q), int(len(vals) * lo_q) + 1)
    return [round(vals[i], 2), round(vals[j - 1], 2)]


def _pct(values, q):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    return round(vals[min(len(vals) - 1, int(len(vals) * q))], 2)


def extract(path: str) -> dict:
    deck = loaders.load(path)
    canvas = deck.canvas

    # ---- typography ------------------------------------------------------
    sizes_by_role: dict[str, list[float]] = {r: [] for r in BODY_ROLES}
    fams: Counter = Counter()
    colors: Counter = Counter()
    mono: set[str] = set()
    for s in deck.slides:
        for tb in s.text_boxes:
            for run in tb.runs:
                if not run.text.strip():
                    continue
                fams[run.font] += len(run.words)
                colors[run.color.lower()] += len(run.words)
                if tb.is_title:
                    sizes_by_role["title"].append(run.size)
                elif run.size >= 13:
                    sizes_by_role["code"].append(run.size)
                elif run.size <= 10:
                    sizes_by_role["caption"].append(run.size)
                else:
                    sizes_by_role["body"].append(run.size)

    cover = deck.slides[0] if deck.slides else None
    cover_runs = [r for tb in cover.text_boxes for r in tb.runs] if cover else []
    cover_sizes = sorted({r.size for r in cover_runs if r.text.strip()}, reverse=True)

    # ---- layout ----------------------------------------------------------
    # Segment first: a table's gridlines and a frame's border are not content,
    # so they must not define the margins.
    stub = {"canvas": {"width": canvas.width}, "grid": {"column_split_x": canvas.width / 2}}
    for s in deck.slides:
        segment.segment(s, stub)

    def prose(s):
        return [
            e
            for e in list(s.text_boxes) + list(s.images)
            if e.rect.width > 8
            and e.rect.y0 < canvas.y1
            and getattr(e, "region", "free") not in ("table", "frame")
        ]

    xs0, xs1, ys0, ys1 = [], [], [], []
    body_tops, slide_bottoms, title_x, title_y = [], [], [], []
    for s in deck.slides[1:]:
        # elements that bleed off an edge are deliberate; they do not set margins
        els = [
            e
            for e in prose(s)
            if e.rect.x0 >= canvas.x0 - 0.5
            and e.rect.y0 >= canvas.y0 - 0.5
            and e.rect.x1 <= canvas.x1 + 0.5
            and e.rect.y1 <= canvas.y1 + 0.5
        ]
        if els:
            xs0.append(min(e.rect.x0 for e in els) - canvas.x0)
            xs1.append(max(e.rect.x1 for e in els) - canvas.x1)
            ys0.append(min(e.rect.y0 for e in els) - canvas.y0)
            ys1.append(max(e.rect.y1 for e in els) - canvas.y1)
        t = s.title_box
        if t is not None:
            title_x.append(t.rect.x0 - canvas.x0)
            title_y.append(t.rect.y0 - canvas.y0)
        bodies = [
            tb
            for tb in s.body_boxes
            if tb.text and tb.region not in ("table", "frame")
        ]
        body_tops += [tb.rect.y0 - canvas.y0 for tb in bodies]
        # per slide, how far down the content actually reaches
        slide_bottoms.append(max((tb.rect.y1 for tb in bodies), default=canvas.y0))

    # ---- spacing ---------------------------------------------------------
    pitches: list[float] = []
    para_gaps: list[float] = []
    from deckcheck.checks.spacing import para_breaks

    for s in deck.slides:
        for tb in s.text_boxes:
            lines = tb.lines
            size = tb.dominant_size
            if size <= 0:
                continue
            breaks = {(id(a), id(b)) for a, b, _ in para_breaks(tb)}
            for a, b in zip(lines, lines[1:]):
                pitch = b.rect.y0 - a.rect.y0
                if pitch <= 0 or (id(a), id(b)) in breaks:
                    continue
                if pitch < size * 1.9:
                    pitches.append(pitch / size)
            para_gaps += [g for _, _, g in para_breaks(tb)]

    # ---- images ----------------------------------------------------------
    img_areas = [100 * im.rect.area / s.area for s in deck.slides for im in s.images]
    coverage = [s.image_area_pct() for s in deck.slides]
    with_img = sum(1 for s in deck.slides if s.images) / max(1, len(deck.slides))

    # ---- borders ---------------------------------------------------------
    strokes: Counter = Counter()
    for s in deck.slides:
        for sh in s.shapes:
            if sh.visible and sh.stroke and sh.width > 0:
                strokes[(sh.stroke.lower(), round(sh.width, 2), tuple(sh.dash or ()))] += 1

    # ---- density ---------------------------------------------------------
    words = [len(s.words) for s in deck.slides]
    prose_lines = []
    for s in deck.slides:
        n = sum(1 for ln in s.all_lines if ln.text)
        n -= sum(len(tb.lines) for tb in s.text_boxes if tb.region == "table")
        prose_lines.append(n)
    bullets = []
    for s in deck.slides:
        n = 0
        for tb in s.text_boxes:
            if tb.is_title or not tb.text:
                continue
            n += 1 + len(para_breaks(tb))
        bullets.append(n)

    return {
        "meta": {
            "source": Path(path).name,
            "slides": len(deck.slides),
            "format": deck.fmt,
            "generated_by": "tools/extract_spec.py - measured, please review",
        },
        "canvas": {
            "width": round(canvas.width, 2),
            "height": round(canvas.height, 2),
            "aspect": f"{canvas.width / canvas.height:.3f}" if canvas.height else "",
            "background": "#ffffff",
        },
        "fonts": {
            "whitelist": sorted({_norm(f) for f in fams}),
            "blacklist": [
                "Times New Roman",
                "Georgia",
                "Garamond",
                "Comic Sans MS",
                "Papyrus",
                "Impact",
            ],
            "mono_whitelist": [
                "Menlo",
                "Monaco",
                "Consolas",
                "Courier New",
                "Roboto Mono",
                "Source Code Pro",
            ],
            "require_mono_for_code": True,
            "roles": {
                "cover_title": {"size": cover_sizes[0] if cover_sizes else 44},
                "cover_subtitle": {
                    "size": cover_sizes[1] if len(cover_sizes) > 1 else 24,
                    "color": _mode(
                        [r.color.lower() for r in cover_runs if r.text.strip() and r.size < (cover_sizes[0] if cover_sizes else 0)],
                        "#595959",
                    ),
                },
                "title": {
                    "size": _mode(sizes_by_role["title"], 25),
                    "weight": "regular",
                    "align": "left",
                },
                "body": {
                    "size": _mode(sizes_by_role["body"], 12),
                    "weight": "regular",
                    "align": "left",
                },
                "bullet": {"size": _mode(sizes_by_role["body"], 12), "marker": "●"},
                "caption": {"size": _mode(sizes_by_role["caption"], 10)},
                "code": {"size": _mode(sizes_by_role["code"], 14), "family": "mono"},
            },
        },
        "colors": {
            "text_primary": _mode(list(colors), "#000000"),
            "text_muted": _mode(
                [c for c in colors if _is_grey(c) and c not in ("#000000", "#ffffff")], "#595959"
            ),
            "accent": _mode([c for c in colors if not _is_grey(c)], "#4285f4"),
            "whitelist": [c for c, _ in colors.most_common(8)],
            "min_contrast_vs_background": 4.5,
            "min_contrast_large_text": 3.0,
            "accent_min_contrast": 3.0,
        },
        "grid": {
            # a margin is the *typical* inset, so take the median per slide and
            # then the median across slides
            "margin_left": _median(xs0, 31.0),
            "margin_right": _median([-v for v in xs1], 28.0),
            "margin_top": _median(ys0, 46.0),
            # the bottom edge is set per slide, then across slides at the 90th
            # percentile, so one overflowing slide cannot redefine the band
            "margin_bottom": round(canvas.height - _pct(slide_bottoms, 0.9), 2),
            "title_baseline_y": round(_median(title_y, 46.0), 2),
            "content_top": _pct(body_tops, 0.05),
            "content_top_tolerance": 8.0,
            "content_bottom": round(_pct(slide_bottoms, 0.9), 2),
            "columns": 2,
            "column_split_x": round(canvas.width / 2, 2),
            "gutter": _median(para_gaps, 12.0),
            "snap_tolerance": 3.0,
        },
        "spacing": {
            "line_height_ratio": _range(pitches, 0.05, 0.95),
            "paragraph_gap": _median(para_gaps, 12.0),
            "column_gutter": _range(_column_gutters(deck), 0.1, 0.9),
            "gutter_consistency_tolerance": 25.0,
            "padding_in_frame": [3.0, 12.0],
        },
        "density": {
            "words_per_slide": {
                "min": min(words) if words else 0,
                "target": [int(_pct(words, 0.25)), int(_pct(words, 0.75))],
                "max": int(_pct(words, 0.95)),
            },
            "chars_per_slide": {
                "target": [200, int(_pct([s.char_count for s in deck.slides], 0.9))],
                "max": int(_pct([s.char_count for s in deck.slides], 0.98)),
            },
            "bullets_per_slide": {
                "target": [2, int(_pct(bullets, 0.75))],
                "max": int(_pct(bullets, 0.95)),
            },
            "lines_per_slide": {"max": int(_pct(prose_lines, 0.9))},
            "min_font_size": int(min([r.size for s in deck.slides for tb in s.text_boxes
                                      for r in tb.runs if r.text.strip()] or [9])),
            "max_title_words": 8,
        },
        "images": {
            "target_area_pct": [int(_pct(img_areas, 0.1)), int(_pct(img_areas, 0.9))],
            "max_area_pct": int(_pct(img_areas, 0.98)),
            "hero_max_area_pct": int(max(img_areas) if img_areas else 60),
            "coverage_target_pct": [int(statistics.mean(coverage) * 0.7),
                                    int(statistics.mean(coverage) * 1.3)],
            "slides_with_image_target": [round(with_img * 0.6, 2), round(min(1.0, with_img * 1.3), 2)],
            "min_native_dpi": 144,
            "max_aspect_distortion": 0.02,
            "align_to": "column_edges",
            "align_tolerance": 3.0,
        },
        "borders": {
            "frame": {
                "color": _mode([c for (c, _, _) in strokes], "#4285f4"),
                "width": _mode([w for (_, w, d) in strokes if d], 0.75),
                "dash": list(_mode([d for (_, _, d) in strokes if d], (3, 2.25))),
                "fill": "none",
            },
            "frame_emphasis": {"color": "#4285f4", "width": 1.5, "dash": None, "fill": "none"},
            "table_grid": {"color": "#c4c7c5", "width": 0.75, "dash": None},
            "whitelist": [
                {"color": c, "widths": sorted({w for (cc, w, _) in strokes if cc == c}),
                 "dashes": sorted({d for (cc, _, d) in strokes if cc == c})}
                for c in {c for (c, _, _) in strokes}
            ],
            "width_tolerance": 0.1,
        },
        "structure": {
            "require_title": True,
            "title_position_locked": True,
            "duplicate_titles_warn": 2,
            "flag_build_slides": True,
            "allow_rounded_corners": False,
            "allow_shadows": False,
            "allow_gradients": False,
            "allow_tinted_fills": True,
            "tinted_fill_max_per_slide": 2,
        },
    }


def _column_gutters(deck) -> list[float]:
    spec_stub = {
        "canvas": {"width": deck.canvas.width},
        "grid": {"column_split_x": deck.canvas.width / 2},
    }
    out = []
    for s in deck.slides:
        segment.segment(s, spec_stub)
        prose = [
            e
            for e in list(s.text_boxes) + list(s.images)
            if e.region.startswith("col") and not hasattr(e, "lines")
            or (e.region.startswith("col") and hasattr(e, "runs"))
        ]
        left = [e for e in prose if e.region == "col0"]
        right = [e for e in prose if e.region == "col1"]
        if left and right and not any(hasattr(e, "digest") for e in left + right):
            g = min(e.rect.x0 for e in right) - max(e.rect.x1 for e in left)
            if g > 0:
                out.append(g)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("deck", help="reference .pdf or .pptx")
    ap.add_argument("-o", "--out", default="guideline.yaml")
    ap.add_argument("--merge", help="existing guideline to update instead of replacing")
    ap.add_argument("--check", action="store_true", help="only report, do not write")
    args = ap.parse_args(argv)

    spec = extract(args.deck)
    if args.merge:
        existing = yaml.safe_load(Path(args.merge).read_text()) or {}
        for k, v in existing.items():
            if k == "meta":
                v["derived_from"] = spec["meta"]["source"]
                spec["meta"] = {**spec["meta"], **v}
            else:
                spec.setdefault(k, v)
    header = (
        "# Presentation style guideline\n"
        f"# Measured from {spec['meta']['source']} ({spec['meta']['slides']} slides).\n"
        "# Regenerate:  python tools/extract_spec.py <reference-deck> -o guideline.yaml\n"
        "# REVIEW THE NUMBERS: this fits the deck's habits, including its mistakes.\n"
        "# All geometry is PDF points (1/72 in).\n\n"
    )
    text = header + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100)
    if args.check:
        print(text)
        return 0
    Path(args.out).write_text(text)
    print(f"wrote {args.out}")
    print(f"  fonts      : {', '.join(spec['fonts']['whitelist'])}")
    print(f"  title/body : {spec['fonts']['roles']['title']['size']}pt / "
          f"{spec['fonts']['roles']['body']['size']}pt")
    print(f"  margins    : L{spec['grid']['margin_left']} R{spec['grid']['margin_right']} "
          f"T{spec['grid']['margin_top']} B{spec['grid']['margin_bottom']}")
    print(f"  leading    : {spec['spacing']['line_height_ratio']}x")
    print(f"  words/slide: {spec['density']['words_per_slide']['target']} "
          f"(max {spec['density']['words_per_slide']['max']})")
    print(f"  borders    : {spec['borders']['whitelist']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
