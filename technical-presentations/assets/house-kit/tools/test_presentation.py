"""Regressions for reusable authoring, source freshness and delivery policy."""
import copy
from pathlib import Path
import tempfile
import unittest

import yaml
from pptx import Presentation

from deckcheck.cli import load_guideline, DEFAULT_GUIDELINE, render
from deckcheck.checks import structure
from deckcheck.loaders import load_pptx
from deckcheck.model import Deck as CheckedDeck, Slide as CheckedSlide, Rect, Span, TextBox, Report, Finding, Severity
from deckgen import Deck, Slide, TextBlock, para, to_pptx
from deckgen import layout as L
from presentation import read_manifest, input_digest, compose, block

ROOT = Path(__file__).resolve().parent.parent


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder/"deck.yaml"
        self.data = yaml.safe_load((ROOT/"templates/presentation/deck.yaml").read_text())

    def read(self, data=None):
        self.path.write_text(yaml.safe_dump(data or self.data, allow_unicode=True))
        return read_manifest(self.path)

    def test_example_is_valid_and_uses_varied_layouts(self):
        data = self.read()
        self.assertEqual(len(data["slides"]), 7)
        self.assertEqual(sum(s["minutes"] for s in data["slides"]), data["brief"]["minutes"])
        self.assertGreaterEqual(len({s["layout"] for s in data["slides"]}), 6)

    def test_rejects_inconsistent_timing(self):
        self.data["slides"][1]["minutes"] += .5
        with self.assertRaisesRegex(ValueError, "timing totals"):
            self.read()

    def test_rejects_missing_speech_and_misspelled_script_key(self):
        for mutation in ("missing", "typo"):
            data = copy.deepcopy(self.data)
            if mutation == "missing":
                del data["slides"][0]["script"]["speech"]
            else:
                data["slides"][0]["script"]["speach"] = "ignored text"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.read(data)

    def test_rejects_duplicate_ids_and_unknown_sources(self):
        data = copy.deepcopy(self.data); data["slides"][1]["id"] = data["slides"][0]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate slide"):
            self.read(data)
        data = copy.deepcopy(self.data); data["slides"][1]["sources"] = ["unknown"]
        with self.assertRaisesRegex(ValueError, "unknown source"):
            self.read(data)

    def test_missing_image_is_not_silently_omitted(self):
        data = copy.deepcopy(self.data)
        data["slides"][1].update(layout="split", image={"path":"missing.png","description":"A figure","source":"style"})
        with self.assertRaisesRegex(ValueError, "image file missing"):
            self.read(data)

    def test_content_change_invalidates_export_digest(self):
        data = self.read(); before = input_digest(self.path, data)
        self.data["slides"][1]["body"][0] += " Дополнительное условие."
        after_data = self.read()
        self.assertNotEqual(before, input_digest(self.path, after_data))

    def test_composition_contains_current_total_and_no_notes(self):
        data = self.read(); deck, media = compose(data, self.folder)
        self.assertEqual(media, [])
        for n, slide in enumerate(deck.slides, 1):
            self.assertFalse(slide.notes)
            self.assertEqual(slide.blocks[-1].paras[0].plain(), f"{n:02d} / 7")

    def test_script_labels_follow_presentation_language(self):
        import pymupdf
        from deckgen import to_pdf
        from presentation_script import build_script
        data = self.read(); deck, _ = compose(data, self.folder)
        pdf = self.folder / "slides.pdf"; to_pdf(deck, pdf)
        for language, expected in [("English", "Slide 1 / 7."), ("Русский", "Слайд 1 / 7.")]:
            data["brief"]["language"] = language
            target = self.folder / "script.pdf"; build_script(data, pdf, target)
            with pymupdf.open(target) as script:
                self.assertIn(expected, "".join(page.get_text() for page in script))
                self.assertEqual(len(script.get_toc()), 7)

    def test_bundled_font_fallback_builds_clean_deck(self):
        import os
        import subprocess
        import sys
        env = dict(os.environ, DECK_USE_BUNDLED_FONTS="1")
        env.pop("DECK_FONT_DIR", None)
        self.path.write_text(yaml.safe_dump(self.data, allow_unicode=True))
        result = subprocess.run([sys.executable, str(ROOT / "tools/presentation.py"), "build", str(self.path)],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pdf: 0 errors, 0 warnings", result.stdout)
        from pptx import Presentation
        deck = Presentation(self.folder / "dist/slides.pptx")
        self.assertTrue(any(run.font.name == "Liberation Sans" for slide in deck.slides
                            for shape in slide.shapes if shape.has_text_frame
                            for para in shape.text_frame.paragraphs for run in para.runs))

    def test_long_speech_is_paginated_without_losing_text_or_bookmarks(self):
        import pymupdf
        from deckgen import to_pdf
        from presentation_script import build_script
        data = self.read(); deck, _ = compose(data,self.folder)
        pdf = self.folder/"slides.pdf"; to_pdf(deck,pdf)
        final = "КОНЕЦ_ПОЛНОЙ_РЕЧИ"
        data["slides"][1]["script"]["speech"] = ("Подробное объяснение сохраняется при переносе речи на следующую страницу. "*500)+final
        target = self.folder/"script.pdf"; build_script(data,pdf,target)
        with pymupdf.open(target) as script:
            self.assertGreater(len(script),8)
            self.assertIn(final,"".join(page.get_text() for page in script))
            self.assertEqual(len(script.get_toc()),7)


class DeliveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.spec = load_guideline(DEFAULT_GUIDELINE)

    def numbered(self, text="1 / 1"):
        rect = Rect(642, 364, 692, 376)
        footer = TextBox(rect, [Span(text,"Arial",9,"#000000",rect=rect)])
        return CheckedDeck("test",[CheckedSlide(1,Rect(0,0,720,405),[footer])],"pptx")

    def test_numbering_checks_total_and_duplicate_footer(self):
        self.assertEqual(structure.check_numbering(self.numbered(),self.spec), [])
        self.assertTrue(structure.check_numbering(self.numbered("1 / 32"),self.spec))
        deck = self.numbered(); deck.slides[0].text_boxes *= 2
        self.assertTrue(structure.check_numbering(deck,self.spec))

    def test_body_fraction_does_not_count_as_footer(self):
        deck = self.numbered(); deck.slides[0].text_boxes[0].rect = Rect(30,100,100,120)
        self.assertTrue(structure.check_numbering(deck,self.spec))

    def test_notes_loader_does_not_create_notes_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"sample.pptx"
            prs = Presentation(); slide = prs.slides.add_slide(prs.slide_layouts[6]); prs.save(path)
            self.assertEqual(structure.check_embedded_notes(load_pptx(path),self.spec), [])
            slide.notes_slide.notes_text_frame.text = "Presenter material"; prs.save(path)
            self.assertTrue(structure.check_embedded_notes(load_pptx(path),self.spec))

    def test_strict_verdict_matches_exit_policy(self):
        report = Report("sample",[Finding("test",Severity.WARN,"warning")])
        self.assertIn("FAIL",render(report,color=False,strict=True))
        self.assertIn("PASS",render(report,color=False,strict=False))

    def test_footer_box_does_not_add_ascent_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"sample.pptx"
            slide = Slide(); slide.blocks.append(TextBlock(642,364,50,[para("1 / 1",size=9,line_spacing=1.3)]))
            deck = Deck("sample","author"); deck.add(slide); to_pptx(deck,path)
            shape = Presentation(path).slides[0].shapes[0]
            self.assertLess(shape.height.pt,15)

    def test_missing_font_and_glyph_fail_before_export(self):
        with self.assertRaisesRegex(ValueError,"Font file missing"):
            L.font_file("UnavailableFontForRegression",False,False)
        with self.assertRaisesRegex(ValueError,"font lacks glyphs"):
            block(Slide(title="test"),30,100,300,["\U0010ffff"])


if __name__ == "__main__":
    unittest.main()
