const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const {applyTheme}=require('C:/Users/Minsoo/.agents/skills/synced/a43ab093-0be2-499a-ac28-68686dfc911c_9cc853e1-ee84-4bcc-b00e-ebb9bbb2bd3c/pptx/scripts/apply_theme.js');
const pptx=new pptxgen();pptx.layout='LAYOUT_WIDE';
pptx.author='ORCHESTRAION';pptx.subject='Haven 기본 프로젝트 구현 계획';pptx.title='Haven AWS 기반 기록 공유 서비스와 보안 검증';pptx.company='ORCHESTRAION';pptx.lang='ko-KR';
const THEME={name:'Haven Teal',headFontFace:'맑은 고딕',bodyFontFace:'맑은 고딕',colors:{dk1:'163E40',lt1:'F7F8F3',dk2:'486466',lt2:'E2EDE8',accent1:'087F78',accent2:'B8E2D0',accent3:'D5674C',accent4:'6A8586',accent5:'91BDB7',accent6:'DFE6D4',hlink:'087F78',folHlink:'486466'}};
pptx.theme={headFontFace:THEME.headFontFace,bodyFontFace:THEME.bodyFontFace,lang:'ko-KR'};
const C=pptx.SchemeColor,S=pptx.ShapeType;
const dark=C.text1,ink=C.text1,muted=C.text2,bg=C.background1,pale=C.background2,teal=C.accent1,mint=C.accent2,coral=C.accent3;
const out=path.resolve(__dirname,'../Haven_프로젝트_계획서_최종.pptx');
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

pptx.addSection({title:"개요와 전체 구성"});
current++;let sl=pptx.addSlide({sectionTitle:'개요와 전체 구성'});sl.background={color:dark};
text(sl,'Haven',.8,.95,7.8,.95,54,C.background1,true);
text(sl,'AWS 기반 기록 공유 서비스와\n보안 검증',.86,2.35,8.9,1.75,38,C.background1,true);
text(sl,'서비스 구축부터 접근 통제와 정책 검증까지',.88,4.62,8.6,.45,20,mint);
text(sl,'팀 ORCHESTRAION  |  기본 프로젝트 계획',.88,6.3,9.1,.36,16,mint);
text(sl,'클라우드\n×\n보안',10.18,2.36,2.35,2.54,30,C.background1,true,{align:'center'});
sl.addNotes('근거: 기본프로젝트_계획.md 1절. AWS에 기록과 파일을 공유하는 서비스를 만들고, 권한과 보안 정책을 검증하는 기본 프로젝트 계획이다. 특정 활성 회원에게 읽기 공유를 부여하거나 해제하고, 첨부는 인가 후 다운로드한다. 계획은 구축 완료나 공식 과제 인정 확정을 뜻하지 않는다.');
manifest.push({slide:1,title:'Haven: AWS 기반 기록 공유 서비스와 보안 검증',source:'1절'});


sl=add('프로젝트 개요','기록과 파일을 공유하는 서비스에 접근 권한을 적용하고, 제대로 동작하는지 시험합니다.',"개요와 전체 구성",'1~3절','소유자는 본인 기록 CRUD, 공유 부여/해제, 첨부 추가/삭제를 수행한다. 현재 사용자와 소유자가 활성이고 글이 ACTIVE인 경우 공유 대상은 조회와 다운로드만 허용한다. 변경이나 재공유는 허용하지 않는다. 공유 해제 후 다음 요청부터 거부하며 이미 받은 사본이나 진행 중 전송을 회수하는 기능은 아니다. 자세한 점검 도구 구분은 뒤의 점검 장표에서 설명한다.');
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


