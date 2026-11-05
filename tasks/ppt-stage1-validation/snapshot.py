# coding: utf-8
from pathlib import Path
import hashlib,json
names=['README.md','기본프로젝트_계획.md','심화프로젝트_계획.md','docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx','docs/발표/통합계획_제작/build_haven_20261105.cjs','docs/발표/Haven_통합계획_기반_미리보기.png']
r={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in names}
Path('tasks/ppt-stage1-validation/protected-before.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print('Protected current final files: '+str(len(r)))
