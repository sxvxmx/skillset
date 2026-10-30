"""Validate assignment formatting, native fields and the exported report.

This structural check complements page-image review; it does not replace it.
"""
from pathlib import Path
from zipfile import ZipFile
import argparse,json,re
from lxml import etree
from docx import Document
from docx.oxml.ns import qn
import pymupdf

def check(root,stem,source_count):
    root=Path(root); text=(root/'report.md').read_text();docx=root/'dist'/f'{stem}.docx';pdf=root/'dist'/f'{stem}.pdf'
    doc=Document(docx);normal=doc.styles['Normal'];pf=normal.paragraph_format
    assert normal.font.name=='Times New Roman' and normal.font.size.pt==12
    assert pf.line_spacing==1.5 and abs(pf.first_line_indent.cm-1.25)<.01 and int(pf.alignment)==3
    for name in ['Heading 1','Heading 2']:
        s=doc.styles[name];assert s.font.name=='Arial' and s.font.bold and s.paragraph_format.space_after.pt>=8
    with ZipFile(docx) as z:
        xml=etree.fromstring(z.read('word/document.xml'));styles=etree.fromstring(z.read('word/styles.xml'))
    fields=[n.text or '' for n in xml.iter(qn('w:instrText'))]
    counts={'headings':len(re.findall(r'^#{2,3} ',text,re.M)),'figures':len(re.findall(r'^!\[',text,re.M)),'tables':len(re.findall(r'^TABLE:',text,re.M)),'formulas':len(re.findall(r'^\$\$ ',text,re.M))}
    assert sum('TOC ' in f for f in fields)==1
    assert sum('PAGEREF ' in f for f in fields)==counts['headings']
    assert sum('SEQ Figure' in f for f in fields)==counts['figures']
    assert sum('SEQ Table' in f for f in fields)==counts['tables']
    assert len(list(xml.iter(qn('m:oMath'))))==counts['formulas']
    assert len(list(xml.iter(qn('w:tbl'))))==counts['tables']
    assert len([n for n in xml.iter(qn('w:numId')) if n.get(qn('w:val'))=='43'])==source_count
    for tree in [xml,styles]:
        assert all(n.get(qn('w:val'))=='000000' and len(n.attrib)==1 for n in tree.iter(qn('w:color'))),'Colored or theme-dependent text'
    first=list(dict.fromkeys(int(n) for n in re.findall(r'\[(\d+)\]',text)))
    assert first==list(range(1,source_count+1)),first
    assert 'CODE:' not in text and not re.search(r'\.(?:csv|npz|json)\b',text,re.I),'Implementation detail in report'
    pages=[];fonts=set()
    with pymupdf.open(pdf) as d:
        for i,p in enumerate(d):
            spans=[s for b in p.get_text('dict',flags=pymupdf.TEXTFLAGS_TEXT)['blocks'] for l in b.get('lines',[]) for s in l['spans']]
            assert all(s['color']==0 for s in spans),f'Colored PDF font p{i+1}'
            assert not any('\ufffd' in s['text'] for s in spans),f'Missing glyph p{i+1}'
            fonts.update(f[3] for f in p.get_fonts())
            for word in p.get_text('words'):
                assert 0<=word[0]<word[2]<=p.rect.width and 0<=word[1]<word[3]<=p.rect.height,(i+1,word)
            if i:
                footer=''.join(b[4] for b in p.get_text('blocks') if b[1]>p.rect.height-50).strip()
                assert footer==str(i+1),(i+1,footer)
            pages.append({'page':i+1,'text_characters':len(p.get_text())})
        assert any('TimesNewRoman' in f for f in fonts) and any('Arial' in f for f in fonts),fonts
        counts.update(pages=len(d),sources=source_count,first_citation_order=first,all_pdf_text_black=True)
    # DOCX and TeX have independent pagination and independent native TOCs.
    import academic_export
    entries=academic_export.headings(doc)
    cached=json.loads((root/'qa/toc-pages.json').read_text())
    render=root/('qa/report-2026-10-19/render' if root.name=='math-visualization' else 'qa/report/render')/f'{stem}.pdf'
    if render.exists():
        actual=academic_export.measure(render,entries)
        assert {e['number']+' '+e['title']:actual[e['bookmark']] for e in entries}==cached
    if (root/'report-latex/main.tex').exists():
        tex=(root/'report-latex/main.tex').read_text()
        assert r'\tableofcontents' in tex and r'\begin{thebibliography}' in tex
        assert len(re.findall(r'\\bibitem\{',tex))==source_count
        actual=academic_export.measure(pdf,entries)
        with pymupdf.open(pdf) as d: outline=d.get_toc()
        assert len(outline)==counts['headings']
        for entry, bookmark in zip(entries,outline):
            assert entry['title']==bookmark[1] and actual[entry['bookmark']]==bookmark[2],(entry,bookmark)
        counts['pdf_engine']='Tectonic/XeTeX';counts['native_pdf_toc_entries']=len(outline)
    result={'status':'pass',**counts,'page_checks':pages}
    (root/'qa/report-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='page_checks'},ensure_ascii=False))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('stem');p.add_argument('--sources',type=int,required=True);a=p.parse_args();check(a.root,a.stem,a.sources)
