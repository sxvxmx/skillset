"""Create the editable deck and academic report from reviewed content."""
from pathlib import Path
import re
import sys
import yaml

PROJECT=Path(__file__).resolve().parents[1]
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
import latex2mathml.converter
import mathml2omml
from report_title import load_title

REPORT_STYLE=yaml.safe_load((PROJECT/"guideline.yaml").read_text())["report"]

def element(tag,**attrs):
    e=OxmlElement(tag)
    for k,v in attrs.items():e.set(qn("w:"+k),str(v))
    return e

def numbering(doc):
    parent=doc.part.numbering_part.element
    for abstract_id,num_id,heading in [(42,42,True),(43,43,False)]:
        ab=element("w:abstractNum",abstractNumId=abstract_id)
        ab.append(element("w:multiLevelType",val="multilevel" if heading else "singleLevel"))
        for level in range(2 if heading else 1):
            lv=element("w:lvl",ilvl=level)
            lv.append(element("w:start",val=1));lv.append(element("w:numFmt",val="decimal"))
            lv.append(element("w:lvlText",val="%1" if heading and level==0 else "%1.%2" if heading else "%1."))
            if heading:lv.append(element("w:pStyle",val=f"Heading{level+1}"))
            lv.append(element("w:lvlJc",val="left"))
            pp=element("w:pPr");pp.append(element("w:ind",left="0" if heading else "420",hanging="0" if heading else "420"));lv.append(pp)
            ab.append(lv)
        parent.append(ab);num=element("w:num",numId=num_id);num.append(element("w:abstractNumId",val=abstract_id));parent.append(num)

def numpr(paragraph,num_id,level=0):
    pr=paragraph._p.get_or_add_pPr();n=element("w:numPr");n.append(element("w:ilvl",val=level));n.append(element("w:numId",val=num_id));pr.append(n)

def field(paragraph,instruction,cached=""):
    run=paragraph.add_run();run._r.append(element("w:fldChar",fldCharType="begin"))
    r=paragraph.add_run();t=element("w:instrText");t.set(qn("xml:space"),"preserve");t.text=" "+instruction+" ";r._r.append(t)
    paragraph.add_run()._r.append(element("w:fldChar",fldCharType="separate"))
    paragraph.add_run(cached)
    paragraph.add_run()._r.append(element("w:fldChar",fldCharType="end"))

def rich(p,text):
    for i,part in enumerate(text.split("**")):
        run=p.add_run(part);run.bold=bool(i%2)

def equation(doc,latex):
    p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.space_before=Pt(6);p.paragraph_format.space_after=Pt(6)
    mathml=latex2mathml.converter.convert(latex)
    omml=mathml2omml.convert(mathml)
    omml=omml.replace("<m:oMath>",'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">',1)
    node=parse_xml(omml)
    for rad in node.iter(qn("m:rad")):
        # mathml2omml omits the required degree child for square roots.
        # Word may repair this, but LibreOffice otherwise shows placeholders.
        if rad.find(qn("m:deg")) is None:
            props=OxmlElement("m:radPr");hide=OxmlElement("m:degHide");hide.set(qn("m:val"),"1");props.append(hide)
            rad.insert(0,props);rad.insert(1,OxmlElement("m:deg"))
    p._p.append(node)

