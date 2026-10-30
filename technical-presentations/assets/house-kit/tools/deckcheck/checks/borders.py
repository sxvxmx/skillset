"""Borders and shapes: stroke colour, weight, dash, fill, corners."""

from __future__ import annotations

import colorsys

from ..model import Finding, Severity


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return None
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def is_on_palette(colour: str, palette: list[str], *, min_delta: float = 0.02) -> bool:
    """True if `colour` is a palette entry, or a tint/shade of one.

    A panel filled with 8% of the accent is the same design decision as a panel
    filled with the accent - only quieter. Flagging it as off-palette trains
    people to ignore the check.

    The test is hue plus direction. In HLS, mixing toward white raises
    lightness and *also* raises saturation, so saturation is not a usable
    discriminator here. Near-grey palette entries are skipped as bases: a grey
    has an arbitrary hue and would match everything.
    """
    low = colour.lower()
    if low in {c.lower() for c in palette}:
        return True
    c = _rgb(low)
    if c is None:
        return False
    ch, cl, _ = colorsys.rgb_to_hls(*c)
    for base in palette:
        b = _rgb(base)
        if b is None:
            continue
        bh, bl, bs = colorsys.rgb_to_hls(*b)
        if bs < 0.15:  # grey: no meaningful hue to match against
            continue
        if abs(ch - bh) > 0.03:
            continue
        if cl - bl > min_delta:
            return True  # a tint: same hue, lighter
        if bl - cl > min_delta and bs > 0.15:
            return True  # a shade: same hue, darker
    return False


def _matches_rule(sh, rule, wtol: float) -> str | None:
    if (sh.stroke or "").lower() != rule["color"].lower():
        return None
    widths = rule.get("widths") or [rule.get("width")]
    if not any(w is not None and abs(sh.width - w) <= wtol for w in widths):
        return None
    dashes = rule.get("dashes", [rule.get("dash")])
    norm = [tuple(d) if d else None for d in dashes]
    got = tuple(sh.dash) if sh.dash else None
    if got is not None:
        got = tuple(round(v, 2) for v in got)
    norm = [tuple(round(v, 2) for v in n) if n else None for n in norm]
    if got not in norm:
        return None
    return rule["color"]


def check_strokes(deck, spec) -> list[Finding]:
    cfg = spec["borders"]
    wtol = cfg.get("width_tolerance", 0.1)
    out = []
    for s in deck.slides:
        for sh in s.shapes:
            if not sh.visible or sh.stroke is None or sh.width <= 0:
                continue
            if sh.rect.width < 1.5 and sh.rect.height < 1.5:
                continue  # a dot / dash cap
            if any(_matches_rule(sh, r, wtol) for r in cfg["whitelist"]):
                continue
            allowed = "; ".join(
                f"{r['color']} {r.get('widths') or r.get('width')}pt "
                f"dash={r.get('dashes') or r.get('dash')}"
                for r in cfg["whitelist"]
            )
            out.append(
                Finding(
                    "border.style",
                    Severity.WARN,
                    f"stroke {sh.stroke} {sh.width:g}pt dash={sh.dash or 'solid'} "
                    f"is not a defined style",
                    s.number,
                    str(sh.rect),
                    f"allowed: {allowed}",
                )
            )
    return out


def check_fills(deck, spec) -> list[Finding]:
    """Fills are for the accent only - an off-palette fill is a hard no."""
    palette = {c.lower() for c in spec["colors"]["whitelist"]}
    accent = spec["colors"]["accent"].lower()
    allowed_bg = spec["canvas"].get("background", "#ffffff")
    cap = spec["structure"].get("tinted_fill_max_per_slide", 2)
    out = []
    for s in deck.slides:
        tinted = 0
        for sh in s.shapes:
            if not sh.visible or sh.fill is None:
                continue
            f = sh.fill.lower()
            if f == allowed_bg or f in ("#000000", "#ffffff"):
                continue
            if is_on_palette(sh.fill, spec["colors"]["whitelist"]):
                if f == accent:
                    tinted += 1
                continue
            out.append(
                Finding(
                    "shape.fill",
                    Severity.WARN,
                    f"shape filled with {sh.fill}, which is not in the palette",
                    s.number,
                    str(sh.rect),
                    f"palette: {', '.join(spec['colors']['whitelist'])}",
                )
            )
        if tinted > cap:
            out.append(
                Finding(
                    "shape.fill_count",
                    Severity.INFO,
                    f"{tinted} accent-filled shapes on one slide (max {cap})",
                    s.number,
                    "one highlight per slide is emphasis; several is decoration",
                )
            )
    return out


