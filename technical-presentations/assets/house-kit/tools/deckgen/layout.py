"""Layout primitives shared by the PDF and PPTX backends.

One layout, two renderers. The whole point is that the geometry is decided
*here*, once, so the PDF and the PPTX agree and the linter sees the same numbers
in both. Nothing in a backend is allowed to invent a position.
"""

from __future__ import annotations

import unicodedata
import os
from pathlib import Path
from dataclasses import dataclass, field

from deckcheck.cli import load_guideline

# Read the authoritative style instead of duplicating it in the generator.
SPEC = load_guideline(Path(__file__).resolve().parents[2] / "guideline.yaml")
_C, _G, _F, _COL = SPEC["canvas"], SPEC["grid"], SPEC["fonts"], SPEC["colors"]
W, H = _C["width"], _C["height"]
ML, MR, MT, MB = (_G[k] for k in ("margin_left", "margin_right", "margin_top", "margin_bottom"))
TITLE_Y = _G["title_baseline_y"]
CONTENT_TOP, CONTENT_BOTTOM = _G["content_top"], _G["content_bottom"]
COL_SPLIT, GUTTER = _G["column_split_x"], _G["gutter"]

BLACK = _COL["text_primary"]
GREY = MUTED = _COL["text_muted"]
ACCENT = _COL["accent"]
GREEN, ORANGE = _COL["accent_secondary"]
GRID = _COL["border_table"]
WHITE = _C["background"]

TITLE_PT, BODY_PT, CAPTION_PT, CODE_PT, COVER_PT, COVER_SUB_PT = (
    _F["roles"][role]["size"] for role in ("title", "body", "caption", "code", "cover_title", "cover_subtitle")
)

FONT = SPEC.get("authoring", {}).get("font_family", "Arial")
MONO = SPEC.get("authoring", {}).get("mono_family", "Courier New")
# The kit includes redistributable, metric-compatible fonts for systems without
# the house fonts. Explicit DECK_FONT_DIR remains authoritative when supplied.
_BUNDLED_FONTS = Path(__file__).resolve().parents[2] / "fonts"
if os.environ.get("DECK_USE_BUNDLED_FONTS") == "1" or (not os.environ.get("DECK_FONT_DIR") and not Path("/System/Library/Fonts/Supplemental/Arial.ttf").is_file()):
    FONT, MONO = "Liberation Sans", "Liberation Mono"

# ---- font metrics ------------------------------------------------------------
# Measured from the real TTFs so the PDF renderer wraps text exactly where the
# PPTX renderer will. Cached per (family, bold, italic).
_FONT_DIR = os.environ.get("DECK_FONT_DIR", "/System/Library/Fonts/Supplemental")
_FILES = {
    ("Arial", False, False): f"{_FONT_DIR}/Arial.ttf",
    ("Arial", True, False): f"{_FONT_DIR}/Arial Bold.ttf",
    ("Arial", False, True): f"{_FONT_DIR}/Arial Italic.ttf",
    ("Arial", True, True): f"{_FONT_DIR}/Arial Bold Italic.ttf",
    ("Courier New", False, False): f"{_FONT_DIR}/Courier New.ttf",
    ("Courier New", True, False): f"{_FONT_DIR}/Courier New Bold.ttf",
    ("Courier New", False, True): f"{_FONT_DIR}/Courier New Italic.ttf",
    ("Courier New", True, True): f"{_FONT_DIR}/Courier New Bold Italic.ttf",
}
for family, stem in (("Liberation Sans", "LiberationSans"), ("Liberation Mono", "LiberationMono")):
    for bold, italic, suffix in ((False, False, "Regular"), (True, False, "Bold"),
                                  (False, True, "Italic"), (True, True, "BoldItalic")):
        _FILES[(family, bold, italic)] = str(_BUNDLED_FONTS / f"{stem}-{suffix}.ttf")
_font_cache: dict[tuple[str, bool, bool], object] = {}


def _pymupdf_font(family: str, bold: bool, italic: bool):
    import pymupdf

    key = (family, bold, italic)
    if key not in _font_cache:
        path = font_file(family, bold, italic)
        _font_cache[key] = pymupdf.Font(fontfile=path)
    return _font_cache[key]


