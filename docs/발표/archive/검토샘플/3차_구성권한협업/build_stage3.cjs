const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const {applyTheme}=require('C:/Users/Minsoo/.agents/skills/synced/a43ab093-0be2-499a-ac28-68686dfc911c_9cc853e1-ee84-4bcc-b00e-ebb9bbb2bd3c/pptx/scripts/apply_theme.js');
const pptx=new pptxgen();pptx.layout='LAYOUT_WIDE';
pptx.author='ORCHESTRAION';pptx.subject='Haven 기본 프로젝트 구현 계획';pptx.title='Haven AWS 기반 기록 공유 서비스와 보안 검증: 3차 샘플';pptx.company='ORCHESTRAION';pptx.lang='ko-KR';
const THEME={name:'Haven Teal',headFontFace:'맑은 고딕',bodyFontFace:'맑은 고딕',colors:{dk1:'163E40',lt1:'F7F8F3',dk2:'486466',lt2:'E2EDE8',accent1:'087F78',accent2:'B8E2D0',accent3:'D5674C',accent4:'6A8586',accent5:'91BDB7',accent6:'DFE6D4',hlink:'087F78',folHlink:'486466'}};
pptx.theme={headFontFace:THEME.headFontFace,bodyFontFace:THEME.bodyFontFace,lang:'ko-KR'};
const C=pptx.SchemeColor,S=pptx.ShapeType;
const dark=C.text1,ink=C.text1,muted=C.text2,bg=C.background1,pale=C.background2,teal=C.accent1,mint=C.accent2,coral=C.accent3;
const out=path.resolve(__dirname,'Haven_재구성_3차샘플.pptx');
const audit=[];const manifest=[];let current=0;
function check(x,y,w,h,kind){assert([x,y,w,h].every(Number.isFinite));assert(x>=-.02&&y>=-.02&&w>=0&&h>=0&&x+w<=13.35&&y+h<=7.52,`${current} ${kind} bounds`);audit.push({slide:current,kind,x,y,w,h});}
function text(sl,str,x,y,w,h,size=20,color=ink,bold=false,extra={}){check(x,y,w,h,'text');sl.addText(str,{x,y,w,h,fontSize:size,color,bold,margin:0,breakLine:false,valign:'mid',isTextBox:true,paraSpaceAfterPt:4,...extra});}
function rect(sl,x,y,w,h,fill=pale,stroke=fill){check(x,y,w,h,'shape');sl.addShape(S.rect,{x,y,w,h,fill:{color:fill},line:{color:stroke,width:1}});}
function line(sl,x1,y1,x2,y2,color=teal,dashed=false,arrow=true){check(Math.min(x1,x2),Math.min(y1,y2),Math.abs(x2-x1),Math.abs(y2-y1),'line');sl.addShape(S.line,{x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.abs(x2-x1),h:Math.abs(y2-y1),flipH:x2<x1,flipV:y2<y1,line:{color,width:1.7,...(dashed?{dashType:'dash'}:{}),...(arrow?{beginArrowType:'none',endArrowType:'triangle'}:{})}});}
function node(sl,title,sub,x,y,w,h,fill=pale){rect(sl,x,y,w,h,fill);text(sl,title,x+.14,y+.12,w-.28,sub?h*.40:h-.24,19,ink,true,{align:'center'});if(sub)text(sl,sub,x+.14,y+h*.51,w-.28,h*.35,14,muted,false,{align:'center'});}
function item(sl,num,title,body,x,y,w){text(sl,num,x,y,.53,.45,23,teal,true);text(sl,title,x+.62,y,w-.62,.43,21,ink,true);text(sl,body,x+.62,y+.54,w-.62,.87,17,muted);}
function note(sl,str,color=muted){text(sl,str,.65,6.63,12.0,.42,14,color);}
function add(title,sub,section,source,notes=''){
 current++;const sl=pptx.addSlide({masterName:'content',sectionTitle:section});sl.addText(title,{placeholder:'title'});sl.addText(sub,{placeholder:'subtitle'});
 sl.addNotes(`근거: 기본프로젝트_계획.md ${source}; 필요한 상세: docs/구현명세/기본프로젝트_구현명세.md.\n${notes}\n상태: 팀 검토용 구현 계획. 모든 시험과 산출물은 예정이며 완료 증거가 아니다.`);
 manifest.push({slide:current,title,source});return sl;
}
pptx.defineSlideMaster({title:'content',background:{color:bg},objects:[
 {text:{text:'Haven / ORCHESTRAION',options:{x:9.2,y:.27,w:3.45,h:.3,fontSize:11,color:muted,align:'right',margin:0,isTextBox:true}}},
 {placeholder:{options:{name:'title',type:'title',x:.65,y:.66,w:12,h:.63,fontSize:32,bold:true,color:ink,margin:0,align:'left'}}},
 {placeholder:{options:{name:'subtitle',type:'body',x:.67,y:1.48,w:12,h:.4,fontSize:16,color:muted,margin:0}}}
]});



