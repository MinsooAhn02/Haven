# coding: utf-8
from pathlib import Path
s=Path('tasks/ppt-new-validation/schema_check.ps1').read_text(encoding='utf-8-sig').replace('docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx','docs/발표/Haven_프로젝트_계획서_최종.pptx').replace('tasks/ppt-new-validation','tasks/ppt-final-validation')
Path('tasks/ppt-final-validation/schema_check.ps1').write_text(s,encoding='utf-8')
