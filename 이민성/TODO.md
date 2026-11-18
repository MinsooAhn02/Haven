# 6번 이민성 TODO

**브랜치:** `Minsung`

**담당:** 팀장(조장, 11/11 인수인계 완료)·서버 배포·백업/격리 복원·AWS 네트워크·EC2·SSM·ALB/HTTPS·SG CLI · WAF ALB 연결·Block 적용(4회차)·SG 점검 도구 live 모드(11/12 결정)

> 2026-11-11 역할 재배치([docs/인수인계/02](../docs/인수인계/02_역할_재배치.md)): 안민수가 맡던 조장 일·배포·백업/복원을 이어받았다. 실제 SG 읽기 수집 → AUD fixture 대조는 권혁민에게 넘겼다(민성은 수집 명령 SG CLI 제공).
>
> 2026-11-12 변경(조장 결정, `docs/조장_운영기록/2026-11-12.md`): 7번 구민철 합류. SG 실제 점검은 **민성이 `network_audit.py` live 모드 구현·시험·병합**, **구민철이 실행·대조**(`구민철/SG_실제점검_인계.md`), 보람이 읽기 권한. 혁민 담당에서 빠짐. WAF는 혁민 Web ACL·규칙·전용 로그(Count)·Block 판단, **민성 ALB 연결·Block 적용**, 보람 WAF 쓰기 권한(4회차, 11/27까지 마무리 목표). 로그인 실패 제한 수치는 요찬 안 → 조장 결정.

**공통 순서:** [TASK_TODO.md](../TASK_TODO.md)

## 수정 범위

본인 폴더의 network/·compute/·dns/·SG CLI와 fixture. 실제 VPC/SG/route/EC2/ALB/DNS/ACM은 본인만 변경한다. IAM 정책은 김보람 담당이다. 서버 배포·백업/복원은 11/11부터 이민성(이전 안민수), 앱 코드는 신요찬. WAF는 ALB 연결·Block 적용만 본인(구성은 권혁민).

## 2일 단위 임무

### 1회차 · 1~2일차

- [x] VPC/CIDR·공개 ALB용 2개 서브넷·비공개 Web/DB·SG 연결표·SSM 및 설치/로그/메일 목적지별 출구/비용을 설계한다. SG CLI fixture로 정상/위반/ERROR/UNKNOWN·출력을 시험한다.
- [x] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 2회차 · 3~4일차

- [ ] 계정/예산/출구와 변경안 확인 후 VPC/route/SG·Web/DB EC2·SSM을 구성한다. 공인 서버 IP 없이 관리 접속·Web→DB·필요 출구·직접 접근 거부·재시작을 확인해 안민수에게 인계한다.
- [ ] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 3회차 · 5~6일차

- [ ] 배포 후 ALB·DNS/ACM·HTTPS/redirect를 연결한다. 지정 계정/리전/VPC/SG의 실제 읽기 전용 수집을 수동 설정과 대조하고 수집/권한 실패를 PASS와 구분한다.
- [ ] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 4회차 · 7~8일차

- [ ] 확인된 네트워크/SG 문제를 수정하고 허용·직접 접근 거부·재시작을 재시험한다. 구성도·실제 자원/SG·CLI 결과·종료 대상을 정리한다.
- [ ] (11/12 추가) WAF: 혁민이 Count로 구성한 Web ACL을 ALB에 연결하고, 혁민 판단(규칙별 Count 결과·정상 요청 영향)에 따라 Block 적용, 문제 시 Count로 되돌림. 연결·적용 직후 healthz·로그인 확인. 선행: 보람 WAF 쓰기 권한(민성 정책에 wafv2 없음). 4회차 안, 11/27까지 마무리 목표
- [ ] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

## 인계·완료 기준

- 김보람에게 필요한 작업/자원 범위와 출구 비용 항목 전달
- 안민수에게 서버/SG/SSM 대상·연결 시험 결과, 권혁민에게 기대 접근표 전달
- ALB→Web은 기본 HTTP이며 HTTPS 접속을 전 구간 TLS로 설명하지 않음
- 본인 검증과 검토 결과가 있는 변경만 main에 합친다. 미완료 작업은 다음 회차로 넘기며 다른 담당자에게 알린다.
- 회차 통합 후 최신 main을 본인 브랜치에 반영하고 다음 회차를 시작한다.

## 결과 기록