def text_width(s: str, size: float, family: str = FONT, bold: bool = False, italic: bool = False) -> float:
    """Advance width of `s` in points."""
    if not s:
        return 0.0
    f = _pymupdf_font(family, bold, italic)
    return f.text_length(s, size)


def font_file(family: str, bold: bool, italic: bool) -> str:
    candidate = _FILES.get((family, bold, italic))
    if candidate is None:
        suffix = " Bold Italic" if bold and italic else " Bold" if bold else " Italic" if italic else ""
        candidate = str(Path(_FONT_DIR)/(family+suffix+".ttf"))
    if not Path(candidate).is_file():
        raise ValueError(f"Font file missing for {family!r}: {candidate}. Set DECK_FONT_DIR; silent substitution is disabled.")
    return candidate


# ---- text model --------------------------------------------------------------
def is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def _char_width(ch: str, size: float, family: str, bold: bool, italic: bool) -> float:
    """Width of one character, cached by the pair (family/bold/italic)."""
    key = (family, bold, italic, ch, size)
    cached = _cw_cache.get(key)
    if cached is None:
        f = _pymupdf_font(family, bold, italic)
        cached = f.text_length(ch, size)
        _cw_cache[key] = cached
    return cached


_cw_cache: dict[tuple, float] = {}


def _tokenize(text: str) -> list[str]:
    """Split into wrappable tokens, keeping the trailing space with each word."""
    out, cur = [], ""
    for ch in text:
        if ch == "\n":
            if cur:
                out.append(cur)
                cur = ""
            out.append("\n")
            continue
        cur += ch
        if ch == " ":
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


@dataclass
class Run:
    text: str
    size: float = BODY_PT
    bold: bool = False
    italic: bool = False
    color: str = BLACK
    family: str = FONT


@dataclass
class Para:
    runs: list[Run] = field(default_factory=list)
    align: str = "left"  # left | center | right
    space_after: float = 0.0
    line_spacing: float = 1.35
    bullet: bool = False
    indent: float = 0.0  # extra first-line indent, beyond the bullet marker

    def plain(self) -> str:
        return "".join(r.text for r in self.runs)


def para(text: str | list, size: float = BODY_PT, **kw) -> Para:
    """Shorthand.

    para("plain text")
    para("plain", size=14, bold=True)
    para([("Term:", {"bold": True}), (" rest of the sentence", {})])
    para([Run("Term:", bold=True), " and then prose"])
    """
    run_kw = {"size", "bold", "italic", "color", "family"}
    runs: list[Run] = []
    if isinstance(text, str):
        # The run properties have to be handed to the Run. Dropping them here
        # made every `para("...", bold=True)` - table headers, key columns,
        # coloured lead-ins - render as plain body text.
        base = {"size": size}
        base.update({k: v for k, v in kw.items() if k in run_kw and v is not None})
        runs.append(Run(text, **base))
    else:
        for item in text:
            if isinstance(item, Run):
                runs.append(item)
                continue
            t, over = item if isinstance(item, tuple) else (item, {})
            base = {"size": size, "color": BLACK}
            base.update({k: v for k, v in kw.items() if k in run_kw and v is not None})
            base.update(over)
            runs.append(Run(t, **base))
    return Para(runs=runs, **{k: v for k, v in kw.items() if k not in run_kw})


@dataclass
class Line:
    """A laid-out line: the tokens to draw, already positioned horizontally."""

    pieces: list[tuple[str, Run, float]]  # (token text, run it came from, x offset)
    y: float = 0.0  # baseline
    height: float = 0.0
    width: float = 0.0


