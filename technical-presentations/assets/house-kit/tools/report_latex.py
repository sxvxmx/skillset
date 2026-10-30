"""Minimal XeTeX/Tectonic report build from the reviewed report manuscript.

One main.tex per topic; bibliography is native thebibliography, TOC is native.
No bibliography service, Pandoc, shell escape or full TeX Live installation.
Font files are local build inputs and excluded from distribution archives.
"""
from pathlib import Path
import argparse,re,shutil,subprocess,json,os
import yaml
from report_title import load_title,latex_title
ROOT=Path(__file__).resolve().parents[1]
FONTS=Path(os.environ.get('REPORT_FONT_DIR','/System/Library/Fonts/Supplemental'))
PREAMBLE=r'''% !TeX program = xelatex
\documentclass[12pt,a4paper]{article}
\usepackage{fontspec}
\setmainfont{Times New Roman.ttf}[Path=fonts/,BoldFont={Times New Roman Bold.ttf},ItalicFont={Times New Roman Italic.ttf},BoldItalicFont={Times New Roman Bold Italic.ttf}]
\setsansfont{Arial.ttf}[Path=fonts/,BoldFont={Arial Bold.ttf},ItalicFont={Arial Italic.ttf},BoldItalicFont={Arial Bold Italic.ttf}]
\usepackage{polyglossia}
\setdefaultlanguage{russian}
\newfontfamily\cyrillicfont{Times New Roman.ttf}[Path=fonts/,BoldFont={Times New Roman Bold.ttf},ItalicFont={Times New Roman Italic.ttf},BoldItalicFont={Times New Roman Bold Italic.ttf}]
\newfontfamily\cyrillicfontsf{Arial.ttf}[Path=fonts/,BoldFont={Arial Bold.ttf}]
\usepackage{unicode-math}
\setmathfont{STIXTwoMath.otf}[Path=fonts/]
\usepackage[left=2.5cm,right=2cm,top=2cm,bottom=2cm]{geometry}
\usepackage{setspace}
\onehalfspacing
\setlength{\parindent}{1.25cm}
\setlength{\parskip}{0pt}
\usepackage{graphicx}
\usepackage{caption}
\captionsetup{labelsep=period,font=normalsize,justification=centering,singlelinecheck=false}
\captionsetup[table]{position=above,justification=raggedright}
\usepackage{longtable,array}
\usepackage{titlesec}
\titleformat{\section}{\sffamily\bfseries\fontsize{14}{17}\selectfont}{\thesection}{.8em}{}
\titleformat{\subsection}{\sffamily\bfseries\fontsize{12}{15}\selectfont}{\thesubsection}{.8em}{}
\titlespacing*{\section}{0pt}{18pt}{12pt}
\titlespacing*{\subsection}{0pt}{14pt}{12pt}
\usepackage[section]{placeins}
\usepackage[hidelinks,unicode]{hyperref}
\urlstyle{same}
\setcounter{tocdepth}{2}
\setlength{\emergencystretch}{3em}
\tolerance=1000
\clubpenalty=10000
\widowpenalty=10000
\displaywidowpenalty=10000
\renewcommand{\figurename}{Рисунок}
\renewcommand{\tablename}{Таблица}
\AtBeginDocument{\renewcommand{\figurename}{Рисунок}\renewcommand{\contentsname}{Оглавление}}
\makeatletter
\renewenvironment{thebibliography}[1]
 {\list{\@arabic\c@enumiv.}{\settowidth\labelwidth{#1.}\leftmargin\labelwidth\advance\leftmargin\labelsep\usecounter{enumiv}\setlength\itemsep{6pt}}\raggedright\clubpenalty4000\widowpenalty4000}
 {\endlist}
\makeatother
\begin{document}
'''
SUP=str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺ⁿ','0123456789-+n');SUB=str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789')
def plain(s):
    escape={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    s=''.join(escape.get(c,c) for c in s)
    s=re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺ⁿ]+',lambda m:r'\({}^{'+m[0].translate(SUP)+r'}\)',s)
    s=re.sub(r'[₀₁₂₃₄₅₆₇₈₉]+',lambda m:r'\({}_{'+m[0].translate(SUB)+r'}\)',s)
    return s