| 회차 | 상태 | 환경·실행 명령·기대/실제 결과 | PR·가림 증거 | 다음 담당자에게 전달할 것 |
|---|---|---|---|---|
| 1 | 완료 | 설계: `network/설계.md`(VPC·서브넷·라우팅·SG·출구/비용, 리전·D6는 김보람 권장, 팀장 승인 대기). SG CLI: Windows·Python 3.13.2, `sg_audit`에서 `python network_audit.py fixture --fixture fixtures\<이름>.json --baseline baseline.json --output-dir out\<이름>` 실행. 기대/실제 종료 코드 일치: pass 0(AUD-01), fail_public_db 1(AUD-02, SG-01), unknown_role 3(AUD-09, SG-06), error_access_denied 2(AUD-08). 덮어쓰기·없는 파일 시 ERROR(2) 확인 | PR 링크(https://github.com/MinsooAhn02/Haven/pull/2). 결과 요약 `sg_audit/README.md` 시험 결과. fixture는 가상 데이터라 가림 대상 없음. 리뷰 보완(팀장): 기대 자산 누락 UNKNOWN, 입력·출력 오류 ERROR(2), 부분 수집 결과 보존, unittest 5개 통과 | 김보람: 리전·D6 승인, 생성 자원·NAT 운영 기간(설계.md 5·6장). 권혁민: 기대 접근표(설계.md 4.3). 안민수: 메일 방식 회신 요청, EC2 OS(AMI) 후보 합의(이민성 제안). 미완료: live 모드·AUD-03~07·10·11(3회차 이후) |
| 2 | 완료 (11/12 NET-06·06-b 통과, 세부 확인 일부 남음) | **11/09 준비(DRY_RUN만):** 환경: Windows Git Bash, aws-cli 2.39.6. 구축 스크립트 `infra/`(build·nat-up·nat-down·destroy) 작성. `bash -n` 6개 OK, `DRY_RUN=1 bash build.sh` → 1/8–8/8, nat-up 1/4–4/4 종료 0, nat-down·destroy(목록·--delete) 미리보기 종료 0. 거부 시험: 프로파일 빈 값 → VPC 생성 전 중단(1), DRY_RUN=2 → 중단(1), destroy --yes → 거절(1). SG 규칙 10줄 설계 4절과 양방향 대조 일치(`infra/SG수작업비교.md`). 연결 확인표 기대값 작성(`network/연결확인표.md`), 실제값은 구축 후.<br>**11/10 EC2 중지·시작(결정 4번):** `ec2-stop.sh`(web→db), `ec2-start.sh`(db→web, 공인 IP·SSM 확인), `night.sh`(ec2-stop + nat-down), `morning.sh`(nat-up + ec2-start, 평일 09~21시만). `DRY_RUN=1` 4개 종료 0. 가짜 aws 시험 `bash test/ec2-fake-test.sh` → **PASS 20 / FAIL 0**(일부러 실패: 서버 0대·2대·ID 불일치·중지 시간 초과·공인 IP·nat-up 실패·시간 밖 → 모두 멈춤(1)). 설명 `infra/EC2시작중지설명.md`, `infra/test/faketest설명.md`<br>**11/10 실제 구축 (팀 IAM 사용자 minsung, 서울):** `build.sh` 7단계에서 nat-up 확인이 Windows `\r` 때문에 오탐으로 멈춤 → `common.sh`에 `aws()` 래퍼(`tr -d '\r'`) 추가 → `nat-up.sh` RST-02 통과 → 남은 8단계만 `build-ec2.sh`(새로 작성, build.sh 8단계와 같음)로 EC2 2대 생성. 모양 확인: 서브넷 자동 공인 IP 끔, rt-private `0.0.0.0/0 → nat-`, SG 규칙 10줄 설계와 일치·전체 허용 outbound 없음, web-1·db-1 t3.small·공인 IP 없음·IMDSv2 필수·SSM 프로파일, gp3 20GB 암호화. 연결확인표 1차: SSM-01~04, NET-02-a/b/c, NET-04-c, OUT-01~04·06·07·09 ✅, OUT-08 ⚠️ 남은 위험, RST-02 ✅. 21:02 `night.sh` → RST-03 ✅(태그된 NAT·EIP 없음)<br>**11/11:** 09:02 `morning.sh` → 새 NAT, 사설 IP 그대로, SSM Online. `test-ec2.sh`(새로 작성)로 시험용 EC2 haven-test-net04 09:09 생성 → 09:23 삭제. **일부러 막힌 걸 확인한 시험:** 시험용 EC2 → db-1:5432, db-1:22, web-1:80 모두 timeout(exit=124) = NET-04·04-b·02-d ✅. 서버 준비(민수 스크립트, 민성 실행): db-setup·web-setup → 첫 배포 `deploy.sh f39e8e64` 중 GitHub SSH 22 timeout(sg-web outbound에 22 없음 = 설계대로 막힘, OUT-13) → 포트를 열지 않고 SSH-over-443으로 해결(민수 #48, OUT-14) → migrate 20건 OK·`haven_app` 점검 OK·healthz `ok` = NET-03 ✅. 재배포 `b068ba5f`(posts.0002_attachment migrate OK, healthz ok). OUT-12 apt 주소 web-1·db-1 모두 `http://` ✅<br>**11/12:** 11/11 21:14 `night.sh` → 09:03 `morning.sh` 뒤 NET-06·06-b ✅(haven·nginx·postgresql active, healthz ok 안·밖, `db ok`). web-1 CloudWatch Agent 설치(nginx access·error·앱 로그 → `/haven/web`, 앱 로그는 rsyslog로 `/var/log/haven/app.log` + logrotate 7일) → 내 PC에서 표시 요청 도착 확인 = OUT-10 web-1 ✅(db-1 미설정). 설치 절차를 `infra/server/cw-agent-setup.sh`로 정리, 가짜 시험 `test/cw-fake-test.sh`. 12:24 web-1 실제 실행에서 스크립트 버그 2개 발견(Agent 상태 확인이 파이프 141로 오판, 설정 원본이 적용 뒤 사라짐) → 수정, 가짜 시험 22개로 늘려 두 버그를 되살리면 FAIL 확인. 12:42 수정 판 web-1 2회 실행 OK(2회차 재시작 없음), CloudWatch 도착 1건씩·중복 없음<br>**남은 것:** NET-03-b, NET-05 정식, OUT-05·11, OUT-10 db-1, RST-01 | PR 링크([#27](…)), PR 링크((https://github.com/MinsooAhn02/Haven/pull/34)). 11/10~11 실행분 PR 작성 예정. 증거: `network/연결확인표.md`(계정 번호·인스턴스 ID·IP 가림). AWS 조회·스크립트 실행은 민성 Git Bash, 서버 안 시험은 SSM 세션(11/10 민수, 11/11 민성). | 안민수: web-1/db-1 사설 IP 전달 완료, 첫 배포·재배포 healthz 결과 전달, NET-06 결과 11/12 아침. 김보람: 3회차 ALB·ACM·Route 53 권한 요청(11/11). 노푸른: 브라우저 접속은 ALB 연결 뒤(현재 web-1 안에서만 응답) |
| 3 | 진행 중 (ALB·HTTPS 완료. SG live 모드는 0.3.1까지 완료·실제 AWS PASS 11(11/16, #116, 구민철 짝 리뷰 통과). 남은 것: 구민철 실행·대조(11/23)) | 도메인 `orchestration-haven.cloud` 확정(11/11). Route 53 공개 호스팅 영역 1개, 네임서버 4개가 구글 DNS(8.8.8.8) 응답과 일치 확인. `infra/build-alb.sh` 작성(ACM DNS 검증 → 대상 그룹 /healthz → ALB → 443 TLS1.2+·80→301 → apex Alias → healthy·NET-01·01-b 확인). 가짜 시험 `test/alb-fake-test.sh` 39개(일부러 실패: ALB 중복·web-1 꺼짐·호스팅 영역 0/2개·기존 A 레코드·권한 없음·인증서 시간 초과/FAILED·unhealthy·302·가짜 도메인 리다이렉트). 시험이 실제로 버그를 잡는지 스크립트를 일부러 망가뜨려 확인(가드 3곳 제거 → 해당 시험 FAIL). 민성 Windows Git Bash 11:32: 가짜 시험 PASS 39 / FAIL 0, `DRY_RUN=1 bash build-alb.sh` 1/5~5/5 종료 0(실제 state ID로 명령만 출력). 권한: ELB·ACM 읽기부터 AccessDenied(11:1x) → 보람님 추가 → 11:36 1차 실행: 인증서 2초 만에 발급, 대상 그룹까지 만들고 ALB에서 `ec2:GetSecurityGroupsForVpc` 없음으로 멈춤 → 스크립트에 "이 스크립트가 만든 것(state 기록과 같은 ID)만 이어서 쓰기" 추가(가짜 시험 F1~F13) → 보람님 권한 추가 → 11:47 2차: 대상 그룹·인증서 재사용, ALB·리스너·도메인 연결, healthy, NET-01 OK, NET-01-b는 **Windows curl이 `/dev/null`을 몰라서** 확인 단계만 실패 → 고침(가짜 curl도 Windows처럼 바꿔 W1 시험 추가, 옛 코드로 되돌리면 13개 FAIL 확인) → 11:58 3차: 전부 재사용(새로 만든 것 없음), **NET-01 200 ok·인증서 OK, NET-01-b 301 → https, 실제 DNS 접속 OK**. 가짜 시험 최종 PASS 59 / FAIL 0(민성 Git Bash). 남은 것: live SG 읽기 수집·AUD 대조, WAF·ALB 접근 로그(설계 7절) | 증거: 연결확인표 NET-01·01-b, `~/alb-1111.log`(계정 번호·ARN 가려서 첨부). PR 작성 예정 | 노푸른: `https://orchestration-haven.cloud` 접속 가능(11/11 11:59~, 평일 09~21시, 밤에는 EC2가 꺼져 502/503). 안민수: ALB 켜 둠(11/11 결정), CSRF_TRUSTED_ORIGINS가 이 도메인인지 실제 로그인으로 확인 요청. 김보람: ALB 요금 시작(11:47~) 비용 확인 |
| 4 | 진행 중 (WAF ALB 연결 11/13, OUT-10 db-1 로그 수집 11/16. 남은 것: Nginx 요청 ID 11/27, WAF Block, 네트워크/SG 재시험·구성도·종료 대상 정리) | 아래 11/13 낮·11/16 오전 코멘트 | #116(db-1 로그 수집) | — |

## 지금 할 일 (11/16 12:10 갱신, 현황판 `TASK_TODO.html` 민성 카드 기준)

| 할 일 | 상태·선행 |
|---|---|
| ~PR #76 로그 수집(OUT-10)·NET-06 기록~ | ✅ 11/12 #76 병합, 최종 판 web-1 실행(14:44)·CloudWatch 도착 확인 |
| ~#64 서버 쪽 PR (boto3, MAIL_FROM → 메일 환경변수) → 같은 커밋 2번 배포~ | ✅ 11/12 #78 병합(요찬 리뷰), `5bccce1` 2회 배포 + web-setup.sh 재실행 → `HAVEN_MAIL_BACKEND=ses` 등 3줄 (앱계약 E5·E6) |
| ~web-1 역할 교체 (보람 #84, `haven-ec2-web-role`)~ | ✅ 11/13 12:23 교체, 12:33까지 기능 확인(SES 빼고 전부). 아래 11/13 낮 코멘트 |
| ~시험 메일 EXT-03(도착)·EXT-04(실패 표시)~ | ✅ 11/13 오후 둘 다 통과(요찬 안내서, 실행·판정 민성·수신 확인 보람·기록 요찬). 아래 11/13 오후 코멘트 |
| ~SG 점검 도구 live 모드 → 명세 5.1 맞춤(0.3.0) → 증거 묶음 → PR~ | ✅ 11/13 #109 병합(0.3.0·증거 묶음, 실제 AWS PASS 11). 남은 것: 구민철에게 새 실행 방법 전달(조장 직접) · 짝 리뷰(구민철·보람) |
| ~백업 → 격리 복원 연습 (`docs/인수인계/03` 2장 7번)~ | ✅ 11/13 10:03 백업 `20261113T010301Z` → 격리 복원 DB 줄 수 일치·업로드 7개 sha256 일치 (아래 11/13 코멘트) |
| ~15번 SG 삭제 실제 시험 (haven-sg-test만 삭제, sg-web·sg-db·sg-alb 거부)~ | ✅ 11/13 11:38~11:42 허용 1·거부 4 (아래 11/13 코멘트). 보람 기록 반영은 보람에게 전달 |
| ALB·WAF 밤 처리 결정 → destroy.sh 정리 순서 | #57 약 $4.55/주 |
| WAF ALB 연결 ✅ · Block 적용 | 연결 ✅ 11/13 12:0x(규칙 3개 Count, 기본 Allow). Block 전환은 4회차, 혁민 Count 관찰·판단 뒤. 연결 상태 조회 권한(`GetWebACLForResource`)은 ✅ 11/16 12:15 확인: `get-web-acl-for-resource` → `haven-web-acl`(ALB에 연결 유지) |
| 가상 운영 관리자 계정 생성(make_operator.py) | 4회차 APP-07·09 시험 직전에만, 끝나면 바로 비활성화 |
| ~로그인 실패 제한 수치 결정~ | ✅ 11/12 결정: 15분·계정 5번·IP 30번(#75). 구현은 요찬(4회차) → 혁민 점검 → 배포. 실제 IP는 X-Forwarded-For 뒤에서 두 번째(nginx가 ALB IP를 붙임) |
| ~OUT-10 db-1 PostgreSQL 로그 수집~ | ✅ 11/16 11:04 db-1 실행(`cw-agent-setup-db.sh`), 11:08 `/haven/db` 도착, 11:13 앱 접속 기록(IP·TLS) 확인, 12:04 1시간 로그 양 +176줄 / 약 28KB. PR #116 병합(main `f60e1c6`). 남은 것: 병합 뒤 짝 리뷰(보람: 권한·보존·비용, 혁민: 기록 범위·조회) |
| 로그인 실패 제한 운영 시험 2차(요찬 안내: 계정 열거·분산 공격·IP 키) | **11/17 진행 예정.** 민성은 3장(6번 직후 db-1에서 `accounts_loginfailure` IP 키 조회, 읽기 전용). 미리 db-1 SSM 세션 열어 둠 |
| Nginx 요청 ID 로그(`log_format`) | **구현 민성 · 재검증 혁민 · 기한 11/27** (11/13 16:46 조장 확정) |
| 조장 일: PR 확인·병합 → 7개 브랜치 동기화 → 현황판·운영기록 → 공지 | 매일 |
| 21시 `night.sh` · 09시 `morning.sh` | 매일 (밤 작업 전 AWS 로그인 새로) |

세부 기능/시험은 [기본 명세](../docs/구현명세/기본프로젝트_구현명세.md)를 따른다. 비밀값과 원본 민감 로그는 기록하지 않는다.

## 민수's comment · 2026-11-06

- PR #2의 SG CLI 설계 fixture 작업은 기록된 완료 범위로 두고, live 수집·추가 AUD 항목은 별도 미완료로 유지해 주세요. 기존 완료 상태를 다시 쓰거나 PR #2를 반복 요청할 필요는 없습니다.
- 김보람·안민수에게 리전·예산·출구 경로 승인을 확인해 주세요. OS/AMI는 제안 상태이며, 메일 방식도 SES API와 SMTP 중 아직 정해지지 않았으니 안민수의 회신을 받아 주세요.
- 승인된 구축 후에는 OS·AMI, EC2/SSM, 디스크, Web DB, 출구 경로와 직접 접속 거부의 실제 근거를 안민수에게 인계해 주세요.
- 기다리는 동안 fixture와 live-read 설계는 확장할 수 있지만 AWS 쓰기 작업은 보류해 주세요. 864 커밋의 문서 보완은 일반 PR로 제출할 수 있습니다.
- TODO에 현재 상태와 확인한 근거, 다음 담당자에게 넘길 내용 및 가능한 인계 시각을 답글로 기록해 주세요.

### ↳ 이민성 답글 · 2026-11-09
- **현재 상태**
  - PR #2(SG CLI fixture) 완료 범위 유지. live 수집·추가 AUD 항목(AUD-03~07·11)은 미완료
  - `864a847` SG 문서 보완: 별도 PR로 main 반영 완료 (11/08)
  - 연결 확인표(기대값) 초안 작성 (11/09). SSM·Role 부분은 11/10 보람님과, DB 계정·무허가 출발지 시험(NET-03-b·NET-04)은 민수님과 확정 → `이민성/network/연결확인표.md`
- **확인한 근거**
  - 회귀 시험 `python -B -m unittest discover -s 이민성/sg_audit -p test_network_audit.py -v` → 5개 OK (11/09 실행)
- **승인·결정 대기**
  - 리전(서울)·출구 D6(NAT Gateway A안)·예산 → 김보람·안민수 확인 요청 (11/09)
  - 메일 방식(SES API / SMTP) → 안민수 회신 대기. SMTP면 Web SG 아웃바운드 규칙 추가 필요
  - OS/AMI → 11/09 오후 의논 예정
- **다음 담당자에게 넘길 것**
  - 승인·구축 후 OS·AMI, EC2/SSM, 디스크, Web→DB, 출구 경로, 직접 접근 거부의 실제 근거 → 안민수
- **가능한 인계 시각**
  - 확인표(기대값): 11/10(화) 보람님과 서버 Role 맞춘 뒤
  - 실제 확인 결과: 승인·구축 시 11/12(목)
[AWS_운영결정 5번 확인 · 이민성]
- Ubuntu 24.04 기본 Python 3.12: 맞음 (packages.ubuntu.com/noble/python3 → 3.12.3) https://packages.ubuntu.com/noble/python3
- apt 기본 저장소 HTTP 80: 맞음 (EC2 Ubuntu 저장소 Port 80, AWS re:Post 사례) https://repost.aws/questions/QURAplea7CQY2d_4BOXR4HLQ/unable-to-connect-101-network-is-unreachable → “both on port 80” (Ctrl+F로 찾기)
- 반영: 설계.md sg-web·sg-db outbound TCP 80 추가, 연결확인표 OUT-07 기대값 변경
- 실제 서버의 apt 저장소 주소(ubuntu.sources)는 구축 후 확인표 OUT-03에서 최종 확인
## 민수's comment · 2026-11-09~13 실행 가이드

- **월 오전** 보람과 리전·예산·출구의 미결 항목을 확인합니다. **화** 보람과 서버 Role, SSM·Web→DB·필요 출구·직접 접근 거부 확인표를 작성합니다.
- **수** 민수·보람과 승인 범위를 대조합니다. **목** 승인과 대상 서버가 확인된 범위에서만 SSM·Web→DB·출구를 확인하고, 직접 접근 거부의 기대값과 실제값을 민수에게 넘깁니다. **금** 네트워크·SG 근거와 미검증 항목을 공용 리뷰에 인계합니다.
- **실행 기준** 저장소 루트에서 `python -B -m unittest discover -s 이민성/sg_audit -p test_network_audit.py -v`로 SG 회귀 시험을 실행합니다. AWS 확인 결과에는 실행 환경·대상·기대/실제 결과를 가려서 기록합니다. 기존 SG 문서 보완 커밋은 필요할 때 별도 PR로 보냅니다.
- **막히면** 승인이 없을 때 설계와 fixture·연결 확인표까지만 준비하고, 어떤 결정이 필요한지 민수·보람에게 넘깁니다.

[공용 일정·리뷰의 내 담당 항목](https://github.com/MinsooAhn02/Haven/blob/main/docs/팀_진행_및_리뷰.md#minsung)


## 민수's comment · 2026-11-08 이번 주 배정 (11/09~13)

운영 방식이 바뀌었습니다. 날짜별 시간표 대신 **주력과 대기열**을 드립니다. **다 못 해도 괜찮아요.** 주력이 막히거나 끝나면 대기열로 넘어가고, 남은 건 매일 저녁 다시 나눕니다. 매일 끝나면 Discord에 오늘 상황 보고 부탁드립니다. 전체 현황은 main의 `TASK_TODO.html`(git pull 후 브라우저로 열기).
- **주력:** ~`864a847` SG 문서 보완 PR + SSM·Web→DB·필요 출구·직접 접근 거부 확인표(기대값까지)~
- **대기열:** ~VPC/SG/EC2 구축 절차·변경안(승인 즉시 실행용)~ → live 읽기 수집 설계·AUD fixture 확장
- **⏳ 기다릴 것:** ~실제 구축은 민수 결정 + 보람 IAM·Role 필요.~ AWS 쓰기 작업은 승인 전 보류.


## 민수's comment · 2026-11-09 배정 갱신

AWS 운영 결정 추천안이 main `docs/AWS_운영결정.md`에 올라갔고, 현황판 `TASK_TODO.html`도 오늘 기준으로 바꿨습니다. 다 못 해도 괜찮고, 끝나면 Discord에 오늘 상황 보고 부탁드립니다.
- **완료:** ~SG 보완 PR #18 병합(`a3c962f`) — 추가 보완 필요 없음~
- **주력:** ~`docs/AWS_운영결정.md` 5번 확인(Ubuntu 24.04 기본 Python 3.12, apt 80 포트) + 서버 사양·대수·가동 시간을 보람님께 → SSM·Web→DB·출구·직접 접근 거부 확인표(기대값까지)~
- **대기열:** 구축 절차서 — 다른 계정에서 그대로 다시 만들 수 있게(계정 ID·ARN·자원 ID는 변수, 가능하면 AWS CLI 명령) → live 읽기 수집 설계·AUD fixture 확장
- **⏳ 기다릴 것:** 실제 구축은 결정 확정 + 보람님 IAM 이후

## 민수's comment · 2026-11-09 확대 배정 (AI 사용 전제)

다들 AI를 쓰니 일을 크게 잡았습니다. **이번 주(11/09~13)에 원래 1·2회차, 다음 주에 3·4회차**를 끝내는 게 목표예요. 다 못 해도 괜찮고, 위에서부터 하다가 막히면 다음 항목으로 넘어가세요. 다른 사람과 같이 정해야 하는 건 회의하지 말고 민수에게 물어보면 바로 정합니다. AWS 운영 결정은 확정됐습니다(main `docs/AWS_운영결정.md`). PR에는 실제로 돌린 명령·결과와 **일부러 실패시킨 거부 시험**을 꼭 붙여 주세요(AI 코드는 시험을 통과해도 틀릴 수 있어서). 매일 끝나면 Discord 상황 보고는 그대로 부탁드려요.

1. ~**구축 스크립트(AWS CLI, 계정 ID·자원 ID는 변수):** VPC·서브넷·라우팅·SG(서버 outbound 80 추가)·S3 Gateway Endpoint·NAT·EC2 2대(Ubuntu 24.04, t3.small, gp3 20GB, 공인 IP 없음, SSM Role)~
2. ~`nat-up` / `nat-down` 스크립트: 새 NAT로 경로가 바뀌었는지, EIP가 해제됐는지 스크립트가 확인 + 전체 삭제 스크립트(실행은 민수 확인 후)~
3. **수요일 구축** (보람님 IAM 적용 후, 조장 사전 승인) → SSM 접속 · Web→DB 5432 · 직접 접근 거부 증거 + 서버에서 `python3 --version`·apt 저장소 주소 기록(결정 5번)
4. 매일 밤 `nat-down` + EC2 중지, 아침 `nat-up` + EC2 시작 → 매일 보고에 실행 여부
5. (대기열) ALB·ACM·HTTPS 설계(3회차, 도메인은 화요일 결정) → live SG 읽기 수집 → AUD fixture 대조

- **짝 리뷰:** 보람님 IAM과 구축 스크립트 대조
- **배포 연결:** 연결 증거가 나오면 민수가 목·금 첫 배포

## 민수's comment · 2026-11-09 연결확인표 답변

연결확인표 잘 받았습니다. 5번 확인까지 해 주셔서 결정 문서에 반영했어요(`docs/AWS_운영결정.md`). 요청하신 4개는 이렇게 확정합니다.

| # | 요청 | 결정 |
|---|---|---|
| 1 | 시험용 출발지 | 임시 EC2 사용 OK. t3.micro, 공인 IP 없음, 시험 끝나면 그날 삭제하고 ID·생성/삭제 시각을 증거에 기록. 결정 11번 사전 승인 범위 |
| 2 | 시험용 DB 계정 | 허용 = `haven_app`, 거부 = `postgres`. 서버 DB가 web-1에서 오는 `haven_app`·`haven_owner`만 받게 하는 설정(pg_hba)은 민수가 함 |
| 3 | 재부팅 시험 | 승인. 수요일 구축 직후, 앱 올리기 전에 실행. 배포 후 다시 하게 되면 Discord에 먼저 알림 |
| 4 | 가동 시간 | 평일 09:00~21:00(12시간), NAT도 같은 시간. 21시 `nat-down` + EC2 중지, 09시 `nat-up`. 주말·야간 필요하면 민수에게 |

덧붙일 것:
- 표 머리말 "AWS 쓰기 작업은 승인 전 보류"는 결정 11번(사전 승인)으로 바뀌었으니 고쳐 주세요. 되돌릴 수 없는 삭제만 민수 확인입니다.
- `nat-up` 다음 확인 줄 하나 추가 부탁드려요(예: RST-02 — 기본 경로가 새 NAT를 가리키는지, SSM-01이 다시 Online인지). 매일 하는 일이라 여기서 조용히 실패하기 쉬워요.
- 연결확인표·설계 보완은 독립 문서라 PR 보내 주시면 먼저 병합할게요.

## 민수's comment · 2026-11-09 밤 · 이번 주 할 일 (11/10~13)

이번 주: 화 = 2회차 병합·AWS 구축, 수 = 첫 배포·3회차 시작, 목 = 3회차, 금 = 4회차·17:30 판정. 다음 주는 심화 점검·시연·보고서. 작업 전 항상 `git pull`. 전체는 `TASK_TODO.html`.

- **화 오전:** ~EC2 중지·시작 스크립트(결정 4번). 보람 권한 시험 결과 확인~
- **화 오후:** ~AWS 실제 구축(`build.sh`, 사전 승인) → SSM 접속 · Web→DB 5432 · 직접 접근 거부 증거(연결확인표) → 민수에게 web-1/db-1 사설 IP 전달. 21시 `nat-down` + EC2 중지~
- **수:** ALB · ACM(도메인은 화 수업 시작 때 민수가 정함) · HTTPS
- **목:** ~실제 SG 읽기 수집 → AUD fixture 대조~ → 권혁민 담당으로 이관(11/11). 민성은 수집 명령(SG CLI)만 제공
- **금:** 네트워크/SG 수정·재시험 · 최종 구성 정리

## 민성's comment · 2026-11-12 · 오늘 한 일과 11/13로 미룬 일

**오늘 한 일 (실제로 돌려 본 것만)**

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 21:14(11/11) → 09:03 | `night.sh` → `morning.sh` 뒤 NET-06·06-b 재시작 확인 | ✅ haven·nginx·postgresql active, healthz ok(안·밖), `db ok`. 11/11 밤 첫 시도는 AWS 로그인 만료로 멈췄고 다시 로그인 뒤 정상 |
| 09:10~14:44 | web-1 CloudWatch Agent·로그 수집(OUT-10 web-1), 설치 스크립트 `infra/server/cw-agent-setup.sh`·가짜 시험 | ✅ #76 병합. 실서버에서 버그 3개 찾아 수정(상태 확인 파이프 141, 설정 원본 사라짐, 백업이 설정 폴더 안). 최종 판 web-1 실행 OK, CloudWatch 도착 1건씩·중복 없음, 보존 30일 |
| 오후 | 조장 결정: 7번 구민철 합류·담당(독립 검증·SG 실제 점검 실행), SG live 모드는 민성 구현, WAF 분담(혁민 구성·판단, 민성 ALB 연결·Block 적용, 보람 권한), 로그인 실패 제한 15분·계정 5번·IP 30번(#75) | ✅ 운영기록·현황판 반영 |
| 15:33 | 운영 사이트 최신화 배포 `74ae5eb` 2회 (#64 메일 코드·#66 화면) | ✅ OK deployed, migration 없음, healthz ok |
| 15:40~16:45 | 메일 서버 설정 PR #78 (`site-lib.sh`·`deploy.sh`·`web-setup.sh`·requirements boto3, 가짜 시험 39개) → 요찬 리뷰 승인 → 병합 → `5bccce1` 배포 1회 → web-setup.sh 재실행(site.conf 기존 값 그대로 + MAIL_FROM) → 배포 2회 | ✅ boto3·botocore 1.43.120, haven.env `HAVEN_MAIL_BACKEND=ses`·`HAVEN_MAIL_FROM=noreply@orchestration-haven.cloud`·`HAVEN_SES_REGION=ap-northeast-2`, `DJANGO_HTTPS=1` 유지, static 경로 그대로 |
| 17:20 | 백업 연습 준비: db-1 `/root/setup`에 backup.sh·restore.sh·common.sh 반입 | ✅ sha256 3개 일치 |
| 17:33 | 재배포 `6c98b90` 2회 (#79~#82, 사이트 변경은 노푸른 base.html "현재 사용자" 1줄) | ✅ OK deployed, migration 없음, healthz ok, 메일 설정 유지 |

**현재 운영 배포:** `6c98b90` (main, #82까지). 이전 `5bccce1`(16:45) → `74ae5eb`(15:33) → `21d01f7`(11/11).

**11/13로 미룬 일**

| 할 일 | 메모 |
|---|---|
| 백업 → 격리 복원 연습 | db-1 스크립트는 반입 끝. ① web-1 `systemctl stop haven` → ② db-1 `backup.sh` → ③ web-1 `backup-uploads.sh <시각>` → ④ `systemctl start haven` → ⑤ db-1 `restore.sh <시각>` → ⑥ web-1 `restore-uploads.sh <시각>`. 복원은 격리 DB·폴더(TARGET 지정 금지). 오전 권장 |
| 시험 메일 EXT-03·EXT-04 | 보람 `ses:SendEmail` 확인 뒤, 요찬과 같이. 받는 주소는 기록에 "SES 등록 주소"로만 |
| #77 26번 정책 의견 | ALB 연결 권한 `SetWebAcl`도 같이, 바꾸는 권한은 우리 ALB·Web ACL 이름으로 좁히기 (보람에게 코멘트) |
| 15번 SG 삭제 실제 시험 | haven-sg-test만 삭제, sg-web·sg-db·sg-alb 거부 |
| SG 점검 도구 live 모드 구현 | 명세 5.1, boto3. 구민철 실행은 3회차(11/23~)라 급하지 않음 |
| ALB·WAF 밤 처리 결정 | 지금은 밤에도 유지 |
| OUT-10 db-1 범위 결정 | 미정 |

## 민성's comment · 2026-11-12 밤 2 · #84 이후 정정과 남은 일

- **정정:** 위 "오늘 한 일"의 17:33 재배포 `6c98b90`은 #81·#82까지 포함하고 **#79는 포함하지 않는다**(`6c98b90`에 `precheck`가 없음, #79는 17:33에 병합). "#79~#82"는 "#81·#82"로 읽는다. #79는 다음 배포에 들어간다.
- **구민철 시험 시점:** 구민철의 AWS 공유 흐름 시험(15:50~16:29) 당시 운영 배포는 이 문서의 기록상 `74ae5eb`(15:33)다. `5bccce1`은 16:45 배포라 시험 이후다.
- **새 작업 — web-1 역할 교체(보람 #84):** 새 Web 전용 역할 `haven-ec2-web-role`이 생겼고 web-1은 옛 역할이다. 교체 전에 정할 것: ① 새 역할에 첨부 백업·복원용 S3 권한(`db-backups/*`, `PutObject`·`GetObject`)이 있어야 `backup-uploads.sh`·`restore-uploads.sh`가 계속 동작한다 ② 교체용 `iam:PassRole`(새 역할)과 인스턴스 프로파일 교체 권한이 지금 기록된 정책에는 없다. 조장이 보람에게 코멘트로 요청했다. 11/13 백업·격리 복원 연습 뒤에 교체하는 것이 안전하다. 교체 뒤 시험 메일 EXT-03·04.
- **ALB·WAF 밤 처리:** 보람 답변(#84 문서)은 WAF 기본요금 월 약 $8(월 약 $1 증가), 야간 유지에 동의. 단가는 보람 계산이고 요금표 대조는 하지 않았다. 정식 결정은 아직 기록하지 않았다.

## 민성's comment · 2026-11-13 오전 · 백업·격리 복원 연습과 재배포

**한 일 (실제로 돌려 본 것만)**

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 09:49 | 로그인 실패 제한(#75 결정) 구현 여부 확인: `git fetch` 뒤 `git grep -niE "attempt\|lockout\|ratelimit\|실패 횟수\|잠금" origin/main -- 신요찬/app` | 결과 없음 → **아직 미구현**. 요찬 구현 PR 병합 뒤 배포 2회 (대기) |
| 약 10:00 | ① web-1 `systemctl stop haven` | ✅ `inactive` |
| 10:03 | ② db-1 `backup.sh` | ✅ `OK backup 20261113T010301Z` → `s3://haven-backup-************/db-backups/`, 51,674 bytes, 13 tables |
| ~10:22 | ③ web-1 `backup-uploads.sh "$TS"` (같은 시간도장) | ✅ OK. 처음 두 번은 시간도장 뒤의 `->`·`s3://…`·`(… bytes)`까지 붙여 넣어 bash 구문 오류 → 명령은 실행되지 않음. `TS=` 변수로 넣어 해결 |
| ~10:22 | ④ web-1 `systemctl start haven` | ✅ active, healthz 200. 사이트 중단 약 20분(붙여넣기 실수로 길어짐) |
| 10:25 | ⑤ db-1 `restore.sh "$TS"` → 격리 DB `haven_restore_check` | ✅ `13 tables, row counts match backup`. `NOTICE: database "haven_restore_check" does not exist, skipping`은 첫 복원이라 지울 옛 격리 DB가 없다는 안내 |
| 10:26 | ⑥ web-1 `restore-uploads.sh "$TS"` → 격리 폴더 `/srv/haven/restore-check/uploads` | ✅ `7 files, sha256 match` |
| 10:30~10:50 | 최신 main `a7bfcd6`(#86까지) 같은 커밋 2회 배포 | ✅ 2회 모두 healthz 200, `readlink -f /srv/haven/current` = `/srv/haven/releases/a7bfcd6158f3d42e6a56dd62bb6eda2b7c5391ce`. 배포 전 `git diff --stat 6c98b90 origin/main -- 신요찬/app 안민수/server 노푸른` →  #79 변경(attachments.py와 시험)만 있음, 화면·서버 설정·migration 없음 |

- 운영 DB와 운영 업로드 폴더는 건드리지 않았다. `TARGET_DB`·`TARGET_DIR`은 지정하지 않았다.
- 시간도장은 UTC다(`T010301Z` = KST 10:03). 시간도장 하나로 DB와 업로드가 한 묶음이다.
- 격리 DB `haven_restore_check`와 격리 폴더는 남겨 두었다(다음 연습 때 스크립트가 지우고 다시 만든다).

**15번 SG 삭제 권한 실제 시험 (11:38~11:42, minsung CLI·Git Bash, 서울)**

정책: 실제 AWS `Haven-Minsung-Delete-Policy`(보람 JSON 34번, 15번이 합쳐짐). `ec2:DeleteSecurityGroup`은 태그 `Project=Haven`과 `Name=haven-sg-test`가 둘 다 맞는 SG만 허용.

| # | 시도 | 결과 | 판정 |
|---|---|---|---|
| 1 | 운영 `haven-sg-alb` 삭제 (`--dry-run`) | `UnauthorizedOperation` | ✅ 거부 |
| 2 | 운영 `haven-sg-web` 삭제 (`--dry-run`) | `UnauthorizedOperation` | ✅ 거부 |
| 3 | 운영 `haven-sg-db` 삭제 (`--dry-run`) | `UnauthorizedOperation` | ✅ 거부 |
| 4 | `default` SG(태그 없음) 삭제 (`--dry-run`) | `UnauthorizedOperation` | ✅ 거부 |
| 5 | 시험용 `haven-sg-test` 생성 (태그 Project=Haven·Name=haven-sg-test·Owner=minsung, 만들 때 태그) | 생성됨 | ✅ |
| 6 | 시험용 SG 삭제 (`--dry-run`) | `DryRunOperation` | ✅ 권한 있음 |
| 7 | 시험용 SG 실제 삭제 → 다시 조회 | `Return: true` → `InvalidGroup.NotFound` | ✅ 허용·삭제 확인 |

- 운영 SG는 `--dry-run`으로만 시험해 실제로 지워질 수 없게 했다. 남은 시험용 리소스 없음.
- "Name은 맞고 Project 태그만 없는 SG"는 만들면 민성 계정으로도 지울 수 없어 하지 않았다. 대신 Name이 다른 경우(1~3)와 태그가 없는 경우(4)를 각각 확인했다.
- 처음 반복문(`for`)을 여러 줄로 붙여 넣다 터미널 붙여넣기 표시(`[200~`)가 섞여 깨졌다. ID가 빈 채로 `--dry-run` 명령이 실행돼 `InvalidGroupId.Malformed`로 거절됨(변경 없음). 한 줄 명령으로 다시 했다.
- 기록에는 SG·VPC ID, 계정 번호, 인코딩된 거부 메시지를 남기지 않는다.

**현재 운영 배포:** `a7bfcd6` (main, #86까지). #79는 이번 배포에 포함된다. 이전 `6c98b90`(11/12 17:33).

**다음**

| 할 일 | 메모 |
|---|---|
| web-1 역할 교체(보람 #84) | 백업 연습이 끝났으므로 진행 가능. 새 역할에 `db-backups/*` `PutObject`·`GetObject`, `iam:PassRole` 확인 먼저. 교체 뒤 `backup-uploads.sh` 다시 돌려 확인 |
| 시험 메일 EXT-03·04 | 역할 교체·보람 `ses:SendEmail` 확인 뒤 |
| 로그인 실패 제한 배포 | 요찬 구현 → 혁민 점검 → 병합 뒤 배포 2회 |
| 4회차 정식 복원 | 오늘과 같은 순서 ①~⑥ |

## 민성's comment · 2026-11-13 낮 · WAF ALB 연결과 web-1 역할 교체

**WAF ALB 연결 (약 12:00~12:10, minsung CLI·Git Bash)**

| 단계 | 결과 |
|---|---|
| Web ACL `haven-web-acl`(혁민 구성) 규칙 확인 | 기본 동작 `Allow`. 관리형 규칙 그룹 3개(`AWSManagedRulesCommonRuleSet`·`SQLiRuleSet`·`KnownBadInputsRuleSet`) 모두 `Override: Count` → 연결해도 막지 않고 기록만 함 |
| 연결 전 사이트 | `https://…/healthz` 200 |
| `wafv2 associate-web-acl` (`haven-web-acl` → `haven-alb`) | ✅ 성공 (26번 정책 `Haven-Minsung-WAF-Manage`) |
| 연결 후 사이트 | `/healthz` 200, `/` 302(로그인 이동) → 정상 사용자 영향 없음 |

- 민성 계정으로는 연결 상태 조회가 안 된다: `wafv2:ListResourcesForWebACL`은 정책에 없고, `wafv2:GetWebACLForResource`는 `webacl/haven-*/*`에만 허용돼 AWS가 `webacl/*/*`로 검사할 때 거부된다. 보람에게 조회 범위 조정 요청(급하지 않음, Block 전환 전까지). 연결 여부는 혁민에게 WAF 콘솔 Associated AWS resources 확인을 부탁했다.
- 되돌리기: `aws wafv2 disassociate-web-acl --resource-arn <haven-alb ARN>` (26번 정책에 있음).
- 주말 동안 ALB 유지 → Count 로그가 쌓이게 한다. Block 전환은 4회차 혁민 판단 뒤 민성이 적용.

**web-1 역할 교체 (12:23 교체 → 12:33 확인 끝, 교체는 minsung CLI·확인은 web-1 SSM root)**

공통 역할 `haven-ec2-ssm-role`(web·db 같이 사용)에서 web 전용 역할 `haven-ec2-web-role`(보람 #84)로 바꿨다. 최소 권한: web-1이 db-1 권한까지 갖지 않게 한다. EC2는 멈추지 않았다.

| 확인 | 방법 | 결과 |
|---|---|---|
| 교체 전 | `describe-iam-instance-profile-associations` | `haven-ec2-ssm-profile` associated |
| 교체 | `replace-iam-instance-profile-association` → `Name=haven-ec2-web-role` | ✅ associated (새 association ID는 기록하지 않음) |
| 새 역할 적용 | web-1 `aws sts get-caller-identity` | ✅ `assumed-role/haven-ec2-web-role` |
| 비밀값 읽기 | `ssm get-parameters` `/haven/django/secret_key`·`/haven/db/app_password`·`/haven/db/owner_password` (이름만 출력) | ✅ 3개, missing 없음 |
| 업로드 백업·복원 (S3 `db-backups/*` Put·Get) | 웹 잠시 멈춤 → `backup-uploads.sh` `20261113T032444Z` → 웹 켬 → `restore-uploads.sh`(격리 폴더) | ✅ 8 files, sha256 일치. 이 시간도장은 **권한 확인용(업로드만, DB 없음)** 이라 복원 대상으로 쓰지 않는다 |
| CloudWatch 로그 쓰기 | web-1 `logger -t gunicorn "haven-role-swap-check …"` → PC `logs filter-log-events` | ✅ `/haven/web`에 도착 |
| SSM 등록 | PC `ssm describe-instance-information` | ✅ `Online` |
| 배포 | `deploy.sh a7bfcd6…` 2회 | ✅ 2회 OK, migration 없음, active, healthz 200 |
| SES 발신 | 시험 메일 EXT-03·04 | ⏳ 요찬·보람과 따로 |

- 업로드 파일이 오전 7개 → 8개: 10:22 웹 재시작 뒤 누군가 첨부를 올린 것으로 보인다(백업은 그 시점 상태를 그대로 담음).
- 처음 `backup-uploads.sh`는 웹이 켜져 있어 `FAIL: haven service is running`으로 멈췄다(스크립트 안전장치, S3 시도 없음). `systemctl stop haven; …; systemctl start haven` 한 줄로 다시 했다.
- Git Bash에서 `/haven/web`처럼 `/`로 시작하는 인자는 `C:/Program Files/Git/…`로 바뀐다 → `MSYS_NO_PATHCONV=1`을 붙인다.
- 되돌리기: `replace-iam-instance-profile-association --association-id <교체 뒤 ID> --iam-instance-profile Name=haven-ec2-ssm-profile`.
- 이제 공통 역할 `haven-ec2-ssm-role`은 db-1만 쓴다. web 전용 권한(SES 발신·web 로그 쓰기)을 뺄지 보람과 정한다. 빼면 db-1 백업·SSM 영향 확인.

**db-1 재시험 (12:45~12:50, 보람이 공통 역할에서 web 로그 쓰기 정책 삭제 뒤, PR #94)**

| 확인 | 결과 |
|---|---|
| 역할 | ✅ `assumed-role/haven-ec2-ssm-role` (db-1은 공통 역할 그대로) |
| SSM | ✅ 세션 정상 |
| Parameter Store 읽기 (`/haven/db/app_password`·`owner_password`, 이름만) | ✅ 2개, missing 없음 |
| DB 백업 S3 쓰기 | ✅ `20261113T034802Z`(KST 12:48), 52,170 bytes, 13 tables (웹 켠 채로, 권한 확인용) |
| 격리 복원 S3 읽기 | ✅ `haven_restore_check` 13 tables, 줄 수 일치 |

- 배포는 web-1(새 web 역할)에서 돌아 db-1 역할과 무관. 12:32 배포 2회 OK.
- 처음 `restore.sh "$TS3"`는 변수 이름을 `TS`로 넣어 비어 있었음 → `usage`로 멈춤(변경 없음).

**시험 메일 첫 시도 (12:54, web-1 `send_test_mail --to <SES 등록 주소>`)**

- 결과: `메일을 보내지 못했습니다 (오류: AccessDeniedException, 실행 ID: …)`, `exit=1`. 메일 나가지 않음, 사이트 영향 없음.
- SES 계정은 샌드박스(`ProductionAccessEnabled=false`, `SendingEnabled=true`, 12:43 민성 `sesv2 get-account`).
- 원인 추정: 28번 `Haven-EC2-Web-SES-Send`의 Resource가 `identity/orchestration-haven.cloud`(보내는 도메인) 하나뿐. 샌드박스에서는 받는 주소 identity도 권한 검사 대상이라 거부된 것으로 보인다. 또는 28번이 새 역할에 안 붙어 있을 가능성. → 보람에게 확인·수정 요청.
- 실패 표시 자체는 명령 설계대로였다(종료 코드 1, 오류 종류만, "접수" 없음, 주소 원문 없음). 다만 권한 문제로 난 실패라 EXT-04 판정은 권한 수정 뒤 다시(요찬 판단).
- 처음엔 다음 주로 이관했으나(요찬 조퇴), 보람이 14:1x에 권한을 고치고 요찬이 안내서를 남겨 같은 날 오후에 다시 했다(아래 11/13 오후 코멘트).

**다음 (11/13 오후)**

| 할 일 | 메모 |
|---|---|
| ~시험 메일 EXT-03·04~ | ✅ 14:25·14:28 실행, 둘 다 통과 |
| SG 점검 도구 live 모드 | ✅ 11/13 오후 baseline 수정·설계·구현·실제 AWS PASS까지 끝냄(아래 11/13 오후 2 코멘트). PR·구민철 전달 끝. 17시 명세 5.1 맞춤(0.3.0) 진행 중 → 11/13 저녁 코멘트 |
| 보람에게 | 15번 SG 시험 결과 전달, WAF 조회 권한 범위, SES 발신 권한(받는 주소 identity), PR #94 리뷰·병합(db-1 재시험 결과 코멘트) |
| 21:00 `night.sh` | ALB 유지(WAF Count 관찰) |

## 민성's comment · 2026-11-13 오후 · 시험 메일 EXT-03·EXT-04

요찬 안내서(시험 메일 실제 확인 EXT-03·EXT-04) 기준. 실행 이민성(web-1 SSM root), 수신 확인 김보람, 기록 신요찬. 앞서 보람이 28번 `Haven-EC2-Web-SES-Send` Resource에 받는 주소 identity를 추가(14:1x 완료 연락).

- 배포 commit `a7bfcd6` · boto3 `1.43.120` · SES 리전 `ap-northeast-2` · sandbox: 예(`ProductionAccessEnabled=false`, 12:43 확인) → EXT-04는 A 방법
- 발신 `noreply@orchestration-haven.cloud` · 수신: SES 등록 주소(주소는 적지 않음). `send_test` 함수로 주소를 숨겨 입력

| 시험 | 실행 시각(UTC) | 명령 출력 요약 | exit | 실제 결과 | 판정 |
|---|---|---|---|---|---|
| EXT-03 성공 | 2026-11-13T05:25:48Z | `SES 접수 message_id=… to=k***@… run_id=b4a1003f…` | 0 | 14:25(KST) 도착(보람 확인). 제목 `[Haven] 시험 메일`, 보낸 사람 `noreply@orchestration-haven.cloud`, 본문 보낸 시각 `05:25:48Z`·실행 ID가 run_id와 일치 | ✅ 통과 |
| EXT-04 실패 (A, `nobody@example.invalid`) | 2026-11-13T05:28:13Z | `메일을 보내지 못했습니다 (오류: AccessDeniedException, 실행 ID: fe121556…)` | 1 | "SES 접수" 없음 | ✅ 통과 |

- run_id: EXT-03 `b4a1003f94d241e7bbaf6b5240f5fa68` / EXT-04 `fe12155658dd46c191996ff0507b1834`
- EXT-04 코드가 `MessageRejected`가 아니라 `AccessDeniedException`: 28번 정책 Resource가 SES 등록 주소로만 좁혀져 있어 SES 전에 IAM이 먼저 거부. 안내서 기준 "실패로 표시됐으면 통과, 코드만 기록".
- 출력에 받는 주소 원문 없음(가려진 형태만).
- 특이사항: 12:54 첫 시도는 주소를 명령 줄에 직접 넣어 web-1 root 명령 기록(bash history)에 주소가 남았다 → 14:2x 해당 1줄 삭제(`history -d` + `history -w`, 파일에서 0건 확인, 개인정보 보호). 이후는 주소를 화면·기록에 남기지 않는 `send_test` 사용.
- SSM 세션 로그 확인: CloudWatch에는 세션 로그 그룹 없음(14:38 민성 `describe-log-groups`, `/haven/web`·`aws-waf-logs-haven`만). S3는 민성 권한 없음(`ssm:GetDocument` 거부) → 보람 확인(14:4x): 콘솔 Session Manager 기본 설정에서 S3 로깅 비활성, `SSM-SessionManagerRunShell` 문서는 CLI 조회 시 `InvalidDocument`(설정 문서가 없음 = 기본값, 세션 로그 저장 안 함). 12:54 당시 설정·과거 로그는 확정 못 함(CloudTrail에서 이 문서의 생성·삭제 이력을 보면 확정 가능). 지울 로그가 확인되지 않아 삭제 조치는 하지 않음.

## 민성's comment · 2026-11-13 오후 2 · SG 점검 도구 live 모드

자세한 기록은 `sg_audit/README.md` "live 모드 설계·실행". 계정 번호·VPC·SG ID는 적지 않는다.

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 14:45~15:20 | baseline 누락 수정: web·db egress TCP 80 → `0.0.0.0/0`(설계 4.2, 11/09 apt 추가분, 구민철 발견). fixture 3개·시험·README·코드설명 함께 수정 | ✅ 시험 6개 통과(15:20 민성 PC). 예전 baseline으로 되돌리면 시험 3개 실패 → 시험이 누락을 잡음 |
| 15:24 | live 설계 확정: 27번 권한 안에서만 수집(VPC → SG → web-1·db-1 → ALB ENI), SG는 이름(`expected_sg_names`)으로 찾고 실제 ID는 파일에 안 씀, default SG는 b안(규칙 있으면 SG-07 FAIL), 실패 시험 L1~L15 | ✅ README 설계 절. ALB ENI 2개·둘 다 `haven-sg-alb` 실제 확인(15:29) |
| 15:30~15:36 | `network_audit.py` 0.2.0 live 구현, `test_live.py` 21개(가짜 AWS, boto3 없이) | ✅ 일부러 코드를 망가뜨린 12가지 경우를 시험이 모두 잡음 |
| 15:38 | 민성 PC 전체 시험 | ✅ 27개 통과 |
| 15:41~15:45 | boto3 설치: `pip install --user "boto3[crt]==1.43.120"`(`aws login` 때문에 `[crt]` 필요) → live 실행 | COMPLETE, PASS 10, FAIL 2(SG-07 default SG 기본 규칙), 종료 코드 1. 우리 SG 3개는 설계와 일치 |
| 15:48 | default SG 사용처 확인(읽기 전용) | ENI 0, EC2 0(중지 포함), 다른 SG 참조 없음 → 비워도 영향 없음 |
| 16:14~16:15 | 보람이 default SG 하나에 한정한 규칙 삭제 권한 추가 → 규칙 2개 삭제 → 비어 있음 확인 | ✅ `[[], []]` |
| 16:15 | live 다시 실행 | ✅ **COMPLETE, PASS 11, FAIL 0, UNKNOWN 0, ERROR 0, 종료 코드 0** |

**다음**

| 할 일 | 메모 |
|---|---|
| sg_audit PR → 리뷰·병합 | baseline·live 구현·시험·README·코드설명 |
| 구민철에게 전달 | `python -m pip install --user "boto3[crt]==1.43.120"` → `python network_audit.py live --baseline baseline.json --output-dir out/live-<시각>`. 27번 권한이면 충분 |
| 보람에게 알림 | default SG 규칙 2개 삭제 완료(16:15), 권한 기록 반영 |
| 증거 폴더(명세 9장) | `evidence/<run-id>/`·ID 가림. 3회차 증거 제출 전 |

## 민성's comment · 2026-11-13 저녁 · 808465d 배포와 SG 도구 명세 5.1 맞춤

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 17:06 | 배포 전 백업(db-1 `backup.sh`) | ✅ 시간도장 `20261113T080630Z` |
| 17:0x | 배포 `808465decd87ecceca00d369bb39d32387bab779` (#88 로그인 실패 제한, 요찬 구현). 앱만 바뀜(`안민수/server`·requirements 변경 없음), 새 migration `accounts.0001_initial` | ✅ `Applying accounts.0001_initial... OK`, healthz 200 |
| 17시 | SG 점검 도구 live 0.2.0이 명세 5.1과 어긋난 점 확인: `--profile`·`--vpc-id`/`--sg-id` 없음, STS 계정 확인 없음, 이름·태그로 자산 추정, SG 지정 시 합집합 없음, 연결 정보 없을 때 처리 없음, 증거 폴더(9장) 없음 | 조장 결정: 지금 고침. AWS 설정은 그대로라 다시 만들 것 없음(수집 부분·명령 형식만) |
| 17:28 | `network_audit.py` 0.3.0 + `make_evidence.py`(증거 묶음) PC에 넣음 | 작업 환경 시험 50개 통과(fixture 6·live 30·증거 14), 일부러 망가뜨린 17가지를 시험이 모두 잡음 |
| 17:29 | 민성 PC 전체 시험 | ❌ 10개 실패: 증거 묶음이 commit 번호를 읽을 때 Windows 기본 인코딩(cp949)으로 git 출력을 풀다가 한글 경로에서 깨짐(stdout 없음). 판정 코드와 무관 |
| 17:30 | git 출력을 UTF-8로 읽게 수정, 못 읽으면 commit `unknown` + 알려진 누락에 기록. 시험 2개 추가 → 민성 PC 다시 시험 | ✅ 52개 통과(OK, 3.578s) |
| 17:31 | `baseline.live.json` 만듦(`baseline.json` 복사 → SG ID 3개를 실제 ID로, Git 제외 확인). SG 3개가 같은 VPC인지 확인 | ✅ `sg-fixture` 0개, 실제 ID 3개, `git status`에 안 나옴 |
| 17:31 | **live 0.3.0 실제 실행** `--region ap-northeast-2 --profile default --vpc-id <VPC>` | ✅ 시작 줄 `대상 계정: 앞4자리********` 출력, **COMPLETE, PASS 11, FAIL 0, UNKNOWN 0, ERROR 0, 종료 코드 0**. 이름·태그 없이 SG ID로 alb·web-1·db-1을 모두 찾음, baseline에 없는 ENI 없음 |
| 17:3x | 코드 커밋 `30f40e4` | ✅ |
| 17:33 | 증거 묶음 1차 `make_evidence.py --results-dir out/live-20261113-1731 --before out/live-20261113-1545` | 만들어짐(종료 코드 0, `commit_dirty: false`, 실제 ID 42개 가림, 전후 비교 SG-07 FAIL 2 → PASS). ❌ 확인 검사에서 `manifest.json`·`results.json`에 계정 앞 4자리가 남음 |
| 17:38 | 증거 묶음은 계정 번호를 앞 4자리도 남기지 않고 `account-masked`로, 남으면 묶음을 막음. 비교표 `None-None` → `전체`. 시험 2개 추가 | 작업 환경 54개 통과, 고친 곳을 되돌리면 시험이 실패함 확인 |
| 17:4x | 커밋·푸시 `ecfc3a2` (가림 수정 코드·TODO·**17:33 1차 증거 묶음**) | ❌ 증거 폴더는 묶음을 다시 만들기 전에 커밋돼 `manifest.json`·`results.json`에 계정 앞 4자리가 남음(리뷰 지적, `git grep`으로 확인). 이전 커밋 이력의 앞 4자리는 강제 푸시 금지 규칙에 따라 지우지 않고 다음 커밋으로 덮음 |
| 17:49 | 민성 PC 전체 시험 | ✅ 54개 통과(OK, 3.938s) |
| 17:50 | 1차 묶음 폴더 지우고 같은 실행 결과(`live-20261113-1731`, 전: `live-20261113-1545`)로 다시 만듦 | ✅ 종료 코드 0. 6개 파일 모두 `sg-0`·`vpc-0`·계정 앞 4자리 0개, `account_id` = `account-masked`, `commit` = `ecfc3a2`, `commit_dirty: true`(README 한 줄 미커밋, 알려진 누락에 기록됨) |

**0.3.0에서 바뀐 것** (자세한 내용은 `sg_audit/README.md` "0.2.0 → 0.3.0")
- 명령: `live --region <리전> --profile <프로필> (--vpc-id <VPC> | --sg-id <SG> ...) --baseline baseline.live.json --output-dir <새 폴더>`. `--project`·`--alb-name` 없어짐.
- 시작할 때 STS로 대상 계정 확인 → `대상 계정: 1234********  리전·범위` 출력.
- 서버는 이름·태그가 아니라 baseline의 실제 SG ID(`expected_sg_ids`)가 붙은 ENI로 찾는다. 실제 ID는 `baseline.live.json`(Git 제외)에만 적는다. `DescribeInstances` 안 씀.
- `--sg-id`는 같은 서버의 다른 SG까지 합집합으로 본다. 한 ENI에 여러 서버 SG·모르는 ENI는 UNKNOWN. ENI 조회 실패는 SG 규칙 결과만 남기고 서버는 UNKNOWN.
- 증거 묶음 `evidence/<run-id>/`: manifest·가림 설정·가린 결과(JSON·CSV)·가림 로그·전후 비교. 원래 값 대응표는 `out/`에만.

**다음**

| 할 일 | 메모 |
|---|---|
| ~민성 PC 시험~ | ✅ 17:30 52개 |
| ~`baseline.live.json` 만들기~ | ✅ 17:31 |
| ~실제 AWS 0.3.0 실행 (`--vpc-id`)~ | ✅ 17:31 PASS 11 |
| ~민성 PC 시험 54개 → 커밋(증거 가림 수정)~ | ✅ 17:49 54개, `ecfc3a2` |
| ~증거 묶음 다시 만들기 → 확인~ | ✅ 17:50 |
| 다시 만든 증거 묶음·README(통합 담당 조장으로 정정)·TODO 커밋 → 푸시 | PR은 다음 주 |
| PR → 병합 → 구민철 전달 | 명령이 바뀜: `--profile`, VPC ID, `baseline.live.json`(SG ID 3개) 만드는 법. 필요 권한은 줄어듦(`DescribeInstances` 불필요) |

## 민성's comment · 2026-11-13 밤 · #109 병합과 짝 리뷰·배포 일정

- **병합됨:** #108을 닫고 #109(SG 점검 도구 0.3.0, 증거 묶음). 조장 검토로 증거 묶음의 계정 앞 4자리를 다시 가렸다.
- **짝 리뷰(병합 뒤):** 구민철(자산 매핑·UNKNOWN 구분·3회차 실행), 보람(권한·가림 범위·`sts:GetCallerIdentity`). 구민철에게 새 실행 방법은 조장이 직접 전달.
- **다음:** 11/16(월) 배포(로그인 실패 제한 #88, migration `accounts/0001`) 뒤 AWS 시험, Nginx 로그 형식 PR(구현 민성·재검증 혁민·11/27), 시험 메일 EXT-03·04 기록 PR(#99 재작성) — 올리면 현황판을 맞춘다.

## 민성's comment · 2026-11-16 아침 · 배포 370b22e

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 09:0x | `morning.sh` (EC2 켜기·NAT 만들기) | ✅ (처음엔 저장소 맨 위에서 실행해 파일을 못 찾음 → `이민성/infra/morning.sh`로 실행) |
| 09:07 | main 확인: `370b22e`(#110). `808465d` 이후 바뀐 19개 파일은 개인 폴더·문서뿐(앱·`안민수/server`·requirements 변경 없음) | → `370b22e` 배포로 결정(앱 내용은 11/13 `808465d`와 같음) |
| 09:08 | 배포 전 백업(db-1 `backup.sh`, `BACKUP_BUCKET`을 STS로 계정 조회해 지정) | ✅ 시간도장 `20261116T000844Z`, 14 tables |
| 09:09~09:10 | 배포 `370b22ea8dba323cbb63ff0990477f7be34041d9` **2회** | ✅ 2회 모두 `No migrations to apply.`·`OK deployed`, `current` → `releases/370b22e…`, healthz 200 |

**다음:** 로그인 실패 제한 실제 AWS 시험(#88, 계정 5번·15분 / IP 30번 / 실제 IP 기록) · 구민철 SG 실행 방법 전달 · 21시 `night.sh`

## 민성's comment · 2026-11-16 오전 · SG 점검 0.3.1(구민철 리뷰)과 db-1 로그 수집(OUT-10)

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 09:2x | 로그인 실패 제한 실제 시험 담당 결정 | 구민철 수행(1~3번: 5번 실패 잠김·잠긴 동안 막힘·15분 뒤 풀림), 4번(web-1 로그에 실제 IP)은 구민철 1~3번 끝난 뒤 민성 확인. 잠겨도 되는 시험용 계정을 쓰도록 안내 |
| 09:2x | 구민철에게 SG 점검 0.3.0 실행 방법 전달 | `--profile`·VPC ID·`baseline.live.json`, 증거는 `구민철/sg_evidence`(`--evidence-root`) |
| 09:36 | db-1 05번 권한 확인: `describe-log-streams /haven/db` | ✅ `ResourceNotFoundException`(권한 있음, 그룹만 없음) |
| 09:37 | db-1 상태 조사(읽기 전용) | PostgreSQL 16.15, 로그 `/var/log/postgresql/postgresql-16-main.log`(stderr), `log_connections`·`log_disconnections` off, prefix에 접속 IP 없음, Agent 없음, 디스크 16G 여유 |
| 09:43 | `/haven/db` 로그 그룹 생성(민성 PC) | ✅ 보존 30일 (`/haven/web`도 30일). 태그 조회는 권한 없음 |
| 09:55 | 구민철 #109 짝 리뷰: 질문 1(분리 ENI도 서버로 봄)·제안 3건 | 4건 모두 타당 → 0.3.1로 반영하기로 함 |
| 10:06 | VPC ENI 상태 확인(읽기 전용) | ENI 5개(ALB 2·EC2 2·NAT Gateway 1(SG 없음)) 모두 `in-use` → 11/13 PASS 11은 0.3.1 기준으로도 유효 |
| 10:13 | 0.3.1 + db-1 스크립트 PC에 넣고 시험 | ✅ SG 60개 OK, db-1 가짜 시험 29개, web-1 가짜 시험 23개 |
| 10:28 | SG 점검 0.3.1 실제 AWS(`--vpc-id`) | ✅ **COMPLETE, PASS 11, 종료 코드 0**, 판정 근거 10줄에 ENI ID |
| 10:29~10:38 | 코드 커밋 `9eaf0ea`(10:29)·푸시 → 증거 묶음 `evidence/547ab001-…`(10:31) → 증거 커밋 | ✅ `tool_version` 0.3.1, `commit_dirty: false`, 11/13과 전후 비교(판정 변화 없음), sg·vpc·eni ID·계정 0개 |
| 10:49~11:02 | db-1에 스크립트 옮김(base64 한 줄) | ✅ 10280바이트, sha256 `a5bdbf8f…e49b` OK (첫 시도는 붙여넣기 빠져 해시 FAILED → 아무것도 안 바뀜) |
| 11:03 | 바꾸기 전 상태 | `postgresql.auto.conf` 백업(`/root/setup/postgresql.auto.conf.bak-…`), 로그 197줄 / 30,670바이트 |
| 11:04 | **`cw-agent-setup-db.sh` 실행** | ✅ `OK` 한 번에 통과. Agent 1.300074 설치, 설정 3개 off→on / off→on / prefix `%m [%p] %q%u@%d from %h `(reload, 재시작 없음), 표시 접속 `cws-1794794667` 기록 |
| 11:08 | 민성 PC `filter-log-events /haven/db` | ✅ `i-…/postgresql` → **OUT-10 db-1 통과** |
| 11:10 | 설정 값 확인·사이트 | ✅ `on`·`on`·prefix 일치, healthz 200 |
| 11:13 | 사이트에서 일부러 로그인 실패 1회 → db-1 로그 | ✅ `haven_app@haven from 10.x.x.x … connection authorized … SSL enabled (TLSv1.3)`. healthz·첫 화면(302)·로그인 화면(200)은 DB를 쓰지 않음 → ALB 상태 확인은 DB 로그를 늘리지 않음 |

| 11:1x | PR #116(0.3.1 + db-1 스크립트) 병합, 병합 뒤 짝 리뷰 요청 | main `f60e1c6`. 리뷰를 병합 전에 받지 못해 "병합 뒤 짝 리뷰"로 처리(#109와 같은 방식), 고칠 점은 새 PR |
| 11:33~11:44 | 로그인 실패 제한 시험(#114, 구민철) 4번: 실제 IP로 세는지 | ✅ 아래 표 |
| 11:46 | 구민철 #116 짝 리뷰 | ✅ 리뷰 4건 의도대로 반영, 명령 옵션 0.3.0과 같음, 구민철 PC main `f60e1c6` 60개 OK. 추가 수정 없음 |
| 12:04 | db-1 PostgreSQL 로그 양(설정 변경 뒤 약 1시간) | 197줄 / 30,670 B → **373줄 / 59,101 B (+176줄, 약 28KB)**, 접속 기록 39건. 로그인 시험·확인 명령 포함이라 평소보다 많음. 넉넉히 잡아 하루 12시간 가동 약 0.3MB/일 → 30일 약 10MB. PR #116 댓글로 보람·혁민에게 전달 |
| 12:15 | WAF 연결 조회(민성 PC, 읽기 전용): `aws wafv2 get-web-acl-for-resource` | ✅ `haven-web-acl` → 조회 권한 생김(11/13엔 없었음), 11/13 연결이 그대로 유지됨 |

되돌리기(재시작 없음): `ALTER SYSTEM RESET log_connections / log_disconnections / log_line_prefix` + `select pg_reload_conf()`

**로그인 실패 제한 시험(#114, 구민철 1~3번 · 민성 4번) 결과** (UTC, KST = +9)

| # | 시험 | 결과 | 근거 |
|---|---|---|---|
| 1 | 같은 아이디 5번 실패 → 잠김 | ✅ | 00:40·02:28·02:35 세 묶음 모두 400 × 5 → 429 (nginx 접근 로그, 앱 로그 `login_failure` → `login_limited`) |
| 2 | 잠긴 동안 막힘 | ✅ | 429 연속(00:41:06~00:43:16) |
| 3 | 15분 뒤 풀림 | ✅ | 마지막 실패 00:41:03 → 00:58:19 로그인 성공(302) |
| 4 | 실제 접속 IP로 셈 | ✅ | DB `accounts_loginfailure`의 IP 키(HMAC): 구민철 10건 같은 키, 다른 네트워크(휴대폰 LTE, 02:43:54) 다른 키. 코드(`신요찬/app/accounts/login_limit.py`)는 X-Forwarded-For 끝에서 두 번째 사용 |
| 참고 | 02:35 묶음의 400 6번 | 정상 | 02:35:31 요청은 실패 기록에 없음(실패로 세지 않은 요청), 세어진 실패 5번 뒤 잠김. 02:28과 02:35는 서로 다른 계정 |

- 아이디·IP 원문은 저장하지 않음(SECRET_KEY HMAC만). 15분 지난 실패 기록은 다음 실패 때 지워짐
- 앱 로그·nginx 로그에는 실제 IP가 없음(nginx는 ALB IP) → **11/27 Nginx 요청 ID 작업 때 X-Forwarded-For도 남기는 것 검토**

**다음**

| 할 일 | 메모 |
|---|---|
| ~1시간 로그 양~ | ✅ 12:04 +176줄 / 약 28KB, PR #116 댓글 |
| ~PR #116 병합·구민철 짝 리뷰~ | ✅ 병합 `f60e1c6`, 구민철 통과(11:46) |
| #116 병합 뒤 짝 리뷰: 보람(권한·보존·비용)·혁민(기록 범위·`/haven/db` 조회) | 고칠 점 나오면 새 PR |
| 11/17 로그인 실패 제한 운영 시험 2차(요찬 안내) | 민성 3장: 6번 직후 db-1에서 IP 키 조회(account 1줄 n=5, ip 3줄 n=2·2·1) |
| 구민철 3회차(11/23) | 0.3.1로 실행 |

## 민성's comment · 2026-11-16 오후 · 운영 경고 점검(DEP-05, `check --deploy`)

결과서 작성 중 DEP-05(구현명세 181줄: 배포 전 `check --deploy` 경고를 조치하거나 근거·만료가 있는 예외로 기록) 실행 기록이 없음을 확인했다. `deploy.sh`는 migrate와 앱 계정 읽기만 확인하고 `check --deploy`는 돌리지 않는다.

| 시각 | 한 일 | 결과 |
|---|---|---|
| 15:08 | web-1 SSM 세션(root)에서 `manage.py check --deploy` (운영 `370b22e`, `/etc/haven/haven.env` 읽기, 설정 변경 없음) | 경고 2건(`2 issues, 0 silenced`). DEBUG·SECRET_KEY·쿠키 Secure·ALLOWED_HOSTS 등 나머지는 경고 없음 |

| 경고 | 처리 |
|---|---|
| security.W008 `SECURE_SSL_REDIRECT` 미설정 | **예외**: ALB 80 리스너가 HTTP를 443으로 301 전환(연결확인표 NET-01-b). ALB → web-1은 설계상 HTTP라 Django에서 켜면 상태 검사·내부 요청까지 전환된다. 재검토: ALB 80 전환이 없어지거나 구조가 바뀔 때 |
| security.W004 `SECURE_HSTS_SECONDS` 미설정 | **미조치**: 잘못 켜면 브라우저가 기억해 되돌리기 어렵다. 짧은 기간(예: 1시간)부터 켜고 확인한 뒤 늘린다. 하위 도메인 포함·preload는 쓰지 않는다 |

**다음**

| 할 일 | 메모 |
|---|---|
| HSTS(W004) 설정 위치·담당 정하기 | Django 설정(요찬) 또는 Nginx 헤더(서버). 요찬과 상의 → 4회차 적용, 적용 뒤 응답 헤더와 `check --deploy` 재실행 |
| W008 예외를 앱 쪽 기록에도 남길지 | 요찬 앱계약·설정 문서와 맞추기 |

## 민성's comment · 2026-11-18 오후 · HSTS 적용 배포(W004 조치)

요찬 HSTS PR(`SECURE_HSTS_SECONDS=3600`, `DJANGO_HTTPS=1`일 때만, 하위 도메인·preload 끔) 병합 → 운영 배포 → 확인. 11/16 DEP-05의 W004 "미조치"를 이걸로 조치.

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 15:34 | PR 병합 뒤 PC에서 `git fetch` → main `f0428d7` | 바뀐 것: 앱 설정·시험·문서(서버 스크립트·requirements·migration 없음). 자동 시험 231개(Python 3.12·3.13) |
| 15:3x | 배포 전 백업(db-1 `backup.sh`, `BACKUP_BUCKET`을 STS로 계정 조회해 지정) | 실행함. 시간도장은 그 자리에서 적지 못함(기록 누락). 16:51 db-1에서 S3 목록 조회는 `s3:ListBucket` 권한 없음으로 거부(백업 쓰기만 허용한 최소 권한, 정상) → 시간도장 미기록. 다음 배포부터 `OK backup …` 줄을 바로 적음 |
| 15:3x | 배포 `f0428d75cd51bbed535a7cb71e75e31614a89cda` **2회** | ✅ 2회 모두 OK, `current` → `releases/f0428d7…` |
| 15:37 | web-1 `healthz` | `ok` |
| 15:37 | `curl -sI https://…/accounts/login/` | `strict-transport-security: max-age=3600` ✅ |
| 15:37 | `curl -sI http://…/` | `301 Moved Permanently` (ALB 전환 그대로) ✅ |
| 15:38 | web-1 SSM(root) `manage.py check --deploy` | 경고 3건(`3 issues, 0 silenced`): **W004 사라짐** ✅ |

| 경고 | 처리 |
|---|---|
| security.W004 `SECURE_HSTS_SECONDS` | **조치 완료**(3600초 = 1시간). 문제 없으면 4회차 이후 늘릴지 요찬과 결정 |
| security.W008 `SECURE_SSL_REDIRECT` | 예외 유지(11/16과 같음, ALB 80 → 443 301) |
| security.W005 `SECURE_HSTS_INCLUDE_SUBDOMAINS` | 의도한 예외: 하위 도메인을 쓰지 않음, 켜면 되돌리기 어려움(앱계약 1.2.1) |
| security.W021 `SECURE_HSTS_PRELOAD` | 의도한 예외: preload 목록은 빼는 데 몇 달 걸려 과제 기간에 맞지 않음(앱계약 1.2.1) |

**다음:** 아래 오후 기록

## 민성's comment · 2026-11-18 오후 2 · 로그인 실패 제한 2차 시험, SG 점검 0.3.2, Nginx 요청 ID 로그

**로그인 실패 제한 운영 시험 2차 (요찬 안내, 요찬 PC·휴대폰 + 민성 web-1·db-1 조회)**

| 시각 | 시험 | 결과 |
|---|---|---|
| 16:07 | 1장 계정 열거 + 가짜 X-Forwarded-For 6개 | ✅ 없는 아이디 400 ×5(789~804ms) → 429(76ms) |
| 16:10~11 | 2장 분산 공격(PC 3 + 휴대폰 2) | ✅ 계정 키 하나에 n=5, 휴대폰 6번째 429 |
| 16:14~20 | 3장 IP 키(web-1 manage.py shell, 읽기 전용 / db-1 SQL 같은 결과) | ✅ account 5·5, ip 8(Y-PC)·2(Y-PHONE). 가짜 XFF는 따로 세지 않고 실제 IP로 셈 |
| 16:36~42 | 4장 IP 30번 | ✅ account n=5 ×6, Y-PC n=30, 31번째·맞는 비밀번호 429. 휴대폰은 맞는 비밀번호로 로그인 성공(안내문 ④는 틀린 비밀번호 400이었으나 성공으로 확인) |

- IP 원문은 기록에 적지 않음. 결과 정리는 요찬 `신요찬/4회차_앱_검증기록.md`
- `locktest_1116`은 최종 정리 때까지 유지(조장 결정, 요찬에게 전달)

**SG 점검 도구 0.3.2 (AUD-03·05·06)**

- fixture 4개·시험 6개 추가, UDP/ICMP를 TCP와 구분(UDP 5432·ICMP가 SG-01로, ALB에서 온 UDP 80이 SG-03으로 잘못 나오던 것 → SG-05), 깨진 규칙 모양은 Traceback·종료 코드 1 대신 ERROR(2)
- 16:05 민성 PC(Windows) 시험 66개 통과. TCP 규칙 판정은 그대로라 11/13·11/16 실제 AWS 결과 영향 없음
- 구민철에게 11/23 실행·대조는 0.3.2로 하도록 전달

**인수인계 03 정정**

- 백업 버킷 지정을 STS 조회 방식으로(`${ACCOUNT_ID}`를 그대로 붙여 넣으면 빈 값), 백업 시각 바로 기록 안내
- 인스턴스 ID·내부 IP 가림

**Nginx 요청 ID 로그 (#143, 구현 민성 · 재검증 혁민 · 기한 11/27)**

| 시각 | 한 일 | 결과·근거 |
|---|---|---|
| 17:40 | #143 병합(리뷰 전 병합 → 병합 뒤 리뷰·재검증을 혁민에게 요청) | 접근 로그 형식 `haven`: combined 뒤에 `trace= rid= cid= run= client= rt=`, `nginx -t` 실패 시 이전 설정 복구. test-wsl.sh 시험 11개 추가(WSL 환경 없어 미실행) |
| 17:42 | 배포 전 백업(db-1 `backup.sh`, 버킷 STS 조회) | ✅ 시간도장 `20261118T084244Z` |
| 17:43~44 | 배포 `187090a669b184903101d93dafd0f67cba3c3095` **2회** | ✅ 2회 모두 `OK deployed`, `current` → `releases/187090a…` |
| 17:45 | web-1 `web-setup.sh` 재실행(`site.conf` 값 그대로) | ✅ `OK web-setup`, `nginx -t` 통과, `grep -c haven_trace` = 2 |
| 17:46 | `X-Haven-Request-ID: minsung-test-1` 요청 1건(PC → ALB → web-1) | ✅ Nginx `trace=1-6afd65d2-…` `rid=11b12b2d…` `cid=minsung-test-1` `client=`(PC 공인 IP, 가림). 앱 로그(journald)의 request_id·trace_id·client_request_id 세 값 모두 같음 |

- 처음 두 번(17:2x·17:41) `web-setup.sh` 재실행은 배포 전이라 예전 스크립트가 돌아 바뀐 것 없음(`grep -c haven_trace` = 0). 배포 뒤 다시 실행해 적용
- 남은 것: 혁민 병합 뒤 리뷰, WAF 로그에서 같은 trace(`1-6afd65d2-004c498b686b533b17a7907b`, 17:46 KST) 찾는 재검증

**다음:** 21시 `night.sh` · 혁민 #143 재검증 · 4회차(WAF Block, 운영 관리자 계정, destroy.sh ALB·WAF 순서, 네트워크/SG 재시험·구성도·종료 대상, 최종 DB+첨부 복원)
