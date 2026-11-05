const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const {applyTheme}=require('C:/Users/Minsoo/.agents/skills/synced/a43ab093-0be2-499a-ac28-68686dfc911c_9cc853e1-ee84-4bcc-b00e-ebb9bbb2bd3c/pptx/scripts/apply_theme.js');
const pptx=new pptxgen();pptx.layout='LAYOUT_WIDE';
pptx.author='ORCHESTRAION';pptx.subject='Haven 기본 프로젝트 구현 계획';pptx.title='Haven AWS 기반 기록 공유 서비스와 보안 검증: 1차 샘플';pptx.company='ORCHESTRAION';pptx.lang='ko-KR';
const THEME={name:'Haven Teal',headFontFace:'맑은 고딕',bodyFontFace:'맑은 고딕',colors:{dk1:'163E40',lt1:'F7F8F3',dk2:'486466',lt2:'E2EDE8',accent1:'087F78',accent2:'B8E2D0',accent3:'D5674C',accent4:'6A8586',accent5:'91BDB7',accent6:'DFE6D4',hlink:'087F78',folHlink:'486466'}};
pptx.theme={headFontFace:THEME.headFontFace,bodyFontFace:THEME.bodyFontFace,lang:'ko-KR'};
const C=pptx.SchemeColor,S=pptx.ShapeType;
const dark=C.text1,ink=C.text1,muted=C.text2,bg=C.background1,pale=C.background2,teal=C.accent1,mint=C.accent2,coral=C.accent3;
const out=path.resolve(__dirname,'Haven_재구성_1차샘플.pptx');
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
text(sl,'서브넷 A\n가용 영역 A',3.26,3.68,1.09,.43,12,muted,false,{align:'center'});
text(sl,'서브넷 B\n가용 영역 B',4.70,3.68,1.09,.43,12,muted,false,{align:'center'});
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
text(sl,'공인 IP 없음\n웹 요청: ALB만 허용',6.72,5.56,2.30,.53,14,muted,false,{align:'center'});
text(sl,'공인 IP 없음\nDB 연결: Web만 허용',9.82,5.56,2.30,.53,14,muted,false,{align:'center'});
text(sl,'사용자는 입구(ALB)를 거칩니다. Web·DB에는 외부에서 직접 접속하지 않습니다.',.7,6.8,11.95,.35,16,teal);

pptx._slides.forEach((slide,i)=>{if(i>0){current=i+1;text(slide,String(i+1),12.1,7.12,.55,.22,10,muted,false,{align:'right'});}});
assert.strictEqual(manifest.length,3);assert.strictEqual(pptx._slides.length,3);
fs.writeFileSync(path.join(__dirname,'stage1-manifest.json'),JSON.stringify({slides:manifest,elements:audit},null,2));
(async()=>{await pptx.writeFile({fileName:out});await applyTheme(out,THEME);console.log(JSON.stringify({file:out,slides:3,elements:audit.length}));})();