sl=add('전체 시스템 구성','서비스 접속 경로에 보안 정책·관리·로그·백업을 연결해 함께 검증할 계획입니다.',"개요와 전체 구성",'4절, 6절','주요 서비스 요청은 사용자→ALB HTTPS443→Web HTTP80→PostgreSQL TCP5432다. ALB는 두 공개 서브넷/AZ에 연결되며 Web과 DB는 별도 비공개 서브넷에 두고 공인 IP를 부여하지 않는다. 세부 배치는 다음 네트워크 장에서 설명한다. WAF는 ALB에 붙이는 정책이지 별도 프록시 서버가 아니다. WAF 로그는 CloudWatch Logs로 모아 요청/규칙/액션을 대조한다. DNS/ACM을 ALB에 연결하고 메일은 SES 또는 외부 서비스를 선택해 실제 수신을 확인한다. SSM은 Web/DB 각각의 인스턴스 권한과 outbound 경로가 필요하다. 백업은 DB와 Web EBS 비공개 첨부, manifest의 정합성을 맞춰 별도 복원한다. ALB TLS 종료로 전 구간 암호화가 아니며 Web/DB 각 한 대로 전체 HA/무중단을 주장하지 않는다. 출구 방식은 아직 미결정이다.');
rect(sl,2.77,3.18,9.80,1.79,C.background1,mint);
rect(sl,3.0,3.31,2.39,1.53,mint);rect(sl,5.86,3.31,3.00,1.53,pale);rect(sl,9.80,3.31,2.54,1.53,pale);
text(sl,'공개 / Public',3.39,3.37,1.64,.26,12,teal,true,{align:'center'});
text(sl,'비공개 / Private · Web',6.03,3.37,2.66,.26,12,teal,true,{align:'center'});
text(sl,'비공개 / Private · DB',9.94,3.37,2.26,.26,12,teal,true,{align:'center'});
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


sl=add('AWS 안에 서비스를 어떻게 배치하는가','외부 요청을 받는 입구만 공개하고, Web과 DB는 각각 비공개 서브넷에 둡니다.',"개요와 전체 구성",'4.1~4.4절','서비스 접속 경로를 단순화한 계획도다. ALB는 서로 다른 AZ의 공개 서브넷 두 개에 연결되며 Web/DB는 각각 별도의 비공개 서브넷에 배치한다. 두 서버는 공인 IP가 없다. 사용자→ALB는 HTTPS443, ALB SG→Web은 HTTP80, Web SG→DB는 TCP5432만 허용한다. ALB에서 TLS가 종료되므로 전 구간 암호화로 설명하지 않는다. Web/DB 각 한 대로 전체 고가용성이나 무중단을 주장하지 않는다. WAF 정책, SSM 관리, 도메인/메일, 출구와 백업은 이후 설명할 내용이며 이 접속 경로 그림에서는 생략한다. 파일 bytes는 비공개 Web EBS에, 기록과 권한/첨부 메타데이터는 DB에 저장한다. 실제 리전/CIDR/출구는 착수 결정 사항이다.');
rect(sl,2.67,2.05,9.98,4.42,C.background1,mint);
text(sl,'AWS 클라우드 / VPC 네트워크',2.94,2.18,8.9,.35,17,teal,true);
rect(sl,3.0,2.84,3.05,3.35,mint);
rect(sl,6.55,2.84,2.65,3.35,pale);
rect(sl,9.65,2.84,2.65,3.35,pale);
text(sl,'공개 서브넷 (Public)',3.16,3.0,2.73,.43,17,ink,true,{align:'center'});
rect(sl,3.2,3.62,1.21,.58,C.background1);rect(sl,4.64,3.62,1.21,.58,C.background1);
text(sl,'서브넷 A\n가용 영역 A',3.26,3.68,1.09,.43,12,muted,false,{align:'center'});
text(sl,'서브넷 B\n가용 영역 B',4.70,3.68,1.09,.43,12,muted,false,{align:'center'});
text(sl,'비공개 (Private)\nWeb 서브넷',6.7,3.03,2.35,.86,19,ink,true,{align:'center'});
text(sl,'비공개 (Private)\nDB 서브넷',9.8,3.03,2.35,.86,19,ink,true,{align:'center'});
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
text(sl,'공인 IP 없음\n웹 요청: ALB만 허용',6.72,5.56,2.30,.53,14,muted,false,{align:'center'});
text(sl,'공인 IP 없음\nDB 연결: Web만 허용',9.82,5.56,2.30,.53,14,muted,false,{align:'center'});
text(sl,'사용자는 입구(ALB)를 거칩니다. Web·DB에는 외부에서 직접 접속하지 않습니다.',.7,6.8,11.95,.35,16,teal);


