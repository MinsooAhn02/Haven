# 6번 이민성 TODO

**브랜치:** `Minsung`

**담당:** 팀장(조장, 11/11 인수인계 완료)·서버 배포·백업/격리 복원·AWS 네트워크·EC2·SSM·ALB/HTTPS·SG CLI

> 2026-11-11 역할 재배치([docs/인수인계/02](../docs/인수인계/02_역할_재배치.md)): 안민수가 맡던 조장 일·배포·백업/복원을 이어받았다. 실제 SG 읽기 수집 → AUD fixture 대조는 권혁민에게 넘겼다(민성은 수집 명령 SG CLI 제공).

**공통 순서:** [TASK_TODO.md](../TASK_TODO.md)

## 수정 범위

본인 폴더의 network/·compute/·dns/·SG CLI와 fixture. 실제 VPC/SG/route/EC2/ALB/DNS/ACM은 본인만 변경한다. IAM 정책은 김보람, 서버 내부 앱/DB는 안민수 담당이다.

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
| 2 | 완료 (11/12 NET-06·06-b 통과, 세부 확인 일부 남음) | **11/09 준비(DRY_RUN만):** 환경: Windows Git Bash, aws-cli 2.39.6. 구축 스크립트 `infra/`(build·nat-up·nat-down·destroy) 작성. `bash -n` 6개 OK, `DRY_RUN=1 bash build.sh` → 1/8–8/8, nat-up 1/4–4/4 종료 0, nat-down·destroy(목록·--delete) 미리보기 종료 0. 거부 시험: 프로파일 빈 값 → VPC 생성 전 중단(1), DRY_RUN=2 → 중단(1), destroy --yes → 거절(1). SG 규칙 10줄 설계 4절과 양방향 대조 일치(`infra/SG수작업비교.md`). 연결 확인표 기대값 작성(`network/연결확인표.md`), 실제값은 구축 후.<br>**11/10 EC2 중지·시작(결정 4번):** `ec2-stop.sh`(web→db), `ec2-start.sh`(db→web, 공인 IP·SSM 확인), `night.sh`(ec2-stop + nat-down), `morning.sh`(nat-up + ec2-start, 평일 09~21시만). `DRY_RUN=1` 4개 종료 0. 가짜 aws 시험 `bash test/ec2-fake-test.sh` → **PASS 20 / FAIL 0**(일부러 실패: 서버 0대·2대·ID 불일치·중지 시간 초과·공인 IP·nat-up 실패·시간 밖 → 모두 멈춤(1)). 설명 `infra/EC2시작중지설명.md`, `infra/test/faketest설명.md`<br>**11/10 실제 구축 (팀 IAM 사용자 minsung, 서울):** `build.sh` 7단계에서 nat-up 확인이 Windows `\r` 때문에 오탐으로 멈춤 → `common.sh`에 `aws()` 래퍼(`tr -d '\r'`) 추가 → `nat-up.sh` RST-02 통과 → 남은 8단계만 `build-ec2.sh`(새로 작성, build.sh 8단계와 같음)로 EC2 2대 생성. 모양 확인: 서브넷 자동 공인 IP 끔, rt-private `0.0.0.0/0 → nat-`, SG 규칙 10줄 설계와 일치·전체 허용 outbound 없음, web-1·db-1 t3.small·공인 IP 없음·IMDSv2 필수·SSM 프로파일, gp3 20GB 암호화. 연결확인표 1차: SSM-01~04, NET-02-a/b/c, NET-04-c, OUT-01~04·06·07·09 ✅, OUT-08 ⚠️ 남은 위험, RST-02 ✅. 21:02 `night.sh` → RST-03 ✅(태그된 NAT·EIP 없음)<br>**11/11:** 09:02 `morning.sh` → 새 NAT, 사설 IP 그대로, SSM Online. `test-ec2.sh`(새로 작성)로 시험용 EC2 haven-test-net04 09:09 생성 → 09:23 삭제. **일부러 막힌 걸 확인한 시험:** 시험용 EC2 → db-1:5432, db-1:22, web-1:80 모두 timeout(exit=124) = NET-04·04-b·02-d ✅. 서버 준비(민수 스크립트, 민성 실행): db-setup·web-setup → 첫 배포 `deploy.sh f39e8e64` 중 GitHub SSH 22 timeout(sg-web outbound에 22 없음 = 설계대로 막힘, OUT-13) → 포트를 열지 않고 SSH-over-443으로 해결(민수 #48, OUT-14) → migrate 20건 OK·`haven_app` 점검 OK·healthz `ok` = NET-03 ✅. 재배포 `b068ba5f`(posts.0002_attachment migrate OK, healthz ok). OUT-12 apt 주소 web-1·db-1 모두 `http://` ✅<br>**11/12:** 11/11 21:14 `night.sh` → 09:03 `morning.sh` 뒤 NET-06·06-b ✅(haven·nginx·postgresql active, healthz ok 안·밖, `db ok`). web-1 CloudWatch Agent 설치(nginx access·error·앱 로그 → `/haven/web`, 앱 로그는 rsyslog로 `/var/log/haven/app.log` + logrotate 7일) → 내 PC에서 표시 요청 도착 확인 = OUT-10 web-1 ✅(db-1 미설정). 설치 절차를 `infra/server/cw-agent-setup.sh`로 정리, 가짜 시험 `test/cw-fake-test.sh`(AI 보조 작성). 12:24 web-1 실제 실행에서 스크립트 버그 2개 발견(Agent 상태 확인이 파이프 141로 오판, 설정 원본이 적용 뒤 사라짐) → 수정, 가짜 시험 22개로 늘려 두 버그를 되살리면 FAIL 확인. 12:42 수정 판 web-1 2회 실행 OK(2회차 재시작 없음), CloudWatch 도착 1건씩·중복 없음<br>**남은 것:** NET-03-b, NET-05 정식, OUT-05·11, OUT-10 db-1, RST-01 | PR 링크([#27](…)), PR 링크((https://github.com/MinsooAhn02/Haven/pull/34)). 11/10~11 실행분 PR 작성 예정. 증거: `network/연결확인표.md`(계정 번호·인스턴스 ID·IP 가림). AWS 조회·스크립트 실행은 민성 Git Bash, 서버 안 시험은 SSM 세션(11/10 민수, 11/11 민성). 스크립트·문서는 AI 보조 작성, 실행은 직접 | 안민수: web-1/db-1 사설 IP 전달 완료, 첫 배포·재배포 healthz 결과 전달, NET-06 결과 11/12 아침. 김보람: 3회차 ALB·ACM·Route 53 권한 요청(11/11). 노푸른: 브라우저 접속은 ALB 연결 뒤(현재 web-1 안에서만 응답) |
| 3 | 진행 중 (ALB·HTTPS 완료, live SG 수집 남음) | 도메인 `orchestration-haven.cloud` 확정(11/11). Route 53 공개 호스팅 영역 1개, 네임서버 4개가 구글 DNS(8.8.8.8) 응답과 일치 확인. `infra/build-alb.sh` 작성(ACM DNS 검증 → 대상 그룹 /healthz → ALB → 443 TLS1.2+·80→301 → apex Alias → healthy·NET-01·01-b 확인). 가짜 시험 `test/alb-fake-test.sh` 39개(일부러 실패: ALB 중복·web-1 꺼짐·호스팅 영역 0/2개·기존 A 레코드·권한 없음·인증서 시간 초과/FAILED·unhealthy·302·가짜 도메인 리다이렉트). 시험이 실제로 버그를 잡는지 스크립트를 일부러 망가뜨려 확인(가드 3곳 제거 → 해당 시험 FAIL). 민성 Windows Git Bash 11:32: 가짜 시험 PASS 39 / FAIL 0, `DRY_RUN=1 bash build-alb.sh` 1/5~5/5 종료 0(실제 state ID로 명령만 출력). 권한: ELB·ACM 읽기부터 AccessDenied(11:1x) → 보람님 추가 → 11:36 1차 실행: 인증서 2초 만에 발급, 대상 그룹까지 만들고 ALB에서 `ec2:GetSecurityGroupsForVpc` 없음으로 멈춤 → 스크립트에 "이 스크립트가 만든 것(state 기록과 같은 ID)만 이어서 쓰기" 추가(가짜 시험 F1~F13) → 보람님 권한 추가 → 11:47 2차: 대상 그룹·인증서 재사용, ALB·리스너·도메인 연결, healthy, NET-01 OK, NET-01-b는 **Windows curl이 `/dev/null`을 몰라서** 확인 단계만 실패 → 고침(가짜 curl도 Windows처럼 바꿔 W1 시험 추가, 옛 코드로 되돌리면 13개 FAIL 확인) → 11:58 3차: 전부 재사용(새로 만든 것 없음), **NET-01 200 ok·인증서 OK, NET-01-b 301 → https, 실제 DNS 접속 OK**. 가짜 시험 최종 PASS 59 / FAIL 0(민성 Git Bash). 남은 것: live SG 읽기 수집·AUD 대조, WAF·ALB 접근 로그(설계 7절) | 증거: 연결확인표 NET-01·01-b, `~/alb-1111.log`(계정 번호·ARN 가려서 첨부). PR 작성 예정 | 노푸른: `https://orchestration-haven.cloud` 접속 가능(11/11 11:59~, 평일 09~21시, 밤에는 EC2가 꺼져 502/503). 안민수: ALB 켜 둠(11/11 결정), CSRF_TRUSTED_ORIGINS가 이 도메인인지 실제 로그인으로 확인 요청. 김보람: ALB 요금 시작(11:47~) 비용 확인 |
| 4 | 미착수 | 미확인 | — | — |

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

## 조장 이민성 · 2026-11-12 저녁 · 현재 상태와 4회차 추가 업무 (현황판 기준)

- **끝난 것(작성자 보고, #73 병합 전):** NET-06·06-b 재시작 확인, OUT-10 web-1 로그 수집(db-1은 미설정), 설치 스크립트와 가짜 시험. 11/11 이후 병합: #54(ALB·HTTPS), #64(메일 코드), #62·#65·#66·#72.
- **지금 할 일(순서대로)**
  1. #73 병합 전 처리: 최종 판 스크립트 web-1 재실행 결과, 보람 짝 리뷰, 이 문서 갱신.
  2. #64 서버 쪽 PR: `안민수/server/requirements.txt`에 `boto3`·`botocore`, `deploy.sh`가 `MAIL_FROM`이 있을 때 메일 환경변수를 같이 쓰기 → 같은 커밋으로 2번 배포. 이때 #66 템플릿(공유 설정 버튼)도 함께 반영된다.
  3. SG 점검 도구 live 모드 구현·시험·병합(`network_audit.py live --region --vpc-id --profile --baseline --output-dir`). 병합 뒤 VPC ID와 실행 방법을 구민철에게 전달(`구민철/SG_실제점검_인계.md`, 구민철 3회차 11/23~).
  4. WAF(4회차, 11/27까지 마무리 목표): 민성 = ALB 연결과 Block 적용. Web ACL·규칙·전용 로그 구성(Count)은 혁민, 쓰기 권한은 보람. 현재 민성 정책(12·18번)에 `wafv2` 권한이 없다.
  5. 백업·격리 복원 연습, 15번 SG 삭제 실제 시험, ALB·WAF 밤 처리 결정(밤·주말 유지 약 $4.55/주).
  6. 가상 운영 관리자 계정: 4회차 계정 상태 변경·이력 시험(APP-07·09) 직전에만 만들고 끝나면 바로 비활성화(400 확인용이 아님).
  7. 조장 일: 로그인 실패 제한 수치 결정(요찬 안 뒤), 4회차 마무리 목표 11/27, 11/13 17:30 판정 범위 확인, 병합·동기화·공지.
