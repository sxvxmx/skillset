"""Package final reports and small standalone LaTeX sources without font files."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
def package():
    files={}
    for name in ['math-visualization','supercomputers-history']:
        topic=ROOT/name
        for ext in ['pdf','docx']:
            p=topic/'dist'/f'{name}-report.{ext}';files[f'reports/{name}/{p.name}']=p
        for p in (topic/'report-latex').rglob('*'):
            if p.is_file() and ('fonts' not in p.parts) and (p.suffix in ['.tex','.png','.md']):
                files[f'reports/{name}/latex/{p.relative_to(topic/"report-latex")}']=p
        files[f'reports/{name}/report.md']=topic/'report.md'
    p=ROOT/'math-visualization/dist/math-visualization-animations.html';files[f'reports/math-visualization/{p.name}']=p
    p=ROOT/'supercomputers-history/report-sources.yaml';files[f'reports/supercomputers-history/{p.name}']=p
    manifest={name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for name,p in files.items()}
    target=ROOT/'dist/academic-reports-latex.zip';target.parent.mkdir(exist_ok=True)
    with ZipFile(target,'w',ZIP_DEFLATED,compresslevel=6) as z:
        for name,p in files.items():z.write(p,name)
        z.writestr('reports/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        z.writestr('reports/README.md','''# Академические доклады

В каждой папке находится итоговый PDF LaTeX и редактируемый DOCX.
Пагинация этих версий различается; каждое оглавление сформировано автоматически.

Для математического доклада рядом с PDF оставлено автономное видеоприложение
math-visualization-animations.html. Откройте его браузером и нажмите Play.
Пять роликов также сохранены во вложениях PDF и могут быть извлечены
просмотрщиком с поддержкой вложений. Воспроизведение внутри страницы PDF
не используется. Простые предпросмотры PDF могут не показывать вложения.

В latex/ лежат main.tex и изображения. Минимальная сборка:
tectonic -X compile main.tex
Для неё предоставьте в latex/fonts/ собственные Times New Roman, Arial
и STIX Two Math с именами, указанными в main.tex. Коммерческие файлы
шрифтов в архив не включены. BibTeX и shell escape не требуются.
''')
    with ZipFile(target) as z:
        assert z.testzip() is None
        for name,meta in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
        assert not any('/fonts/' in name for name in z.namelist())
    print(f'{target}: {len(files)} files, {target.stat().st_size/1048576:.1f} MiB')
    return target
if __name__=='__main__':package()
