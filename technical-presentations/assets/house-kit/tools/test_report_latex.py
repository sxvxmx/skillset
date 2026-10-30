"""Regressions for text escaping and typographic math conversion."""
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import report_latex
from report_latex import plain,rich
class ReportLatexTests(unittest.TestCase):
    def test_literal_markup_is_escaped(self):
        self.assertEqual(plain('A_1 & 50% {x}'),r'A\_1 \& 50\% \{x\}')
    def test_unicode_exponents_do_not_need_text_font_glyphs(self):
        self.assertEqual(plain('10⁻⁷ и z₀'),r'10\({}^{-7}\) и z\({}_{0}\)')
    def test_citations_and_selective_emphasis(self):
        self.assertEqual(rich('**Вывод** [12]'),r'\textbf{Вывод} \cite{ref12}')
    def test_coordinate_intervals_are_not_citations(self):
        self.assertEqual(rich('[−2; 2]'),r'[−2; 2]')
    def test_report_bibliography_overrides_presentation_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            topic=Path(directory)/'math-visualization';topic.mkdir()
            (topic/'report.md').write_text('# Тема\n\n## Список источников\n\nREFERENCES\n')
            (topic/'report-sources.yaml').write_text('- title: Report source\n  url: https://example.com/report\n  description: Report reference\n')
            legacy=SimpleNamespace(SOURCES=[('Slide source','https://example.com/slide','Slide reference')])
            with patch.dict('sys.modules',{'content':legacy}),patch.object(report_latex.shutil,'copyfile'):
                project=report_latex.prepare(topic)
            tex=(project/'main.tex').read_text()
            self.assertIn('Report source',tex)
            self.assertNotIn('Slide source',tex)
            self.assertEqual(tex.count(r'\bibitem{'),1)
if __name__=='__main__':unittest.main()
