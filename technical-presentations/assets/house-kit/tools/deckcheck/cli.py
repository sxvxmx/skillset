"""deckcheck - presentation consistency linter.

    deckcheck reference.pdf
    deckcheck deck.pptx --guideline guideline.yaml --strict
    deckcheck deck.pdf --only overlap- gutter,leading --json report.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import asdict
from pathlib import Path

from . import loaders, segment
from .checks import CHECKS, CHECK_NAMES
from .model import Deck, Report, Severity

DEFAULT_GUIDELINE = Path(__file__).resolve().parents[2] / "guideline.yaml"


def load_guideline(path: str | Path) -> dict:
    import yaml

    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"guideline not found: {p}\n"
            "Create one with:  python tools/extract_spec.py <reference-deck.pdf> -o guideline.yaml"
        )
    with p.open(encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    return spec


def _selftest(spec: dict) -> dict:
    """Sanity-check the guideline itself before blaming the deck."""
    problems = []
    if not isinstance(spec, dict):
        return {"ok": False, "problems": ["guideline must be a YAML mapping"]}
    required = {
        "canvas": ("width", "height", "background"),
        "grid": ("margin_left", "margin_right", "margin_top", "margin_bottom", "content_top", "content_bottom"),
        "fonts": ("whitelist", "blacklist", "roles"),
        "colors": ("whitelist", "accent"),
        "spacing": ("line_height_ratio", "paragraph_gap", "column_gutter", "padding_in_frame"),
        "density": ("words_per_slide", "chars_per_slide", "bullets_per_slide", "lines_per_slide", "min_font_size", "max_title_words"),
        "images": ("target_area_pct", "max_area_pct", "coverage_target_pct", "slides_with_image_target", "min_native_dpi", "max_aspect_distortion"),
        "borders": ("whitelist", "frame"),
        "structure": (),
    }
    for section, keys in required.items():
        if not isinstance(spec.get(section), dict):
            problems.append(f"{section} must be a mapping")
            continue
        for key in keys:
            if key not in spec[section]:
                problems.append(f"missing {section}.{key}")
    if problems:
        return {"ok": False, "problems": problems}
    c = spec.get("canvas", {})
    def positive(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
    if not all(positive(c[k]) for k in ("width", "height")):
        problems.append("canvas dimensions must be finite positive numbers")
    else:
        ratio = c["width"] / c["height"]
        if abs(ratio - 16 / 9) > 0.02:
            problems.append(f"canvas aspect {ratio:.3f} is not 16:9")
    g = spec.get("grid", {})
    if not all(positive(g[k]) for k in ("content_top", "content_bottom")):
        problems.append("content band limits must be finite positive numbers")
    elif g["content_bottom"] <= g["content_top"]:
        problems.append("grid.content_bottom must be below grid.content_top")
    pair = spec["spacing"]["line_height_ratio"]
    if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(positive(x) for x in pair) or pair[0] >= pair[1]:
        problems.append("spacing.line_height_ratio must be an increasing pair")
    roles = spec["fonts"]["roles"]
    for role in ("title", "body", "cover_title", "cover_subtitle"):
        if not isinstance(roles, dict) or not isinstance(roles.get(role), dict) or not positive(roles[role].get("size")):
            problems.append(f"fonts.roles.{role}.size must be a positive number")
    palette = spec["colors"]["whitelist"]
    if not isinstance(palette, list) or not palette:
        problems.append("colors.whitelist must be a non-empty list")
        palette = []
    for name, color in [("canvas.background", c["background"]), ("colors.accent", spec["colors"]["accent"]), *[("colors.whitelist", x) for x in palette]]:
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            problems.append(f"{name} must contain #rrggbb colours")
    authoring = spec.get("authoring")
    if authoring is not None:
        if not isinstance(authoring, dict):
            problems.append("authoring must be a mapping")
        else:
            for key in ("content_width", "content_bottom", "line_spacing"):
                if not positive(authoring.get(key)):
                    problems.append(f"authoring.{key} must be positive")
            footer = authoring.get("footer", {})
            if not isinstance(footer, dict) or not all(positive(footer.get(k)) for k in ("x", "y", "width", "size")):
                problems.append("authoring.footer needs positive x, y, width, size")
            elif positive(c["width"]) and positive(c["height"]) and (footer["x"]+footer["width"] > c["width"] or footer["y"]+footer["size"] > c["height"]):
                problems.append("authoring.footer must fit on the canvas")
    script = spec.get("speaker_script")
    if script is not None and (not isinstance(script, dict) or script.get("location") != "separate_pdf"
                               or not isinstance(script.get("required_fields"), list)
                               or not {"see", "message", "speech"}.issubset(script["required_fields"])):
        problems.append("speaker_script must require see, message, speech in a separate_pdf")
    return {"ok": not problems, "problems": problems}


def build_report(deck: Deck, spec: dict, only: set[str] | None = None) -> Report:
    segment.segment_deck(deck, spec)
    report = Report(deck=deck.path)
    for name, fn in CHECKS:
        if only is not None and name not in only:
            continue
        try:
            report.extend(fn(deck, spec) or [])
        except Exception as exc:  # a broken check must not kill the run
            report.add(
                "engine.check_crashed",
                Severity.ERROR,
                f"{name}: check crashed: {type(exc).__name__}: {exc}",
                fix="this is a bug in deckcheck, not in the deck",
            )
    report.stats = deck_stats(deck)
    report.stats["checks_selected"] = sum(only is None or name in only for name, _ in CHECKS)
    report.stats["checks_failed"] = sum(f.check == "engine.check_crashed" for f in report.findings)
    return report


def deck_stats(deck: Deck) -> dict:
    words = [len(s.words) for s in deck.slides]
    lines = [len(s.all_lines) for s in deck.slides]
    imgs = sum(len(s.images) for s in deck.slides)
    fams: dict[str, int] = {}
    sizes: dict[float, int] = {}
    for s in deck.slides:
        for tb in s.text_boxes:
            for f in tb.families:
                fams[f] = fams.get(f, 0) + 1
            for z in tb.sizes:
                sizes[round(z)] = sizes.get(round(z), 0) + 1
    return {
        "slides": len(deck.slides),
        "canvas": f"{deck.canvas.width:.0f}x{deck.canvas.height:.0f}pt",
        "format": deck.fmt,
        "words_total": sum(words),
        "words_median": statistics.median(words) if words else 0,
        "words_max": max(words, default=0),
        "lines_max": max(lines, default=0),
        "images": imgs,
        "slides_with_image": sum(1 for s in deck.slides if s.images),
        "coverage_pct": round(statistics.mean([s.image_area_pct() for s in deck.slides]), 1)
        if deck.slides
        else 0.0,
        "fonts": dict(sorted(fams.items(), key=lambda kv: -kv[1])),
        "sizes": dict(sorted(sizes.items())),
    }


COLOR = {
    Severity.ERROR: "\033[31m",
    Severity.WARN: "\033[33m",
    Severity.INFO: "\033[36m",
}
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def render(report: Report, color: bool = True, show_info: bool = True, strict: bool = False) -> str:
    def c(sev, text):
        return f"{COLOR[sev]}{text}{RESET}" if color else text

    lines = []
    st = report.stats
    lines.append(f"{BOLD if color else ''}deckcheck{RESET if color else ''}  {report.deck}")
    lines.append(
        f"  {st.get('slides')} slides | {st.get('canvas')} {st.get('format')} | "
        f"{st.get('words_total')} words (median {st.get('words_median')}, max "
        f"{st.get('words_max')}) | {st.get('images')} images on "
        f"{st.get('slides_with_image')} slides, {st.get('coverage_pct')}% coverage"
    )
    if st.get("fonts"):
        lines.append(f"  fonts: " + ", ".join(f"{k} x{v}" for k, v in st["fonts"].items()))
    lines.append("")

    findings = [f for f in report.sorted_findings() if show_info or f.severity is not Severity.INFO]
    if not findings:
        lines.append(c(Severity.INFO, "  clean - no findings"))
    else:
        by_sev = {s: [f for f in findings if f.severity is s] for s in Severity}
        width = max((len(f"{f.slide or ''}") for f in findings), default=4)
        for sev in (Severity.ERROR, Severity.WARN, Severity.INFO):
            group = by_sev[sev]
            if not group:
                continue
            lines.append(
                c(sev, f"{BOLD if color else ''}{sev.value.upper()} ({len(group)}){RESET if color else ''}")
            )
            for f in group:
                loc = f"p{f.slide}" if f.slide else "deck"
                lines.append(f"  {c(sev, loc.rjust(width))}  {f.check:<20} {f.message}")
                if f.fix:
                    lines.append(f"  {' ' * width}  {DIM if color else ''}-> {f.fix}{RESET if color else ''}")
            lines.append("")

    n_e, n_w, n_i = (report.count(s) for s in (Severity.ERROR, Severity.WARN, Severity.INFO))
    verdict = "PASS" if n_e == 0 and (not strict or n_w == 0) else "FAIL"
    lines.append(f"{BOLD if color else ''}{verdict}{RESET if color else ''}  {n_e} error, {n_w} warn, {n_i} info")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="deckcheck",
        description="Lint a .pdf or .pptx deck against a style guideline.",
    )
    ap.add_argument("deck", nargs="?", help="path to deck.pdf or deck.pptx")
    ap.add_argument("-g", "--guideline", default=DEFAULT_GUIDELINE)
    ap.add_argument("--only", help="comma-separated check names to run (default: all)")
    ap.add_argument("--skip", help="comma-separated check names to skip")
    ap.add_argument("--json", help="also write a machine-readable report here")
    ap.add_argument("--minutes", type=float, help="talk length, enables words-per-minute pacing")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on warnings as well as errors; info is advisory",
    )
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="suppress info-level findings")
    ap.add_argument(
        "--list-checks", action="store_true", help="print every check name and exit"
    )
    args = ap.parse_args(argv)

    if args.list_checks:
        for name, _ in CHECKS:
            print(name)
        return 0
    if not args.deck:
        ap.error("a deck path is required unless --list-checks is used")
    if args.minutes is not None and (not math.isfinite(args.minutes) or args.minutes <= 0):
        ap.error("--minutes must be a finite positive number")

    spec = load_guideline(args.guideline)
    health = _selftest(spec)
    if not health["ok"]:
        print("guideline looks malformed:", file=sys.stderr)
        for p in health["problems"]:
            print(f"  - {p}", file=sys.stderr)
        return 2

    only = None
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = only - set(CHECK_NAMES)
        if unknown:
            print(f"unknown check(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"available: {', '.join(CHECK_NAMES)}", file=sys.stderr)
            return 2
    if args.skip:
        skip = {s.strip() for s in args.skip.split(",") if s.strip()}
        unknown = skip - set(CHECK_NAMES)
        if unknown:
            ap.error(f"unknown check(s): {', '.join(sorted(unknown))}")
        only = (set(CHECK_NAMES) if only is None else only) - skip
    if only == set():
        ap.error("no checks selected")

    deck = loaders.load(args.deck)
    report = build_report(deck, spec, only)

    if args.minutes:
        from .checks import density

        report.extend(density.check_pace_per_minute(deck, spec, args.minutes) or [])

    if not args.quiet:
        print(render(report, color=not args.no_color, show_info=True, strict=args.strict))
    else:
        errs = report.count(Severity.ERROR)
        warns = report.count(Severity.WARN)
        print(f"{errs} error, {warns} warn")

    if args.json:
        payload = {
            "deck": report.deck,
            "stats": report.stats,
            "guideline": str(args.guideline),
            "counts": {s.value: report.count(s) for s in Severity},
            "findings": [
                {**asdict(f), "severity": f.severity.value} for f in report.sorted_findings()
            ],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"wrote {args.json}")

    if report.count(Severity.ERROR):
        return 1
    if args.strict and report.count(Severity.WARN):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
