# coding: utf-8
from pathlib import Path
src=Path('docs/발표/샘플_검토/1차_표지개요AWS/build_stage1.cjs').read_text(encoding='utf-8-sig')
prefix=src.split("pptx.addSection({title:'표지와 개요'});")[0]
prefix=prefix.replace('Haven_재구성_1차샘플.pptx','Haven_재구성_2차샘플.pptx').replace('보안 검증: 1차 샘플','보안 검증: 2차 샘플')
body=r'''
pptx.addSection({title:'접속·구현·복구'});
let sl=add('허용할 연결과 막을 연결','사용자 요청은 정해진 세 구간으로 통과시키고, 서버로 바로 들어오는 우회 접속을 막습니다.','접속·구현·복구','4.2~4.4절','기본 사용자 서비스 경로만 설명한 그림이다. 사용자→ALB HTTPS443, ALB SG→Web HTTP80, Web SG→DB TCP5432를 허용한다. Web/DB는 공인 IP 없이 비공개 서브넷에 두고 SG/route/NACL/listener를 함께 검증한다. HTTP80을 외부에 열면 HTTPS 전환용이다. SSM 관리와 패키지/메일/로그 outbound는 별도 권한과 경로이며 이 사용자 요청 세 구간과 구분한다. 앱의 기록/첨부 인가를 SG가 수행하는 것으로 설명하지 않는다. 실제 허용과 거부 결과는 앞으로 확인할 시험이다.');
const allowed=[
 ['사용자 → 외부 요청 입구','HTTPS 443 / 인터넷에서 서비스 접속'],
 ['외부 요청 입구 → 웹 서버','ALB 보안 그룹에서만 / HTTP 80'],
 ['웹 서버 → DB 서버','Web 보안 그룹에서만 / TCP 5432']
];
allowed.forEach((a,i)=>{
 const y=2.26+i*1.20;rect(sl,.75,y,7.25,.99,i===0?mint:pale);
 text(sl,'0'+(i+1),.98,y+.14,.56,.36,22,teal,true);
 text(sl,a[0],1.77,y+.12,5.96,.39,22,ink,true);
 text(sl,a[1],1.77,y+.61,5.96,.25,15,muted);
});
rect(sl,8.55,2.26,4.05,3.39,C.background1,coral);
text(sl,'차단할 연결',8.81,2.49,3.53,.47,25,coral,true);
text(sl,'사용자 → 웹 서버\n사용자 → DB 서버',8.81,3.39,3.53,1.00,21,ink);
text(sl,'허가되지 않은 서버의\nDB 접속도 거부',8.81,4.63,3.53,.67,18,muted);
text(sl,'기록 공유·파일 다운로드 권한은\n앱이 별도로 확인합니다.',8.58,5.92,4.0,.58,15,muted);
text(sl,'서비스 접속과 관리 접속은 구분합니다. 서버 관리는 SSM 권한과 연결 경로를 따로 준비합니다.',.76,6.77,11.95,.37,16,teal);

sl=add('화면에서 저장까지의 동작','화면에서 보낸 내용을 웹 서버가 확인한 뒤, 기록 정보와 실제 파일을 나눠 저장합니다.','접속·구현·복구','3절, 5~6절','서비스 입구 ALB는 앞의 구성도에 설명한 경유 지점이다. 이 그림은 그 뒤 Web 내부 처리를 확대한 것이다. Nginx가 요청을 전달하고 Gunicorn이 Django 앱을 실행한다. Django에서 인증과 입력을 검사하며 조회는 소유자 또는 활성 공유, 변경은 소유자만 허용한다. CSRF와 파일 형식/크기/용량 검증을 적용한다. 텍스트 CRUD와 multipart 업로드는 별도 endpoint/제한이다. Post/PostShare/Attachment 메타데이터는 PostgreSQL에, 파일 bytes는 동일 Web EC2의 EBS 비공개 폴더에 둔다. 다운로드는 인가 후 서버 스트림이며 공개 media URL이 없다. DB와 파일시스템은 하나의 transaction이 아니므로 최종 저장 실패와 예약/임시/고아 정리를 명세대로 처리한다.');
rect(sl,4.10,2.21,5.18,4.00,pale);
text(sl,'웹 서버 안에서 처리',4.39,2.43,4.6,.44,23,teal,true);
node(sl,'웹 화면','기록 / 공유 / 첨부',.75,3.22,2.28,1.14,mint);
node(sl,'요청 전달','Nginx',4.40,3.22,1.80,1.14,C.background1);
node(sl,'권한 검사·처리','Django / Gunicorn',6.65,3.22,2.25,1.14,mint);
node(sl,'DB 서버','기록·권한·파일 정보',10.08,3.22,2.50,1.14,pale);
line(sl,3.03,3.79,4.40,3.79);line(sl,6.20,3.79,6.65,3.79);line(sl,8.90,3.79,10.08,3.79);
text(sl,'ALB 경유',3.06,3.25,1.31,.30,14,teal,false,{align:'center'});
text(sl,'정보 저장',8.98,3.25,1.01,.30,13,teal,false,{align:'center'});
node(sl,'비공개 파일','Web EBS / 실제 파일',6.65,4.98,2.25,1.02,C.background1);
line(sl,7.78,4.36,7.78,4.98);
text(sl,'소유자·공유 권한 확인\n입력·파일 검증\n거부 시 최종 저장 안 함',4.40,4.88,1.93,1.10,14,muted);
text(sl,'별도 DB 서버',10.08,4.70,2.50,.34,16,muted,false,{align:'center'});
text(sl,'실제 첨부 파일은 Web의 비공개 저장 공간에, 기록·권한·파일 정보는 DB에 보관합니다.',.76,6.77,11.95,.37,16,teal);

sl=add('저장한 내용을 유지하고 복구하는 방법','재시작 후에도 남아 있는지, 백업으로 다시 사용할 수 있는지를 나눠 확인합니다.','접속·구현·복구','5.3절, 6.2~6.3절, 8절','두 검증 절차를 설명한 장표이며 사용자 저장마다 서버를 재시작하거나 복원한다는 의미가 아니다. 첫 행은 서비스/서버 재시작 뒤 기록과 첨부의 영속성을 확인한다. 둘째 행은 DB, 비공개 파일과 대응 목록(manifest)을 같은 정합 기준으로 백업하고 별도 환경에 복원하는 시험이다. 일관된 스냅샷이 없으면 짧은 쓰기 중지 구간으로 기준점을 맞춘다. manifest에는 파일 참조/크기/무결성 정보를 두고 누락/고아를 구분한다. 복원 뒤 소유자와 활성 공유 대상의 조회/다운로드, 비인가/해제/삭제 파일의 거부를 확인한다. health나 백업 파일 생성만으로 성공을 판단하지 않는다. 실패 시 운영 데이터에 덮어쓰지 않고 원인 분석과 재시험을 수행한다. 심화 암호화/키 복원은 이 기본 장표 범위가 아니다.');
text(sl,'재시작 시험',.82,2.17,5.7,.43,23,teal,true);
const persistence=[['기록·파일 저장','가상 데이터로 준비'],['서버 재시작','저장 공간은 유지'],['다시 조회','기록·첨부가 같은지 확인']];
persistence.forEach((a,i)=>{const x=.8+i*4.17;node(sl,a[0],a[1],x,2.86,3.39,1.12,i===2?mint:pale);if(i<2)line(sl,x+3.39,3.42,x+4.17,3.42);});
text(sl,'백업·복원 시험',.82,4.39,5.7,.43,23,teal,true);
const recovery=[['DB·파일·대응 목록 백업','같은 기준 시점으로 보관'],['별도 환경에 복원','원본 운영 환경과 분리'],['내용·권한 재시험','파일 대조 / 허용·거부 확인']];
recovery.forEach((a,i)=>{const x=.8+i*4.17;node(sl,a[0],a[1],x,5.07,3.39,1.12,i===2?mint:pale);if(i<2)line(sl,x+3.39,5.63,x+4.17,5.63);});
text(sl,'백업 파일이 생긴 것만으로 완료하지 않습니다. 복원한 기록·첨부와 접근 권한까지 다시 확인합니다.',.76,6.77,11.95,.37,16,teal);

const targets=[4,7,8];pptx._slides.forEach((slide,i)=>{current=i+1;text(slide,String(targets[i]),12.1,7.12,.55,.22,10,muted,false,{align:'right'});manifest[i].finalSlide=targets[i];});
assert.strictEqual(pptx._slides.length,3);
fs.writeFileSync(path.join(__dirname,'stage2-manifest.json'),JSON.stringify({stage:2,finalSlideNumbers:targets,slides:manifest,elements:audit},null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,slides:3,finalSlides:targets,elements:audit.length}));})();
'''
Path('docs/발표/샘플_검토/2차_연결구현복원/build_stage2.cjs').write_text(prefix+body,encoding='utf-8')
render=Path('tasks/ppt-stage1-validation/render_stage1.ps1').read_text(encoding='utf-8-sig').replace('docs/발표/샘플_검토/1차_표지개요AWS/Haven_재구성_1차샘플.pptx','docs/발표/샘플_검토/2차_연결구현복원/Haven_재구성_2차샘플.pptx').replace('tasks/ppt-stage1-validation','tasks/ppt-stage2-validation')
Path('tasks/ppt-stage2-validation/render_stage2.ps1').write_text(render,encoding='utf-8')
print('Stage 2 only: planned slides 4, 7, 8.')