def rich(s):
    # Citation tokens are retained until escaping has completed.
    math=[]
    for literal,formula in [('x = y = ±√(β(ρ − 1))',r'x=y=\pm\sqrt{\beta(\rho-1)}'),('√2',r'\sqrt{2}')]:
        if literal in s:
            key='@@MATH'+str(len(math))+'@@';s=s.replace(literal,key);math.append((key,formula))
    out=''.join((r'\textbf{'+plain(p)+'}') if i%2 else plain(p) for i,p in enumerate(s.split('**')))
    for key,formula in math:out=out.replace(key,r'\('+formula+r'\)')
    return re.sub(r'\[(\d+)\]',lambda m:r'\cite{ref'+m[1]+'}',out)

def prepare(topic):
    topic=Path(topic).resolve();project=topic/'report-latex';project.mkdir(exist_ok=True)
    (project/'images').mkdir(exist_ok=True);(project/'fonts').mkdir(exist_ok=True)
    for name in ['Times New Roman.ttf','Times New Roman Bold.ttf','Times New Roman Italic.ttf','Times New Roman Bold Italic.ttf','Arial.ttf','Arial Bold.ttf','Arial Italic.ttf','Arial Bold Italic.ttf','STIXTwoMath.otf']:
        shutil.copyfile(FONTS/name,project/'fonts'/name)
    text=(topic/'report.md').read_text();title=text.splitlines()[0][2:]
    if topic.name=='math-visualization':
        import sys;sys.path.insert(0,str(topic/'build'));from content import SOURCES
        refs=[dict(title=a,url=b,description=c) for a,b,c in SOURCES];author='[ФИО]'
    else:
        refs=yaml.safe_load((topic/'report-sources.yaml').read_text());author=yaml.safe_load((topic/'deck.yaml').read_text())['brief']['author']
    tex=[PREAMBLE,r'\begin{titlepage}\centering',r'[Вуз]\\[6pt][Факультет / кафедра]\\[6pt][Дисциплина]',r'\vspace{2.4cm}',r'{\fontsize{14}{18}\selectfont Доклад\par}',r'\vspace{.8cm}',r'{\sffamily\bfseries\fontsize{20}{25}\selectfont '+plain(title)+r'\par}',r'\vspace{.8cm}',r'\begin{flushright}Выполнил(а): '+plain(author)+r', [Группа]\\Проверил(а): [Преподаватель]\end{flushright}',r'\vfill [Город]\\2026',r'\end{titlepage}',r'\setcounter{page}{2}',r'\begingroup\setstretch{1.05}\tableofcontents\endgroup\clearpage']
    if (topic/'report-sources.yaml').exists():
        refs=yaml.safe_load((topic/'report-sources.yaml').read_text())
    metadata=load_title(topic)
    if metadata:
        tex=[PREAMBLE,*latex_title(title,metadata,plain),r'\setcounter{page}{2}',r'\begingroup\setstretch{1.05}\tableofcontents\endgroup\clearpage']
    lines=text.splitlines();i=0;figures=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line or line.startswith('# '):continue
        if line.startswith('## '):tex.append(r'\section{'+plain(line[3:])+'}')
        elif line.startswith('### '):tex.append(r'\subsection{'+plain(line[4:])+'}')
        elif line.startswith('$$ '):
            eq=line[3:-3].strip()
            # Keep descriptive labels upright in the engineering formulas.
            eq=re.sub(r'_\{(seq|pipe|max|peak)\}',lambda m:r'_{\mathrm{'+m[1]+'}}',eq)
            tex.append('\\[\n'+eq+'\n\\]')
        elif line.startswith('!['):
            caption,name=re.match(r'!\[(.*)\]\((.*)\)',line).groups();p=Path(name) if Path(name).suffix else Path('figures')/(name+'.png')
            figures+=1;target=f'figure-{figures:02d}{p.suffix}';shutil.copy2(topic/p,project/'images'/target)
            tex.append(r'\begin{figure}[htbp]\centering'+ '\n'+r'\includegraphics[width=\linewidth,height=.39\textheight,keepaspectratio]{images/'+target+'}\n'+r'\caption{'+rich(caption)+r'}\end{figure}')
        elif line.startswith('LINK:'):
            label,target=[p.strip() for p in line[5:].split('|',1)];tex.append(r'\noindent\href{'+target+'}{'+plain(label)+r'}\par')
        elif line.startswith('TABLE:'):
            caption=line[6:].strip();rows=[]
            while lines[i].strip()!='ENDTABLE':rows.append([p.strip() for p in lines[i].split('|')]);i+=1
            i+=1;n=len(rows[0]);weights=[.25,.31,.44] if n==3 else [.20,.17,.28,.35] if n==4 else [1/n]*n
            widths=[16.5*w-.42 for w in weights]
            columns='|'.join(r'>{\raggedright\arraybackslash}p{'+str(round(w,3))+'cm}' for w in widths)
            header=' & '.join(r'\textbf{'+plain(p)+'}' for p in rows[0])+r' \\ \hline'
            tex.extend([r'\begingroup\setstretch{1.1}\setlength{\tabcolsep}{5pt}\renewcommand{\arraystretch}{1.25}',r'\begin{longtable}{|'+columns+'|}',r'\caption{'+plain(caption)+r'}\\\hline',header,r'\endfirsthead',r'\hline',header,r'\endhead'])
            for row in rows[1:]:tex.append(' & '.join(rich(p) for p in row)+r' \\ \hline')
            tex.extend([r'\end{longtable}\endgroup'])
        elif line=='REFERENCES':
            tex.append(r'\begin{thebibliography}{99}')
            for n,ref in enumerate(refs,1):tex.append(r'\bibitem{ref'+str(n)+'} '+plain(ref['title'].rstrip('. '))+'. '+plain(ref['description'].rstrip('. '))+r'. URL: \url{'+ref['url']+r'} (дата обращения: 19.10.2026).')
            tex.append(r'\end{thebibliography}')
        else:tex.append(rich(line)+'\n')
    tex.append(r'\end{document}')
    (project/'main.tex').write_text('\n\n'.join(tex)+'\n')
    (project/'README.md').write_text('''# LaTeX-версия доклада

`main.tex` — основной исходник, `images/` — иллюстрации. Оглавление и ссылки
формируются LaTeX автоматически. Сборка не использует BibTeX или shell escape.

Для локальной сборки нужен Tectonic 0.17 или совместимый XeLaTeX, а также
Times New Roman, Arial и STIX Two Math. Каталог `fonts/` содержит локальные
копии установленных шрифтов только для сборки на этом компьютере. Они не
включаются в архив исходников; при переносе предоставьте собственные шрифты.

```sh
tectonic -X compile --keep-intermediates --keep-logs main.tex
```

Итоговый PDF копируется в `../dist/`. Содержимое и DOCX формируются из
`../report.md`; номера страниц в LaTeX и DOCX могут различаться.
''')
    return project

def compile_project(project,cli):
    qa=project.parent/'qa/report-latex';qa.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.setdefault('TECTONIC_CACHE_DIR',str(Path.home()/'Library/Application Support/ChatGPT/latex/tectonic'))
    result=subprocess.run([cli,'-X','compile','--keep-intermediates','--keep-logs','--outdir',str(qa),str(project/'main.tex')],cwd=project,env=env,capture_output=True,text=True,timeout=300)
    (qa/'compile-output.txt').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError((result.stdout+result.stderr)[-6000:])
    pdf=project.parent/'dist'/f'{project.parent.name}-report.pdf';shutil.copy2(qa/'main.pdf',pdf)
    print(pdf)
    return pdf
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('topic');p.add_argument('--compile',dest='cli');a=p.parse_args();project=prepare(a.topic)
    if a.cli:compile_project(project,a.cli)
    else:print(project/'main.tex')
