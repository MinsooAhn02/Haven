# coding: utf-8
from pathlib import Path
import hashlib,json,zipfile,xml.etree.ElementTree as E,re,shutil
protected=json.loads(Path('tasks/ppt-stage1-validation/protected-before.json').read_text(encoding='utf-8'))
errors=[]
for name,digest in protected.items():
 if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:errors.append('Protected file changed: '+name)
sample=Path('docs/발표/샘플_검토/1차_표지개요AWS/Haven_재구성_1차샘플.pptx')
with zipfile.ZipFile(sample) as z:
 slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
 if len(slides)!=3:errors.append('Must only create 3 stage1 slides')
 for n in slides:
  t=E.fromstring(z.read(n));ids=[a.attrib['id'] for a in t.iter() if a.tag.endswith('}cNvPr')]
  if len(ids)!=len(set(ids)):errors.append(n+': duplicate ids')
  for a in t.iter():
   if a.tag.endswith('}ext') and any(int(a.attrib.get(k,'0'))<0 for k in ['cx','cy']):errors.append(n+': negative size')
for i,label in [(1,'표지'),(2,'개요'),(3,'AWS배치')]:
 shutil.copyfile(Path('tasks/ppt-stage1-validation/render')/('슬라이드%d.PNG'%i),sample.parent/('%02d_%s.png'%(i,label)))
report={'status':'PASS' if not errors else 'FAIL','sample_slides':3,'protected_files_unchanged':len(protected),'errors':errors}
Path('tasks/ppt-stage1-validation/structure-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report));raise SystemExit(bool(errors))
