# coding: utf-8
from pathlib import Path
import zipfile,xml.etree.ElementTree as E,re,posixpath,json,collections
p=Path('docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx');errors=[]
with zipfile.ZipFile(p) as z:
 names=set(z.namelist());slides=sorted(n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',n));notes=[n for n in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
 if len(slides)!=14 or len(notes)!=14:errors.append('slide/notes count')
 native=0;pics=0;texts=[]
 for n in names:
  if not n.endswith(('.xml','.rels')):continue
  t=E.fromstring(z.read(n))
  if n in slides:
   ids=[a.attrib['id'] for a in t.iter() if a.tag.endswith('}cNvPr')]
   if len(ids)!=len(set(ids)):errors.append(n+': duplicate ID')
   for a in t.iter():
    if a.tag.endswith('}ext') and any(int(a.attrib.get(k,'0'))<0 for k in ['cx','cy']):errors.append(n+': negative size')
    if a.tag.endswith('}sp'):native+=1
    if a.tag.endswith('}pic'):pics+=1
    if a.tag.endswith('}tcPr') and a.attrib.get('anchor','t') not in ['t','ctr','b','just','dist']:errors.append(n+': table anchor')
   texts.extend(a.text or '' for a in t.iter() if a.tag.endswith('}t'))
  if n.endswith('.rels'):
   base=posixpath.dirname(posixpath.dirname(n)) if n!='_rels/.rels' else ''
   for rel in t:
    if rel.attrib.get('TargetMode')=='External':continue
    target=rel.attrib['Target'];resolved=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(base,target))
    if resolved not in names:errors.append(n+': missing target '+resolved)
 for expected in ['B1','B2','B3','B4','C1','C2','C3','C4','Haven','ORCHESTRAION','PASS / FAIL / UNKNOWN / ERROR']:
  if expected not in '\n'.join(texts):errors.append('missing '+expected)
 if pics:errors.append('raster diagram found')
 source=Path('README.md').read_text(encoding='utf-8-sig')
 if str(p).replace('\\','/') not in source:errors.append('README link missing')
 result={'status':'PASS' if not errors else 'FAIL','slides':len(slides),'notes':len(notes),'editable_shapes':native,'embedded_raster_images':pics,'relationship_check':'PASS' if not errors else 'inspect','errors':errors}
 Path('tasks/ppt-new-validation/structure-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result))
 raise SystemExit(bool(errors))
