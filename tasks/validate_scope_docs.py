# coding: utf-8
from pathlib import Path
import re,json,subprocess
from urllib.parse import unquote
names=['README.md','기본프로젝트_계획.md','심화프로젝트_계획.md','docs/구현명세/기본프로젝트_구현명세.md','docs/구현명세/심화프로젝트_구현명세.md']
errors=[];details=[]
for name in names:
 s=Path(name).read_text(encoding='utf-8-sig');before=subprocess.check_output(['git','show','HEAD:'+name]).decode('utf-8-sig')
 if '\ufffd' in s or re.search(r'[\u3400-\u9fff]',s):errors.append(name+': encoding')
 if s.count('```')%2:errors.append(name+': unbalanced fences')
 ids=lambda txt:set(re.findall(r'\b[A-Z]{2,5}-\d{2}\b',txt))
 if ids(before)-ids(s):errors.append(name+': missing tests '+str(sorted(ids(before)-ids(s))))
 for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',s):
  if re.match(r'https?://',target):continue
  if not (Path(name).parent/unquote(target.split('#')[0])).exists():errors.append(name+': missing link '+target)
 inside=False;cols=None
 for line in s.splitlines():
  if line.startswith('```'):inside=not inside;cols=None;continue
  if not inside and line.startswith('|'):
   count=len(re.split(r'(?<!\\)\|',line))-2
   if cols is not None and count!=cols:errors.append(name+': bad table '+line[:60])
   cols=count
  else:cols=None
 details.append({'file':name,'lines':len(s.splitlines()),'test_ids':len(ids(s)),'previous_test_ids_preserved':len(ids(before)&ids(s))})
spec=Path(names[3]).read_text(encoding='utf-8')
for i in range(1,8):
 if 'SH-%02d'%i not in spec:errors.append('missing SH test')
for i in range(1,13):
 if 'UP-%02d'%i not in spec:errors.append('missing UP test')
r={'status':'PASS' if not errors else 'FAIL','files':details,'errors':errors}
Path('tasks/ppt-new-validation/sharing-document-validation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=True));raise SystemExit(bool(errors))
