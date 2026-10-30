"""Format-agnostic deck model.

Both the PDF and the PPTX loader normalise into these primitives so every check
is written once. All coordinates are PDF points (1/72 in), origin top-left.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARN = "warn"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 0, "warn": 1, "info": 2}[self.value]


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def intersection(self, other: "Rect") -> "Rect | None":
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return Rect(x0, y0, x1, y1)

    def overlap_area(self, other: "Rect") -> float:
        inter = self.intersection(other)
        return inter.area if inter else 0.0

    def overlaps(self, other: "Rect", min_area: float = 0.0) -> bool:
        return self.overlap_area(other) > min_area

    def expand(self, d: float) -> "Rect":
        return Rect(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def contains(self, other: "Rect") -> bool:
        return (
            self.x0 <= other.x0
            and self.y0 <= other.y0
            and self.x1 >= other.x1
            and self.y1 >= other.y1
        )

    def crosses(self, other: "Rect", tol: float = 0.0) -> bool:
        """True if `other` straddles this rect's edge rather than sitting inside it."""
        if self.contains(other) or other.contains(self):
            return False
        return self.overlaps(other)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def __str__(self) -> str:
        return f"({self.x0:.0f},{self.y0:.0f})-({self.x1:.0f},{self.y1:.0f}) {self.width:.0f}x{self.height:.0f}"


@dataclass
class Span:
    """A run of text with uniform formatting."""

    text: str
    font: str
    size: float
    color: str  # "#rrggbb"
    bold: bool = False
    italic: bool = False
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))

    @property
    def words(self) -> list[str]:
        return self.text.split()

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(
            f"{self.font}|{self.size:.1f}|{self.color}|{self.bold}|{self.italic}".encode()
        ).hexdigest()[:8]


@dataclass
class Line:
    """One visual line, aggregated from every run that shares its baseline."""

    runs: list[Span] = field(default_factory=list)

    @property
    def rect(self) -> Rect:
        return Rect(
            min(r.rect.x0 for r in self.runs),
            min(r.rect.y0 for r in self.runs),
            max(r.rect.x1 for r in self.runs),
            max(r.rect.y1 for r in self.runs),
        )

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs).strip()

    @property
    def words(self) -> list[str]:
        out: list[str] = []
        for r in self.runs:
            out.extend(r.words)
        return out

    @property
    def size(self) -> float:
        return max((r.size for r in self.runs), default=0.0)

    @property
    def font(self) -> str:
        return self.runs[0].font if self.runs else ""

    @property
    def color(self) -> str:
        return self.runs[0].color if self.runs else ""

    @property
    def bold(self) -> bool:
        return any(r.bold for r in self.runs)

    @property
    def italic(self) -> bool:
        return any(r.italic for r in self.runs)


@dataclass
class TextBox:
    """A text frame. `runs` keeps per-run formatting; `lines` groups them by baseline."""

    rect: Rect
    runs: list[Span] = field(default_factory=list)
    is_title: bool = False
    is_bullet_list: bool = False
    align: str = "left"
    frame_fill: str | None = None
    region: str = "free"  # set by segment.py: free|table|frame|col<N>

    @property
    def lines(self) -> list[Line]:
        """Group runs into visual lines by baseline, tolerating marker glyphs.

        A PDF exports a list marker ("1.", "●") as its own run with a slightly
        different y than the text it belongs to, so a plain round(y0) buckets
        them as two lines. Cluster on the vertical centre instead.
        """
        runs = [r for r in self.runs if r.text.strip()]
        if not runs:
            return []
        runs.sort(key=lambda r: ((r.rect.y0 + r.rect.y1) / 2, r.rect.x0))
        clusters: list[list[Span]] = []
        for r in runs:
            cy = (r.rect.y0 + r.rect.y1) / 2
            tol = 0.3 * max(r.size, 1.0)
            if clusters:
                last = clusters[-1]
                lcy = (last[0].rect.y0 + last[-1].rect.y1) / 2
                if abs(cy - lcy) <= tol:
                    last.append(r)
                    continue
            clusters.append([r])
        return [
            Line(runs=sorted(c, key=lambda s: s.rect.x0))
            for c in sorted(clusters, key=lambda c: min(s.rect.y0 for s in c))
        ]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.runs).strip()

    @property
    def words(self) -> list[str]:
        out: list[str] = []
        for r in self.runs:
            out.extend(r.words)
        return out

    @property
    def sizes(self) -> list[float]:
        return [r.size for r in self.runs if r.text.strip()]

    @property
    def families(self) -> list[str]:
        return [r.font for r in self.runs if r.text.strip()]

    @property
    def colors(self) -> list[str]:
        return [r.color for r in self.runs if r.text.strip()]

    @property
    def bold_words(self) -> int:
        return sum(len(r.words) for r in self.runs if r.bold and r.text.strip())

    @property
    def accent_words(self) -> int:
        return sum(
            len(r.words)
            for r in self.runs
            if r.text.strip() and r.color not in ("#000000", "#1f1f1f", "#595959")
        )

    @property
    def dominant_size(self) -> float:
        return max(self.sizes, default=0.0)

    def line_bottoms(self) -> list[float]:
        return sorted(ln.rect.y1 for ln in self.lines)

    def line_tops(self) -> list[float]:
        return sorted(ln.rect.y0 for ln in self.lines)


