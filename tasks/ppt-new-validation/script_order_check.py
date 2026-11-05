# coding: utf-8
from pathlib import Path
import json
p=Path('docs/발표/통합계획_제작/new-deck-manifest.json')
r=json.loads(p.read_text(encoding='utf-8-sig'))
for s in r['slides']:print(str(s['slide'])+' '+s['title'])
