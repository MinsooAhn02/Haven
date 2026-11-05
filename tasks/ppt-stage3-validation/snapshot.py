# coding: utf-8
from pathlib import Path
import hashlib,json
before=json.loads(Path('tasks/ppt-stage2-validation/protected-before.json').read_text(encoding='utf-8'))
for p in Path('docs/발표/샘플_검토/2차_연결구현복원').glob('*'):
 if p.is_file():before[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
Path('tasks/ppt-stage3-validation/protected-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