sl=add('허용할 연결과 막을 연결','사용자 요청은 정해진 세 구간으로 통과시키고, 서버로 바로 들어오는 우회 접속을 막습니다.',"개요와 전체 구성",'4.2~4.4절','기본 사용자 서비스 경로만 설명한 그림이다. 사용자→ALB HTTPS443, ALB SG→Web HTTP80, Web SG→DB TCP5432를 허용한다. Web/DB는 공인 IP 없이 비공개 서브넷에 두고 SG/route/NACL/listener를 함께 검증한다. HTTP80을 외부에 열면 HTTPS 전환용이다. SSM 관리와 패키지/메일/로그 outbound는 별도 권한과 경로이며 이 사용자 요청 세 구간과 구분한다. 앱의 기록/첨부 인가를 SG가 수행하는 것으로 설명하지 않는다. 실제 허용과 거부 결과는 앞으로 확인할 시험이다.');
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


// 03 UI native wireframes
sl=add('사용자가 이용할 기능과 화면','내 기록·공유받은 기록과 공유·첨부 기능을 화면에서 사용할 계획입니다.',"개요와 전체 구성",'2~3절, 5절','가입/로그인/내 기록/공유받은 기록/공유 관리/첨부와 제한된 계정 관리 화면을 구현한다. GET 삭제는 확인 화면만, 실제 삭제와 로그아웃은 POST+CSRF. 인증된 사용자의 미공유/해제/소유자 비활성/없는 ID는 동일 404. 현재 계정 비활성은 인증 단계에서 거부한다. 공유 대상은 조회와 첨부 다운로드만 가능하다. 관리자에는 상태 관리와 LogEntry 이력만 허용하며 타인 본문/비밀번호/권한 편집 금지. OS/DB 최고권한까지 열람 불가를 의미하지 않는다. 입력 label, 키보드, 대비, 좁은 화면과 오류 안내를 시험한다. 첨부 제안 상한은 TXT/PDF, 파일당 2MiB, 기록당 3개, 계정당 10MiB다. 텍스트 body 8192바이트와 별도 multipart 2162688바이트를 구분한다. 파일 형식과 크기를 검사하고 UUID 비공개 저장, attachment/nosniff/no-store 응답과 임시/고아 정리를 적용한다. 형식 검증은 악성 파일 부재를 보장하지 않는다.');
rect(sl,.7,2.2,5.75,3.25,C.background1,mint);rect(sl,.7,2.2,5.75,.57,pale);text(sl,'Haven  /  내 기록',.95,2.3,4.8,.32,18,ink,true);
text(sl,'내 기록 / 공유받은 기록',.96,3.04,3.8,.4,19,teal,true);text(sl,'[새 기록]',5.05,3.06,1.1,.34,15,teal,true);
text(sl,'네트워크 실습 메모                 작성 시각\n정책 검증 준비                      작성 시각',.96,3.75,5.1,.85,17);
text(sl,'기록이 없으면 첫 작성 안내 / 페이지 이동',.96,4.84,5.1,.3,14,muted);
rect(sl,6.86,2.2,5.75,3.25,C.background1,mint);rect(sl,6.86,2.2,5.75,.57,pale);text(sl,'기록 작성 / 공유·첨부',7.11,2.3,4.8,.32,18,ink,true);
text(sl,'제목',7.13,3.04,.8,.3,16);rect(sl,8.02,2.99,4.28,.45,pale);
text(sl,'본문',7.13,3.74,.8,.3,16);rect(sl,8.02,3.66,4.28,.66,pale);
text(sl,'첨부 [파일 선택] [업로드] / 저장 후 소유자만',7.13,4.47,5.1,.3,14,muted);text(sl,'공유 [회원 지정] [읽기 권한 부여/해제]',7.13,4.93,5.1,.3,14,muted);
text(sl,'회원: 본인 변경 / 공유받은 글 조회',.75,5.85,5.6,.4,19,teal,true);text(sl,'관리자: 계정 상태와 이력만',6.95,5.85,5.65,.4,19,teal,true);
note(sl,'파일: TXT/PDF · 2MiB/개 · 3개/기록 · 10MiB/계정. 비공개 저장하고 인가 후 다운로드합니다.');

