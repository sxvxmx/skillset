"""TOC verification must tolerate a heading split across PDF text blocks."""
import unittest
from unittest.mock import patch
import academic_export
class AcademicExportTests(unittest.TestCase):
    def test_wrapped_heading_in_two_blocks(self):
        class Page:
            number=4
            def get_text(self,kind,flags):
                def block(text):return {'lines':[{'spans':[{'text':text,'font':'Arial-BoldMT','size':12}]}]}
                return {'blocks':[block('Программа ASCI связывает вычислительную мощность'),block('с научной задачей')]}
        class PDF:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def __iter__(self):return iter([Page()])
        with patch.object(academic_export.pymupdf,'open',return_value=PDF()):
            self.assertEqual(academic_export.measure('unused.pdf',[{'title':'Программа ASCI связывает вычислительную мощность с научной задачей','bookmark':'heading'}]),{'heading':5})
if __name__=='__main__':unittest.main()
