# 6번 이민성 TODO

**브랜치:** `Minsung`

**담당:** AWS 네트워크·EC2·SSM·ALB/HTTPS·SG CLI

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
| 2 | 진행 중 | **준비 완료, AWS 실행 전.** 환경: Windows Git Bash, aws-cli 2.39.6. 구축 스크립트 `infra/`(build·nat-up·nat-down·destroy) 작성. `bash -n` 6개 OK, `DRY_RUN=1 bash build.sh` → 1/8~8/8·nat-up 1/4~4/4 종료 0, nat-down·destroy(목록·--delete) 미리보기 종료 0. 거부 시험: 프로파일 빈 값 → VPC 생성 전 중단(1), DRY_RUN=2 → 중단(1), destroy --yes → 거절(1). SG 규칙 10줄 설계 4절과 양방향 대조 일치(`infra/SG수작업비교.md`). 연결 확인표 기대값 작성(`network/연결확인표.md`), 실제값은 수요일 구축 후 | PR 링크(#번호). AWS 호출 없음(DRY_RUN만)이라 가릴 값 없음. 수요일 실행 결과는 계정 번호·인스턴스 ID·IP 가려서 기록 | 김보람: IAM 적용(Role `haven-ec2-ssm-role`·프로파일 `haven-ec2-ssm-profile`, 민성 `iam:PassRole`은 이 Role만, `ssm:GetParameter`), 팀 계정 번호, 짝 리뷰. 안민수: 수요일 구축 직후 재부팅 시험(NET-06), pg_hba·`haven_app`/`postgres` 계정(NET-03), destroy 실행 시 사전 확인. 미완료: 실제 구축·연결 시험, EC2 중지·시작 스크립트 |
| 3 | 미착수 | 미확인 | — | — |
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
- **주력:** ~`864a847` SG 문서 보완 PR~ + SSM·Web→DB·필요 출구·직접 접근 거부 확인표(기대값까지)
- **대기열:** VPC/SG/EC2 구축 절차·변경안(승인 즉시 실행용) → live 읽기 수집 설계·AUD fixture 확장
- **⏳ 기다릴 것:** 실제 구축은 민수 결정 + 보람 IAM·Role 필요. AWS 쓰기 작업은 승인 전 보류.


## 민수's comment · 2026-11-09 배정 갱신

AWS 운영 결정 추천안이 main `docs/AWS_운영결정.md`에 올라갔고, 현황판 `TASK_TODO.html`도 오늘 기준으로 바꿨습니다. 다 못 해도 괜찮고, 끝나면 Discord에 오늘 상황 보고 부탁드립니다.
- **완료:** SG 보완 PR #18 병합(`a3c962f`) — 추가 보완 필요 없음
- **주력:** `docs/AWS_운영결정.md` 5번 확인(Ubuntu 24.04 기본 Python 3.12, apt 80 포트) + 서버 사양·대수·가동 시간을 보람님께 → SSM·Web→DB·출구·직접 접근 거부 확인표(기대값까지)
- **대기열:** 구축 절차서 — 다른 계정에서 그대로 다시 만들 수 있게(계정 ID·ARN·자원 ID는 변수, 가능하면 AWS CLI 명령) → live 읽기 수집 설계·AUD fixture 확장
- **⏳ 기다릴 것:** 실제 구축은 결정 확정 + 보람님 IAM 이후

## 민수's comment · 2026-11-09 확대 배정 (AI 사용 전제)

다들 AI를 쓰니 일을 크게 잡았습니다. **이번 주(11/09~13)에 원래 1·2회차, 다음 주에 3·4회차**를 끝내는 게 목표예요. 다 못 해도 괜찮고, 위에서부터 하다가 막히면 다음 항목으로 넘어가세요. 다른 사람과 같이 정해야 하는 건 회의하지 말고 민수에게 물어보면 바로 정합니다. AWS 운영 결정은 확정됐습니다(main `docs/AWS_운영결정.md`). PR에는 실제로 돌린 명령·결과와 **일부러 실패시킨 거부 시험**을 꼭 붙여 주세요(AI 코드는 시험을 통과해도 틀릴 수 있어서). 매일 끝나면 Discord 상황 보고는 그대로 부탁드려요.

1. **구축 스크립트(AWS CLI, 계정 ID·자원 ID는 변수):** VPC·서브넷·라우팅·SG(서버 outbound 80 추가)·S3 Gateway Endpoint·NAT·EC2 2대(Ubuntu 24.04, t3.small, gp3 20GB, 공인 IP 없음, SSM Role)
2. `nat-up` / `nat-down` 스크립트: 새 NAT로 경로가 바뀌었는지, EIP가 해제됐는지 스크립트가 확인 + 전체 삭제 스크립트(실행은 민수 확인 후)
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