def layout_para(p: Para, x: float, width: float, y: float, size: float) -> list[Line]:
    """Wrap one paragraph into positioned lines. Returns lines with baselines."""
    lines: list[Line] = []
    max_size = max((r.size for r in p.runs), default=size)
    line_h = max_size * p.line_spacing

    cur: list[tuple[str, Run, float]] = []
    cur_w = 0.0
    baseline = y + max_size * 0.98  # approximate ascent from the line top

    def flush() -> None:
        nonlocal cur, cur_w, baseline
        if cur or not lines:
            lines.append(Line(pieces=list(cur), y=baseline, height=line_h, width=cur_w))
        cur, cur_w = [], 0.0
        baseline += line_h

    avail = width - (p.indent if p.bullet else 0.0)
    for run in p.runs:
        if not run.text:
            continue
        for tok in _tokenize(run.text):
            if tok == "\n":
                flush()
                continue
            tw = text_width(tok, run.size, run.family, run.bold, run.italic)
            bare = tok.rstrip(" ")
            bw = text_width(bare, run.size, run.family, run.bold, run.italic) if bare else 0.0
            if cur and cur_w + bw > avail + 0.5:
                # drop the trailing space of the line we are closing
                if cur and cur[-1][0].endswith(" "):
                    last_text, last_run, last_x = cur[-1]
                    cur[-1] = (last_text.rstrip(" "), last_run, last_x)
                flush()
                if not bare:
                    continue  # a space at a line start: swallow it
            cur.append((tok, run, cur_w))
            cur_w += tw
    flush()

    # horizontal alignment
    if p.align != "left":
        for ln in lines:
            slack = width - ln.width
            if slack <= 0:
                continue
            shift = slack / 2 if p.align == "center" else slack
            ln.pieces = [(t, r, xoff + shift) for t, r, xoff in ln.pieces]
    return lines


# ---- graphics ----------------------------------------------------------------
@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str | None = None
    stroke: str | None = None
    width: float = 0.75
    dash: tuple[float, ...] | None = None


@dataclass
class Line_:
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = ACCENT
    width: float = 0.75
    dash: tuple[float, ...] | None = None
    arrow: bool = False


@dataclass
class Image:
    x: float
    y: float
    w: float
    h: float
    path: str


@dataclass
class NativeTable:
    x: float
    y: float
    w: float
    h: float
    widths: list[float]
    header: list[str]
    rows: list[list[str]]
    head_h: float
    row_h: float


@dataclass
class TextBlock:
    """A positioned group of paragraphs - the unit both backends consume."""

    x: float
    y: float
    w: float
    paras: list[Para] = field(default_factory=list)
    h: float = 0.0
    role: str = "body"  # title | cover | body | caption | code

    def layout(self) -> list[Line]:
        out: list[Line] = []
        y = self.y
        for p in self.paras:
            size = max((r.size for r in p.runs), default=BODY_PT)
            lines = layout_para(p, self.x, self.w, y, size)
            out.extend(lines)
            # A baseline already includes the ascent. Adding it again between
            # paragraphs made PDF spacing drift away from native PPTX spacing.
            y += sum(line.height for line in lines) + p.space_after
        self.h = max(0.0, y - self.y)
        return out


@dataclass
class Slide:
    """A laid-out slide: text blocks and graphics, all in absolute points."""

    blocks: list[TextBlock] = field(default_factory=list)
    rects: list[Rect] = field(default_factory=list)
    lines: list[Line_] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    tables: list[NativeTable] = field(default_factory=list)
    notes: str = ""
    title: str = ""

    def add_block(self, block: TextBlock) -> TextBlock:
        self.blocks.append(block)
        return block

    def flattened_text(self) -> list[tuple[float, float, str, Run]]:
        """(x, baseline, token, run) for every token on the slide, in draw order.

        Yields *tokens*, not runs: a wrapped run is split across lines, and
        drawing the whole run at each token position would repeat the text.
        """
        out: list[tuple[float, float, str, Run]] = []
        for b in self.blocks:
            for ln in b.layout():
                for token, run, xoff in ln.pieces:
                    if token.strip():
                        out.append((b.x + xoff, ln.y, token, run))
        return out

    def ink_width(self) -> float:
        w = 0.0
        for x, _baseline, token, run in self.flattened_text():
            w = max(w, x + text_width(token, run.size, run.family, run.bold, run.italic))
        for im in self.images:
            w = max(w, im.x + im.w)
        return w

    def ink_bottom(self) -> float:
        b = 0.0
        for blk in self.blocks:
            lines = blk.layout()
            if lines:
                b = max(b, lines[-1].y)
        for im in self.images:
            b = max(b, im.y + im.h)
        for r in self.rects:
            if r.fill or r.stroke:
                b = max(b, r.y + r.h)
        return b


class Deck:
    def __init__(self, title: str, author: str = ""):
        self.slides: list[Slide] = []
        self.title = title
        self.author = author

    def add(self, slide: Slide) -> Slide:
        self.slides.append(slide)
        return slide

    def __len__(self) -> int:
        return len(self.slides)
