# coding: utf-8
from pathlib import Path
from collections import Counter
files=[p for p in Path('docs/발표').rglob('*') if p.is_file()]
print('Presentation files:',len(files),'Types:',dict(Counter(p.suffix for p in files)),'Total MiB:',round(sum(p.stat().st_size for p in files)/1048576,2))
assert all(p.suffix in ['.md','.pptx','.png','.cjs','.json'] for p in files)
