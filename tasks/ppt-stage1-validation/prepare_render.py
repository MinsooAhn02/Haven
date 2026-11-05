# coding: utf-8
from pathlib import Path
p=Path('tasks/ppt-new-validation/render_new.ps1');s=p.read_text(encoding='utf-8-sig')
s=s.replace('docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx','docs/발표/샘플_검토/1차_표지개요AWS/Haven_재구성_1차샘플.pptx').replace('tasks/ppt-new-validation','tasks/ppt-stage1-validation')
Path('tasks/ppt-stage1-validation/render_stage1.ps1').write_text(s,encoding='utf-8')
