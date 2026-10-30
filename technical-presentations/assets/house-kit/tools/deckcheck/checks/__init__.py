"""Check registry: everything deckcheck knows how to complain about."""

from __future__ import annotations

from . import borders, density, geometry, images, overlap, spacing, structure, symmetry, typography

# (name, callable, default severity weight for --strict promotion)
# Each callable has the signature (deck, spec) -> list[Finding].
# Checks that need extra CLI options declare them via EXTRA_ARGS.
CHECKS: list[tuple[str, object]] = [
    # geometry
    ("offcanvas", geometry.check_offcanvas),
    ("margin", geometry.check_content_band),
    ("title-lock", geometry.check_title_lock),
    ("grid-snap", geometry.check_alignment),
    # spacing
    ("leading", spacing.check_line_spacing),
    ("para-gap", spacing.check_paragraph_gaps),
    ("gutter", spacing.check_column_gutter),
    ("frame-padding", spacing.check_frame_padding),
    ("v-rhythm", spacing.check_vertical_rhythm),
    # symmetry
    ("symmetry-h", symmetry.check_margin_balance),
    ("symmetry-v", symmetry.check_optical_centering),
    ("symmetry-weight", symmetry.check_weight_balance),
    ("symmetry-columns", symmetry.check_column_symmetry),
    ("symmetry-block", symmetry.check_centred_blocks),
    # overlap
    ("overlap-text", overlap.check_text_overlap),
    ("overlap-image", overlap.check_text_image_overlap),
    ("overlap-frames", overlap.check_frame_crossing),
    ("overlap-image-pair", overlap.check_image_overlap),
    ("overlap-cells", overlap.check_table_cell_overlap),
    # typography
    ("fonts", typography.check_fonts),
    ("code-font", typography.check_code_font),
    ("sizes", typography.check_sizes),
    ("title-weight", typography.check_title_weight),
    ("colors", typography.check_colors),
    ("contrast", typography.check_contrast),
    ("accent-prose", typography.check_accent_discipline),
    ("emphasis", typography.check_emphasis),
    ("justify", typography.check_no_justification),
    # density
    ("words", density.check_words_per_slide),
    ("chars", density.check_chars_per_slide),
    ("lines", density.check_lines_per_slide),
    ("bullets", density.check_bullets_per_slide),
    ("pacing", density.check_pacing),
    # images
    ("image-area", images.check_image_area),
    ("image-coverage", images.check_coverage),
    ("image-dpi", images.check_resolution),
    ("image-distortion", images.check_distortion),
    ("image-placement", images.check_image_placement_consistency),
    ("image-reuse", images.check_duplicate_images),
    # borders
    ("border-style", borders.check_strokes),
    ("shape-fill", borders.check_fills),
    ("frame-size", borders.check_frame_consistency),
    ("frame-dash", borders.check_frame_dash),
    ("decoration", borders.check_no_decoration),
    # structure
    ("title", structure.check_titles),
    ("title-repeat", structure.check_repeated_titles),
    ("build-slides", structure.check_build_slides),
    ("cover", structure.check_cover),
    ("arc", structure.check_narrative_arc),
    ("language", structure.check_language_consistency),
    ("numbering", structure.check_numbering),
    ("speaker-notes", structure.check_embedded_notes),
]

CHECK_NAMES = [name for name, _ in CHECKS]
