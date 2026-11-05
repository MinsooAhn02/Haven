# coding: utf-8
from pathlib import Path
import hashlib,json,re,subprocess
from urllib.parse import unquote
records=json.loads(Path('tasks/presentation-organization/moves.json').read_text(encoding='utf-8-sig'))
modified={Path('docs/발표/발표대본.md').resolve(),Path('docs/발표/src/build_haven.cjs').resolve(),Path('docs/발표/src/manifest.json').resolve()}
errors=[];unchanged=0;binary_count=0
for r in records:
 p=Path(r['to'])
 if not p.exists():errors.append('Missing moved file: '+r['to']);continue
 if p.resolve() not in modified:
  if hashlib.sha256(p.read_bytes()).hexdigest().upper()!=r['hash']:errors.append('Content changed: '+r['to'])
  else:unchanged+=1
 if p.suffix.lower() in ['.pptx','.png']:binary_count+=1
links=0
for name in ['README.md','docs/발표/README.md','docs/발표/발표대본.md','docs/발표/archive/README.md']:
 p=Path(name);s=p.read_text(encoding='utf-8-sig')
 if '\ufffd' in s:errors.append(name+': replacement character')
 for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',s):
  if re.match(r'https?://',target):continue
  filepart=unquote(target.split('#')[0]);q=p.parent/filepart if filepart else p
  if not q.exists():errors.append(name+': missing link '+target)
  links+=1
current=Path('docs/발표/Haven_프로젝트_계획서.pptx')
expected=subprocess.check_output(['git','rev-parse','HEAD:docs/발표/Haven_프로젝트_계획서_최종.pptx']).decode().strip()
actual=subprocess.check_output(['git','hash-object',str(current)]).decode().strip()
if actual!=expected:errors.append('Current PPT differs from committed final PPT')
s=Path('docs/발표/src/build_haven.cjs').read_text(encoding='utf-8-sig')
if "path.resolve(__dirname,'../Haven_프로젝트_계획서.pptx')" not in s or "'manifest.json'" not in s:errors.append('Generator paths inconsistent')
m=json.loads(Path('docs/발표/src/manifest.json').read_text(encoding='utf-8-sig'))
if m['slideCount']!=14 or m['file']!='docs/발표/Haven_프로젝트_계획서.pptx':errors.append('Manifest inconsistent')
if Path('docs/발표/샘플_검토').exists() or Path('docs/발표/통합계획_제작').exists():errors.append('Old top-level work directories remain')
r={'status':'PASS' if not errors else 'FAIL','moved_files':len(records),'content_preserved_files':unchanged,'ppt_png_content_preserved':binary_count,'updated_source_or_text_files':len(modified),'local_links_checked':links,'current_ppt_matches_committed_final':actual==expected,'slide_count':m['slideCount'],'errors':errors}
Path('tasks/presentation-organization/validation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=True));raise SystemExit(bool(errors))
