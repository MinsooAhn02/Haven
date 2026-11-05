# coding: utf-8
from pathlib import Path
p=Path('docs/발표/샘플_검토/2차_연결구현복원/build_stage2.cjs');s=p.read_text(encoding='utf-8')
s=s.replace('소유자·공유 권한 확인\\n입력·파일 검증\\n거부 시 최종 저장 안 함','소유자·공유 확인\\n입력·파일 검증\\n거부 시 저장 안 함')
p.write_text(s,encoding='utf-8')
