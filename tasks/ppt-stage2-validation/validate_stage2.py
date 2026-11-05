# coding: utf-8
from pathlib import Path
import hashlib,json,zipfile,xml.etree.ElementTree as E,re,shutil,posixpath
protected=json.loads(Path('tasks/ppt-stage2-validation/protected-before.json').read_text(encoding='utf-8'));errors=[]
for name,digest in protected.items():
 if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:errors.append('Protected file changed: '+name)
sample=Path('docs/발표/샘플_검토/2차_연결구현복원/Haven_재구성_2차샘플.pptx')
with zipfile.ZipFile(sample) as z:
 names=set(z.namelist());slides=[n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
 if len(slides)!=3:errors.append('Must only create 3 stage2 slides')
 for n in slides:
  t=E.fromstring(z.read(n));ids=[a.attrib['id'] for a in t.iter() if a.tag.endswith('}cNvPr')]
  if len(ids)!=len(set(ids)):errors.append(n+': duplicate ids')
  for a in t.iter():
   if a.tag.endswith('}ext') and any(int(a.attrib.get(k,'0'))<0 for k in ['cx','cy']):errors.append(n+': negative size')
 for n in names:
  if n.endswith(('.xml','.rels')):E.fromstring(z.read(n))
  if n.endswith('.rels'):
   base=posixpath.dirname(posixpath.dirname(n)) if n!='_rels/.rels' else ''
   for rel in E.fromstring(z.read(n)):
    if rel.attrib.get('TargetMode')=='External':continue
    target=rel.attrib['Target'];target=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(base,target))
    if target not in names:errors.append(n+': missing relationship '+target)
for i,number,label in [(1,4,'연결규칙'),(2,7,'구현흐름'),(3,8,'재시작복원')]:
 shutil.copyfile(Path('tasks/ppt-stage2-validation/render')/('슬라이드%d.PNG'%i),sample.parent/('%02d_%s.png'%(number,label)))
manifest=json.loads((sample.parent/'stage2-manifest.json').read_text(encoding='utf-8'))
if manifest['finalSlideNumbers']!=[4,7,8]:errors.append('Wrong stage2 pages')
report={'status':'PASS' if not errors else 'FAIL','sample_slides':3,'final_slides':[4,7,8],'protected_files_unchanged':len(protected),'errors':errors}
Path('tasks/ppt-stage2-validation/structure-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report));raise SystemExit(bool(errors))
