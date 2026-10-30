"""Density / pacing: is there too much on the slide to be read?"""

from __future__ import annotations

import statistics
import re

from ..model import Finding, Severity
from .spacing import para_items

# A slide whose content is a diagram is allowed to be short on words.
FIGURE_WORD_LIMIT = 25


def _is_figure_slide(slide) -> bool:
    return bool(slide.images) and len(slide.words) < FIGURE_WORD_LIMIT

# A "slide" with a handful of words is a section break, not an oversight - but
# only the first and last couple of slides are allowed to be that sparse.
STRUCTURAL_SLIDES = 2


def check_words_per_slide(deck, spec) -> list[Finding]:
    d = spec["density"]["words_per_slide"]
    lo, hi = d["target"]
    hard_max = d["max"]
    out = []
    for s in deck.slides:
        n = len(s.words)
        if n == 0 or _is_figure_slide(s):
            continue
        if n > hard_max:
            out.append(
                Finding(
                    "density.words",
                    Severity.ERROR,
                    f"{n} words (max {hard_max}) - this is a document, not a slide",
                    s.number,
                    fix="split into 2-3 slides, one idea each",
                )
            )
        elif n > hi:
            out.append(
                Finding(
                    "density.words",
                    Severity.WARN,
                    f"{n} words (target {lo}-{hi})",
                    s.number,
                    fix="move detail to a speaker note or an appendix",
                )
            )
        elif n < lo and s.number > STRUCTURAL_SLIDES and s.number < len(deck) - 1:
            out.append(
                Finding(
                    "density.words",
                    Severity.INFO,
                    f"only {n} words (target {lo}-{hi})",
                    s.number,
                    fix="a sparse slide should carry a strong visual instead",
                )
            )
    return out


def check_chars_per_slide(deck, spec) -> list[Finding]:
    d = spec["density"]["chars_per_slide"]
    out = []
    for s in deck.slides:
        n = s.char_count
        if n > d["max"]:
            out.append(
                Finding(
                    "density.chars",
                    Severity.WARN,
                    f"{n} characters (max {d['max']})",
                    s.number,
                    fix="the eye scans a slide in about five seconds",
                )
            )
    return out


def check_lines_per_slide(deck, spec) -> list[Finding]:
    cap = spec["density"]["lines_per_slide"]["max"]
    out = []
    for s in deck.slides:
        # table cells are reference material, not prose the eye has to scan
        n = sum(1 for ln in s.all_lines if ln.text)
        n -= sum(len(tb.lines) for tb in s.text_boxes if tb.region == "table")
        if n > cap:
            out.append(
                Finding(
                    "density.lines",
                    Severity.WARN,
                    f"{n} rendered lines (max {cap})",
                    s.number,
                    fix="cut a third of it",
                )
            )
    return out


def _is_stat_slide(slide, threshold: float = 20.0, caption: float = 13.0) -> bool:
    """A slide built from display-size items (big numbers) is not a bullet list.

    Only body-or-larger blocks count: the 10pt captions under each number are
    labels for the stat, not bullets in their own right.
    """
    blocks = [
        tb
        for tb in slide.text_boxes
        if tb.text and not tb.is_title and tb.dominant_size >= caption
    ]
    if len(blocks) < 3:
        return False
    display = sum(1 for tb in blocks if tb.dominant_size >= threshold)
    return display >= 3 and display >= len(blocks) * 0.6


def _table_cells(slide) -> set[int]:
    """Ids of text boxes that sit in a row with two or more peers.

    A definition table is three blocks per row; counting each cell as a bullet
    would report a tidy four-row table as a twelve-item list.
    """
    rows: dict[int, list[int]] = {}
    for tb in slide.text_boxes:
        if not tb.text or tb.is_title:
            continue
        rows.setdefault(round(tb.rect.y0 / 2.0), []).append(id(tb))
    paired = [ids for ids in rows.values() if len(ids) >= 2]
    if len(paired) < 3:
        return set()
    out: set[int] = set()
    for ids in paired:
        out.update(ids)
    return out


def check_bullets_per_slide(deck, spec) -> list[Finding]:
    """Count bullets as paragraphs, so a wrapped bullet is not counted twice."""
    cap = spec["density"]["bullets_per_slide"]["max"]
    out = []
    for s in deck.slides:
        if _is_stat_slide(s):
            continue
        cells = _table_cells(s)
        bullets = 0
        for tb in s.text_boxes:
            if tb.is_title or tb.region in ("table", "frame") or not tb.text:
                continue
            # A bibliography is reference material, not a list of claims to
            # read during the talk. Its word/line limits are still checked.
            if re.match(r"^\[\d+\]\s", tb.text.strip()):
                continue
            if id(tb) in cells:
                continue
            bullets += para_items(tb)
        if bullets > cap:
            out.append(
                Finding(
                    "density.bullets",
                    Severity.WARN,
                    f"{bullets} bullets (max {cap})",
                    s.number,
                    fix="group them, or split the slide",
                )
            )
    return out


def check_pacing(deck, spec) -> list[Finding]:
    """Slide-to-slide rhythm: a dense slide next to a dense slide is exhausting."""
    d = spec["density"]["words_per_slide"]["target"]
    out = []
    counts = [(s.number, len(s.words)) for s in deck.slides if s.words]
    if len(counts) < 4:
        return out
    med = statistics.median(n for _, n in counts)
    run: list[tuple[int, int]] = []
    for num, n in counts + [(None, 0)]:
        if n > med * 1.6:
            run.append((num, n))
            continue
        if len(run) >= 3:
            pages = ", ".join(str(p) for p, _ in run)
            out.append(
                Finding(
                    "pacing.run",
                    Severity.WARN,
                    f"{len(run)} consecutive over-dense slides (p{pages}) - no visual rest",
                    fix="interleave an image, a diagram or a sparse slide",
                )
            )
        run = []
    return out


def check_pace_per_minute(deck, spec, minutes: float | None) -> list[Finding]:
    if not minutes:
        return []
    words = sum(len(s.words) for s in deck.slides)
    wpm = words / minutes
    out = []
    if wpm > 180:
        out.append(
            Finding(
                "pacing.speed",
                Severity.WARN,
                f"{words} words over {minutes:g} min = {wpm:.0f} wpm - too fast to read aloud",
                fix="cut ~{:.0f} words or add time".format(wpm * minutes - 150 * minutes),
            )
        )
    elif wpm < 60:
        out.append(
            Finding(
                "pacing.speed",
                Severity.INFO,
                f"{wpm:.0f} wpm - lots of room to slow down and expand",
            )
        )
    return out