def create_report(root, title, sources, output_name, author="[ФИО]", accessed="19.10.2026"):
    ROOT=Path(root); DIST=ROOT/"dist"; DIST.mkdir(exist_ok=True)
    REPORT=(ROOT/"report.md").read_text(); SOURCES=sources
    doc=Document();sec=doc.sections[0]
    sec.page_width=Cm(21);sec.page_height=Cm(29.7)
    sec.top_margin=sec.bottom_margin=Cm(2);sec.left_margin=Cm(2.5);sec.right_margin=Cm(2)
    sec.different_first_page_header_footer=True
    body=REPORT_STYLE["body"];heading=REPORT_STYLE["heading"]
    normal=doc.styles["Normal"];normal.font.name=body["family"];normal.font.size=Pt(body["size"]);normal.font.color.rgb=RGBColor(0,0,0)
    pf=normal.paragraph_format;pf.line_spacing=body["line_spacing"];pf.first_line_indent=Cm(body["first_line_indent_cm"]);pf.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY;pf.space_after=Pt(0)
    for name,size in [("Title",20),("Heading 1",14),("Heading 2",12)]:
        style=doc.styles[name];style.font.name=heading["family"];style.font.size=Pt(size);style.font.bold=heading["bold"];style.font.color.rgb=RGBColor(0,0,0)
        p=style.paragraph_format;p.first_line_indent=Cm(0);p.alignment=WD_ALIGN_PARAGRAPH.LEFT;p.space_before=Pt(18);p.space_after=Pt(heading["space_after_pt"]);p.keep_with_next=True;p.line_spacing=1.15
    for name in ["Caption","TOC Heading"]:
        style=doc.styles[name];style.font.name="Times New Roman";style.font.size=Pt(12);style.font.color.rgb=RGBColor(0,0,0)
        style.font.bold=False;style.font.italic=False
        style.paragraph_format.first_line_indent=Cm(0)
    doc.styles["Subtitle"].font.name="Times New Roman"
    doc.styles["Subtitle"].font.size=Pt(14)
    doc.styles["Subtitle"].font.italic=False
    doc.styles["Subtitle"].font.color.rgb=RGBColor(0,0,0)
    numbering(doc)
    metadata=load_title(ROOT)
    if metadata:author=metadata['author']
    # Unspecified topics retain the existing placeholder title leaf.
    for text in ([metadata['university'],metadata['faculty']] if metadata else ["[Вуз]","[Факультет / кафедра]","[Дисциплина]"]):
        p=doc.add_paragraph(text);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.first_line_indent=Cm(0)
        if metadata:
            p.paragraph_format.line_spacing=1.25
            p.runs[0].bold=True
    p=doc.add_paragraph("Доклад",style="Subtitle");p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.space_before=Pt(70);p.paragraph_format.first_line_indent=Cm(0)
    if metadata:
        p.paragraph_format.space_before=Pt(90);p.runs[0].bold=True
    p=doc.add_paragraph(title,style="Title");p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    authors=(["Выполнил:","студент группы "+metadata['group'],author] if metadata else [f"Выполнил(а): {author}, [Группа]","Проверил(а): [Преподаватель]"])
    if metadata and metadata.get('supervisor'):authors.append('Преподаватель: '+metadata['supervisor'])
    for index,text in enumerate(authors):
        p=doc.add_paragraph(text);p.alignment=WD_ALIGN_PARAGRAPH.RIGHT;p.paragraph_format.first_line_indent=Cm(0)
        if metadata:
            p.alignment=WD_ALIGN_PARAGRAPH.RIGHT;p.paragraph_format.left_indent=Cm(9.2)
            p.paragraph_format.line_spacing=1.25;p.paragraph_format.keep_with_next=index<len(authors)-1
            p.paragraph_format.space_before=Pt(70 if index==0 else 0)
    p=doc.add_paragraph(metadata['city']+'\n'+metadata['year'] if metadata else "[Город]\n2026");p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.space_before=Pt(150 if metadata else 100)
    doc.add_page_break()
    doc.add_paragraph("Оглавление",style="TOC Heading")
    p=doc.add_paragraph();p.paragraph_format.first_line_indent=Cm(0);field(p,'TOC \\o "1-2" \\h \\z \\u')
    settings=doc.settings.element;settings.append(element("w:updateFields",val="true"))
    doc.add_page_break()
    footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER;footer.paragraph_format.first_line_indent=Cm(0);field(footer,"PAGE","1")
    fig_no=table_no=0;lines=REPORT.splitlines();i=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line or line.startswith("# "):continue
        if line.startswith("## ") or line.startswith("### "):
            level=1 if line.startswith("## ") else 2
            p=doc.add_paragraph(line.lstrip("# "),style=f"Heading {level}");numpr(p,42,level-1)
        elif line.startswith("$$ "):
            equation(doc,line[3:-3].strip())
        elif line.startswith("!["):
            m=re.match(r"!\[(.*)\]\((.*)\)",line);caption,name=m.groups();fig_no+=1
            p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.space_before=Pt(8);p.paragraph_format.keep_with_next=True
            picture=Path(name) if Path(name).suffix else Path("figures")/(name+".png")
            from PIL import Image
            with Image.open(ROOT/picture) as im: picture_width=min(16.0, 15.0*im.width/im.height)
            inline=p.add_run().add_picture(str(ROOT/picture),width=Cm(picture_width));inline._inline.docPr.set("descr",caption)
            cap=doc.add_paragraph(style="Caption");cap.alignment=WD_ALIGN_PARAGRAPH.CENTER;cap.paragraph_format.line_spacing=1.1;cap.paragraph_format.space_after=Pt(8)
            cap.add_run("Рисунок ");field(cap,"SEQ Figure \\* ARABIC",str(fig_no));cap.add_run(". "+caption)
        elif line.startswith("LINK:"):
            from docx.opc.constants import RELATIONSHIP_TYPE as RT
            label,target=[part.strip() for part in line[5:].split("|",1)]
            p=doc.add_paragraph();p.paragraph_format.first_line_indent=Cm(0)
            hyperlink=element("w:hyperlink"); hyperlink.set(qn("r:id"),p.part.relate_to(target,RT.HYPERLINK,is_external=True))
            run=element("w:r");pr=element("w:rPr");pr.append(element("w:color",val="000000"));pr.append(element("w:u",val="single"));run.append(pr)
            text=element("w:t");text.text=label;run.append(text);hyperlink.append(run);p._p.append(hyperlink)
        elif line.startswith("TABLE:"):
            table_no+=1;caption=line.split(":",1)[1].strip();rows=[]
            while lines[i].strip()!="ENDTABLE":rows.append([x.strip() for x in lines[i].split("|")]);i+=1
            i+=1
            p=doc.add_paragraph();p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.keep_with_next=True;p.paragraph_format.space_before=Pt(8);p.paragraph_format.space_after=Pt(6)
            p.add_run("Таблица ");field(p,"SEQ Table \\* ARABIC",str(table_no));p.add_run(". "+caption)
            table=doc.add_table(rows=1,cols=len(rows[0]));table.autofit=False
            widths=[16.5/len(rows[0])]*len(rows[0])
            if len(rows[0])==3: widths=[4.2,5.3,7.0]
            elif len(rows[0])==4: widths=[2.7,4.2,4.5,5.1]
            for c,w in zip(table.columns,widths):c.width=Cm(w)
            for ri,row in enumerate(rows):
                cells=table.rows[0].cells if ri==0 else table.add_row().cells
                for ci,(cell,text) in enumerate(zip(cells,row)):
                    cell.width=Cm(widths[ci]);cell.text=text
                    tcpr=cell._tc.get_or_add_tcPr();border=element("w:tcBorders")
                    for side in ("top","left","bottom","right"):border.append(element("w:"+side,val="single",sz="6",color="D9D9D9"))
                    tcpr.append(border);margin=element("w:tcMar")
                    for side in ("top","left","bottom","right"):margin.append(element("w:"+side,w="90",type="dxa"))
                    tcpr.append(margin);tcpr.append(element("w:vAlign",val="center"))
                    if ri==0:tcpr.append(element("w:shd",fill="EEEEEE"))
                    for p in cell.paragraphs:
                        p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.line_spacing=1.1;p.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.LEFT
                        p.paragraph_format.keep_with_next=ri==0
                        for r in p.runs:r.font.size=Pt(12);r.bold=ri==0
                if ri==0:table.rows[0]._tr.get_or_add_trPr().append(element("w:tblHeader"))
                table.rows[ri]._tr.get_or_add_trPr().append(element("w:cantSplit"))
            doc.add_paragraph().paragraph_format.space_after=Pt(6)
        elif line=="REFERENCES":
            for source,url,desc in SOURCES:
                p=doc.add_paragraph();p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.line_spacing=1.15;p.paragraph_format.space_after=Pt(8);p.paragraph_format.keep_together=True;p.alignment=WD_ALIGN_PARAGRAPH.LEFT;numpr(p,43)
                p.add_run(source.rstrip(". ")+". "+desc.rstrip(". ")+". URL: "+url+f" (дата обращения: {accessed}).")
        elif line=="CODE:":
            code=[]
            while lines[i].strip()!="ENDCODE":code.append(lines[i]);i+=1
            i+=1
            for code_index,code_line in enumerate(code):
                p=doc.add_paragraph();p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.line_spacing=1;p.paragraph_format.keep_with_next=code_index<len(code)-1
                r=p.add_run(code_line);r.font.name="Courier New";r.font.size=Pt(10)
        else:
            p=doc.add_paragraph();rich(p,line)
    # Theme attributes take precedence over explicit fonts in some renderers.
    # Pin every script, including Cyrillic, and remove template title borders.
    for style in doc.styles:
        if hasattr(style,"font") and style.font.name:
            fonts=style.element.get_or_add_rPr().find(qn("w:rFonts"))
            if fonts is not None:
                for key in list(fonts.attrib):
                    if "theme" in key.lower():del fonts.attrib[key]
                for script in ("ascii","hAnsi","eastAsia","cs"):
                    fonts.set(qn("w:"+script),style.font.name)
        for border in list(style.element.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    # Explicit language avoids inherited spellchecking defaults.
    for p in doc.paragraphs:
        for run in p.runs:
            pr=run._r.get_or_add_rPr();pr.append(element("w:lang",val="ru-RU"))
    doc.core_properties.title=title;doc.core_properties.author=author;doc.core_properties.subject=title
    # All text styles and explicit runs are neutral, including field results and links.
    for style in doc.styles:
        if hasattr(style, "font"):
            style.font.color.rgb=RGBColor(0,0,0)
            for color in style.element.iter(qn("w:color")):
                color.attrib.clear();color.set(qn("w:val"),"000000")
    for color in doc.element.iter(qn("w:color")):
        color.attrib.clear();color.set(qn("w:val"),"000000")
    output=DIST/output_name;doc.save(output)
    print(f"DOCX: {fig_no} figures, {table_no} tables, {len(doc.paragraphs)} paragraphs")

    return output
