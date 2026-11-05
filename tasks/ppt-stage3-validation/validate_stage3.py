# coding: utf-8
from pathlib import Path
import hashlib,json,zipfile,xml.etree.ElementTree as E,re,shutil,posixpath
protected=json.loads(Path('tasks/ppt-stage3-validation/protected-before.json').read_text(encoding='utf-8'));errors=[]
for name,digest in protected.items():
 if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:errors.append('Protected file changed: '+name)
sample=Path('docs/발표/샘플_검토/3차_구성권한협업/Haven_재구성_3차샘플.pptx')
with zipfile.ZipFile(sample) as z:
 names=set(z.namelist());slides=[n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)];notes=[n for n in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
 if len(slides)!=6 or len(notes)!=6:errors.append('Stage 3 must have exactly 6 sample slides and notes')
 for n in slides:
  t=E.fromstring(z.read(n));ids=[a.attrib['id'] for a in t.iter() if a.tag.endswith('}cNvPr')]
  if len(ids)!=len(set(ids)):errors.append(n+': duplicate ids')
  for a in t.iter():
   if a.tag.endswith('}ext') and any(int(a.attrib.get(k,'0'))<0 for k in ['cx','cy']):errors.append(n+': negative size')
   if a.tag.endswith('}tcPr') and a.attrib.get('anchor','t') not in ['t','ctr','b','just','dist']:errors.append(n+': bad table anchor')
 for n in names:
  if n.endswith(('.xml','.rels')):E.fromstring(z.read(n))
  if n.endswith('.rels'):
   base=posixpath.dirname(posixpath.dirname(n)) if n!='_rels/.rels' else ''
   for rel in E.fromstring(z.read(n)):
    if rel.attrib.get('TargetMode')=='External':continue
    target=rel.attrib['Target'];target=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(base,target))
    if target not in names:errors.append(n+': missing relationship '+target)
labels=[(3,'전체시스템'),(7,'주제안내'),(10,'사용자권한'),(11,'운영권한'),(13,'점검도구'),(14,'GitHub협업')]
for i,(number,label) in enumerate(labels,1):
 shutil.copyfile(Path('tasks/ppt-stage3-validation/render')/('슬라이드%d.PNG'%i),sample.parent/('%02d_%s.png'%(number,label)))
m=json.loads((sample.parent/'stage3-manifest.json').read_text(encoding='utf-8'))
if m['finalSlideNumbers']!=[3,7,10,11,13,14]:errors.append('Wrong final slide mapping')
report={'status':'PASS' if not errors else 'FAIL','sample_slides':6,'final_slides':[3,7,10,11,13,14],'protected_files_unchanged':len(protected),'errors':errors}
Path('tasks/ppt-stage3-validation/structure-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report));raise SystemExit(bool(errors))