pptx.addSection({title:"구현과 보안 검증"});
sl=add('구현 및 보안 검증 계획','서비스를 만든 뒤 접근을 보호하고, 점검 결과를 바탕으로 개선합니다.',"구현과 보안 검증",'6~9절','뒤에 설명할 내용을 미리 보여주는 구분 장표다. 서비스 구현은 요청 처리/저장과 재시작/정합 백업 복원이다. 접근 보호는 앱 사용자 권한, AWS/SSM/DB 운영 권한, WAF를 구분한다. 점검 도구는 SG 읽기 전용 CLI와 제한된 요청 재현이며 운영자가 수동 변경 후 같은 조건으로 재시험한다. GitHub 협업은 전 단계를 지원하며 마지막 장에서 구체화한다.');
const intro=[['01  서비스 만들기','화면과 서버 연결\n데이터 저장·복구','8~9장'],['02  접근 보호하기','사용자·운영 권한\n웹 요청 보안 정책','10~12장'],['03  점검·개선하기','설정과 요청 시험\n결과 비교·정책 개선','13장']];
intro.forEach((a,i)=>{const x=.8+i*4.17;node(sl,a[0],'',x,2.90,3.39,.88,i===1?mint:pale);text(sl,a[1],x+.12,4.28,3.15,1.0,22,ink);text(sl,a[2],x+.12,5.52,3.15,.34,17,teal,true);if(i<2)line(sl,x+3.39,3.34,x+4.17,3.34);});
text(sl,'협업은 GitHub에서 작업·변경·시험 결과를 공유하는 방식으로 진행할 계획입니다.',.76,6.80,11.95,.33,16,teal);


sl=add('화면에서 저장까지의 동작','화면에서 보낸 내용을 웹 서버가 확인한 뒤, 기록 정보와 실제 파일을 나눠 저장합니다.',"구현과 보안 검증",'3절, 5~6절','서비스 입구 ALB는 앞의 구성도에 설명한 경유 지점이다. 이 그림은 그 뒤 Web 내부 처리를 확대한 것이다. Nginx가 요청을 전달하고 Gunicorn이 Django 앱을 실행한다. Django에서 인증과 입력을 검사하며 조회는 소유자 또는 활성 공유, 변경은 소유자만 허용한다. CSRF와 파일 형식/크기/용량 검증을 적용한다. 텍스트 CRUD와 multipart 업로드는 별도 endpoint/제한이다. Post/PostShare/Attachment 메타데이터는 PostgreSQL에, 파일 bytes는 동일 Web EC2의 EBS 비공개 폴더에 둔다. 다운로드는 인가 후 서버 스트림이며 공개 media URL이 없다. DB와 파일시스템은 하나의 transaction이 아니므로 최종 저장 실패와 예약/임시/고아 정리를 명세대로 처리한다.');
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
text(sl,'소유자·공유 확인\n입력·파일 검증\n최종 저장 거부',4.40,4.88,1.93,1.10,14,muted);
text(sl,'별도 DB 서버',10.08,4.70,2.50,.34,16,muted,false,{align:'center'});
text(sl,'실제 첨부 파일은 Web의 비공개 저장 공간에, 기록·권한·파일 정보는 DB에 보관합니다.',.76,6.77,11.95,.37,16,teal);


