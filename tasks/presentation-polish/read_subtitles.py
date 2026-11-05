# coding: utf-8
from pathlib import Path
import re,json,hashlib
s=Path('docs/발표/src/build_haven.cjs').read_text(encoding='utf-8-sig')
for m in re.finditer(r'sl=add\(([\'\"])(.*?)\1,([\'\"])(.*?)\3,',s):print(m.group(2)+' | '+m.group(4))
r={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('docs/발표/archive').rglob('*') if p.is_file()}
Path('tasks/presentation-polish/archive-before.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
