"""Identity metadata must survive rebuilds without unrequested personal fields."""
import tempfile
import unittest
from pathlib import Path
import yaml
from docx import Document
from report_title import load_title, latex_title
from report_latex import plain
from academic_report import create_report


class ReportTitleTests(unittest.TestCase):
    metadata = dict(university='Санкт-Петербургский государственный университет',
                    faculty='Факультет прикладной математики и процессов управления',
                    author='Ибатуллин Евгений', group='25.М12-пу', city='Санкт-Петербург', year=2026)

    def test_absent_metadata_preserves_placeholder_workflow(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(load_title(root))

    def test_metadata_keeps_cyrillic_group_and_normalizes_year(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'report-title.yaml').write_text(yaml.safe_dump(self.metadata, allow_unicode=True))
            values = load_title(root)
            self.assertEqual(values['group'], '25.М12-пу')
            self.assertEqual(values['year'], '2026')

    def test_missing_identity_fails_clearly(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'report-title.yaml').write_text('university: СПбГУ\n')
            with self.assertRaisesRegex(ValueError, 'missing faculty'):
                load_title(root)

    def test_tex_omits_supervisor_and_course_and_escapes_title(self):
        metadata = {k:str(v) for k,v in self.metadata.items()}
        text = '\n'.join(latex_title('Тема A & B_1', metadata, plain))
        self.assertIn(r'A \& B\_1', text)
        self.assertIn('25.М12-пу', text)
        self.assertIn(r'\raggedleft', text)
        self.assertNotIn('Преподаватель', text)
        self.assertNotIn('курса', text)
        self.assertIn('Выполнил:' + '\\\\' + '\nстудент группы', text)

    def test_optional_supervisor_is_explicit(self):
        metadata = {k:str(v) for k,v in self.metadata.items()}
        metadata['supervisor'] = 'Иванов И. И.'
        text = '\n'.join(latex_title('Тема', metadata, plain))
        self.assertIn('Преподаватель: Иванов И. И.', text)

    def test_docx_cover_uses_same_identity_without_placeholders(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'report-title.yaml').write_text(yaml.safe_dump(self.metadata, allow_unicode=True))
            Path(root, 'report.md').write_text('# Тема\n\n## Введение\n\nТекст.\n')
            path = create_report(root, 'Тема', [], 'report.docx')
            doc = Document(path)
            title = '\n'.join(p.text for p in doc.paragraphs).split('Оглавление')[0]
            for value in self.metadata.values():
                self.assertIn(str(value), title)
            self.assertNotIn('[', title)
            self.assertNotIn('Преподаватель', title)
            self.assertNotIn('Проверил', title)
            self.assertEqual(doc.core_properties.author, self.metadata['author'])
            for paragraph in doc.paragraphs:
                if paragraph.text in ['Выполнил:', 'студент группы 25.М12-пу', self.metadata['author']]:
                    self.assertEqual(int(paragraph.alignment), 2)


if __name__ == '__main__':
    unittest.main()