sl=add('저장한 내용을 유지하고 복구하는 방법','재시작 후에도 남아 있는지, 백업으로 다시 사용할 수 있는지를 나눠 확인합니다.',"구현과 보안 검증",'5.3절, 6.2~6.3절, 8절','두 검증 절차를 설명한 장표이며 사용자 저장마다 서버를 재시작하거나 복원한다는 의미가 아니다. 첫 행은 서비스/서버 재시작 뒤 기록과 첨부의 영속성을 확인한다. 둘째 행은 DB, 비공개 파일과 대응 목록(manifest)을 같은 정합 기준으로 백업하고 별도 환경에 복원하는 시험이다. 일관된 스냅샷이 없으면 짧은 쓰기 중지 구간으로 기준점을 맞춘다. manifest에는 파일 참조/크기/무결성 정보를 두고 누락/고아를 구분한다. 복원 뒤 소유자와 활성 공유 대상의 조회/다운로드, 비인가/해제/삭제 파일의 거부를 확인한다. health나 백업 파일 생성만으로 성공을 판단하지 않는다. 실패 시 운영 데이터에 덮어쓰지 않고 원인 분석과 재시험을 수행한다. 심화 암호화/키 복원은 이 기본 장표 범위가 아니다.');
text(sl,'재시작 시험',.82,2.17,5.7,.43,23,teal,true);
const persistence=[['기록·파일 저장','가상 데이터로 준비'],['서버 재시작','저장 공간은 유지'],['다시 조회','기록·첨부가 같은지 확인']];
persistence.forEach((a,i)=>{const x=.8+i*4.17;node(sl,a[0],a[1],x,2.86,3.39,1.12,i===2?mint:pale);if(i<2)line(sl,x+3.39,3.42,x+4.17,3.42);});
text(sl,'백업·복원 시험',.82,4.39,5.7,.43,23,teal,true);
const recovery=[['DB·파일·대응 목록 백업','같은 기준 시점으로 보관'],['별도 환경에 복원','원본 운영 환경과 분리'],['내용·권한 재시험','파일 대조 / 허용·거부 확인']];
recovery.forEach((a,i)=>{const x=.8+i*4.17;node(sl,a[0],a[1],x,5.07,3.39,1.12,i===2?mint:pale);if(i<2)line(sl,x+3.39,5.63,x+4.17,5.63);});
text(sl,'백업 파일이 생긴 것만으로 완료하지 않습니다. 복원한 기록·첨부와 접근 권한까지 다시 확인합니다.',.76,6.77,11.95,.37,16,teal);


