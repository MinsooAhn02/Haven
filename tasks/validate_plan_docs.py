from pathlib import Path
import hashlib,json,re,os
root=Path.cwd()
names=['통합프로젝트_계획.md','심화프로젝트_계획.md','docs/구현명세/기본프로젝트_구현명세.md','docs/구현명세/심화프로젝트_구현명세.md']
texts={n:(root/n).read_text(encoding='utf-8-sig') for n in names}
errors=[];details=[]
for name,s in texts.items():
 if '\ufffd' in s:errors.append(name+': replacement character')
 if any(c in s for c in ['\u2013','\u2014','\u00b7']):errors.append(name+': forbidden rewritten-prose punctuation')
 if len(re.findall(r'^```',s,re.M))%2:errors.append(name+': unbalanced fences')
 if re.search(r'[\u3400-\u9fff]',s):errors.append(name+': unexpected CJK ideograph; inspect encoding')
 for label,target in re.findall(r'\[([^\]]+)\]\(([^)]+)\)',s):
  if re.match(r'https?://',target):continue
  filepart=target.split('#')[0]
  if filepart and not ((root/name).parent/filepart).resolve().exists():errors.append(name+': missing link '+target)
 # Tables, excluding code fences. UI wireframes are not Markdown tables.
 outside=True;table=[]
 for line in s.splitlines()+['']:
  if line.startswith('```'):outside=not outside
  if outside and line.startswith('|'):
   cells=len(re.split(r'(?<!\\)\|',line))-2
   if table and cells!=table[0]:errors.append(name+': inconsistent table columns '+line[:70])
   table.append(cells)
  else:table=[]
 details.append({'file':name,'lines':len(s.splitlines()),'mermaid':len(re.findall(r'^```mermaid',s,re.M))})
base=Path(os.environ['TEMP'],'haven-plan-before-20261105.md').read_text(encoding='utf-8-sig')
ids=lambda s:set(re.findall(r'\b(?:APP|IAM|NET|DB|DEP|EXT|AUD|WAF|CI|ENC|KEY|PKI|TLS|INT)-\d{2}\b',s))
missing=sorted(ids(base)-ids('\n'.join(texts.values())))
if missing:errors.append('Baseline test IDs missing: '+','.join(missing))
for heading in ['原本','## 2. 원본 검토 범위','## 11. 이력서','## 12. 원본 제안별 반영']:
 if heading in texts[names[0]]:errors.append('Report-style content retained: '+heading)
expected={'README.md':'1DF05860E2281857F97303CB6E5998F10BDE496633919062EE7153D7F5CA35BA','통합프로젝트_선택근거_부록.md':'E6F3E34580103595E84D6D306DA747515EBC40C0290040A36295DCC0BB937850'}
for name,digest in expected.items():
 if hashlib.sha256((root/name).read_bytes()).hexdigest().upper()!=digest:errors.append('Protected file changed: '+name)
if 'id="26-비판-검토-반영과-공식-근거"' not in texts[names[0]]:errors.append('Preserved appendix anchor missing')
report={'status':'PASS' if not errors else 'FAIL','files':details,'source_test_ids':len(ids(base)),'preserved_source_test_ids':len(ids(base)&ids('\n'.join(texts.values()))),'errors':errors,'notes':['README preserved at interrupted-turn state, not reset to HEAD.','Source appendix unchanged; historical section-26 anchor retained as an alias to the related-document section.']}
(root/'tasks/validation/document-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
raise SystemExit(bool(errors))