pptx.addSection({title:'전체 구성과 설명 순서'});
let sl=add('전체 시스템 구성','서비스 접속 경로에 보안 정책·관리·로그·백업을 연결해 함께 검증할 계획입니다.','전체 구성과 설명 순서','4절, 6절','주요 서비스 요청은 사용자→ALB HTTPS443→Web HTTP80→PostgreSQL TCP5432다. ALB는 두 공개 서브넷/AZ에 연결되며 Web과 DB는 별도 비공개 서브넷에 두고 공인 IP를 부여하지 않는다. 세부 배치는 다음 네트워크 장에서 설명한다. WAF는 ALB에 붙이는 정책이지 별도 프록시 서버가 아니다. WAF 로그는 CloudWatch Logs로 모아 요청/규칙/액션을 대조한다. DNS/ACM을 ALB에 연결하고 메일은 SES 또는 외부 서비스를 선택해 실제 수신을 확인한다. SSM은 Web/DB 각각의 인스턴스 권한과 outbound 경로가 필요하다. 백업은 DB와 Web EBS 비공개 첨부, manifest의 정합성을 맞춰 별도 복원한다. ALB TLS 종료로 전 구간 암호화가 아니며 Web/DB 각 한 대로 전체 HA/무중단을 주장하지 않는다. 출구 방식은 아직 미결정이다.');
rect(sl,2.77,3.18,9.80,1.79,C.background1,mint);
rect(sl,3.0,3.31,2.39,1.53,mint);rect(sl,5.86,3.31,3.00,1.53,pale);rect(sl,9.80,3.31,2.54,1.53,pale);
text(sl,'Public',3.39,3.37,1.64,.26,12,teal,true,{align:'center'});
text(sl,'Private / Web',6.03,3.37,2.66,.26,12,teal,true,{align:'center'});
text(sl,'Private / DB',9.94,3.37,2.26,.26,12,teal,true,{align:'center'});
node(sl,'사용자','HTTPS 접속',.65,3.82,1.55,.88,pale);
node(sl,'요청 입구','ALB',3.15,3.82,2.10,.88,C.background1);
node(sl,'웹 서버','Django / 비공개 첨부',6.04,3.82,2.64,.88,C.background1);
node(sl,'DB 서버','PostgreSQL',9.97,3.82,2.19,.88,C.background1);
line(sl,2.20,4.26,3.15,4.26);line(sl,5.25,4.26,6.04,4.26);line(sl,8.68,4.26,9.97,4.26);
text(sl,'HTTPS',2.20,3.85,.94,.25,12,teal,false,{align:'center'});
text(sl,'HTTP 80',5.18,3.85,.95,.25,11,teal,false,{align:'center'});
text(sl,'TCP 5432',8.77,3.85,1.08,.25,11,teal,false,{align:'center'});
node(sl,'도메인·인증서','DNS / ACM',.65,2.17,2.13,.80,pale);
node(sl,'웹 요청 보안','WAF 정책',3.11,2.17,2.20,.80,mint);
node(sl,'요청 로그 확인','CloudWatch Logs',6.10,2.17,2.58,.80,pale);
line(sl,2.78,2.57,3.15,3.99,muted,true);line(sl,3.22,2.97,3.22,3.82,muted,true);line(sl,5.31,2.57,6.10,2.57,muted,true);
node(sl,'서버 관리','SSM / 작업별 권한',.65,5.60,2.62,.80,pale);
node(sl,'시험 메일','SES 또는 외부 메일',6.10,5.60,2.58,.80,pale);
node(sl,'백업·복원','DB / 파일 / 목록',9.97,5.60,2.19,.80,pale);
line(sl,3.27,5.92,6.10,4.70,muted,true);line(sl,3.27,5.92,10.02,4.70,muted,true);
line(sl,8.35,4.70,7.4,5.60,muted,true);line(sl,11.07,4.70,11.07,5.60,muted,true);line(sl,8.68,4.70,9.97,5.60,muted,true);
text(sl,'실선: 서비스 요청   /   점선: 정책·관리·보조 연결. 공개·비공개 배치는 다음 장에서 자세히 봅니다.',.73,6.80,11.96,.33,15,teal);