sl=add('서비스 사용자 권한','기록과 첨부를 볼 수 있는 권한과, 바꿀 수 있는 권한을 나눕니다.',"구현과 보안 검증",'2~3절, 5절','일반 사용자는 현재 계정과 소유자가 활성이고 글이 ACTIVE인 상태에서 본인 또는 유효한 공유를 확인한다. 소유자는 본인 CRUD와 공유/해제/첨부 관리를 수행하고 공유 대상은 조회와 활성 첨부 다운로드만 허용한다. 직접 URL/ID/author 조작과 POST 변경도 서버에서 검증한다. 인증된 사용자의 미공유/해제/소유자 비활성/없는 객체는 같은404, 현재 계정 비활성은 기존 세션도 인증 단계에서 거부한다. 공유 해제는 다음 요청부터 반영하며 이미 받은 사본이나 진행 중 전송을 회수하는 보장은 아니다. 앱 관리자의 계정 상태 권한이 타인 기록이나 첨부 권한을 자동 부여하지 않는다. 관리자는 비밀번호/그룹/staff/superuser 수정 권한이 없다. OS/DB 최고관리자까지 원문을 못 읽는다고 주장하지 않는다.');
sl.addTable([
 ['사용자','읽기·다운로드','기록·첨부 변경','공유 대상 관리'].map(t=>({text:t,options:{bold:true,fill:mint}})),
 ['소유자 A','허용','작성·수정·삭제 허용','권한 부여·해제 허용'],
 ['공유 대상 B','허용','거부','거부'],
 ['그 외 회원','거부','거부','거부']
],{x:.76,y:2.40,w:11.85,colW:[1.74,3.37,3.37,3.37],rowH:.78,fontSize:18,color:ink,fontFace:'+mn-lt',border:{type:'solid',color:'C9DBD4',pt:.6},fill:bg,margin:.12,autoPage:false,align:'left',valign:'middle'});
rect(sl,.78,5.86,11.80,.56,pale);text(sl,'앱 관리자: 계정 활성·비활성과 변경 이력만 관리. 타인 본문·첨부 접근 권한은 자동으로 생기지 않습니다.',.98,5.99,11.40,.29,15,ink);
text(sl,'공유 예시: A가 B에게 공유 → B는 읽기만 가능 → 공유 해제 → B의 다음 조회·다운로드 거부',.76,6.79,11.95,.34,15,teal);


sl=add('AWS·서버·DB 권한','서비스 회원 권한과 별개로, 운영 작업에 필요한 권한도 나눕니다.',"구현과 보안 검증",'2.1절, 6.3~6.4절','IAM 사용자와 그룹 정책은 과제 실습으로 유지하며 운영은 임시 Role 기반 인증을 우선 비교한다. 교육 환경 예외는 MFA와 근거를 기록한다. 구축/배포/읽기 점검/Web 실행/DB 관리를 역할별로 제한하고 Resource:* 하나만으로 과권한을 단정하지 않는다. SSM은 Web과 DB 모두 Agent, 인스턴스 프로파일, DNS와 outbound 경로가 필요하다. DB runtime은 앱의 필요한 작업, migration은 스키마 변경으로 분리하고 앱이 슈퍼유저로 동작하지 않게 한다. 담당자는 아직 배정하지 않는다. 실제 허용/거부 시험과 정책 diff로 최소권한 개선을 확인한다.');
const ops=[['AWS 자원 관리','IAM / 작업별 역할','구축 담당: 필요한 설정 변경\n점검 도구: 설정 읽기만\n불필요한 자원 접근 거부'],['서버 관리 접속','SSM / 승인된 운영자','승인된 운영자만 접속\nWeb·DB별 권한과 연결 준비\n일반 계정의 관리 접속 거부'],['DB 사용과 변경','DB 계정 / 작업 분리','앱 계정: 필요한 데이터 작업\n변경 계정: 스키마 변경\n앱의 최고관리 권한 사용 금지']];
ops.forEach((a,i)=>{const x=.8+i*4.17;text(sl,a[0],x,2.38,3.45,.48,24,teal,true);text(sl,a[1],x,3.06,3.45,.34,16,muted);text(sl,a[2],x,3.94,3.45,1.66,18,ink);});
rect(sl,.8,5.96,11.80,.58,mint);text(sl,'확인할 결과: 필요한 작업은 성공하고, 맡지 않은 작업과 무권한 접속은 거부되는가?',1.0,6.10,11.40,.30,18,ink,true);
text(sl,'역할 이름만 나누지 않고 정책 설정·허용 작업·거부 작업의 결과를 함께 남길 계획입니다.',.76,6.80,11.95,.33,16,teal);


