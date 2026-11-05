# coding: utf-8
from pathlib import Path
p=Path('docs/발표/샘플_검토/1차_표지개요AWS/build_stage1.cjs');s=p.read_text(encoding='utf-8')
s=s.replace("'서브넷 A\\nAZ A'","'서브넷 A\\n가용 영역 A'").replace("'서브넷 B\\nAZ B'","'서브넷 B\\n가용 영역 B'")
s=s.replace("'공인 IP 없음\\nALB에서만 접속'","'공인 IP 없음\\n웹 요청: ALB만 허용'").replace("'공인 IP 없음\\nWeb에서만 접속'","'공인 IP 없음\\nDB 연결: Web만 허용'")
p.write_text(s,encoding='utf-8')
