"""Regression tests for failures that can make a broken deck appear clean.

Run: python -m unittest discover -s tools -p 'test_*.py'
"""
from __future__ import annotations

import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Pt

from deckcheck import cli
from deckcheck.checks import typography, density, symmetry
from deckcheck.loaders import _dash_tuple, _line_multiple, _pdf_text_box, _pptx_line_dash
from deckcheck.model import Deck, Finding, Rect, Report, Severity, Slide, Span, TextBox
from deckgen import layout


class PdfTextExtractionTests(unittest.TestCase):
    """A discretionary hyphen must not leak into the extracted text."""

    def test_soft_hyphen_becomes_hyphen(self):
        block = {
            "bbox": (0, 0, 100, 20),
            "lines": [
                {"spans": [{"text": "Cray­1 обработал", "bbox": (0, 0, 100, 20),
                             "size": 25.0, "font": "Helvetica", "flags": 0, "color": 0}]}
            ],
        }
        tb = _pdf_text_box(block)
        self.assertIsNotNone(tb)
        self.assertIn("Cray-1 обработал", tb.text)

    def test_plain_hyphen_is_unchanged(self):
        block = {
            "bbox": (0, 0, 100, 20),
            "lines": [
                {"spans": [{"text": "X-MP и Z", "bbox": (0, 0, 100, 20),
                             "size": 25.0, "font": "Helvetica", "flags": 0, "color": 0}]}
            ],
        }
        tb = _pdf_text_box(block)
        self.assertEqual(tb.text, "X-MP и Z")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.spec = cli.load_guideline(cli.DEFAULT_GUIDELINE)
        self.deck = Deck("test.pptx", [], "pptx")

    def test_crashed_check_is_error(self):
        def broken(*args):
            raise RuntimeError("synthetic failure")
        with patch.object(cli, "CHECKS", [("broken", broken)]):
            report = cli.build_report(self.deck, self.spec)
        self.assertEqual(report.count(Severity.ERROR), 1)
        self.assertEqual(report.stats["checks_failed"], 1)
        self.assertEqual(report.findings[0].check, "engine.check_crashed")

    def test_empty_selector_does_not_run_everything(self):
        with patch.object(cli, "CHECKS", [("must-not-run", lambda *args: self.fail())]):
            report = cli.build_report(self.deck, self.spec, set())
        self.assertEqual(report.stats["checks_selected"], 0)

    def test_list_checks_needs_no_deck(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--list-checks"]), 0)

    def test_skip_typo_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            cli.main(["unused.pptx", "--skip", "overlp"])
        self.assertEqual(exc.exception.code, 2)

    def test_empty_cli_selection_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            cli.main(["unused.pptx", "--only", "fonts", "--skip", "fonts"])
        self.assertEqual(exc.exception.code, 2)

    def test_invalid_duration_is_rejected(self):
        for duration in ("0", "-1", "nan", "inf"):
            with self.subTest(duration=duration), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                cli.main(["unused.pptx", "--minutes", duration])
            self.assertEqual(exc.exception.code, 2)

    def test_strict_does_not_promote_info(self):
        report = Report("test.pptx", [Finding("advice", Severity.INFO, "advisory")])
        with patch.object(cli.loaders, "load", return_value=self.deck), patch.object(cli, "build_report", return_value=report), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["test.pptx", "--strict"]), 0)

    def test_invalid_guideline_is_reported(self):
        self.assertFalse(cli._selftest(None)["ok"])
        self.assertFalse(cli._selftest({})["ok"])
        for section, key, value in (("canvas", "height", 0), ("canvas", "width", float("nan")), ("grid", "content_top", "bad"), ("colors", "whitelist", None), ("spacing", "line_height_ratio", [1.2]), ("speaker_script", "required_fields", None), ("authoring", "footer", {"x":700,"y":364,"width":50,"size":9})):
            spec = copy.deepcopy(self.spec)
            spec[section][key] = value
            with self.subTest(section=section, key=key):
                self.assertFalse(cli._selftest(spec)["ok"])


