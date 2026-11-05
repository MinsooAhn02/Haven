from pathlib import Path
p=Path('docs/발표/통합계획_제작/build_haven_20261105.cjs');s=p.read_text(encoding='utf-8')
s=s.replace("'권한 검토와 필요한 정책 수정'","'권한 검토와 정책 수정'").replace("'제한된 요청 재현과 WAF 조정'","'요청 재현 / WAF 정책 조정'")
s=s.replace("line(sl,4.3,2.8,4.9,2.8);line(sl,8.45,2.8,9.05,2.8);",'')
p.write_text(s,encoding='utf-8')
