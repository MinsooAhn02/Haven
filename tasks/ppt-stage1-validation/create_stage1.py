# coding: utf-8
from pathlib import Path
src=Path('docs/발표/통합계획_제작/build_haven_20261105.cjs').read_text(encoding='utf-8-sig')
prefix=src.split("pptx.addSection({title:'서비스와 구성'});")[0]
prefix=prefix.replace("path.resolve(__dirname,'../Haven_통합계획_기반_프로젝트계획서_초안.pptx')","path.resolve(__dirname,'Haven_재구성_1차샘플.pptx')")
prefix=prefix.replace("fontSize:32,bold:true,color:ink,margin:0","fontSize:32,bold:true,color:ink,margin:0,align:'left'")
prefix=prefix.replace("pptx.title='Haven 클라우드 보안 프로젝트 계획서'","pptx.title='Haven AWS 기반 기록 공유 서비스와 보안 검증: 1차 샘플'")
body=r'''
pptx.addSection({title:'표지와 개요'});
current++;let sl=pptx.addSlide({sectionTitle:'표지와 개요'});sl.background={color:dark};
text(sl,'Haven',.8,.95,7.8,.95,54,C.background1,true);
text(sl,'AWS 기반 기록 공유 서비스와\n보안 검증',.86,2.35,8.9,1.75,38,C.background1,true);
text(sl,'서비스 구축부터 접근 통제와 정책 검증까지',.88,4.62,8.6,.45,20,mint);
text(sl,'팀 ORCHESTRAION  |  기본 프로젝트 계획',.88,6.3,9.1,.36,16,mint);
text(sl,'클라우드\n×\n보안',10.18,2.36,2.35,2.54,30,C.background1,true,{align:'center'});
sl.addNotes('근거: 기본프로젝트_계획.md 1절. AWS에 기록과 파일을 공유하는 서비스를 만들고, 권한과 보안 정책을 검증하는 기본 프로젝트 계획이다. 특정 활성 회원에게 읽기 공유를 부여하거나 해제하고, 첨부는 인가 후 다운로드한다. 계획은 구축 완료나 공식 과제 인정 확정을 뜻하지 않는다.');
manifest.push({slide:1,title:'Haven: AWS 기반 기록 공유 서비스와 보안 검증',source:'1절'});

sl=add('프로젝트 개요','기록과 파일을 공유하는 서비스에 접근 권한을 적용하고, 제대로 동작하는지 시험합니다.','표지와 개요','1~3절','소유자는 본인 기록 CRUD, 공유 부여/해제, 첨부 추가/삭제를 수행한다. 현재 사용자와 소유자가 활성이고 글이 ACTIVE인 경우 공유 대상은 조회와 다운로드만 허용한다. 변경이나 재공유는 허용하지 않는다. 공유 해제 후 다음 요청부터 거부하며 이미 받은 사본이나 진행 중 전송을 회수하는 기능은 아니다. 자세한 점검 도구 구분은 뒤의 점검 장표에서 설명한다.');
node(sl,'작성자 A','기록 작성 / 파일 추가',.78,2.7,2.25,1.08,mint);
node(sl,'기록과 첨부 파일','소유자가 공유 대상을 지정',4.1,2.7,4.35,1.08,pale);
node(sl,'공유받은 회원 B','읽기 / 다운로드',9.55,2.7,2.98,1.08,mint);
line(sl,3.03,3.24,4.1,3.24);line(sl,8.45,3.24,9.55,3.24);
text(sl,'작성·첨부',3.02,2.26,1.15,.32,14,teal,false,{align:'center'});
text(sl,'공유 허용',8.42,2.26,1.2,.32,14,teal,false,{align:'center'});
rect(sl,9.55,4.38,2.98,.92,C.background1,coral);
text(sl,'그 외 사용자',9.73,4.48,2.62,.33,19,ink,true,{align:'center'});
text(sl,'접근 거부',9.73,4.91,2.62,.25,14,coral,true,{align:'center'});
line(sl,6.28,3.78,6.28,4.84,coral,true,false);line(sl,6.28,4.84,9.55,4.84,coral,true,false);
text(sl,'공유 대상이 아니면',6.49,4.35,2.84,.32,16,coral);
text(sl,'만들기',.82,5.86,3.55,.43,23,teal,true);text(sl,'공유·첨부 웹 서비스',.82,6.48,3.55,.39,19,ink);
text(sl,'보호하기',5.0,5.86,3.55,.43,23,teal,true);text(sl,'허용된 사람만 접근',5,6.48,3.55,.39,19,ink);
text(sl,'확인하기',9.18,5.86,3.45,.43,23,teal,true);text(sl,'정상·거부·복원 시험',9.18,6.48,3.45,.39,19,ink);

pptx.addSection({title:'AWS 배치'});
sl=add('AWS 안에 서비스를 어떻게 배치하는가','외부 요청을 받는 입구만 공개하고, Web과 DB는 각각 비공개 서브넷에 둡니다.','AWS 배치','4.1~4.4절','서비스 접속 경로를 단순화한 계획도다. ALB는 서로 다른 AZ의 공개 서브넷 두 개에 연결되며 Web/DB는 각각 별도의 비공개 서브넷에 배치한다. 두 서버는 공인 IP가 없다. 사용자→ALB는 HTTPS443, ALB SG→Web은 HTTP80, Web SG→DB는 TCP5432만 허용한다. ALB에서 TLS가 종료되므로 전 구간 암호화로 설명하지 않는다. Web/DB 각 한 대로 전체 고가용성이나 무중단을 주장하지 않는다. WAF 정책, SSM 관리, 도메인/메일, 출구와 백업은 이후 설명할 내용이며 이 접속 경로 그림에서는 생략한다. 파일 bytes는 비공개 Web EBS에, 기록과 권한/첨부 메타데이터는 DB에 저장한다. 실제 리전/CIDR/출구는 착수 결정 사항이다.');
rect(sl,2.67,2.05,9.98,4.42,C.background1,mint);
text(sl,'AWS 클라우드 / VPC 네트워크',2.94,2.18,8.9,.35,17,teal,true);
rect(sl,3.0,2.84,3.05,3.35,mint);
rect(sl,6.55,2.84,2.65,3.35,pale);
rect(sl,9.65,2.84,2.65,3.35,pale);
text(sl,'공개 서브넷 2개',3.16,3.0,2.73,.43,20,ink,true,{align:'center'});
rect(sl,3.2,3.62,1.21,.58,C.background1);rect(sl,4.64,3.62,1.21,.58,C.background1);
text(sl,'서브넷 A\nAZ A',3.26,3.68,1.09,.43,12,muted,false,{align:'center'});
text(sl,'서브넷 B\nAZ B',4.70,3.68,1.09,.43,12,muted,false,{align:'center'});
text(sl,'비공개 영역\nWeb 서브넷',6.7,3.03,2.35,.86,19,ink,true,{align:'center'});
text(sl,'비공개 영역\nDB 서브넷',9.8,3.03,2.35,.86,19,ink,true,{align:'center'});
node(sl,'사용자','브라우저',.62,4.37,1.58,1.0,pale);
node(sl,'외부 요청 입구','ALB',3.2,4.37,2.65,1.0,C.background1);
node(sl,'웹 서버','화면과 기능 처리',6.72,4.37,2.30,1.0,C.background1);
node(sl,'DB 서버','기록·권한 저장',9.82,4.37,2.30,1.0,C.background1);
line(sl,3.81,4.20,4.10,4.37,muted,true,false);line(sl,5.25,4.20,4.95,4.37,muted,true,false);
line(sl,2.20,4.87,3.20,4.87);line(sl,5.85,4.87,6.72,4.87);line(sl,9.02,4.87,9.82,4.87);
text(sl,'HTTPS',2.18,4.42,1.02,.26,12,teal,false,{align:'center'});
text(sl,'요청',5.9,4.43,.78,.26,12,teal,false,{align:'center'});
text(sl,'조회·저장',8.96,4.43,.96,.26,11,teal,false,{align:'center'});
text(sl,'서비스의 공개 입구',3.2,5.64,2.65,.31,16,ink,false,{align:'center'});
text(sl,'공인 IP 없음\nALB에서만 접속',6.72,5.56,2.30,.53,14,muted,false,{align:'center'});
text(sl,'공인 IP 없음\nWeb에서만 접속',9.82,5.56,2.30,.53,14,muted,false,{align:'center'});
text(sl,'사용자는 입구(ALB)를 거칩니다. Web·DB에는 외부에서 직접 접속하지 않습니다.',.7,6.8,11.95,.35,16,teal);

pptx._slides.forEach((slide,i)=>{if(i>0){current=i+1;text(slide,String(i+1),12.1,7.12,.55,.22,10,muted,false,{align:'right'});}});
assert.strictEqual(manifest.length,3);assert.strictEqual(pptx._slides.length,3);
fs.writeFileSync(path.join(__dirname,'stage1-manifest.json'),JSON.stringify({slides:manifest,elements:audit},null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,slides:3,elements:audit.length}));})();
'''
Path('docs/발표/샘플_검토/1차_표지개요AWS/build_stage1.cjs').write_text(prefix+body,encoding='utf-8')
print('Stage-1 source created from approved new source helpers; no final artifact changed.')
