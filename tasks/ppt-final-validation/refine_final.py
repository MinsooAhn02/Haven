# coding: utf-8
from pathlib import Path
p=Path('docs/발표/통합계획_제작/build_haven_20261105.cjs');s=p.read_text(encoding='utf-8').replace('거부 시 저장 안 함','최종 저장 거부');p.write_text(s,encoding='utf-8')