@dataclass
class ImageBox:
    rect: Rect  # visible (clipped) extent - use for area, coverage, alignment
    placed_rect: Rect | None = None  # unclipped placement - use to judge stretching
    native_px: tuple[int, int] | None = None
    name: str = ""
    digest: str = ""
    region: str = "free"

    @property
    def stretch_rect(self) -> Rect:
        """The rect whose aspect ratio should match the source image's."""
        return self.placed_rect or self.rect

    @property
    def native_aspect(self) -> float | None:
        if not self.native_px or not self.native_px[1]:
            return None
        return self.native_px[0] / self.native_px[1]

    @property
    def aspect(self) -> float:
        r = self.stretch_rect
        return r.width / r.height if r.height else 0.0

    @property
    def effective_dpi(self) -> float | None:
        if not self.native_px:
            return None
        dpi_x = self.native_px[0] / (self.rect.width / 72)
        dpi_y = self.native_px[1] / (self.rect.height / 72)
        return min(dpi_x, dpi_y)

    @property
    def area_pct(self) -> float:
        return 100 * self.rect.area


@dataclass
class Shape:
    """A vector rectangle / line - the raw material for borders and frames."""

    rect: Rect
    stroke: str | None = None
    fill: str | None = None
    width: float = 0.0
    dash: tuple[float, ...] | None = None
    is_text_frame: bool = False  # invisible placeholder rect emitted by the exporter
    visible: bool = True
    region: str = "free"
    has_curves: bool = False  # Bézier items => rounded corners or an organic shape
    n_items: int = 0

    @property
    def dashed(self) -> bool:
        return bool(self.dash) and any(d > 0 for d in (self.dash or ()))

    @property
    def is_frame_candidate(self) -> bool:
        """A closed stroked rectangle big enough to read as a container."""
        return (
            self.visible
            and self.stroke is not None
            and self.width > 0
            and self.rect.width > 40
            and self.rect.height > 30
        )


@dataclass
class Slide:
    number: int
    rect: Rect  # page/canvas rect
    text_boxes: list[TextBox] = field(default_factory=list)
    images: list[ImageBox] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    has_notes_part: bool = False

    @property
    def area(self) -> float:
        return self.rect.area

    @property
    def all_lines(self) -> list[Line]:
        return [ln for tb in self.text_boxes for ln in tb.lines]

    @property
    def words(self) -> list[str]:
        out: list[str] = []
        for tb in self.text_boxes:
            out.extend(tb.words)
        return out

    @property
    def char_count(self) -> int:
        return sum(len(s.text.strip()) for s in self.all_lines)

    @property
    def title_box(self) -> TextBox | None:
        """The visually dominant text box (may just be body text)."""
        if not self.text_boxes:
            return None
        return max(self.text_boxes, key=lambda tb: tb.dominant_size)

    @property
    def heading(self) -> TextBox | None:
        """The title, or None when the slide simply has no title.

        `title_box` always returns something, so a title-less slide needs its
        own predicate or every "missing title" check silently passes.
        """
        for tb in self.text_boxes:
            if tb.is_title or tb.dominant_size >= 18:
                return tb
        return None

    @property
    def body_boxes(self) -> list[TextBox]:
        t = self.heading
        return [tb for tb in self.text_boxes if tb is not t]

    def image_area_pct(self) -> float:
        return 100 * sum(i.rect.area for i in self.images) / self.area if self.area else 0.0

    def ink_area_pct(self) -> float:
        """Coarse visual-weight metric: text boxes + images as fraction of slide."""
        if not self.area:
            return 0.0
        tb = sum(tb.rect.area for tb in self.text_boxes)
        im = sum(i.rect.area for i in self.images)
        return 100 * (tb + im) / self.area

    def left_ink(self) -> float:
        if not self.area:
            return 0.5
        cx = self.rect.cx
        tb = sum(tb.rect.area for tb in self.text_boxes if tb.rect.cx < cx)
        im = sum(i.rect.area for i in self.images if i.rect.cx < cx)
        return (tb + im) / max(1e-9, self.ink_area_pct() / 100 * self.area)

    def fingerprint(self) -> str:
        """Content hash for duplicate/build-slide detection."""
        h = hashlib.sha1()
        for tb in sorted(self.text_boxes, key=lambda b: (round(b.rect.y0), round(b.rect.x0))):
            h.update(tb.text.encode())
        for im in sorted(self.images, key=lambda b: b.digest or b.name):
            h.update((im.digest or im.name).encode())
        return h.hexdigest()[:12]


@dataclass
class Deck:
    path: str
    slides: list[Slide]
    fmt: str  # "pdf" | "pptx"

    @property
    def canvas(self) -> Rect:
        return self.slides[0].rect if self.slides else Rect(0, 0, 720, 405)

    def __iter__(self):
        return iter(self.slides)

    def __len__(self) -> int:
        return len(self.slides)


@dataclass
class Finding:
    check: str
    severity: Severity
    message: str
    slide: int | None = None
    where: str = ""
    fix: str = ""

    def __str__(self) -> str:
        loc = f"p{self.slide}" if self.slide else "deck"
        if self.where:
            loc += f" {self.where}"
        return f"[{self.severity.value.upper():<5}] {loc:<14} {self.check:<22} {self.message}"


@dataclass
class Report:
    deck: str
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))

    def extend(self, findings: list[Finding]) -> None:
        self.findings.extend(findings)

    def count(self, sev: Severity) -> int:
        return sum(1 for f in self.findings if f.severity is sev)

    @property
    def ok(self) -> bool:
        return self.count(Severity.ERROR) == 0

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (f.severity.rank, f.slide or 0, f.check),
        )