sl=add('구현 및 보안 검증 계획','서비스를 만든 뒤 접근을 보호하고, 점검 결과를 바탕으로 개선합니다.','전체 구성과 설명 순서','6~9절','뒤에 설명할 내용을 미리 보여주는 구분 장표다. 서비스 구현은 요청 처리/저장과 재시작/정합 백업 복원이다. 접근 보호는 앱 사용자 권한, AWS/SSM/DB 운영 권한, WAF를 구분한다. 점검 도구는 SG 읽기 전용 CLI와 제한된 요청 재현이며 운영자가 수동 변경 후 같은 조건으로 재시험한다. GitHub 협업은 전 단계를 지원하며 마지막 장에서 구체화한다.');
const intro=[['01  서비스 만들기','화면과 서버 연결\n데이터 저장·복구','8~9장'],['02  접근 보호하기','사용자·운영 권한\n웹 요청 보안 정책','10~12장'],['03  점검·개선하기','설정과 요청 시험\n결과 비교·정책 개선','13장']];
intro.forEach((a,i)=>{const x=.8+i*4.17;node(sl,a[0],'',x,2.90,3.39,.88,i===1?mint:pale);text(sl,a[1],x+.12,4.28,3.15,1.0,22,ink);text(sl,a[2],x+.12,5.52,3.15,.34,17,teal,true);if(i<2)line(sl,x+3.39,3.34,x+4.17,3.34);});
text(sl,'협업은 GitHub에서 작업·변경·시험 결과를 공유하는 방식으로 진행할 계획입니다.',.76,6.80,11.95,.33,16,teal);

pptx.addSection({title:'사용자 권한과 운영 권한'});
sl=add('서비스 사용자 권한','기록과 첨부를 볼 수 있는 권한과, 바꿀 수 있는 권한을 나눕니다.','사용자 권한과 운영 권한','2~3절, 5절','일반 사용자는 현재 계정과 소유자가 활성이고 글이 ACTIVE인 상태에서 본인 또는 유효한 공유를 확인한다. 소유자는 본인 CRUD와 공유/해제/첨부 관리를 수행하고 공유 대상은 조회와 활성 첨부 다운로드만 허용한다. 직접 URL/ID/author 조작과 POST 변경도 서버에서 검증한다. 인증된 사용자의 미공유/해제/소유자 비활성/없는 객체는 같은404, 현재 계정 비활성은 기존 세션도 인증 단계에서 거부한다. 공유 해제는 다음 요청부터 반영하며 이미 받은 사본이나 진행 중 전송을 회수하는 보장은 아니다. 앱 관리자의 계정 상태 권한이 타인 기록이나 첨부 권한을 자동 부여하지 않는다. 관리자는 비밀번호/그룹/staff/superuser 수정 권한이 없다. OS/DB 최고관리자까지 원문을 못 읽는다고 주장하지 않는다.');
sl.addTable([
 ['사용자','읽기·다운로드','기록·첨부 변경','공유 대상 관리'].map(t=>({text:t,options:{bold:true,fill:mint}})),
 ['소유자 A','허용','작성·수정·삭제 허용','권한 부여·해제 허용'],
 ['공유 대상 B','허용','거부','거부'],
 ['그 외 회원','거부','거부','거부']
],{x:.76,y:2.40,w:11.85,colW:[1.74,3.37,3.37,3.37],rowH:.78,fontSize:18,color:ink,fontFace:'+mn-lt',border:{type:'solid',color:'C9DBD4',pt:.6},fill:bg,margin:.12,autoPage:false,align:'left',valign:'middle'});
rect(sl,.78,5.86,11.80,.56,pale);text(sl,'앱 관리자: 계정 활성·비활성과 변경 이력만 관리. 타인 본문·첨부 접근 권한은 자동으로 생기지 않습니다.',.98,5.99,11.40,.29,15,ink);
text(sl,'공유 예시: A가 B에게 공유 → B는 읽기만 가능 → 공유 해제 → B의 다음 조회·다운로드 거부',.76,6.79,11.95,.34,15,teal);

