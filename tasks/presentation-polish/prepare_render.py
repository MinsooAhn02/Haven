# coding: utf-8
from pathlib import Path
s=Path('tasks/ppt-final-validation/render_final.ps1').read_text(encoding='utf-8-sig').replace('docs/발표/Haven_프로젝트_계획서_최종.pptx','docs/발표/Haven_프로젝트_계획서.pptx').replace('tasks/ppt-final-validation','tasks/presentation-polish')
Path('tasks/presentation-polish/render_polished.ps1').write_text(s,encoding='utf-8')
