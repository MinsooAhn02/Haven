# coding: utf-8
from pathlib import Path
import re,json
p=Path('docs/발표/통합계획_제작/build_haven_20261105.cjs');s=p.read_text(encoding='utf-8')
notes={
'서비스 구현과 복원':'Django 기본 User, Post와 세션을 재사용한다. 작성자는 서버 세션에서 정한다. 글 요청 body는 한국어와 CSRF 부가 바이트를 포함해 8,192바이트 경계를 시험한다. DB runtime과 migration 계정을 분리하고 비밀값을 Git에 넣지 않는다. health 응답만으로 DB 성공을 판단하지 않는다. 별도 DB 복원 후 앱 조회와 접근 거부를 확인하고 코드 롤백 전 DB 호환을 검토한다.',
'권한 분리와 관리 접속':'IAM 사용자와 그룹은 과제 실습으로 구성한다. 일상 운영은 임시 Role을 우선 비교하고 개인 IAM 예외에는 MFA와 근거를 기록한다. 점검, 배포, Web, DB 권한을 분리한다. Resource:*만으로 과권한을 단정하지 않는다. Web과 DB 모두 SSM Agent, 인스턴스 프로파일, DNS와 outbound 연결이 필요하다. 앱 관리자는 계정 상태와 이력만 관리한다.',
'도메인·HTTPS·메일 연결':'도메인 주체, DNS 권한과 메일 방식은 결정할 사항이다. DNS를 ALB에 연결하고 ACM 인증서와 443 listener를 구성한다. 80은 필요한 경우 HTTPS 전환용이다. 브라우저에서 프록시 경계, 쿠키와 CSRF를 확인한다. 메일 API 성공과 실제 수신을 구분하며 이메일 인증을 가입 필수로 추가하지 않는다. Endpoint만으로 일반 인터넷 연결이 가능하다고 가정하지 않는다.',
'WAF 정책 적용과 개선':'ALB Regional web ACL을 Count부터 적용한다. 규칙 이름, 버전, priority, 예외, WCU와 비용을 기록한다. 정상 한국어, 기호, 코드와 8,191/8,192/8,193바이트 경계를 시험한다. 빈도 시험은 평가창과 지연을 기록하며 N번째 즉시 차단을 가정하지 않는다. 조정용과 확인용 요청을 나누고 정상 실패 시 되돌린다. HTTP 403만으로 WAF 차단을 확정하지 않는다.',
'운영자용 점검 도구':'구현 예정 파일은 scripts/network_audit.py와 scripts/request_verify.py다. SG는 live/fixture, 재현은 run/correlate를 제공한다. AWS profile 또는 Role을 쓰고 키를 입력 파일에 넣지 않는다. 대화형 비밀번호와 메모리 세션, TLS 검증, 외부 리다이렉트 거부를 적용한다. 제안 기본값은 timeout 10초, 요청 100회, 초당 1회, 총 300초이며 상한은 각각 30초, 1,000회, 초당 5회, 900초다. SG는 IPv4/IPv6, 범위 포트, 전체 프로토콜, 참조, SG 합집합, pagination과 API 실패를 다루고 방향을 결과에 포함한다.',
'검증과 증거 정리':'PR 검사는 앱과 SG fixture부터 Django 설정과 의존성 점검으로 확장한다. Action 고정과 최소 권한을 검토하고 외부 PR에 운영 Secret을 주지 않는다. 소수 표준 매핑을 전체 준수로 설명하지 않는다. 요청 상관 ID는 인증 근거가 아니다. WAF 판정 BLOCK/ALLOW/UNKNOWN과 대응 상태 PENDING_LOG/MATCHED/UNRESOLVED를 구분한다. 분모 0은 N/A이며 정책 외 조건이 다르면 직접 개선율로 비교하지 않는다. sampled requests의 노출도 확인한다.',
'추진 순서와 완료 기준':'M0에서 범위, 계정, 리전, 주소, 출구, 인증, 버전, 예산, 담당, 날짜와 로그인 제한 수치를 결정한다. 로컬 서비스 후 AWS 통합과 복원을 확인한다. 점검 기준선 이후 수동 정책 변경과 재시험을 수행한다. 앱, IAM 초안, 네트워크 설계와 fixture는 병렬 준비할 수 있다. 출구 실패 시 설계를 다시 결정하고 서버를 임시 공개하지 않는다. 제출 전 가림본, 시연과 비용/종료 절차를 준비한다.'}
pattern=r"sl=add\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'\);"
def replace(m):
 if m.group(1) not in notes:return m.group(0)
 return 'sl=add('+','.join(json.dumps(x,ensure_ascii=False) for x in [m.group(1),m.group(2),m.group(3),m.group(4),notes[m.group(1)]])+');'
s=re.sub(pattern,replace,s).replace(' 기존 PPT와 미리보기 및 제작 소스는 사용하지 않았다.','')
s=s.replace('B1 EC2Web/DB구축 B2 IAM사용자그룹정책 B3 VPCSG라우팅 B4 WAF/IPS범위확인. 모든산출물예정. 본PPT는공식원문을다시검토한결과가아니며 현재기본계획 내부분류를사용한다.','B1은 Web/DB, B2는 IAM, B3는 네트워크, B4는 WAF 정책과 연결한다. 산출물은 예정 작업이며 공식 인정 조건과 별도 IPS 요구는 추가 확인이 필요하다.')
s=s.replace('C2 최소권한분석은Prowler+정책검토/실제허용거부로확인하고자체SGCLI가IAM전체정책해석을하는것으로설명하지않는다. C4테스트집합차단율은전체공격방어율아님.','C2는 Prowler와 정책 검토, 실제 허용/거부로 확인한다. SG CLI는 IAM 전체 정책 해석을 제공하지 않는다. C4 시험 집합 차단율은 전체 공격 방어율을 뜻하지 않는다.')
p.write_text(s,encoding='utf-8')
p=Path('README.md');s=p.read_text(encoding='utf-8-sig');s=s.replace('새 기본 계획서 PPT는 **README 검토 후 작성 예정**입니다. 아직 생성하지 않은 PPT 링크는 게시하지 않습니다.','[기본 프로젝트 계획서 PPT 초안](docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx): 새 기본 계획서를 바탕으로 만든 14장 발표 자료입니다. 기술과 구성은 팀 검토용 권고안이며 구현 완료를 뜻하지 않습니다.')
p.write_text(s,encoding='utf-8')
p=Path('docs/발표/통합계획_제작/debug_new.cjs')
if p.exists():p.unlink()
print('Speaker notes polished; README linked to new 14-slide artifact.')
