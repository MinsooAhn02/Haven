const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const {applyTheme}=require('C:/Users/Minsoo/.agents/skills/synced/a43ab093-0be2-499a-ac28-68686dfc911c_9cc853e1-ee84-4bcc-b00e-ebb9bbb2bd3c/pptx/scripts/apply_theme.js');
const pptx=new pptxgen();pptx.layout='LAYOUT_WIDE';
pptx.author='ORCHESTRAION';pptx.subject='Haven 기본 프로젝트 구현 계획';pptx.title='Haven 클라우드 보안 프로젝트 계획서';pptx.company='ORCHESTRAION';pptx.lang='ko-KR';
const THEME={name:'Haven Teal',headFontFace:'맑은 고딕',bodyFontFace:'맑은 고딕',colors:{dk1:'163E40',lt1:'F7F8F3',dk2:'486466',lt2:'E2EDE8',accent1:'087F78',accent2:'B8E2D0',accent3:'D5674C',accent4:'6A8586',accent5:'91BDB7',accent6:'DFE6D4',hlink:'087F78',folHlink:'486466'}};
pptx.theme={headFontFace:THEME.headFontFace,bodyFontFace:THEME.bodyFontFace,lang:'ko-KR'};
const C=pptx.SchemeColor,S=pptx.ShapeType;
const dark=C.text1,ink=C.text1,muted=C.text2,bg=C.background1,pale=C.background2,teal=C.accent1,mint=C.accent2,coral=C.accent3;
const out=path.resolve(__dirname,'../Haven_통합계획_기반_프로젝트계획서_초안.pptx');
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
 {placeholder:{options:{name:'title',type:'title',x:.65,y:.66,w:12,h:.63,fontSize:32,bold:true,color:ink,margin:0}}},
 {placeholder:{options:{name:'subtitle',type:'body',x:.67,y:1.48,w:12,h:.4,fontSize:16,color:muted,margin:0}}}
]});
pptx.addSection({title:'서비스와 구성'});
// 01 cover: no legacy asset or source is loaded.
current++;let sl=pptx.addSlide({sectionTitle:'서비스와 구성'});sl.background={color:dark};
text(sl,'Haven',.8,1.65,7,1.3,76,C.background1,true);
text(sl,'클라우드 보안 프로젝트 계획서',.86,3.13,7,.6,27,mint);
text(sl,'ORCHESTRAION',.86,4.14,7,.55,26,C.background1,true);
text(sl,'기본 프로젝트 / 팀 검토용 초안',.86,5.6,7,.4,16,mint);
text(sl,'클라우드\n×\n보안',9.3,2.0,3.1,3.15,39,C.background1,true,{align:'center'});
sl.addNotes('근거: 기본프로젝트_계획.md 1절. 기본 프로젝트만 설명한다. 권고 설계이며 구현 완료 또는 팀 합의를 뜻하지 않는다. 심화 암호화, PKI, 파일 공유, 보안 웹 대시보드, 자동 대응은 본 초안 범위에서 제외한다.');manifest.push({slide:1,title:'Haven',source:'1절'});
// 02
sl=add('서비스와 점검 도구','사용자는 자신의 기록을 관리하고, 운영자는 접근 통제와 정책을 검증한다.','서비스와 구성','1~2절','시험에는 가상 계정과 데이터만 사용한다. 점검 Role은 읽기 전용이며 설정 변경은 별도 운영자가 검토 후 수동으로 수행한다.');
text(sl,'사용자용 개인 기록 서비스',.7,2.3,5.8,.5,26,teal,true);
text(sl,'가입·로그인 → 내 기록 → 본인 글 CRUD',.7,3.08,5.8,.78,21);
text(sl,'Django 화면과 서버의 소유권 검사로\n작성자만 자신의 기록을 사용할 수 있게 한다.',.7,4.12,5.75,1.0,19,muted);
text(sl,'운영자용 보안 점검 도구',7.0,2.3,5.6,.5,26,teal,true);
text(sl,'SG 설정 점검 + 제한된 요청 재현',7,3.08,5.6,.78,21);
text(sl,'결과·로그 대조 → 정책 수동 수정 → 재시험\nJSON/CSV와 변경 전후 증거를 남긴다.',7,4.12,5.6,1.0,19,muted);
line(sl,6.5,2.3,6.5,5.55,mint,false,false);
node(sl,'예정 결과물','웹 서비스 / 두 CLI / 검증 자료',.7,5.55,11.95,.8,mint);
note(sl,'기본 범위: 가상 데이터 기반 검증. 공유 글·파일·보안 대시보드·실시간 탐지·자동 정책 변경은 제외.');
// 03 UI native wireframes
sl=add('사용자 화면과 권한','Django Templates로 필요한 화면을 구현하고, 서버가 매 요청의 소유권을 검사한다.','서비스와 구성','2~3절, 5절','가입/로그인/목록/상세/작성/수정/삭제 확인, 제한된 계정 관리와 이력을 구현한다. GET 삭제는 확인 화면만, 실제 삭제와 로그아웃은 POST+CSRF. 타인/없는 ID는 동일 404. 관리자에는 상태 관리와 LogEntry 이력만 허용하며 타인 본문/비밀번호/권한 편집 금지. OS/DB 최고권한까지 열람 불가를 의미하지 않는다. 입력 label, 키보드, 대비, 좁은 화면과 오류 안내를 시험한다.');
rect(sl,.7,2.2,5.75,3.25,C.background1,mint);rect(sl,.7,2.2,5.75,.57,pale);text(sl,'Haven  /  내 기록',.95,2.3,4.8,.32,18,ink,true);
text(sl,'내 기록 목록',.96,3.04,3.8,.4,21,teal,true);text(sl,'[새 기록]',5.05,3.06,1.1,.34,15,teal,true);
text(sl,'네트워크 실습 메모                 작성 시각\n정책 검증 준비                      작성 시각',.96,3.75,5.1,.85,17);
text(sl,'기록이 없으면 첫 작성 안내 / 페이지 이동',.96,4.84,5.1,.3,14,muted);
rect(sl,6.86,2.2,5.75,3.25,C.background1,mint);rect(sl,6.86,2.2,5.75,.57,pale);text(sl,'기록 작성 / 수정',7.11,2.3,4.8,.32,18,ink,true);
text(sl,'제목',7.13,3.04,.8,.3,16);rect(sl,8.02,2.99,4.28,.45,pale);
text(sl,'본문',7.13,3.74,.8,.3,16);rect(sl,8.02,3.66,4.28,1.0,pale);
text(sl,'오류는 입력 아래 / 실패 시 비민감 입력 보존',7.13,4.83,5.1,.3,14,muted);
text(sl,'일반 회원: 본인 기록 CRUD',.75,5.85,5.6,.4,19,teal,true);text(sl,'관리자: 계정 활성/비활성과 변경 이력',6.95,5.85,5.65,.4,19,teal,true);
note(sl,'서버 검증: 세션 인증 + owner 조회 + POST/CSRF. 타인·없는 기록은 같은 404로 거부한다.');
// 04 architecture
sl=add('전체 시스템 구성','외부 요청은 ALB로 받고 Web과 DB는 비공개로 운영한다.','서비스와 구성','4.1절','WAF는 ALB에 연결한 정책으로 별도 프록시 서버가 아니다. 실선은 서비스 요청, 점선은 정책/관리/보조 관계. Web/DB 각 1대이며 전체 HA나 무중단을 전제하지 않는다. CloudWatch Logs 우선, SSM Agent/IAM/outbound를 두 서버 모두 준비한다.');
node(sl,'사용자','브라우저',.75,3.28,1.75,1.0);
node(sl,'ALB','TLS 종료',3.35,3.28,2.25,1.0,mint);
node(sl,'Web EC2 × 1','Nginx / Gunicorn / Django',6.35,3.28,2.75,1.0,mint);
node(sl,'DB EC2 × 1','PostgreSQL / EBS',10.0,3.28,2.55,1.0);
line(sl,2.5,3.78,3.35,3.78);line(sl,5.6,3.78,6.35,3.78);line(sl,9.1,3.78,10,3.78);
text(sl,'HTTPS 443',2.4,2.89,1.2,.3,13,teal);text(sl,'HTTP 80',5.56,2.89,1.1,.3,13,teal);text(sl,'TCP 5432',8.97,2.89,1.2,.3,13,teal);
node(sl,'DNS / ACM','도메인 / 인증서',.75,2.03,2.3,.83);line(sl,3.05,2.45,4.47,3.28,muted,true);
node(sl,'AWS WAF','web ACL 연결',3.35,2.03,2.25,.83);line(sl,4.47,2.86,4.47,3.28,muted,true);
node(sl,'CloudWatch Logs','WAF 요청 / 규칙',6.35,2.03,2.75,.83);line(sl,5.6,2.44,6.35,2.44,muted,true);
node(sl,'SSM 관리','서버별 권한 / 연결',6.35,5.02,2.75,.83);line(sl,7.72,5.02,7.72,4.28,muted,true);line(sl,9.1,5.44,11.27,5.44,muted,true);line(sl,11.27,5.44,11.27,4.28,muted,true);
text(sl,'메일 시험 발송 / 백업과 별도 복원',.78,5.23,5.0,.5,19,teal,true);
note(sl,'ALB→Web은 HTTP: 전 구간 암호화 아님. Web/DB 각 1대: 전체 고가용성·무중단 구성 아님.');
// 05 network
sl=add('네트워크와 접근 경계','서브넷 배치와 SG의 출발지·포트를 함께 정의하고 정상·거부 연결을 시험한다.','서비스와 구성','4.2~4.4절','ALB를 서로 다른 AZ의 공개 서브넷 두 개에 연결한다. 그림은 배치 관계이며 ALB가 두 서버라는 뜻이 아니다. Web/DB 공인 IP 없음. 443은 외부, 80은 ALB SG, 5432는 Web SG만. 실제 도달성은 IP/route/SG/NACL/listener를 함께 확인한다. 관리22/3389 기본 미개방. 출구D6는 NAT/Endpoint 목적지 비교 후 결정, Endpoint 일반 인터넷 대체 아님.');
rect(sl,.7,2.18,7.2,3.98,pale);text(sl,'VPC / IGW와 공개 라우팅',.93,2.38,6.7,.4,20,teal,true);
node(sl,'공개 서브넷 A','AZ A',1.0,3.02,2.9,.78,C.background1);node(sl,'공개 서브넷 B','AZ B',4.55,3.02,2.9,.78,C.background1);
node(sl,'ALB','두 공개 서브넷에 연결',2.47,4.13,3.1,.8,mint);line(sl,2.45,3.8,3.25,4.13,muted,true);line(sl,6.0,3.8,4.85,4.13,muted,true);
node(sl,'비공개 Web','공인 IP 없음',1.0,5.24,2.9,.86,C.background1);node(sl,'비공개 DB','공인 IP 없음',4.55,5.24,2.9,.86,C.background1);line(sl,3.93,4.93,2.45,5.24);line(sl,3.9,5.60,4.55,5.60);
text(sl,'허용할 연결',8.48,2.32,4.0,.45,23,teal,true);
text(sl,'외부 → ALB     HTTPS 443\nALB SG → Web  TCP 80\nWeb SG → DB    TCP 5432',8.48,3.0,4.1,1.48,20);
text(sl,'거부할 연결',8.48,4.76,4.0,.45,23,coral,true);text(sl,'Web 우회 / 무권한 DB 접속\n일반 계정 관리 접속',8.48,5.37,4.1,.8,19);
note(sl,'출구 D6 미결정: SSM·패키지·메일·로그 목적지별로 비교. Endpoint는 일반 인터넷 출구가 아니다.');
pptx.addSection({title:'구현과 보안 검증'});
// 06 implementation
sl=add("서비스 구현과 복원","사용 가능한 UI부터 배포·데이터 복구까지 하나의 완료 기준으로 연결한다.","구현과 보안 검증","5~6.3절","Django 기본 User, Post와 세션을 재사용한다. 작성자는 서버 세션에서 정한다. 글 요청 body는 한국어와 CSRF 부가 바이트를 포함해 8,192바이트 경계를 시험한다. DB runtime과 migration 계정을 분리하고 비밀값을 Git에 넣지 않는다. health 응답만으로 DB 성공을 판단하지 않는다. 별도 DB 복원 후 앱 조회와 접근 거부를 확인하고 코드 롤백 전 DB 호환을 검토한다.");
node(sl,'Django Templates','화면 / 인증 / 개인 기록',.75,2.3,3.55,1.0,mint);node(sl,'Nginx + Gunicorn','요청 전달 / 앱 실행',4.9,2.3,3.55,1.0,mint);node(sl,'PostgreSQL + EBS','기록 / 계정 / 데이터 유지',9.05,2.3,3.55,1.0,mint);
item(sl,'01','앱 기능과 입력', '본인 CRUD / CSRF\n안전한 출력 / 로그인 방어',.78,3.85,3.5);
item(sl,'02','운영 배포', '비root / systemd\n재시작 후 실제 기능 확인',4.93,3.85,3.5);
item(sl,'03','DB와 복원', 'DB 계정 권한 분리\n별도 복원 후 기록 대조',9.08,3.85,3.5);
text(sl,'저장 → 재시작 후 조회 → 백업 → 별도 복원 → 앱 조회·거부 재확인',.8,5.88,11.8,.43,21,teal,true);
note(sl,'예정 산출물: 앱·배포 설정 / CRUD·재시작 결과 / DB 권한표 / 백업·복원 결과.');
// 07 IAM
sl=add("권한 분리와 관리 접속","AWS 권한, 회원 권한, DB 권한을 구분하고 각 영역의 허용·거부를 검증한다.","구현과 보안 검증","2.1절, 6.4절","IAM 사용자와 그룹은 과제 실습으로 구성한다. 일상 운영은 임시 Role을 우선 비교하고 개인 IAM 예외에는 MFA와 근거를 기록한다. 점검, 배포, Web, DB 권한을 분리한다. Resource:*만으로 과권한을 단정하지 않는다. Web과 DB 모두 SSM Agent, 인스턴스 프로파일, DNS와 outbound 연결이 필요하다. 앱 관리자는 계정 상태와 이력만 관리한다.");
text(sl,'AWS 운영 / 점검',.78,2.35,3.7,.5,24,teal,true);text(sl,'IAM 사용자·그룹 실습\n운영은 임시 Role 우선 비교\n점검 Role은 읽기 전용',.78,3.16,3.65,1.5,20);
text(sl,'웹 회원 / 관리자',4.95,2.35,3.7,.5,24,teal,true);text(sl,'회원은 본인 기록만\n관리자는 계정 상태만 변경\n서버 소유권 검사와 이력',4.95,3.16,3.65,1.5,20);
text(sl,'DB 실행 / 변경',9.08,2.35,3.5,.5,24,teal,true);text(sl,'runtime과 migration 분리\n앱의 슈퍼유저 사용 금지\n무권한 출발지·작업 거부',9.08,3.16,3.5,1.5,20);
rect(sl,.76,5.28,11.82,.85,mint);text(sl,'SSM 관리: Web·DB 모두 인스턴스 권한 + Agent + 실제 연결 경로 준비',1.0,5.48,11.3,.4,20,ink,true);
note(sl,'예정 증거: 정책·역할표 / 필요한 작업 성공·불필요한 작업 거부 / 일반 계정 관리 접속 거부.');
// 08 external
sl=add("도메인·HTTPS·메일 연결","브라우저 접속과 실제 수신까지 확인해 외부 연결을 마무리한다.","구현과 보안 검증","4.4절, 6.5절","도메인 주체, DNS 권한과 메일 방식은 결정할 사항이다. DNS를 ALB에 연결하고 ACM 인증서와 443 listener를 구성한다. 80은 필요한 경우 HTTPS 전환용이다. 브라우저에서 프록시 경계, 쿠키와 CSRF를 확인한다. 메일 API 성공과 실제 수신을 구분하며 이메일 인증을 가입 필수로 추가하지 않는다. Endpoint만으로 일반 인터넷 연결이 가능하다고 가정하지 않는다.");
node(sl,'DNS','도메인 → ALB',.8,2.55,3.3,1.0,mint);node(sl,'ACM + ALB','인증서 / HTTPS 443',5.0,2.55,3.3,1.0,mint);node(sl,'브라우저','로그인 / 저장 확인',9.2,2.55,3.3,1.0,mint);line(sl,4.1,3.05,5.0,3.05);line(sl,8.3,3.05,9.2,3.05);
text(sl,'접속 검증',.85,4.14,5.55,.45,24,teal,true);text(sl,'도메인·인증서 호스트·유효기간\nHTTP 전환 정책 / 쿠키·CSRF',.85,4.91,5.55,1.0,20);
text(sl,'메일 검증',7.0,4.14,5.55,.45,24,teal,true);text(sl,'SES 또는 외부 서비스 시험 발송\n발송 결과와 실제 수신을 각각 확인',7,4.91,5.55,1.0,20);
note(sl,'메일·SSM·패키지·로그에 필요한 outbound 경로와 비용은 착수 전에 결정한다.');
// 09 waf
sl=add("WAF 정책 적용과 개선","정상 요청을 유지하면서 규칙의 효과와 오탐을 로그로 확인한다.","구현과 보안 검증","6.6절, 8.2절","ALB Regional web ACL을 Count부터 적용한다. 규칙 이름, 버전, priority, 예외, WCU와 비용을 기록한다. 정상 한국어, 기호, 코드와 8,191/8,192/8,193바이트 경계를 시험한다. 빈도 시험은 평가창과 지연을 기록하며 N번째 즉시 차단을 가정하지 않는다. 조정용과 확인용 요청을 나누고 정상 실패 시 되돌린다. HTTP 403만으로 WAF 차단을 확정하지 않는다.");
const steps=[['Count','요청과 로그 관찰'],['로그 대조','규칙·액션 확인'],['선별 Block','필요한 정책만'],['재시험','같은 조건 유지']];
steps.forEach((a,i)=>{const x=.8+i*3.15;node(sl,a[0],a[1],x,2.55,2.72,1.03,i===2?mint:pale);if(i<3)line(sl,x+2.72,3.06,x+3.15,3.06);});
text(sl,'정상 요청',.85,4.15,3.5,.45,24,teal,true);text(sl,'한국어·기호·코드 입력\n로그인·저장·수정 기능 유지',.85,4.88,5.4,1.0,20);
text(sl,'시험 요청',7.0,4.15,3.5,.45,24,teal,true);text(sl,'정해진 SQLi/XSS 패턴·빈도\n규칙 차단과 앱 거부를 구분',7,4.88,5.4,1.0,20);
note(sl,'조정에 쓰지 않은 요청으로 추가 확인. 정상 기능 실패 시 되돌림. HTTP 403만으로 차단을 확정하지 않는다.');
// 10 tools
sl=add("운영자용 점검 도구","기존 스캐너를 활용하면서 자체 도구는 SG 판정과 요청 재현에 집중한다.","구현과 보안 검증","7절","구현 예정 파일은 scripts/network_audit.py와 scripts/request_verify.py다. SG는 live/fixture, 재현은 run/correlate를 제공한다. AWS profile 또는 Role을 쓰고 키를 입력 파일에 넣지 않는다. 대화형 비밀번호와 메모리 세션, TLS 검증, 외부 리다이렉트 거부를 적용한다. 제안 기본값은 timeout 10초, 요청 100회, 초당 1회, 총 300초이며 상한은 각각 30초, 1,000회, 초당 5회, 900초다. SG는 IPv4/IPv6, 범위 포트, 전체 프로토콜, 참조, SG 합집합, pagination과 API 실패를 다루고 방향을 결과에 포함한다.");
text(sl,'자체 SG 점검 CLI',.8,2.3,5.65,.46,25,teal,true);text(sl,'명시한 리전·VPC·SG + 읽기 Role\n→ 수집·기대 규칙 비교 → JSON/CSV',.8,3.03,5.65,1.0,20);
text(sl,'IPv4/IPv6·포트 범위·SG 합집합\npagination과 API 실패를 구분',.8,4.31,5.65,.85,18,muted);
text(sl,'요청 재현 CLI',7.0,2.3,5.6,.46,25,teal,true);text(sl,'허용 URL·시험 계정·요청 집합\n→ 제한된 실행 → WAF·앱 로그 대조',7,3.03,5.6,1.0,20);
text(sl,'요청 수·속도·시간 상한 / TLS 검증\n비밀값·세션은 결과에 저장하지 않음',7,4.31,5.6,.85,18,muted);
rect(sl,.8,5.58,11.8,.62,mint);text(sl,'설정 판정: PASS / FAIL / UNKNOWN / ERROR',1.0,5.74,11.4,.31,20,ink,true);
note(sl,'보조 도구: Prowler는 AWS 설정, ZAP Baseline은 허가된 웹 범위. 경고 수를 실제 취약점 수로 쓰지 않는다.');
// 11 evidence
sl=add("검증과 증거 정리","로컬 시험, 실제 AWS 동작, 정책 전후 비교를 구분해 근거를 남긴다.","구현과 보안 검증","8절, 9.1절","PR 검사는 앱과 SG fixture부터 Django 설정과 의존성 점검으로 확장한다. Action 고정과 최소 권한을 검토하고 외부 PR에 운영 Secret을 주지 않는다. 소수 표준 매핑을 전체 준수로 설명하지 않는다. 요청 상관 ID는 인증 근거가 아니다. WAF 판정 BLOCK/ALLOW/UNKNOWN과 대응 상태 PENDING_LOG/MATCHED/UNRESOLVED를 구분한다. 분모 0은 N/A이며 정책 외 조건이 다르면 직접 개선율로 비교하지 않는다. sampled requests의 노출도 확인한다.");
item(sl,'01','로컬 / PR CI','앱 권한·CSRF·입력 / SG fixture\nDjango 설정·의존성 점검',.8,2.3,5.7);
item(sl,'02','실제 AWS 통합','IAM·SSM·정상/거부 경로\n재시작·복원·HTTPS·메일',7.0,2.3,5.6);
rect(sl,.8,4.26,11.8,.8,pale);text(sl,'실행 ID → 환경·버전 → 요청 → WAF/앱 로그 → 결과·정책 변경',1.0,4.46,11.4,.39,20,teal,true);
text(sl,'비교할 값',.85,5.47,2.35,.4,22,teal,true);text(sl,'정상 요청 오탐 / 시험 요청 차단 / UNKNOWN·ERROR\n전체 수·판정 가능한 분모·제외 사유를 함께 기록',3.3,5.36,9.0,.87,19);
note(sl,'CI 통과는 실제 AWS 증거를 대신하지 않는다. 공개 자료에는 비밀값·쿠키·개인정보·원문 로그를 제외한다.');
pptx.addSection({title:'추진과 과업 대응'});
// 12 milestones
sl=add("추진 순서와 완료 기준","구현과 검증을 단계별로 끝내고, 미결정 사항은 착수 전에 확정한다.","추진과 과업 대응","9절, 11절","M0에서 범위, 계정, 리전, 주소, 출구, 인증, 버전, 예산, 담당, 날짜와 로그인 제한 수치를 결정한다. 로컬 서비스 후 AWS 통합과 복원을 확인한다. 점검 기준선 이후 수동 정책 변경과 재시험을 수행한다. 앱, IAM 초안, 네트워크 설계와 fixture는 병렬 준비할 수 있다. 출구 실패 시 설계를 다시 결정하고 서버를 임시 공개하지 않는다. 제출 전 가림본, 시연과 비용/종료 절차를 준비한다.");
const ms=[['M0','설계','화면·권한·구성·비용 결정'],['M1','로컬 서비스','UI·개인 CRUD·권한 시험'],['M2','AWS 통합','접속·거부·재시작·복원'],['M3','점검 도구','fixture·실제 설정·로그 대조'],['M4','정책 개선','동일 조건 전후·정상 회귀'],['M5','제출 준비','증거·시연·운영·종료 절차']];
ms.forEach((a,i)=>{const y=2.19+i*.57;text(sl,a[0],.83,y,.7,.4,19,teal,true);text(sl,a[1],1.73,y,2.35,.4,19,ink,true);text(sl,a[2],4.28,y,8.0,.4,19);if(i<5)line(sl,1.15,y+.43,1.15,y+.57,mint,false,false);});
text(sl,'시연: 사용자 기능 → 타인 접근 거부 → 설정 점검 → WAF 개선 결과',.83,5.91,11.7,.4,20,teal,true);
note(sl,'착수 결정: 출구·리전·버전·예산·담당·일정·메일 방식. 날짜와 역할은 임의로 확정하지 않는다.');
function checklist(title,subtitle,rows,notes){const s=add(title,subtitle,'추진과 과업 대응','10절',notes);s.addTable([['과업','구현 계획','검증 / 예정 산출물','설명 장'].map(t=>({text:t,options:{bold:true,fill:mint}})),...rows],{x:.7,y:2.25,w:11.95,h:3.8,colW:[1.55,3.4,5.85,1.15],rowH:.79,fontSize:17,color:ink,fontFace:'+mn-lt',border:{type:'solid',color:'C9DBD4',pt:.6},fill:bg,margin:.13,bold:false,autoPage:false,verbose:false,align:'left',valign:'middle'});note(s,'통합 계획의 내부 추적 번호이며 완료 체크가 아니다. 공식 인정 조건과 별도 IPS 요구 여부는 미확인.');return s;}
// 13 B checklist
sl=checklist('필수 과업 체크리스트','기본 필수 4개를 서비스·권한·네트워크·보안 정책의 결과물로 연결한다.',[
['B1\n서비스','EC2 Web/DB와 개인 기록 UI','CRUD·재시작·별도 복원\n구축 결과서 / 인프라 구성도','3~6'],
['B2\nIAM','사용자·그룹·정책과 역할 분리','필요 작업 성공·무권한 거부\n정책 / 권한표 / 결과서','7'],
['B3\n네트워크','VPC·서브넷·SG·라우팅·관리','정상 경로·우회 접속 거부\n네트워크 구성도 / 접속 결과','4~5, 7'],
['B4\n보안 정책','ALB WAF 연결과 로그 대조','정상/시험 요청·규칙/액션 확인\n보안 장비·정책 구성 결과서','9~11']
],'B1은 Web/DB, B2는 IAM, B3는 네트워크, B4는 WAF 정책과 연결한다. 산출물은 예정 작업이며 공식 인정 조건과 별도 IPS 요구는 추가 확인이 필요하다.');
// 14 C checklist
sl=checklist('선택 과업 체크리스트','외부 연결과 점검·개선까지 같은 서비스에서 확인한다.',[
['C1\n외부 연결','도메인·DNS·HTTPS·메일','인증서·브라우저 접속·실제 수신\n설정과 동작 확인 자료','8'],
['C2\n최소권한','권한 검토와 정책 수정','변경 근거·정책 diff·허용/거부 재시험\n권한 개선 결과','7, 10'],
['C3\n자체 점검','읽기 전용 SG 점검 CLI','fixture·실제 대조·오류 분류\n소스 / JSON·CSV / 시험 결과','10~11'],
['C4\n개선·재현','요청 재현 / WAF 정책 조정','같은 조건 전후·확인용·정상 회귀\n오탐·차단·UNKNOWN 비교','9~11']
],'C2는 Prowler와 정책 검토, 실제 허용/거부로 확인한다. SG CLI는 IAM 전체 정책 해석을 제공하지 않는다. C4 시험 집합 차단율은 전체 공격 방어율을 뜻하지 않는다.');
pptx._slides.forEach((slide,i)=>{if(i>0){current=i+1;text(slide,String(i+1),12.1,7.08,.55,.22,10,muted,false,{align:'right'});}});
assert.strictEqual(manifest.length,14);assert.strictEqual(current,14);
fs.writeFileSync(path.join(__dirname,'new-deck-manifest.json'),JSON.stringify({slideCount:14,slides:manifest,elements:audit},null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,slides:current,checkedElements:audit.length}));})();
