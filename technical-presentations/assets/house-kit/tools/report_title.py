"""Optional topic-owned title metadata shared by the Word and TeX builders."""
from pathlib import Path
import yaml


def load_title(root):
    path = Path(root) / 'report-title.yaml'
    if not path.exists():
        return None
    values = yaml.safe_load(path.read_text())
    if not isinstance(values, dict):
        raise ValueError('report-title.yaml must be a mapping')
    for field in ['university', 'faculty', 'author', 'group', 'city', 'year']:
        if field not in values or not str(values[field]).strip():
            raise ValueError(f'report-title.yaml: missing {field}')
    return {key: str(value) for key, value in values.items()}


def latex_title(title, metadata, escape):
    """A single title leaf; user-provided values remain literal TeX text."""
    m = {key: escape(value) for key, value in metadata.items()}
    author = [r'Выполнил:', r'студент группы ' + m['group'], m['author']]
    if m.get('supervisor'):
        author += [r'\medskip Преподаватель: ' + m['supervisor']]
    return [
        r'\begin{titlepage}', r'\begin{center}\bfseries',
        m['university'] + r'\\', m['faculty'] + r'\par\end{center}',
        r'\vspace{5em}',
        r'\begin{center}{\bfseries\fontsize{16}{20}\selectfont Доклад\par}',
        r'\vspace{1em}',
        r'{\sffamily\bfseries\fontsize{20}{25}\selectfont ' + escape(title) + r'\par}\end{center}',
        r'\vspace{5em}',
        r'\begin{flushright}\begin{minipage}{.44\textwidth}\raggedleft',
        '\\\\\n'.join(author),
        r'\end{minipage}\end{flushright}',
        r'\vfill', r'\begin{center}' + m['city'] + r'\\' + m['year'] + r'\end{center}',
        r'\end{titlepage}',
    ]
