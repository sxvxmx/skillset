"""Images: size, resolution, distortion, alignment, deck-level coverage."""

from __future__ import annotations

import statistics

from ..model import Finding, Severity

# First and last slides are cover/closing: full-bleed art is expected there.
STRUCTURAL_SLIDES = 2


def check_image_area(deck, spec) -> list[Finding]:
    cfg = spec["images"]
    lo, hi = cfg["target_area_pct"]
    hard = cfg["max_area_pct"]
    hero = cfg["hero_max_area_pct"]
    out = []
    fig_cap = cfg.get("figure_slide_max_pct", hard)
    for s in deck.slides:
        # a "figure slide" carries a diagram and little else; the normal
        # image cap would force a diagram to be too small to read
        figure_slide = len(s.words) < 25
        for im in s.images:
            pct = 100 * im.rect.area / s.area
            structural = s.number <= STRUCTURAL_SLIDES
            cap = hero if structural else (fig_cap if figure_slide else hard)
            if pct > cap:
                out.append(
                    Finding(
                        "image.area",
                        Severity.WARN,
                        f"image covers {pct:.0f}% of the slide (cap {cap:.0f}%)",
                        s.number,
                        str(im.rect),
                        "scale it down; the text needs the room",
                    )
                )
            elif not structural and not figure_slide and (pct < lo or pct > hi):
                out.append(
                    Finding(
                        "image.area",
                        Severity.INFO,
                        f"image covers {pct:.0f}% (target {lo:.0f}-{hi:.0f}%)",
                        s.number,
                        str(im.rect),
                    )
                )
    return out


def check_coverage(deck, spec) -> list[Finding]:
    cfg = spec["images"]
    lo, hi = cfg["coverage_target_pct"]
    # coverage statistics need a sample; on a 5-slide deck they are noise
    if len(deck.slides) < 8:
        return []
    per = [s.image_area_pct() for s in deck.slides]
    mean = statistics.mean(per)
    out = []
    if not lo <= mean <= hi:
        out.append(
            Finding(
                "image.coverage",
                Severity.WARN,
                f"graphic coverage averages {mean:.0f}% of the slide (target {lo:.0f}-{hi:.0f}%)",
                fix="aim for roughly one image per 1.5 slides",
            )
        )
    share = sum(1 for s in deck.slides if s.images) / len(deck.slides)
    tlo, thi = cfg["slides_with_image_target"]
    if not tlo <= share <= thi:
        out.append(
            Finding(
                "image.frequency",
                Severity.INFO,
                f"{100 * share:.0f}% of slides carry an image (target {100 * tlo:.0f}-"
                f"{100 * thi:.0f}%)",
            )
        )
    return out


def check_resolution(deck, spec) -> list[Finding]:
    need = spec["images"]["min_native_dpi"]
    out = []
    for s in deck.slides:
        for im in s.images:
            dpi = im.effective_dpi
            if dpi is None:
                continue
            if dpi < need:
                out.append(
                    Finding(
                        "image.resolution",
                        Severity.WARN,
                        f"effective {dpi:.0f} dpi (need {need}); native "
                        f"{im.native_px[0]}x{im.native_px[1]} shown at "
                        f"{im.rect.width:.0f}x{im.rect.height:.0f}pt",
                        s.number,
                        str(im.rect),
                        "use the vector original, or a larger raster",
                    )
                )
    return out


def check_distortion(deck, spec) -> list[Finding]:
    tol = spec["images"]["max_aspect_distortion"]
    out = []
    for s in deck.slides:
        for im in s.images:
            nat = im.native_aspect
            if not nat or not im.aspect:
                continue
            drift = abs(im.aspect - nat) / nat
            if drift > tol:
                out.append(
                    Finding(
                        "image.distortion",
                        Severity.WARN,
                        f"stretched {100 * drift:.0f}%: native aspect {nat:.3f} vs "
                        f"placed {im.aspect:.3f}",
                        s.number,
                        str(im.rect),
                        "lock the aspect ratio when resizing",
                    )
                )
    return out


def check_image_placement_consistency(deck, spec) -> list[Finding]:
    """Same-sized images should sit in the same place on every slide.

    More useful than demanding that an image line up with a text edge: in a
    text-left / image-right deck, jitter in the image's x is what actually
    makes a deck look hand-made rather than designed.
    """
    tol = spec["images"].get("align_tolerance", 3.0)
    groups: dict[tuple[int, int], list[tuple[int, object]]] = {}
    for s in deck.slides:
        for im in s.images:
            key = (round(im.rect.width / 10) * 10, round(im.rect.height / 10) * 10)
            groups.setdefault(key, []).append((s.number, im))
    out = []
    for key, items in groups.items():
        if len(items) < 3:
            continue
        xs = [im.rect.x0 for _, im in items]
        spread = max(xs) - min(xs)
        if spread <= tol:
            continue
        pages = ", ".join(f"p{n}:x={im.rect.x0:.0f}" for n, im in items)
        out.append(
            Finding(
                "image.placement",
                Severity.WARN,
                f"images of the same size ({key[0]}x{key[1]}pt) sit {spread:.0f}pt apart "
                f"horizontally - {pages}",
                fix="copy the placed image from the first slide instead of re-inserting it",
            )
        )
    return out


def check_duplicate_images(deck, spec) -> list[Finding]:
    seen: dict[str, list[int]] = {}
    for s in deck.slides:
        for im in s.images:
            if im.digest:
                seen.setdefault(im.digest, []).append(s.number)
    out = []
    for digest, pages in seen.items():
        if len(pages) >= 3:
            out.append(
                Finding(
                    "image.reuse",
                    Severity.INFO,
                    f"same image {digest} on {len(pages)} slides (p{', '.join(map(str, pages))})",
                    fix="expected when building a diagram step by step",
                )
            )
    return out
