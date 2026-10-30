"""Typography: family, size, colour, contrast, emphasis discipline."""

from __future__ import annotations

import os
import re

from ..model import Finding, Severity

_CJK = re.compile(r"[\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF]")
_CODE_HINT = re.compile(
    r"(^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WITH|FROM|WHERE|GROUP BY|ORDER BY|"
    r"JOIN|HAVING|UNION|CASE|LIMIT|VALUES|SET|--|/\*|#!/)|[{};]\s*$|\b\w+\s*=\s*\w+\s*$|"
    r"^\s*[\w.]+\s*\(.*\)\s*\{)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://|www\.")


def _is_code_like(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _URL.search(t):
        return False
    return bool(_CODE_HINT.search(t))


def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def check_fonts(deck, spec) -> list[Finding]:
    f = spec["fonts"]
    allowed = {a.lower() for a in f["whitelist"]}
    # a monospace face for code is a deliberate second family, not an accident
    allowed |= {m.lower() for m in f.get("mono_whitelist", [])}
    banned = {a.lower() for a in f["blacklist"]}
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            for fam in set(tb.families):
                low = fam.lower()
                if low in banned:
                    out.append(
                        Finding(
                            "font.banned",
                            Severity.ERROR,
                            f"{fam!r} is on the blacklist: {tb.text[:30]!r}",
                            s.number,
                            str(tb.rect),
                            f"use one of {', '.join(f['whitelist'])}",
                        )
                    )
                elif low not in allowed:
                    root = re.sub(r"[\-\+,].*$", "", low)
                    if root not in allowed:
                        out.append(
                            Finding(
                                "font.offlist",
                                Severity.WARN,
                                f"{fam!r} is not in the font whitelist",
                                s.number,
                                str(tb.rect),
                                "one family per deck",
                            )
                        )
    return out


def check_code_font(deck, spec) -> list[Finding]:
    f = spec["fonts"]
    if not f.get("require_mono_for_code", True):
        return []
    mono = {m.lower() for m in f.get("mono_whitelist", [])}
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            if not _is_code_like(tb.text):
                continue
            for fam in set(tb.families):
                root = re.sub(r"[\-\+,].*$", "", fam.lower())
                if root not in mono:
                    out.append(
                        Finding(
                            "font.code_not_mono",
                            Severity.WARN,
                            f"code rendered in {fam!r}, not a monospace face: {tb.text[:32]!r}",
                            s.number,
                            str(tb.rect),
                            f"switch to {f.get('mono_whitelist', ['Consolas'])[0]}",
                        )
                    )
    return out


def check_sizes(deck, spec) -> list[Finding]:
    roles = spec["fonts"]["roles"]
    body = roles["body"]["size"]
    title = roles["title"]["size"]
    min_size = spec["density"]["min_font_size"]
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            if not tb.text:
                continue
            for size in sorted(set(tb.sizes)):
                if size < min_size - 0.05:
                    out.append(
                        Finding(
                            "size.min",
                            Severity.ERROR,
                            f"{size:.1f}pt is below the {min_size}pt readability floor",
                            s.number,
                            str(tb.rect),
                            "shrink the content, not the type",
                        )
                    )
            if s.number == 1:
                continue  # the cover has its own roles, checked by `cover`
            if tb.is_title and abs(tb.dominant_size - title) > 1.5:
                out.append(
                    Finding(
                        "size.title",
                        Severity.WARN,
                        f"title is {tb.dominant_size:.1f}pt, spec {title}pt",
                        s.number,
                        str(tb.rect),
                        "use the layout placeholder so the size is automatic",
                    )
                )
            elif not tb.is_title and abs(tb.dominant_size - body) > 3.5 and tb.dominant_size < title:
                out.append(
                    Finding(
                        "size.offscale",
                        Severity.INFO,
                        f"body text at {tb.dominant_size:.1f}pt (spec {body}pt)",
                        s.number,
                        str(tb.rect),
                        "a second body size is fine for captions, not for prose",
                    )
                )
    return out


def check_title_weight(deck, spec) -> list[Finding]:
    want = spec["fonts"]["roles"]["title"].get("weight", "regular")
    if want == "bold":
        return []
    out = []
    for s in deck.slides:
        t = s.heading
        if t is None or not t.text:
            continue
        if any(l.bold for l in t.lines):
            out.append(
                Finding(
                    "title.weight",
                    Severity.WARN,
                    f"title is bold; house style is {want}: {t.text[:30]!r}",
                    s.number,
                    str(t.rect),
                    "titles get their weight from size, not from bold",
                )
            )
    return out


def check_colors(deck, spec) -> list[Finding]:
    c = spec["colors"]
    allowed = {x.lower() for x in c["whitelist"]}
    accent = c["accent"].lower()
    secondaries = {x.lower() for x in c.get("accent_secondary", [])}
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            for col in set(tb.colors):
                if col.lower() in allowed:
                    continue
                out.append(
                    Finding(
                        "color.offlist",
                        Severity.WARN,
                        f"{col} is not in the palette: {tb.text[:30]!r}",
                        s.number,
                        str(tb.rect),
                        f"palette: {', '.join(c['whitelist'])}",
                    )
                )
    secondary_uses = sum(
        1
        for s in deck.slides
        for tb in s.text_boxes
        for col in tb.colors
        if col.lower() in secondaries
    )
    if secondary_uses > 4:
        out.append(
            Finding(
                "color.accent_spread",
                Severity.WARN,
                f"secondary accent colours used {secondary_uses} times; "
                f"{accent} should carry the deck",
                fix="one accent colour, used sparingly",
            )
        )
    return out


def is_large(size: float, bold: bool) -> bool:
    """WCAG 'large text': >=18pt, or >=14pt bold."""
    return size >= 18 or (bold and size >= 14)


def local_background(slide, rect, canvas_bg: str) -> str:
    """The colour actually behind a box.

    Picks the *smallest* fill that covers the box, so a table cell beats the
    page background. A shape spanning the whole slide is the canvas itself and
    is skipped.
    """
    slide_area = slide.rect.area
    best, best_area = None, 0.0
    for sh in slide.shapes:
        if not sh.visible or sh.fill is None:
            continue
        if sh.rect.area >= slide_area * 0.98:
            continue  # the page background, not a local fill
        area = sh.rect.overlap_area(rect)
        if area < 0.6 * rect.area:
            continue
        if best is None or sh.rect.area < best_area:
            best, best_area = sh, sh.rect.area
    return best.fill if best is not None else canvas_bg


def check_contrast(deck, spec) -> list[Finding]:
    canvas_bg = spec["canvas"].get("background", "#ffffff")
    need_normal = spec["colors"].get("min_contrast_vs_background", 4.5)
    need_large = spec["colors"].get("min_contrast_large_text", 3.0)
    accent = spec["colors"]["accent"].lower()
    accent_floor = spec["colors"].get("accent_min_contrast", need_large)
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            for run in tb.runs:
                if not run.text.strip():
                    continue
                # resolve the background per run: a block bbox can span cells
                bg = local_background(s, run.rect, canvas_bg)
                ratio = contrast_ratio(run.color, bg)
                large = is_large(run.size, run.bold)
                if run.color.lower() == accent and large:
                    need = max(need_large, accent_floor)
                else:
                    need = need_large if large else need_normal
                if ratio >= need:
                    continue
                sev = Severity.ERROR if not large else Severity.WARN
                out.append(
                    Finding(
                        "color.contrast",
                        sev,
                        f"{run.color} on {bg} is {ratio:.1f}:1 at {run.size:.0f}pt"
                        f"{' bold' if run.bold else ''} (need {need}:1): "
                        f"{run.text.strip()[:28]!r}",
                        s.number,
                        str(tb.rect),
                        "darken the text, or set it on a solid dark fill",
                    )
                )
    return out


def check_accent_discipline(deck, spec) -> list[Finding]:
    """The accent colour is for short lead-ins, never for running prose."""
    accent = spec["colors"]["accent"].lower()
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            for run in tb.runs:
                if run.color.lower() != accent or not run.text.strip():
                    continue
                if len(run.words) > 6:
                    out.append(
                        Finding(
                            "color.accent_prose",
                            Severity.WARN,
                            f"{len(run.words)} words of accent-coloured prose: "
                            f"{run.text.strip()[:36]!r}",
                            s.number,
                            str(tb.rect),
                            "reserve the accent for a short bold lead-in or a link",
                        )
                    )
    return out


def check_emphasis(deck, spec) -> list[Finding]:
    """Bold is the highlighting device: enough to work, not so much it is noise."""
    out = []
    for s in deck.slides:
        words = s.words
        if len(words) < 20:
            continue
        bold = sum(tb.bold_words for tb in s.text_boxes)
        share = bold / len(words)
        if share > 0.35:
            out.append(
                Finding(
                    "emphasis.too_much",
                    Severity.WARN,
                    f"{100 * share:.0f}% of words are bold - bold stops meaning anything",
                    s.number,
                    fix="bold only the term being defined, not the whole sentence",
                )
            )
        elif bold == 0 and len(words) >= 60:
            out.append(
                Finding(
                    "emphasis.none",
                    Severity.INFO,
                    f"{len(words)} words and not one bold term",
                    s.number,
                    fix="consider highlighting a key term when it helps reading; narrative prose may remain regular",
                )
            )
    return out


def check_no_justification(deck, spec) -> list[Finding]:
    out = []
    for s in deck.slides:
        for tb in s.text_boxes:
            if tb.align == "justify":
                out.append(
                    Finding(
                        "align.justify",
                        Severity.WARN,
                        "justified text creates rivers in narrow columns",
                        s.number,
                        str(tb.rect),
                        "use left alignment",
                    )
                )
    return out