// 09 waf
sl=add("잘못된 웹 요청을 어떻게 막는가","웹 요청 보안 정책(WAF)을 적용하고, 정상 사용을 유지하면서 필요한 요청을 차단합니다.","구현과 보안 검증","6.6절, 8.2절","ALB Regional web ACL을 Count부터 적용한다. 규칙 이름, 버전, priority, 예외, WCU와 비용을 기록한다. 정상 한국어, 기호, 코드와 텍스트 body의 8,191/8,192/8,193바이트 경계를 시험한다. 업로드는 별도 multipart 상한이며 WAF의 부분 본문 검사와 oversize를 확인한다. Count 결과에 따라 해당 경로의 필요한 특정 body 규칙만 조정하고 헤더/쿼리 통제와 앱 검증을 유지한다. 빈도 시험은 평가창과 지연을 기록하며 N번째 즉시 차단을 가정하지 않는다. 조정용과 확인용 요청을 나누고 정상 실패 시 되돌린다. HTTP 403만으로 WAF 차단을 확정하지 않는다.");
const steps=[['관찰(Count)','차단 전 영향 확인'],['로그 확인','정상·시험 요청 대조'],['필요한 차단','확인한 규칙만 적용'],['다시 시험','정상 기능 유지 확인']];
steps.forEach((a,i)=>{const x=.8+i*3.15;node(sl,a[0],a[1],x,2.55,2.72,1.03,i===2?mint:pale);if(i<3)line(sl,x+2.72,3.06,x+3.15,3.06);});
text(sl,'정상 요청',.85,4.15,3.5,.45,24,teal,true);text(sl,'한국어·기호·코드 입력\n로그인·저장·수정 기능 유지',.85,4.88,5.4,1.0,20);
text(sl,'시험 요청',7.0,4.15,3.5,.45,24,teal,true);text(sl,'정해진 공격 패턴·반복 요청\n보안 정책 차단과 앱 거부 구분',7,4.88,5.4,1.0,20);
note(sl,'파일 요청은 전체 검사가 보장되지 않아 앱의 파일 검증도 수행합니다. 차단 원인은 로그와 함께 확인합니다.');

sl=add('점검 도구로 무엇을 확인하는가','설정을 읽어 비교하는 도구와, 정해진 요청을 보내 확인하는 도구를 만듭니다.',"구현과 보안 검증",'7~8절','설정 점검은 읽기 전용 SG 수집과 기대 규칙 비교다. IPv4/IPv6, 범위/전체 프로토콜, SG 참조/합집합, pagination과 API 실패를 처리하고 PASS/FAIL/UNKNOWN/ERROR로 출력한다. 요청 재현은 허가 대상과 가상 계정, 무해한 시험 payload, 요청 수/속도/시간 상한, TLS 검증과 리다이렉트 제한을 둔다. 응답403만으로 WAF 차단을 확정하지 않고 규칙/액션과 앱 처리 결과를 대조한다. 정상 입력과 소유자/공유/비인가/해제, 첨부의 권한과 거부 시험을 포함한다. WAF 로그 대기와 수집 오류는 성공으로 계산하지 않는다. 점검 도구가 자동으로 정책을 바꾸지 않는다. 정책 외 조건을 유지해 전후 비교하고 조정용/확인용 집합을 구분한다. 경고 수와 실제 문제 수를 혼동하지 않는다.');
text(sl,'설정 점검 도구',.82,2.29,5.65,.48,25,teal,true);text(sl,'요청 재현 도구',7.00,2.29,5.60,.48,25,teal,true);
node(sl,'AWS 연결 규칙 읽기','읽기 전용 권한 / 보안 그룹',.82,3.09,5.55,.92,pale);
node(sl,'정해진 사용자·요청·대상','정상 사용 / 권한 실패 / 시험 요청',7.00,3.09,5.55,.92,pale);
line(sl,3.59,4.01,3.59,4.45);line(sl,9.77,4.01,9.77,4.45);
text(sl,'실제 설정 ↔ 기대 규칙 비교',.88,4.61,5.43,.46,21,ink,true);text(sl,'응답 ↔ WAF·앱 로그 대조',7.06,4.61,5.43,.46,21,ink,true);
text(sl,'통과 / 위반 / 판단 불가 / 실행 오류',.88,5.27,5.43,.37,17,muted);text(sl,'허용·거부·미확정을 근거와 함께 기록',7.06,5.27,5.43,.37,17,muted);
rect(sl,.82,6.02,11.73,.52,mint);text(sl,'문제 확인 → 필요한 정책을 수동 수정 → 같은 조건으로 재시험',1.03,6.12,11.31,.31,19,ink,true);
text(sl,'기존 도구도 활용: Prowler는 AWS 설정, ZAP Baseline은 허가된 웹 범위의 보조 점검.',.76,6.80,11.95,.33,15,teal);


