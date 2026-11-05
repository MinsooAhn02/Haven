# coding: utf-8
from pathlib import Path
from urllib.parse import unquote
import zipfile,xml.etree.ElementTree as E,posixpath,re,json,hashlib
p=Path('docs/발표/Haven_프로젝트_계획서_최종.pptx');errors=[];visible=[];shape_count=0
manifest=json.loads(Path('docs/발표/통합계획_제작/new-deck-manifest.json').read_text(encoding='utf-8'))
expected=['Haven: AWS 기반 기록 공유 서비스와 보안 검증','프로젝트 개요','전체 시스템 구성','AWS 안에 서비스를 어떻게 배치하는가','허용할 연결과 막을 연결','사용자가 이용할 기능과 화면','구현 및 보안 검증 계획','화면에서 저장까지의 동작','저장한 내용을 유지하고 복구하는 방법','서비스 사용자 권한','AWS·서버·DB 권한','잘못된 웹 요청을 어떻게 막는가','점검 도구로 무엇을 확인하는가','GitHub로 협업하며 구현하는 방법']
if [s['title'] for s in manifest['slides']]!=expected:errors.append('Final outline mismatch')
with zipfile.ZipFile(p) as z:
 names=set(z.namelist());slides=sorted([n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)],key=lambda n:int(re.search(r'(\d+)\.xml',n).group(1)));notes=[n for n in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
 if len(slides)!=14 or len(notes)!=14:errors.append('Slide or notes count')
 for n in names:
  if not n.endswith(('.xml','.rels')):continue
  t=E.fromstring(z.read(n))
  if n in slides:
   ids=[a.attrib['id'] for a in t.iter() if a.tag.endswith('}cNvPr')]
   if len(ids)!=len(set(ids)):errors.append(n+': duplicate id')
   txt='\n'.join(a.text or '' for a in t.iter() if a.tag.endswith('}t'));visible.append(txt)
   for a in t.iter():
    if a.tag.endswith('}sp'):shape_count+=1
    if a.tag.endswith('}pic'):errors.append(n+': raster content')
    if a.tag.endswith('}ext') and any(int(a.attrib.get(k,'0'))<0 for k in ['cx','cy']):errors.append(n+': negative dimensions')
    if a.tag.endswith('}tcPr') and a.attrib.get('anchor','t') not in ['t','ctr','b','just','dist']:errors.append(n+': invalid table anchor')
  if n.endswith('.rels'):
   base=posixpath.dirname(posixpath.dirname(n)) if n!='_rels/.rels' else ''
   for rel in t:
    if rel.attrib.get('TargetMode')=='External':continue
    target=rel.attrib['Target'];resolved=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(base,target))
    if resolved not in names:errors.append(n+': missing relationship '+resolved)
 alltext='\n'.join(visible)
 for forbidden in ['필수 과업 체크리스트','선택 과업 체크리스트']:
  if forbidden in alltext:errors.append('Unwanted checklist slide')
 for required in ['Public','Private','TXT/PDF','2MiB','10MiB','CloudWatch Logs','SSM','DNS / ACM','Prowler','ZAP Baseline','GitHub','계정','정책']:
  if required not in alltext:errors.append('Missing visible content '+required)
protected=json.loads(Path('tasks/ppt-final-validation/protected-before.json').read_text(encoding='utf-8'))
for name,digest in protected.items():
 if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:errors.append('Prior draft/sample changed '+name)
files=['README.md','기본프로젝트_계획.md','docs/발표/Haven_프로젝트_계획서_발표대본.md']
for name in files:
 text=Path(name).read_text(encoding='utf-8-sig')
 if '\ufffd' in text:errors.append(name+': replacement character')
 for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',text):
  if re.match(r'https?://',target):continue
  bits=target.split('#',1);file=Path(name).parent/unquote(bits[0]) if bits[0] else Path(name)
  if not file.exists():errors.append(name+': missing link '+target)
  elif len(bits)>1 and file.suffix=='.md':
   headings=re.findall(r'^#+\s+(.+)$',file.read_text(encoding='utf-8-sig'),re.M)
   slugs=[re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in headings]
   if unquote(bits[1]) not in slugs:errors.append(name+': missing anchor '+target)
script=Path(files[2]).read_text(encoding='utf-8-sig')
if len(re.findall(r'^## \d+\.',script,re.M))!=14:errors.append('Speech script must have 14 numbered sections')
if 'GitHub Issues' not in Path(files[1]).read_text(encoding='utf-8'):errors.append('Collaboration plan missing')
r={'status':'PASS' if not errors else 'FAIL','slides':len(slides),'notes':len(notes),'editable_shapes':shape_count,'raster_images':0,'previous_drafts_and_samples_preserved':len(protected),'speech_sections':14,'errors':errors}
Path('tasks/ppt-final-validation/structure-document-validation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=True));raise SystemExit(bool(errors))
