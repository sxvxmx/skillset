"""Structure: titles, build slides, cover conventions, narrative arc."""

from __future__ import annotations

import re

from ..model import Finding, Severity

# Trailing full stop on a slide title is a copy-paste habit, not a style choice.
TITLE_PUNCT = re.compile(r"[.:;,]$")


def check_numbering(deck, spec) -> list[Finding]:
    if not spec["structure"].get("require_slide_numbers", False):
        return []
    if not deck.slides:
        return [Finding("structure.empty", Severity.ERROR, "presentation has no slides")]
    out = []
    footer_size = spec.get("authoring", {}).get("footer", {}).get("size", 9)
    for slide in deck.slides:
        footers = [tb.text.strip() for tb in slide.text_boxes
                   if tb.rect.y0 >= slide.rect.height - 50 and tb.dominant_size <= footer_size+1]
        pairs = [tuple(map(int, m)) for text in footers
                 for m in re.findall(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", text)]
        expected = (slide.number, len(deck.slides))
        if pairs != [expected]:
            out.append(Finding("numbering.current_total", Severity.ERROR,
                               f"footer must contain {expected[0]} / {expected[1]} exactly once; found {pairs}",
                               slide.number, fix="number every slide, including cover and sources"))
    return out


def check_embedded_notes(deck, spec) -> list[Finding]:
    if spec["structure"].get("embedded_speaker_notes", True) or deck.fmt != "pptx":
        return []
    return [Finding("notes.embedded", Severity.ERROR,
                    "embedded speaker notes found", slide.number,
                    fix="move presenter material and references to the separate script PDF")
            for slide in deck.slides if slide.has_notes_part]


def check_titles(deck, spec) -> list[Finding]:
    st = spec["structure"]
    out = []
    max_words = spec["density"]["max_title_words"]
    for s in deck.slides[1:]:
        t = s.heading
        if t is None:
            continue
        title = t.text.strip()
        if not title:
            continue
        if len(title.split()) > max_words:
            out.append(
                Finding(
                    "title.length",
                    Severity.WARN,
                    f"title is {len(title.split())} words (max {max_words}): {title[:44]!r}",
                    s.number,
                    fix="titles label the slide; the body says the rest",
                )
            )
        if TITLE_PUNCT.search(title):
            out.append(
                Finding(
                    "title.punctuation",
                    Severity.INFO,
                    f"title ends with punctuation: {title[:44]!r}",
                    s.number,
                    fix="drop the trailing period",
                )
            )
    return out


def check_repeated_titles(deck, spec) -> list[Finding]:
    warn_at = spec["structure"].get("duplicate_titles_warn", 2)
    counts: dict[str, list[int]] = {}
    for s in deck.slides[1:]:
        t = s.heading
        if t is None or not t.text.strip():
            continue
        counts.setdefault(t.text.strip().lower(), []).append(s.number)
    out = []
    for title, pages in counts.items():
        if len(pages) > warn_at:
            out.append(
                Finding(
                    "title.repeated",
                    Severity.WARN,
                    f"{len(pages)} slides share the title {title!r} (p{', '.join(map(str, pages))})",
                    fix="a repeated title means a build sequence - animate it instead",
                )
            )
    return out


def check_build_slides(deck, spec) -> list[Finding]:
    """Consecutive identical slides are wasted space; use animation."""
    if not spec["structure"].get("flag_build_slides", True):
        return []
    groups: list[tuple[int, int]] = []
    prev_fp, start = None, None
    for s in deck.slides:
        fp = s.fingerprint()
        if fp == prev_fp:
            continue
        if start is not None and s.number - start > 1:
            groups.append((start, s.number - 1))
        start, prev_fp = s.number, fp
    if start is not None and deck.slides[-1].number > start:
        groups.append((start, deck.slides[-1].number))

    out = []
    for a, b in groups:
        if b > a:
            out.append(
                Finding(
                    "build.duplicate",
                    Severity.WARN,
                    f"p{a}-{b} ({b - a + 1} slides) are content-identical",
                    a,
                    fix="use appear-on-click animation, or delete the copies",
                )
            )
    return out


def check_cover(deck, spec) -> list[Finding]:
    roles = spec["fonts"]["roles"]
    out = []
    if not deck.slides:
        return out
    cover = deck.slides[0]
    sizes = sorted({s.size for s in cover.all_lines}, reverse=True)
    if not sizes:
        return out
    want = roles["cover_title"]["size"]
    tol = roles["cover_title"].get("tolerance", 4)
    if abs(sizes[0] - want) > tol:
        out.append(
            Finding(
                "cover.title_size",
                Severity.WARN,
                f"cover title is {sizes[0]:.0f}pt, spec {want}pt",
                1,
                fix="the cover is the one place a big number is allowed",
            )
        )
    if len(cover.text_boxes) < 2:
        out.append(
            Finding(
                "cover.subtitle",
                Severity.INFO,
                "cover has no presenter/subtitle line",
                1,
                fix=f"add a {roles['cover_subtitle']['size']:.0f}pt "
                f"{roles['cover_subtitle']['color']} line with the author",
            )
        )
    return out


def check_narrative_arc(deck, spec) -> list[Finding]:
    """Cheap sanity checks on the shape of the deck as a whole."""
    out = []
    n = len(deck.slides)
    if n == 0:
        return out
    # the cover is the first slide; judging it by word count punishes a
    # title that happens to be a full sentence
    has_cover = bool(deck.slides) and len(deck.slides[0].text_boxes) <= 3
    if not has_cover:
        out.append(
            Finding(
                "arc.no_cover",
                Severity.INFO,
                "no sparse opening slide - the deck starts straight into content",
                fix="one title slide, then content",
            )
        )
    last = deck.slides[-1]
    if len(last.words) > 120:
        out.append(
            Finding(
                "arc.no_close",
                Severity.INFO,
                f"final slide carries {len(last.words)} words - no summary / call to action",
                n,
                fix="end on a takeaway or a next step",
            )
        )
    if n and n < 5:
        out.append(
            Finding("arc.length", Severity.INFO, f"only {n} slides", fix="")
        )
    return out


def check_language_consistency(deck, spec) -> list[Finding]:
    """A deck that mixes scripts usually means pasted-in text."""
    def script(text: str) -> str:
        if re.search(r"[Ѐ-ӿ]", text):
            return "cyrillic"
        if re.search(r"[一-鿿]", text):
            return "cjk"
        if re.search(r"[A-Za-z]", text):
            return "latin"
        return "other"

    out = []
    for s in deck.slides:
        counts: dict[str, int] = {}
        for tb in s.text_boxes:
            counts[script(tb.text)] = counts.get(script(tb.text), 0) + len(tb.words)
        total = sum(counts.values())
        if total < 30:
            continue
        dominant = max(counts, key=lambda k: counts[k])
        if dominant == "latin" and counts.get("cyrillic", 0) / total > 0.15:
            out.append(
                Finding(
                    "language.mixed",
                    Severity.INFO,
                    f"slide mixes Latin ({counts['latin']}w) and Cyrillic "
                    f"({counts.get('cyrillic', 0)}w) body text",
                    s.number,
                    fix="pick one language for the narrative; keep the other for terms",
                )
            )
    return out