pptx.addSection({title:"협업과 추진"});
sl=add('GitHub로 협업하며 구현하는 방법','기능과 시험 작업을 나누고, 변경 내용과 검증 결과를 공유하며 만들 계획입니다.',"협업과 추진",'9.1절 및 사용자 승인 협업 계획','앞으로 사용할 협업 방식이며 Issue, 브랜치 규칙이나 Actions가 이미 설정됐다는 뜻이 아니다. Issue에 작업/완료 조건을 적고 담당을 팀에서 정한다. 작업별 브랜치에서 수정하고 PR에 변경/관련Issue/시험과 가림 자료를 공유한다. 다른 팀원 검토와 준비된 자동 검사를 거쳐 main에 통합한다. 자동 검사는 구현된 앱/SG fixture부터 Django 설정/의존성 검사로 확장한다. CI 통과는 실제 AWS 배포와 통합 동작 증거가 아니며 AWS 반영은 별도 절차다. 실제 환경 시험과 증거를 작업에 연결해 다음 개선을 정한다. 비밀값/세션/민감 원본 로그는 올리지 않는다. 추진 순서는 설계→로컬 서비스→AWS 통합→점검/개선→증거/시연/종료다. 날짜와 담당은 임의로 배정하지 않는다.');
const team=[['01  작업 나누기','Issue / 할 일과 완료 조건'],['02  개별 작업','브랜치 / 작업별로 분리'],['03  변경 공유','PR / 변경 내용과 시험 결과'],['04  검토·검사','팀원 검토 / 준비된 자동 검사'],['05  main에 통합','검토와 필요한 검사를 통과'],['06  실제 시험·개선','AWS 동작 / 가림 증거 공유']];
team.forEach((a,i)=>{const x=.8+(i%3)*4.17,y=i<3?2.55:4.67;node(sl,a[0],a[1],x,y,3.39,.97,i===5?mint:pale);if(i%3<2)line(sl,x+3.39,y+.485,x+4.17,y+.485);});
line(sl,10.84,3.52,10.84,4.08,muted,false,false);line(sl,10.84,4.08,2.50,4.08,muted,false,false);line(sl,2.50,4.08,2.50,4.67,muted);
text(sl,'추진: 설계 → 로컬 서비스 → AWS 통합 → 점검·개선 → 증거·시연',.84,6.17,11.72,.40,20,teal,true);
text(sl,'검토·자동 검사와 실제 AWS 동작 확인은 구분합니다. 비밀값과 민감한 원본 로그는 공유하지 않습니다.',.76,6.80,11.95,.33,15,teal);



pptx._slides.forEach((slide,i)=>{if(i>0){current=i+1;text(slide,String(i+1),12.1,7.12,.55,.22,10,muted,false,{align:'right'});}});
assert.strictEqual(manifest.length,14);assert.strictEqual(pptx._slides.length,14);
const finalManifest={file:out,slideCount:14,slides:manifest,elements:audit};
fs.writeFileSync(path.join(__dirname,'new-deck-manifest.json'),JSON.stringify(finalManifest,null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,slides:pptx._slides.length,elements:audit.length}));})();
