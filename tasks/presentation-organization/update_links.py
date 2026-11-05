# coding: utf-8
from pathlib import Path
import json
p=Path('README.md');s=p.read_text(encoding='utf-8-sig')
s=s.replace('[기본 프로젝트 계획서 PPT 최종 정리본](docs/발표/Haven_프로젝트_계획서_최종.pptx)','[현재 발표 PPT](docs/발표/Haven_프로젝트_계획서.pptx)')
s=s.replace('[14장 발표 대본](docs/발표/Haven_프로젝트_계획서_발표대본.md)','[14장 발표 대본](docs/발표/발표대본.md)')
anchor='[14장 발표 대본](docs/발표/발표대본.md)도 함께 제공합니다.'
assert anchor in s
s=s.replace(anchor,anchor+'\n\n[발표 자료 안내](docs/발표/README.md)에서 현재 자료를 확인할 수 있습니다. 이전 PPT와 단계별 검토 샘플은 [발표 아카이브](docs/발표/archive/README.md)에 모았습니다.')
p.write_text(s,encoding='utf-8')
p=Path('docs/발표/발표대본.md');s=p.read_text(encoding='utf-8-sig').replace('[Haven 프로젝트 계획서 최종 정리본](Haven_프로젝트_계획서_최종.pptx)','[Haven 프로젝트 계획서](Haven_프로젝트_계획서.pptx)');p.write_text(s,encoding='utf-8')
p=Path('docs/발표/src/build_haven.cjs');s=p.read_text(encoding='utf-8-sig')
assert "'../Haven_프로젝트_계획서_최종.pptx'" in s
s=s.replace("'../Haven_프로젝트_계획서_최종.pptx'","'../Haven_프로젝트_계획서.pptx'")
s=s.replace("'new-deck-manifest.json'","'manifest.json'")
s=s.replace('const finalManifest={file:out,',"const finalManifest={file:'docs/발표/Haven_프로젝트_계획서.pptx',")
p.write_text(s,encoding='utf-8')
p=Path('docs/발표/src/manifest.json');r=json.loads(p.read_text(encoding='utf-8-sig'));r['file']='docs/발표/Haven_프로젝트_계획서.pptx';p.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Current document links and generator/manifest paths updated; PPT binary unchanged.')