class TypographyTests(unittest.TestCase):
    def setUp(self):
        self.spec = cli.load_guideline(cli.DEFAULT_GUIDELINE)
        self.spec["colors"]["accent"] = "#4285f4"

    def deck(self, size, bold, text="Accent"):
        rect = Rect(30, 100, 300, 130)
        run = Span(text, "Arial", size, "#4285f4", bold, rect=rect)
        return Deck("test", [Slide(1, Rect(0, 0, 720, 405), [TextBox(rect, [run])])], "pptx")

    def test_small_bold_accent_still_needs_aa(self):
        self.assertEqual(len(typography.check_contrast(self.deck(12, True), self.spec)), 1)

    def test_large_accent_uses_large_text_threshold(self):
        self.assertEqual(typography.check_contrast(self.deck(18, False), self.spec), [])

    def test_bold_prose_is_not_a_short_leadin(self):
        deck = self.deck(12, True, "one two three four five six seven eight")
        self.assertEqual(len(typography.check_accent_discipline(deck, self.spec)), 1)


class DensityTests(unittest.TestCase):
    def test_bibliography_is_not_bullets_but_still_has_word_limit(self):
        spec = cli.load_guideline(cli.DEFAULT_GUIDELINE)
        boxes = [TextBox(Rect(30, 100+i*30, 690, 125+i*30),
                         [Span(f"[{i+1}] " + "word "*30, "Arial", 12, "#000000")])
                 for i in range(8)]
        deck = Deck("references.pptx", [Slide(1, Rect(0, 0, 720, 405), boxes)], "pptx")
        self.assertEqual(density.check_bullets_per_slide(deck, spec), [])
        self.assertTrue(density.check_words_per_slide(deck, spec))
        for box in boxes:
            box.runs[0].text = "A normal claim with a mechanism"
        self.assertTrue(density.check_bullets_per_slide(deck, spec))


class LayoutAndLoaderTests(unittest.TestCase):
    def test_left_aligned_cover_is_not_forced_to_center(self):
        spec = cli.load_guideline(cli.DEFAULT_GUIDELINE)
        rect = Rect(31.3,100,500,190)
        box = TextBox(rect,[Span("Cover title","Arial",36,"#000000",rect=rect)],is_title=True)
        deck = Deck("cover",[Slide(1,Rect(0,0,720,405),[box])],"pdf")
        self.assertEqual(symmetry.check_margin_balance(deck,spec),[])
        spec["fonts"]["roles"]["cover_title"]["align"]="center"
        self.assertTrue(symmetry.check_margin_balance(deck,spec))

    def test_pdf_dash_string_ignores_phase(self):
        self.assertEqual(_dash_tuple("[3 2.25] 0"), (3, 2.25))
        self.assertIsNone(_dash_tuple("[] 0"))

    def test_pptx_dash_preserves_width(self):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(20), Pt(20), Pt(100), Pt(50))
        shape.line.width = Pt(0.75)
        shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        self.assertEqual(_pptx_line_dash(shape.line), (3, 2.25))

    def test_fixed_point_leading_is_not_an_emu_multiple(self):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        p = slide.shapes.add_textbox(Pt(30), Pt(100), Pt(300), Pt(100)).text_frame.paragraphs[0]
        p.add_run().font.size = Pt(12)
        p.line_spacing = Pt(18)
        self.assertAlmostEqual(_line_multiple(p), 1.5)

    def test_character_cache_includes_size(self):
        layout._cw_cache.clear()
        small = layout._char_width("A", 12, "Arial", False, False)
        large = layout._char_width("A", 24, "Arial", False, False)
        self.assertAlmostEqual(large, small * 2)

    def test_list_paragraph_inherits_run_options(self):
        p = layout.para(["first", ("second", {"bold": False})], color="#3159a6", bold=True)
        self.assertTrue(p.runs[0].bold)
        self.assertFalse(p.runs[1].bold)
        self.assertEqual(p.runs[1].color, "#3159a6")

    def test_paragraph_spacing_does_not_add_ascent_twice(self):
        block = layout.TextBlock(30, 100, 300, [layout.para("first", size=12, line_spacing=1.3, space_after=10), layout.para("second", size=12, line_spacing=1.3)])
        lines = block.layout()
        self.assertAlmostEqual(lines[1].y - lines[0].y, 12 * 1.3 + 10)

    def test_generator_uses_authoritative_style(self):
        spec = cli.load_guideline(cli.DEFAULT_GUIDELINE)
        self.assertEqual(layout.ACCENT, spec["colors"]["accent"])
        self.assertEqual(layout.COVER_PT, spec["fonts"]["roles"]["cover_title"]["size"])


if __name__ == "__main__":
    unittest.main()
