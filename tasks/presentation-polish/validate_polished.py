# coding: utf-8
from pathlib import Path
from urllib.parse import unquote
import json,re,zipfile,xml.etree.ElementTree as E,posixpath,hashlib,subprocess
errors=[];doc_details=[]
active=['README.md','기본프로젝트_계획.md','docs/구현명세/기본프로젝트_구현명세.md','docs/발표/발표대본.md','docs/발표/README.md','docs/발표/archive/README.md']
ids=lambda s:set(re.findall(r'\b[A-Z]{2,5}-\d{2}\b',s))
for name in active:
 p=Path(name);s=p.read_text(encoding='utf-8-sig')
 if '\ufffd' in s or re.search(r'[\u3400-\u9fff]',s):errors.append(name+': encoding')
 if s.count('```')%2:errors.append(name+': fences')
 for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',s):
  if re.match(r'https?://',target):continue
  parts=target.split('#',1);q=p.parent/unquote(parts[0]) if parts[0] else p
  if not q.exists():errors.append(name+': missing link '+target)
  elif len(parts)>1 and q.suffix=='.md':
   heads=re.findall(r'^#+\s+(.+)$',q.read_text(encoding='utf-8-sig'),re.M)
   slugs=[re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in heads]
   if unquote(parts[1]) not in slugs:errors.append(name+': missing anchor '+target)
 inside=False;cols=None
 for line in s.splitlines():
  if line.startswith('```'):inside=not inside;cols=None;continue
  if not inside and line.startswith('|'):
   n=len(re.split(r'(?<!\\)\|',line))-2
   if cols is not None and n!=cols:errors.append(name+': table columns')
   cols=n
  else:cols=None
 if name in active[:3]:
  before=subprocess.check_output(['git','show','HEAD:'+name]).decode('utf-8-sig')
  if ids(before)-ids(s):errors.append(name+': lost test IDs')
 doc_details.append({'file':name,'test_ids':len(ids(s))})
spec=Path(active[2]).read_text(encoding='utf-8-sig');plan=Path(active[1]).read_text(encoding='utf-8-sig')
if '자동 수정과 자동 차단은 구현하지 않는다' in spec:errors.append('Ambiguous automatic blocking exclusion')
for name,s in [('plan',plan),('spec',spec)]:
 for term in ['Count','Block','자동 차단','AWS WAF']:
  if term not in s:errors.append(name+': missing '+term)
if len(re.findall(r'^## \d+\.',Path(active[3]).read_text(encoding='utf-8-sig'),re.M))!=14:errors.append('Speech script section count')
manifest=json.loads(Path('docs/발표/src/manifest.json').read_text(encoding='utf-8-sig'))
expected=['Haven: AWS 기반 기록 공유 서비스와 보안 검증','프로젝트 개요','전체 시스템 구성','AWS 안에 서비스를 어떻게 배치하는가','허용할 연결과 막을 연결','사용자가 이용할 기능과 화면','구현 및 보안 검증 계획','화면에서 저장까지의 동작','저장한 내용을 유지하고 복구하는 방법','서비스 사용자 권한','AWS·서버·DB 권한','잘못된 웹 요청을 어떻게 막는가','점검 도구로 무엇을 확인하는가','GitHub로 협업하며 구현하는 방법']
if [x['title'] for x in manifest['slides']]!=expected:errors.append('PPT outline changed')
with zipfile.ZipFile('docs/발표/Haven_프로젝트_계획서.pptx') as z:
 names=set(z.namelist());slides=[n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)];notes=[n for n in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
 if len(slides)!=14 or len(notes)!=14:errors.append('PPT slide/notes count')
 for n in names:
  if not n.endswith(('.xml','.rels')):continue
  t=E.fromstring(z.read(n))
  if n in slides:
   ident=[a.attrib['id'] for a in t.iter() if a.tag.endswith('}cNvPr')]
   if len(ident)!=len(set(ident)):errors.append(n+': duplicate IDs')
   for a in t.iter():
    if a.tag.endswith('}ext') and any(int(a.attrib.get(k,'0'))<0 for k in ['cx','cy']):errors.append(n+': negative size')
    if a.tag.endswith('}tcPr') and a.attrib.get('anchor','t') not in ['t','ctr','b','just','dist']:errors.append(n+': table anchor')
  if n.endswith('.rels'):
   base=posixpath.dirname(posixpath.dirname(n)) if n!='_rels/.rels' else ''
   for rel in t:
    if rel.attrib.get('TargetMode')=='External':continue
    target=rel.attrib['Target'];resolved=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(base,target))
    if resolved not in names:errors.append(n+': missing relationship')
 text12='\n'.join(a.text or '' for a in E.fromstring(z.read('ppt/slides/slide12.xml')).iter() if a.tag.endswith('}t'))
 if '자동 차단' not in text12 or 'Block 전환' not in text12 or 'Count 관찰' not in text12:errors.append('WAF slide missing operation/verification distinction')
 if '필요한 요청을 차단' in text12:errors.append('Old vague WAF text remains')
archive=json.loads(Path('tasks/presentation-polish/archive-before.json').read_text(encoding='utf-8'))
for name,digest in archive.items():
 if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:errors.append('Archive changed '+name)
r={'status':'PASS' if not errors else 'FAIL','slides':len(slides),'notes':len(notes),'speech_sections':14,'archive_files_unchanged':len(archive),'documents':doc_details,'errors':errors}
Path('tasks/presentation-polish/validation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=True));raise SystemExit(bool(errors))