sl=add('AWS·서버·DB 권한','서비스 회원 권한과 별개로, 운영 작업에 필요한 권한도 나눕니다.','사용자 권한과 운영 권한','2.1절, 6.3~6.4절','IAM 사용자와 그룹 정책은 과제 실습으로 유지하며 운영은 임시 Role 기반 인증을 우선 비교한다. 교육 환경 예외는 MFA와 근거를 기록한다. 구축/배포/읽기 점검/Web 실행/DB 관리를 역할별로 제한하고 Resource:* 하나만으로 과권한을 단정하지 않는다. SSM은 Web과 DB 모두 Agent, 인스턴스 프로파일, DNS와 outbound 경로가 필요하다. DB runtime은 앱의 필요한 작업, migration은 스키마 변경으로 분리하고 앱이 슈퍼유저로 동작하지 않게 한다. 담당자는 아직 배정하지 않는다. 실제 허용/거부 시험과 정책 diff로 최소권한 개선을 확인한다.');
const ops=[['AWS 자원 관리','IAM / 작업별 역할','구축 담당: 필요한 설정 변경\n점검 도구: 설정 읽기만\n불필요한 자원 접근 거부'],['서버 관리 접속','SSM / 승인된 운영자','승인된 운영자만 접속\nWeb·DB별 권한과 연결 준비\n일반 계정의 관리 접속 거부'],['DB 사용과 변경','DB 계정 / 작업 분리','앱 계정: 필요한 데이터 작업\n변경 계정: 스키마 변경\n앱의 최고관리 권한 사용 금지']];
ops.forEach((a,i)=>{const x=.8+i*4.17;text(sl,a[0],x,2.38,3.45,.48,24,teal,true);text(sl,a[1],x,3.06,3.45,.34,16,muted);text(sl,a[2],x,3.94,3.45,1.66,18,ink);});
rect(sl,.8,5.96,11.80,.58,mint);text(sl,'확인할 결과: 필요한 작업은 성공하고, 맡지 않은 작업과 무권한 접속은 거부되는가?',1.0,6.10,11.40,.30,18,ink,true);
text(sl,'역할 이름만 나누지 않고 정책 설정·허용 작업·거부 작업의 결과를 함께 남길 계획입니다.',.76,6.80,11.95,.33,16,teal);

pptx.addSection({title:'점검과 GitHub 협업'});
sl=add('점검 도구로 무엇을 확인하는가','설정을 읽어 비교하는 도구와, 정해진 요청을 보내 확인하는 도구를 만듭니다.','점검과 GitHub 협업','7~8절','설정 점검은 읽기 전용 SG 수집과 기대 규칙 비교다. IPv4/IPv6, 범위/전체 프로토콜, SG 참조/합집합, pagination과 API 실패를 처리하고 PASS/FAIL/UNKNOWN/ERROR로 출력한다. 요청 재현은 허가 대상과 가상 계정, 무해한 시험 payload, 요청 수/속도/시간 상한, TLS 검증과 리다이렉트 제한을 둔다. 응답403만으로 WAF 차단을 확정하지 않고 규칙/액션과 앱 처리 결과를 대조한다. 정상 입력과 소유자/공유/비인가/해제, 첨부의 권한과 거부 시험을 포함한다. WAF 로그 대기와 수집 오류는 성공으로 계산하지 않는다. 점검 도구가 자동으로 정책을 바꾸지 않는다. 정책 외 조건을 유지해 전후 비교하고 조정용/확인용 집합을 구분한다. 경고 수와 실제 문제 수를 혼동하지 않는다.');
text(sl,'설정 점검 도구',.82,2.29,5.65,.48,25,teal,true);text(sl,'요청 재현 도구',7.00,2.29,5.60,.48,25,teal,true);
node(sl,'AWS 연결 규칙 읽기','읽기 전용 권한 / 보안 그룹',.82,3.09,5.55,.92,pale);
node(sl,'정해진 사용자·요청·대상','정상 사용 / 권한 실패 / 시험 요청',7.00,3.09,5.55,.92,pale);
line(sl,3.59,4.01,3.59,4.45);line(sl,9.77,4.01,9.77,4.45);
text(sl,'실제 설정 ↔ 기대 규칙 비교',.88,4.61,5.43,.46,21,ink,true);text(sl,'응답 ↔ WAF·앱 로그 대조',7.06,4.61,5.43,.46,21,ink,true);
text(sl,'통과 / 위반 / 판단 불가 / 실행 오류',.88,5.27,5.43,.37,17,muted);text(sl,'허용·거부·미확정을 근거와 함께 기록',7.06,5.27,5.43,.37,17,muted);
rect(sl,.82,6.02,11.73,.52,mint);text(sl,'문제 확인 → 필요한 정책을 수동 수정 → 같은 조건으로 재시험',1.03,6.12,11.31,.31,19,ink,true);
text(sl,'기존 도구도 활용: Prowler는 AWS 설정, ZAP Baseline은 허가된 웹 범위의 보조 점검.',.76,6.80,11.95,.33,15,teal);