def check_frame_consistency(deck, spec) -> list[Finding]:
    """Compare repeated frames with the same content role.

    A code panel and a figure frame may legitimately have different sizes.
    """
    out = []
    by_key: dict[tuple, list[tuple[int, object]]] = {}
    for s in deck.slides:
        for sh in s.shapes:
            if sh.is_frame_candidate and sh.dashed:
                role = "image" if any(sh.rect.expand(1).contains(im.rect) for im in s.images) else "text"
                key = (sh.stroke, sh.width, tuple(sh.dash or ()), role)
                by_key.setdefault(key, []).append((s.number, sh))
    for key, items in by_key.items():
        if len(items) < 3:
            continue
        widths = [sh.rect.width for _, sh in items]
        heights = [sh.rect.height for _, sh in items]
        wspread, hspread = max(widths) - min(widths), max(heights) - min(heights)
        if wspread > 4 or hspread > 4:
            pages = ", ".join(f"p{n}" for n, _ in items)
            out.append(
                Finding(
                    "frame.size",
                    Severity.WARN,
                    f"repeated dashed frames vary in size: {wspread:.0f}x{hspread:.0f}pt spread "
                    f"across {len(items)} uses ({pages})",
                    fix="copy the frame, do not redraw it - repeated frames must be identical",
                )
            )
    return out


def check_frame_dash(deck, spec) -> list[Finding]:
    """The house dash pattern is [3, 2.25]; a doubled pattern is a separate style."""
    want = spec["borders"]["frame"].get("dash")
    heavy = spec["borders"].get("frame_heavy", {}).get("dash")
    out = []
    for s in deck.slides:
        for sh in s.shapes:
            if not sh.is_frame_candidate or not sh.dashed:
                continue
            got = tuple(round(v, 2) for v in (sh.dash or ()))
            if got == tuple(want) or got == tuple(heavy or ()):
                continue
            out.append(
                Finding(
                    "frame.dash",
                    Severity.INFO,
                    f"dash {list(got)} is neither the standard {list(want)} nor the "
                    f"heavy variant {list(heavy or [])}",
                    s.number,
                    str(sh.rect),
                )
            )
    return out


def check_no_decoration(deck, spec) -> list[Finding]:
    """House style is flat and square: no rounded corners, no blobs, no shadows."""
    st = spec["structure"]
    out = []
    for s in deck.slides:
        for sh in s.shapes:
            if not sh.visible or sh.is_text_frame:
                continue
            if st.get("allow_rounded_corners", False):
                break
            # a stroked frame is a legitimate container, curves and all
            if sh.is_frame_candidate:
                continue
            if sh.has_curves and sh.rect.area > 900:
                out.append(
                    Finding(
                        "shape.rounded",
                        Severity.INFO,
                        "shape has rounded/curved corners; the house style is square",
                        s.number,
                        str(sh.rect),
                        "set corner radius to 0",
                    )
                )
            if st.get("allow_shadows", False):
                continue
            if sh.n_items > 40 and sh.rect.area > 2000 and sh.stroke is None:
                out.append(
                    Finding(
                        "shape.complex",
                        Severity.INFO,
                        f"organic shape with {sh.n_items} path segments - reads as decoration",
                        s.number,
                        str(sh.rect),
                        "flat geometry only",
                    )
                )
    return out
