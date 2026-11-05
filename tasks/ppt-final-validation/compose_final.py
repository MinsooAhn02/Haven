# coding: utf-8
from pathlib import Path
import re,json,hashlib
root=Path.cwd()
s1=Path('docs/발표/샘플_검토/1차_표지개요AWS/build_stage1.cjs').read_text(encoding='utf-8-sig')
s2=Path('docs/발표/샘플_검토/2차_연결구현복원/build_stage2.cjs').read_text(encoding='utf-8-sig')
s3=Path('docs/발표/샘플_검토/3차_구성권한협업/build_stage3.cjs').read_text(encoding='utf-8-sig')
old=Path('docs/발표/통합계획_제작/build_haven_20261105.cjs').read_text(encoding='utf-8-sig')
protected={}
for p in [Path('docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx'),Path('docs/발표/Haven_통합계획_기반_미리보기.png'),*Path('docs/발표/샘플_검토').rglob('*')]:
 if p.is_file():protected[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
Path('tasks/ppt-final-validation/protected-before.json').write_text(json.dumps(protected,ensure_ascii=False,indent=2),encoding='utf-8')
def blocks(source):
 cutoff=re.search(r'(?m)^(?:const targets=|pptx\._slides\.forEach)',source)
 if cutoff:source=source[:cutoff.start()]
 starts=list(re.finditer(r'(?m)^(?:let )?sl=add\(',source));result={}
 for i,m in enumerate(starts):
  b=source[m.start():starts[i+1].start() if i+1<len(starts) else len(source)]
  b=re.sub(r'(?m)^pptx\.addSection\([^\n]*\);\s*','',b)
  b=b.replace('let sl=add(', 'sl=add(')
  title=re.search(r'sl=add\(([\'\"])(.*?)\1',b).group(2)
  result[title]=b
 return result
b1,b2,b3=blocks(s1),blocks(s2),blocks(s3)
prefix=s1.split("pptx.addSection({title:'표지와 개요'});")[0]
prefix=prefix.replace("path.resolve(__dirname,'Haven_재구성_1차샘플.pptx')","path.resolve(__dirname,'../Haven_프로젝트_계획서_최종.pptx')")
prefix=prefix.replace('Haven AWS 기반 기록 공유 서비스와 보안 검증: 1차 샘플','Haven AWS 기반 기록 공유 서비스와 보안 검증')
cover=s1[s1.index('current++;let sl='):s1.index("sl=add('프로젝트 개요'")]
cover=cover.replace("sectionTitle:'표지와 개요'","sectionTitle:'개요와 전체 구성'")
ui=old[old.index('// 03 UI'):old.index('// 04 architecture')]
ui=ui.replace('사용자 화면과 권한','사용자가 이용할 기능과 화면').replace('내 기록·공유받은 기록·첨부 화면을 만들고, 서버가 조회와 변경 권한을 구분한다.','내 기록·공유받은 기록과 공유·첨부 기능을 화면에서 사용할 계획입니다.')
ui=ui.replace('첨부 [파일 선택] [업로드]  /  소유자만','첨부 [파일 선택] [업로드] / 저장 후 소유자만')
network=b1['AWS 안에 서비스를 어떻게 배치하는가']
network=network.replace("'공개 서브넷 2개',3.16,3.0,2.73,.43,20", "'공개 서브넷 (Public)',3.16,3.0,2.73,.43,17")
network=network.replace('비공개 영역\\nWeb 서브넷','비공개 (Private)\\nWeb 서브넷').replace('비공개 영역\\nDB 서브넷','비공개 (Private)\\nDB 서브넷')
whole=b3['전체 시스템 구성'].replace("'Public',3.39", "'공개 / Public',3.39").replace("'Private / Web',6.03", "'비공개 / Private · Web',6.03").replace("'Private / DB',9.94", "'비공개 / Private · DB',9.94")
waf=old[old.index('// 09 waf'):old.index('// 10 tools')]
waf=waf.replace('WAF 정책 적용과 개선','잘못된 웹 요청을 어떻게 막는가').replace('정상 요청을 유지하면서 규칙의 효과와 오탐을 로그로 확인한다.','웹 요청 보안 정책(WAF)을 적용하고, 정상 사용을 유지하면서 필요한 요청을 차단합니다.')
waf=waf.replace("['Count','요청과 로그 관찰']","['관찰(Count)','차단 전 영향 확인']").replace("['로그 대조','규칙·액션 확인']","['로그 확인','정상·시험 요청 대조']").replace("['선별 Block','필요한 정책만']","['필요한 차단','확인한 규칙만 적용']").replace("['재시험','같은 조건 유지']","['다시 시험','정상 기능 유지 확인']")
waf=waf.replace('정해진 SQLi/XSS 패턴·빈도','정해진 공격 패턴·반복 요청').replace('규칙 차단과 앱 거부를 구분','보안 정책 차단과 앱 거부 구분')
outline=[
 ('개요와 전체 구성',None,cover),
 ('개요와 전체 구성','프로젝트 개요',b1['프로젝트 개요']),
 ('개요와 전체 구성','전체 시스템 구성',whole),
 ('개요와 전체 구성','AWS 안에 서비스를 어떻게 배치하는가',network),
 ('개요와 전체 구성','허용할 연결과 막을 연결',b2['허용할 연결과 막을 연결']),
 ('개요와 전체 구성','사용자가 이용할 기능과 화면',ui),
 ('구현과 보안 검증','구현 및 보안 검증 계획',b3['구현 및 보안 검증 계획']),
 ('구현과 보안 검증','화면에서 저장까지의 동작',b2['화면에서 저장까지의 동작']),
 ('구현과 보안 검증','저장한 내용을 유지하고 복구하는 방법',b2['저장한 내용을 유지하고 복구하는 방법']),
 ('구현과 보안 검증','서비스 사용자 권한',b3['서비스 사용자 권한']),
 ('구현과 보안 검증','AWS·서버·DB 권한',b3['AWS·서버·DB 권한']),
 ('구현과 보안 검증','잘못된 웹 요청을 어떻게 막는가',waf),
 ('구현과 보안 검증','점검 도구로 무엇을 확인하는가',b3['점검 도구로 무엇을 확인하는가']),
 ('협업과 추진','GitHub로 협업하며 구현하는 방법',b3['GitHub로 협업하며 구현하는 방법'])]
parts=[prefix];section=None
for sec,title,block in outline:
 if sec!=section:parts.append('pptx.addSection({title:'+json.dumps(sec,ensure_ascii=False)+'});\n');section=sec
 if title is not None:
  pattern=r"sl=add\*((['\"])[^\n]*?" # unused; replace only the literal third argument below
  argpat=r"sl=add\((\"[^\"]*\"|'[^']*'),(\"[^\"]*\"|'[^']*'),(\"[^\"]*\"|'[^']*'),"
  block,n=re.subn(argpat,lambda m:'sl=add('+m.group(1)+','+m.group(2)+','+json.dumps(sec,ensure_ascii=False)+',',block,count=1)
  assert n==1,title
 parts.append(block+'\n')
parts.append(r'''
pptx._slides.forEach((slide,i)=>{if(i>0){current=i+1;text(slide,String(i+1),12.1,7.12,.55,.22,10,muted,false,{align:'right'});}});
assert.strictEqual(manifest.length,14);assert.strictEqual(pptx._slides.length,14);
const finalManifest={file:out,slideCount:14,slides:manifest,elements:audit};
fs.writeFileSync(path.join(__dirname,'new-deck-manifest.json'),JSON.stringify(finalManifest,null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,slides:pptx._slides.length,elements:audit.length}));})();
''')
Path('docs/발표/통합계획_제작/build_haven_20261105.cjs').write_text(''.join(parts),encoding='utf-8')
render=Path('tasks/ppt-stage3-validation/render_stage3.ps1').read_text(encoding='utf-8-sig').replace('docs/발표/샘플_검토/3차_구성권한협업/Haven_재구성_3차샘플.pptx','docs/발표/Haven_프로젝트_계획서_최종.pptx').replace('tasks/ppt-stage3-validation','tasks/ppt-final-validation')
Path('tasks/ppt-final-validation/render_final.ps1').write_text(render,encoding='utf-8')
print('Final source composed in approved 14-slide outline; previous draft and samples retained.')