sl=add('GitHub로 협업하며 구현하는 방법','기능과 시험 작업을 나누고, 변경 내용과 검증 결과를 공유하며 만들 계획입니다.','점검과 GitHub 협업','9.1절 및 사용자 승인 협업 계획','앞으로 사용할 협업 방식이며 Issue, 브랜치 규칙이나 Actions가 이미 설정됐다는 뜻이 아니다. Issue에 작업/완료 조건을 적고 담당을 팀에서 정한다. 작업별 브랜치에서 수정하고 PR에 변경/관련Issue/시험과 가림 자료를 공유한다. 다른 팀원 검토와 준비된 자동 검사를 거쳐 main에 통합한다. 자동 검사는 구현된 앱/SG fixture부터 Django 설정/의존성 검사로 확장한다. CI 통과는 실제 AWS 배포와 통합 동작 증거가 아니며 AWS 반영은 별도 절차다. 실제 환경 시험과 증거를 작업에 연결해 다음 개선을 정한다. 비밀값/세션/민감 원본 로그는 올리지 않는다. 추진 순서는 설계→로컬 서비스→AWS 통합→점검/개선→증거/시연/종료다. 날짜와 담당은 임의로 배정하지 않는다.');
const team=[['01  작업 나누기','Issue / 할 일과 완료 조건'],['02  개별 작업','브랜치 / 작업별로 분리'],['03  변경 공유','PR / 변경 내용과 시험 결과'],['04  검토·검사','팀원 검토 / 준비된 자동 검사'],['05  main에 통합','검토와 필요한 검사를 통과'],['06  실제 시험·개선','AWS 동작 / 가림 증거 공유']];
team.forEach((a,i)=>{const x=.8+(i%3)*4.17,y=i<3?2.55:4.67;node(sl,a[0],a[1],x,y,3.39,.97,i===5?mint:pale);if(i%3<2)line(sl,x+3.39,y+.485,x+4.17,y+.485);});
line(sl,10.84,3.52,10.84,4.08,muted,false,false);line(sl,10.84,4.08,2.50,4.08,muted,false,false);line(sl,2.50,4.08,2.50,4.67,muted);
text(sl,'추진: 설계 → 로컬 서비스 → AWS 통합 → 점검·개선 → 증거·시연',.84,6.17,11.72,.40,20,teal,true);
text(sl,'검토·자동 검사와 실제 AWS 동작 확인은 구분합니다. 비밀값과 민감한 원본 로그는 공유하지 않습니다.',.76,6.80,11.95,.33,15,teal);

const targets=[3,7,10,11,13,14];pptx._slides.forEach((slide,i)=>{current=i+1;text(slide,String(targets[i]),12.1,7.12,.55,.22,10,muted,false,{align:'right'});manifest[i].finalSlide=targets[i];});
assert.strictEqual(pptx._slides.length,6);
fs.writeFileSync(path.join(__dirname,'stage3-manifest.json'),JSON.stringify({stage:3,finalSlideNumbers:targets,slides:manifest,elements:audit},null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,sampleSlides:6,finalSlides:targets,elements:audit.length}));})();
