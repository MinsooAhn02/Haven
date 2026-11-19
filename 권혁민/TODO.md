# 3번 권혁민 TODO

**브랜치:** `Hyeokmin`

**담당:** 레드팀 시험·요청 재현 CLI·WAF·로그 검증

**공통 순서:** [TASK_TODO.md](../TASK_TODO.md)

## 수정 범위

본인 폴더의 시험 케이스·요청 CLI·fixture·WAF 설정/전용 로그 결과. 앱·SG·라우팅·IAM·DB는 직접 수정하지 않는다.

## 2일 단위 임무

### 1회차 · 1~2일차

- [x] 명세 시험 ID를 연결한 정상/비로그인/타인/공유/해제/비활성/CSRF/크기/첨부 시험표를 만든다. 요청 재현 CLI를 fixture/로컬부터 구현한다.
- [x] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 2회차 · 3~4일차

- [x] 대상·경로/파일 범위·인증·요청 수/속도·timeout·응답 크기 제한을 시험한다. 준비된 앱에서 재현하고 요청 ID·기대/실제 결과·가림 로그를 담당자에게 전달한다.
- [x] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 3회차 · 5~6일차

- [x] 업로드 보안·용량·PDF 시험을 통합하고 로컬 Django에서 검증한다.
- [x] AWS WAF Count 시험 및 앱/WAF 로그 상관분석을 수행한다. (11/13 Count 탐지: `시험결과/2026-11-13_AWS_01.md`, 11/16 요청별 WAF↔Django 자동 상관분석: 아래 "AWS 정리·로그 상관분석 검증")
- [ ] 시험 결과 보고서 작성 및 PR 제출

### 4회차 · 7~8일차

- [x] AWS WAF Web ACL 생성 및 관리형 규칙 3개 Count 모드 구성
- [x] WAF 전용 CloudWatch 로그 그룹 생성 및 30일 보존 설정
- [x] WAF 로깅 연동 및 민감 헤더 마스킹 설정
- [x] IAM 권한 검증 (CloudWatch·EC2·WAF 조회, SSM 접속 거부)
- [x] ALB 연결 후 WAF Count 로그 수집 및 오탐 분석 — 시험 요청 Count 동작 확인(11/13 수동, 11/17 요청 CLI 재시험 4건 PASS), 누적 Count 로그 분석(11/18, 아래 "누적 Count 로그 분석"): 첨부 업로드의 `SizeRestrictions_BODY` 오탐 확인. 로그인 `SQLi_BODY` 8건·User-Agent 없는 요청의 출처는 팀 확인 필요
- [x] WAF·Nginx·Django 로그 상관분석 — WAF↔Django는 Trace Root 기준 자동 연결(11/16). Nginx는 #143 적용 뒤 재검증 완료(11/19, 요청 40건 WAF·Nginx·앱 모두 1건씩 연결, 아래 "Nginx 요청 식별자 재검증")
- [ ] AWS 환경에서 보안 fixture 재실행 — 부분 완료: 게시글·첨부·공유·해제 스모크 9건(`cases_haven_aws.json`, 11/16), 2회차 보안 회귀 25건(`cases_aws_security_phase2.json`, 11/19, HTTP 32/32·로그 32/32 MATCHED), 3회차 업로드 20건(`cases_aws_upload.json`, 11/19, HTTP 38/38·로그 38/38 MATCHED). 공유 경계 등 나머지와 용량 시험·관리자 시험은 AWS 변환 전. 실행 결과는 로컬 `권혁민/output/` 아래 보관
- [ ] Count 결과를 바탕으로 Block 전환 대상 선정 — 근거 확보: 누적 Count 로그(11/18), 보안 회귀·업로드·WAF 오탐·미탐 검증(11/19, `시험결과/2026-11-19_AWS_01~03.md`). 판단 문서 작성 중
- [ ] Block 적용 전후 정상 기능 및 차단 결과 비교
- [ ] 발견 문제의 수정 후 재시험과 정상 회귀를 확인한다.
- [ ] 최종 시험 결과 보고서 작성 및 PR 제출

#### IAM 권한 검증 결과 (2026-11-13)

- 환경: AWS CLI, profile `hyeokmin`, region `ap-northeast-2`
- WAF 조회: `aws wafv2 get-web-acl` → 성공
  - `haven-web-acl`, 기본 Allow, 관리형 규칙 3개 Count 확인
  - `--query` 없이 원본 JSON 조회 및 로컬 저장
- CloudWatch 로그 그룹 조회: `logs describe-log-groups` → 성공
  - `/haven/web`, 보존 기간 30일
- 로그 스트림 조회: `logs describe-log-streams` → 성공
  - `app`, `nginx-access`, `nginx-error` 확인
- 로그 읽기: `logs get-log-events` → 이벤트 5건 조회 성공
- 로그 검색: `logs filter-log-events` → 이벤트 5건 검색 성공
- EC2 조회: `ec2 describe-instances` → 실행 중인 인스턴스 2대 확인
- SSM 접근 거부: `ssm start-session` → `AccessDeniedException`
  - `ssm:StartSession` 허용 정책 없음 확인

결과: 조회·검색 권한 정상, SSM 기본 셸 세션 접근 거부 정상.
범위: 실제 실행한 API 호출 기준. IAM 전체 정책 및 다른 세션 방식은 미검증.

#### WAF Web ACL 원본 검증 (2026-11-13)

- 대상: `haven-web-acl` (`REGIONAL`, `ap-northeast-2`)
- 검증 방법: AWS CLI `get-web-acl` 실제 조회
- 검증 결과:
  - 기본 동작 Allow 확인
  - 관리형 규칙 3개 모두 Count 모드 확인
  - `SampledRequestsEnabled=false` 확인
  - 원본 JSON 조회 성공 (`WAF_READ_OK`)
- 원본 증빙: `waf/2026-11-13_get-web-acl_raw.json`

실행 명령:

```cmd
aws wafv2 get-web-acl --name haven-web-acl --scope REGIONAL --id ddd129cb-9894-4907-9807-bbdfb79e36c1 --profile hyeokmin --region ap-northeast-2 --output json --no-cli-pager
```

※ 2026-11-13 12:00경(KST) 조장이 ALB 연결 완료(#98). 이후 정상 요청 및 SQLi·XSS·PROPFIND의 실제 WAF Count 동작과 CloudWatch 로그 수집을 확인함. WAF–Nginx–Gunicorn 로그 상관분석은 요청 경로·시각 기준으로 완료했으며, Nginx·Gunicorn의 요청 ID 헤더 기록 개선은 별도 진행 예정.

#### AWS 정리·로그 상관분석 검증 (2026-11-16)

- 대상: `https://orchestration-haven.cloud`, suite `haven-aws-cleanup-smoke-001`, run_id `cb5c3f96-b6f3-4c4e-aa35-4c0da7d9446e`
- 코드: Hyeokmin `084d3dd` (Windows CMD 로컬 `python -m pytest -q`: 398 passed, main 반영 `fb12e49` 후에도 398 passed)
- 시험 계정: 고정 시험 계정 member_a/b/c 재사용, 운영 DB 초기화 없음, 이번 실행이 만든 게시글·공유만 정리

실행 명령:

```cmd
python request_verify.py run --target https://orchestration-haven.cloud --allowlist fixtures/allowlist_aws.json --cases fixtures/cases_haven_aws.json --fixture-dir fixtures --output-dir output_aws_cleanup_03 --max-requests 100 --max-duration 300
python request_verify.py collect-logs --run-json output_aws_cleanup_03/results.json --profile hyeokmin --region ap-northeast-2 --expected-account ${ACCOUNT_ID} --output-dir output_aws_cleanup_logs_03
python request_verify.py correlate-cloudwatch --run-json output_aws_cleanup_03/results.json --logs-dir output_aws_cleanup_logs_03 --expected-account ${ACCOUNT_ID} --output-dir output_aws_cleanup_corr_03
```

| 항목 | 결과 |
|---|---|
| 본시험 HTTP 기대값 | 9/9 일치 |
| 자동 정리 | `cleanup_complete: true`, 오류 0, 삭제 302 → 확인 GET 404 |
| 요청·응답 집계 | 본시험 9 + 준비 7 + 정리 4 = 20, 응답 20 |
| 로그 수집 | WAF 22건, 앱 119건, `collection_complete: true` |
| 로그 선택 | WAF 11건, 앱 11건 (본시험 9 + 삭제 1 + 확인 GET 1) |
| 상관분석 | 11건 모두 MATCHED, WAF ALLOW, 앱 MATCH |
| 판정 | 확인 GET PASS(http_only), 나머지 10건 UNKNOWN(manual_required), 종료 코드 3 |

같은 요청의 WAF·앱 로그 대조 (`AWS-A-POST-READ`, `GET /posts/13/`, 식별자는 앞부분만):

| 위치 | 시각(UTC) | 결과 | 식별자 | CLI Root와 일치 |
|---|---|---|---|---|
| CLI 전송 | 03:31:34.931 | — | Root `1-6afa7916-fff0153e…` | 기준 |
| WAF | 03:31:35.735 | ALLOW | 헤더 `X-Amzn-Trace-Id` Root | 일치 (로그 선택 기준) |
| WAF | 03:31:35.735 | ALLOW | `requestId` `1-6afa7917-4ef22ca9…` | **불일치** |
| 앱 (Django) | 03:31:35.768 | 200 | `trace_id` `1-6afa7916-fff0153e…` | 일치 |

해석: CLI처럼 클라이언트가 `X-Amzn-Trace-Id`를 보내면 그 Root가 앱 `trace_id`까지 유지되지만, WAF `requestId`는 별도 값이다. 따라서 WAF↔Django 연결 키는 WAF 로그에 기록된 `X-Amzn-Trace-Id` 헤더 Root이며, "WAF `requestId` = 앱 `trace_id`"는 이 요청에서는 성립하지 않는다. 클라이언트가 Trace 헤더를 보내지 않은 요청의 경우는 이번에 확인하지 않았다.

범위: HTTP 응답과 WAF·Django 로그 연결까지 확인. 정리 검증 수준은 `HTTP_ONLY`이며 DB 행·첨부 파일의 물리 삭제는 확인하지 않음. Nginx 로그는 요청 식별자 기록 전이라 대조하지 않음. 수집 시간 범위에는 다른 사용자의 로그가 포함될 수 있어 원본 로그는 커밋하지 않음.

#### WAF Count 재시험 (2026-11-17)

- 목적: 11/13 수동 Count 시험은 결과 파일이 남지 않아, 요청 CLI로 다시 실행하고 결과·로그·상관분석을 저장한다.
- 대상: `https://orchestration-haven.cloud`, suite `haven-aws-waf-count-001`(`fixtures/cases_aws_waf_count.json`), run_id `2710825f-674a-4a9e-933f-cffbedf51c67`, 시작 2026-11-17 09:10 KST
- 코드: Hyeokmin `3de308e` (로컬 `python -m pytest -q`: 400 passed). CSV에 `count_rule_ids` 열 추가
- 요청: 비로그인 GET 4건(정상 2, SQLi 형태 1, XSS 형태 1). 시험 문자열은 무해한 형태이고 WAF는 Count 모드

| 케이스 | HTTP | 상관 | WAF | Count 규칙 | 판정 |
|---|---|---|---|---|---|
| WAF-NORMAL-LOGIN-GET | 200 | MATCHED | ALLOW | 없음 | PASS |
| WAF-NORMAL-QUERY-GET | 200 | MATCHED | ALLOW | 없음 | PASS |
| WAF-SQLI-QUERY-COUNT | 200 | MATCHED | ALLOW | `AWSManagedRulesSQLiRuleSet#Version_2.5::SQLi_QUERYARGUMENTS` | PASS |
| WAF-XSS-QUERY-COUNT | 200 | MATCHED | ALLOW | `AWSManagedRulesCommonRuleSet#Version_1.23::CrossSiteScripting_QUERYARGUMENTS` | PASS |

- 요청 4 = 응답 4, 로그 수집 WAF 4건·앱 48건(`collection_complete: true`), 상관분석 종료 코드 0
- 가림: 이번 시험과 11/16 시험의 WAF 로그에서 Cookie 헤더가 있는 요청 14건 모두 `REDACTED`. Authorization 헤더는 보낸 요청이 없어 실제 로그로는 미확인(설정은 확인)
- 범위: 시험 요청 기준의 관찰이며 방어율이 아니다. 11/13과 달리 `SQLiExtendedPatterns_QUERYARGUMENTS`는 걸리지 않았다(시험 문자열 차이로 보임). PROPFIND는 요청 CLI가 GET·POST만 지원해 재시험하지 않았다. WAF 로그는 URI·쿼리 값을 가리지 않으므로 원본 로그는 커밋하지 않는다.

#### 2회차 보안 회귀 시험 AWS 실행 (2026-11-19)

- 결과 보고서: `시험결과/2026-11-19_AWS_01.md` — 25건(실행 32건) HTTP 32/32 일치, 로그 32/32 MATCHED, WAF 공격형 16건 중 14건 Count(미탐: `admin' -- `), 정상·거부 요청 24건 오탐 0. 정리 5건 완료(1건 `recover`).

#### 누적 Count 로그 분석 (2026-11-18)

- 방법: CloudWatch Logs Insights, 로그 그룹 `aws-waf-logs-haven`. 규칙 그룹마다 처음 걸린 규칙 기준으로 집계(최소 건수). 접속 IP는 집계에서 뺐다.
- 범위: 2026-11-13 21:00 ~ 11-18 16:15 KST (시작 시각을 UTC로 잘못 넣어 11/13 12:00~21:00 KST 9시간이 빠짐. 이 구간에는 11/13 수동 Count 시험이 있음)
- 전체 요청 8,753건(모두 ALLOW, 그중 요청 CLI 70건), 규칙에 걸린 요청 1,494건

| 규칙 (그룹) | 건수 | 출처·대상 | 판단 |
|---|---:|---|---|
| `ExploitablePaths_URIPATH` (KnownBadInputs) | 684 | `/.env`·`/.aws/config` 등 없는 경로 탐색 | 스캐너, 정탐 |
| `NoUserAgent_HEADER` (Common) | 534 | 대부분 해외 스캐너. 일부 KR에서 `/`·`/posts/`·`/accounts/login/` 반복(같은 순간 2건씩) | 대부분 정탐, **KR 반복 요청은 팀 점검 스크립트인지 확인 필요** |
| `UserAgent_BadBots_HEADER` (Common) | 120 | zgrab·masscan·360Spider | 정탐 |
| `RestrictedExtensions_URIPATH`, `GenericLFI_*`, `GenericRFI_*` (Common) | 98 | `.bak`·`/.aws/credentials`·경로 조작 | 정탐 |
| `SizeRestrictions_BODY` (Common) | 27 | **KR 브라우저의 `POST /posts/{id}/attachments/`(11/16~17, 게시글 9개)** | **오탐: 8KB 넘는 정상 첨부 업로드** |
| `CrossSiteScripting_BODY` (Common) | 21 | `/`·`/xml`·`/soap`·`/api`에 curl 등 | 정탐 |
| `ReactJSRCE_BODY`, `PROPFIND_METHOD`, `Host_localhost_HEADER` (KnownBadInputs) | 14 | `POST /` 등 | 정탐 |
| `SQLi_BODY` (SQLi) | 8 | **KR 브라우저의 `POST /accounts/login/`·`/signup/`(11/16 11:16~11:35, 11/17 12:42 KST)** | **팀원 시험인지 평범한 입력인지 확인 필요** |
| 기타 (`EC2MetaDataSSRF_BODY`, CLI 재시험 2건) | 4 | | |

- 실제 기능 주소(`/`, `/accounts/`, `/posts/`, `/admin/`)에 걸린 요청 중 팀원 사용으로 보이는 것은 위 굵은 글씨 3종류뿐이다.
- Block 판단 시사점: KnownBadInputs는 스캐너 경로에만 걸렸다. Common을 통째로 Block하면 8KB 넘는 첨부 업로드가 막히므로 `SizeRestrictions_BODY`는 Count로 남겨야 한다. SQLi는 로그인 8건의 정체를 확인한 뒤 판단한다.

#### Nginx 요청 식별자 재검증 (2026-11-19, #143)

- 근거 로그: 2회차 보안 회귀 시험 AWS 실행(run_id `f28910cd`, 09:12 KST)에서 `collect-logs`로 수집한 `aws-waf-logs-haven`·`/haven/web`. 새 요청 없음
- `/haven/web`의 `nginx-access` 스트림 114줄 모두 `trace= rid= cid= run= client= rt=` 형식

| 확인 | 결과 |
|---|---|
| CLI 요청 40건이 WAF·Nginx·앱 로그에 1건씩 | 40/40 · 40/40 · 40/40 |
| Nginx `trace`·`run` = CLI가 보낸 Trace Root·run_id | 40/40 |
| Nginx `rid`·`trace` = 앱 `request_id`·`trace_id` | 40/40 |
| Nginx 상태 = 앱 `status` | 40/40 |
| WAF `X-Amzn-Trace-Id` Root = Nginx `trace` | 52/52 (준비 요청 포함) |

- #143 리뷰 의견(PR 댓글): Trace Root 대소문자 처리가 Nginx와 앱이 다름, Root가 2개인 헤더를 앱은 null·Nginx는 첫 값으로 기록, Trace는 클라이언트가 정할 수 있어 `rid`·시각과 함께 대조해야 함, `client=`는 접속 IP라 공유 시 가림, `test-wsl.sh` 새 시험 11개는 미실행
- 조장 시험 요청 단건(11/18 17:46, trace `1-6afd65d2-…`)의 WAF 확인은 위 40건 재검증으로 대신했다.

#### 3회차 업로드 시험 AWS 실행 (2026-11-19)

- 결과 보고서: `시험결과/2026-11-19_AWS_02.md` — 20건(실행 38건) HTTP 38/38 일치, 로그 38/38 MATCHED, 정리 2건 완료. **정확히 2 MiB 정상 업로드가 `SizeRestrictions_BODY`에 걸려 누적 로그의 오탐을 재현**(Block 시 정상 업로드 차단). WAF가 탐지한 업로드 공격은 파일명 `../` 1종(`GenericLFI_BODY`), 위험한 형식 11종은 WAF 미탐·앱이 모두 거부.

#### WAF 오탐·미탐 검증 (2026-11-19)

- 결과 보고서: `시험결과/2026-11-19_AWS_03.md` — 19건(실행 35건) HTTP 35/35 일치, 로그 34/35 MATCHED(경로 조작 1건은 WAF·Nginx·앱 로그가 없어 ALB 거부로 보임), 정리 완료. **정상 글 9종(SQL·HTML 설명, 경로, 코드, 6.8KB 한국어 포함) 오탐 0**, 공격 변형 20/21 탐지(XSS 인코딩·대소문자·이중 인코딩, password SQLi, 재표시 XSS, 파일명 XSS), `.env`·LFI·SSRF 탐지. **주석형 SQL(`admin'--`) 미탐**(로그인 P04와 같은 형태, 앱이 거부).

## 인계·완료 기준

- 앱 문제=신요찬, 네트워크=이민성, IAM=김보람, 배포=안민수에게 재현 조건 인계
- 시험은 승인된 Haven 대상·가상 계정·무해한 파일 fixture로 제한
- 403만으로 WAF 차단을 단정하지 않고 WAF/앱 로그로 대조
- 본인 검증과 검토 결과가 있는 변경만 main에 합친다. 미완료 작업은 다음 회차로 넘기며 다른 담당자에게 알린다.
- 회차 통합 후 최신 main을 본인 브랜치에 반영하고 다음 회차를 시작한다.

## 결과 기록

| 회차 | 상태 | 환경·실행 명령·기대/실제 결과 | PR·가림 증거 | 다음 담당자에게 전달할 것 |
|---|---|---|---|---|
| 1 | 로컬 검증 완료·PR 병합 완료 | Windows 11, Python 3.13.1 / `python -m pytest -q tests`: 45 passed in 14.74s / `python -m pytest -q tests -k probe`: 5 passed, 40 deselected in 6.57s / 실제 Django·AWS WAF 검증은 미실행 | 테스트 실행 출력 확인 | Django URL·폼·인증/CSRF·로그 계약 및 시험 데이터 초기화 방법 확인 후 앱 연동 시험 |
| 2 | 로컬 Django HTTP 시험 완료·추가 검증 대기 | 2026-11-10 / Django + PostgreSQL (`haven_verify`) / `--phase 2`: 87개 논리 케이스, 109/109 HTTP 기대값 일치, 전체 137요청, 오류 0건, 복구 완료 | `시험결과/2026-11-10_로컬_02.md` 파일 확인. 세부내용은 로컬 `output_django_phase2_01/results.json`로 보관 | DB·브라우저 검증, 앱/WAF 로그 상관분석, AWS 환경 재시험 |
| 3 | 로컬 Django HTTP 통합 완료·AWS 미검증 | 2026-11-11 / 로컬 통합 시험 당시 pytest 237 통과. 이후 PR #62 리뷰 반영 후 pytest 251 통과. 통합 HTTP 시험 기록은 153개 논리 케이스·197/197 일치. / 1~3회차 통합 153개 케이스, HTTP 197/197 일치, 전체 요청 231건, 복구 완료·오류 0건 | `output_django_phase3_full_02/results.json` 로컬 보관, 보고서 작성 예정 | WAF Count·로그 상관분석, 저장소 잔여 파일 확인, AWS 재시험 |
| 4 | WAF Count 구성·탐지 확인, AWS 정리·WAF↔Django 상관분석 검증 완료, Count 재시험 완료, Block 판단 대기 | 2026-11-16 / `https://orchestration-haven.cloud` / run_id `cb5c3f96` / `run` → `collect-logs` → `correlate-cloudwatch` / 본시험 HTTP 9/9 일치, 자동 정리 완료(오류 0), 요청 20 = 응답 20, 본시험 9·삭제 1·삭제 후 확인 GET 1 모두 MATCHED(WAF ALLOW·앱 MATCH), 확인 GET PASS, 종료 코드 3(manual_required 10건) / 2026-11-17 Count 재시험 run_id `2710825f`: 정상 2·SQLi 1·XSS 1 모두 MATCHED·PASS, 정상 요청 Count 0건, 종료 코드 0 / pytest 400 passed | 로컬 `output_aws_cleanup_03`·`_logs_03`·`_corr_03`, `output_aws_waf_count_01`·`_logs_01`·`_corr_01` 보관(원본 로그 미커밋). 정리 검증은 HTTP_ONLY, DB 행·첨부 파일 물리 삭제는 미검증 | 누적 Count 로그 오탐 분석 → Block 대상 선정 → 민성 적용, Nginx 식별자 재검증(11/27) |

세부 기능/시험은 [기본 명세](../docs/구현명세/기본프로젝트_구현명세.md)를 따른다. 비밀값과 원본 민감 로그는 기록하지 않는다.

## 민수's comment · 2026-11-06

- 현재 로컬 mock·fixture·pytest 기록(19 tests)은 기록된 로컬 결과로 두고, 실제로 다시 실행하지 않은 시험을 재실행한 것처럼 쓰지 말아 주세요. 해당 기존 작업은 PR로 열어 검토받고 상태를 로컬 검증 완료·PR 대기로 구분해 주세요.
- 신요찬에게 URL·폼·인증/CSRF·로그 계약을 받고, 안민수에게 실제 앱 시험의 실행 출처와 commit을 확인한 뒤 실제 앱/WAF 범위를 정해 주세요.
- 기다리는 동안 mock 기반 session·rate·timeout·외부 대상 0건 시험은 병렬로 보완할 수 있습니다.
- 실제 WAF 시험은 승인된 Haven 대상과 준비된 로그가 있을 때 진행해 주세요. synthetic PASS는 실제 WAF 통과 근거로 기록하지 않습니다.
- TODO에 현재 상태와 실행 근거, 다음 담당자에게 넘길 내용 및 가능한 인계 시각을 답글로 기록해 주세요.

## 혁민's reply · 2026-11-07

- 기존 19개 테스트 통과 기록은 당시 코드에서 실제 실행한 결과입니다. 이후 fixture 확장, 회차 선택, 리다이렉트 목적지 검증을 추가하고 다시 실행하여, 최신 결과인 `45 passed in 14.74s`로 갱신했습니다.
- 1회차 담당 범위인 시험표·요청 재현 CLI·로컬 fixture 구현과 로컬 검증을 완료했습니다. 현재 상태는 로컬 검증 완료·PR 대기입니다.
- 요청 CLI의 기본 구조는 구현했으며, 실제 앱 연동 시험은 아직 수행하지 않았습니다. 앱 담당자의 URL·폼·인증/CSRF·로그 계약을 확인한 뒤 path와 payload 등을 맞출 예정입니다.
- 기본 동작·권한 검증용 JSON과 일부 보안 시험 예시는 준비했습니다. 실제 WAF 검증용 케이스는 앱 서버와 WAF·로그 환경이 준비된 이후 확장하겠습니다. 현재 mock 시험 결과는 실제 앱이나 WAF의 보안 검증 결과가 아닙니다.

### 추가 로컬 시험 결과

- 앱 구현 대기 중 CLI 자체 동작을 확인하는 mock 기반 시험 5개를 추가했습니다.
- 추가 시험: `python -m pytest -q tests -k probe`
  → `5 passed, 40 deselected in 6.57s`
- 전체 회귀 시험: `python -m pytest -q tests`
  → `45 passed in 14.74s`

확인한 범위:
- session: 가짜 로그인 쿠키를 이용해 A·B·비로그인 역할 간 쿠키 분리와 같은 역할의 세션 재사용 확인.
- rate: 초당 1회 설정에서 HTTP 전송 시작 간격 확인(20ms 허용 오차).
- timeout: 응답 헤더 지연 시 오류 종료, 부분 결과 저장 및 후속 요청 중단 확인.
- 외부 대상 0건: 미승인 origin 직접 요청과 다른 origin으로의 리다이렉트에서 미승인 대상에 대한 전송 0건 확인.

모든 시험은 로컬 loopback 서버에서 수행했습니다.
실제 Django 로그인·세션 만료 및 AWS WAF 검증 결과는 아닙니다.

## 민수's comment · 2026-11-09~13 실행 가이드

- **월 오전** 요찬에게 URL·폼·인증/CSRF·로그 계약을 받습니다. **월 오후** #7의 빈 correlate와 외부 리다이렉트 오판을 재현합니다.
- **화 오전** 민수와 권혁민 폴더에서 `python -m pytest -q tests`를 실행합니다. 빈 결과는 종료 코드 2, 세 슬래시 외부 리다이렉트는 불일치, 같은 origin의 정상 로그인 이동은 일치가 기준입니다. **화 오후** 실패를 재검증하고 명령·기대값·실제값을 민수에게 넘깁니다.
- **수** 앱 SHA와 승인된 시험 주소를 받으면 실제 앱용 경로·입력을 맞춥니다. **목** 요찬·푸른과 정상 CRUD, 타인 글·CSRF 거부를 확인하고 공유·해제 사례를 맞춥니다. **금** 결과와 미검증 범위를 민수·요찬에게 인계합니다.
- **완료 기준** #7은 로컬 fixture 시험까지 기록합니다. 실제 대상에 요청하기 전 느린 302의 시간·크기 제한, HTTPS 인증·CSRF, 대상 승인과 앱·WAF 로그 연결을 확인합니다.
- **막히면** 앱·시험 주소가 없을 때 로컬 모의 서버와 fixture까지만 실행합니다. 로그가 부족한 건은 UNKNOWN으로 남깁니다.

[공용 일정·리뷰의 내 담당 항목](https://github.com/MinsooAhn02/Haven/blob/main/docs/팀_진행_및_리뷰.md#hyeokmin)

## 민수's comment · 2026-11-08 주간 점검

- #7은 11/07 `3855664`로 병합됐고 전체 pytest 51건과 main CI가 통과했습니다. 위 결과 기록 1회차 "로컬 검증 완료·PR 대기"를 "병합 완료(#7 `3855664`, 51 passed)"로 바꿔 주세요.
- 실행 가이드의 월 오후 재현·화 pytest/병합 판정은 이미 끝났습니다. 그 시간은 **실제 앱 대비**로 써 주세요: `cases_haven_*` fixture에서 앱 계약이 오면 바꿀 path·필드·CSRF 위치를 목록으로 정리하고, 느린 302의 시간·크기 제한을 확인합니다.
- 이 코멘트를 넣으면서 `Hyeokmin`을 최신 main(#14 `0876109`)으로 맞췄습니다. 작업 전에 `git pull` 해 주세요.


## 민수's comment · 2026-11-08 이번 주 배정 (11/09~13)

운영 방식이 바뀌었습니다. 날짜별 시간표 대신 **주력과 대기열**을 드립니다. **다 못 해도 괜찮아요.** 주력이 막히거나 끝나면 대기열로 넘어가고, 남은 건 매일 저녁 다시 나눕니다. 매일 끝나면 Discord에 오늘 상황 보고 부탁드립니다. 전체 현황은 main의 `TASK_TODO.html`(git pull 후 브라우저로 열기).
- **주력:** 1회차 시험 시나리오(정상 / 비로그인 / 타인 글 404 / CSRF 누락 403)를 fixture로 준비 + 느린 302의 시간·크기 제한 확인 → 앱 SHA를 받으면 실제 실행
- **대기열:** 공유·해제·비활성 시험 fixture(2회차) → 첨부 형식·크기·타인 다운로드 fixture(3회차)
- **⏳ 기다릴 것:** 실제 앱 실행은 요찬님 앱 SHA와 민수 실행 환경 필요. path·필드는 계약 오면 맞추기.


## 민수's comment · 2026-11-09 배정 갱신

AWS 운영 결정 추천안이 main `docs/AWS_운영결정.md`에 올라갔고, 현황판 `TASK_TODO.html`도 오늘 기준으로 바꿨습니다. 다 못 해도 괜찮고, 끝나면 Discord에 오늘 상황 보고 부탁드립니다.
- **주력:** 요찬님 `신요찬/앱계약.md` 3·4장 기준으로 1회차 fixture의 path·필드·CSRF 맞추기 + 결정 답변(#9 413/CSRF 우선순위, #10 중복 아이디 안내, #11 redirect 쿼리 제외 비교) → 느린 302 시간·크기 제한 확인
- **대기열:** 공유·해제·비활성 fixture(2회차) → 첨부 형식·크기·타인 다운로드 fixture(3회차)
- **⏳ 기다릴 것:** 실제 실행은 요찬님 코드·민수 실행 환경 필요

## 민수's comment · 2026-11-09 확대 배정 (AI 사용 전제)

다들 AI를 쓰니 일을 크게 잡았습니다. **이번 주(11/09~13)에 원래 1·2회차, 다음 주에 3·4회차**를 끝내는 게 목표예요. 다 못 해도 괜찮고, 위에서부터 하다가 막히면 다음 항목으로 넘어가세요. 다른 사람과 같이 정해야 하는 건 회의하지 말고 민수에게 물어보면 바로 정합니다. AWS 운영 결정은 확정됐습니다(main `docs/AWS_운영결정.md`). PR에는 실제로 돌린 명령·결과와 **일부러 실패시킨 거부 시험**을 꼭 붙여 주세요(AI 코드는 시험을 통과해도 틀릴 수 있어서). 매일 끝나면 Discord 상황 보고는 그대로 부탁드려요.

1. 앱계약 3·4장 기준 1회차 fixture path·필드·CSRF 맞추기 + 결정 #9·#10·#11 답변 + 느린 302 시간·크기 제한
2. 2회차 공유·해제·비활성 fixture + 3회차 첨부 형식·크기·타인 다운로드 fixture
3. **요찬님 PR마다 보안 점검** (인가 누락·IDOR·CSRF·경로 조작) → PR 코멘트로
4. 요찬님 코드로 로컬 실제 시험 → 목·금 AWS 첫 배포 후 같은 시험 재실행
5. (대기열) request_id 로그 대조 도구 → WAF Count 관찰 계획(어떤 규칙·어떤 요청·기대값)

- **화요일까지:** 저장소 루트에서 `powershell -ExecutionPolicy Bypass -File 안민수\dev-db-setup.ps1` 실행(Minsoo 브랜치, main 병합 후엔 main) → 로컬 PostgreSQL 16 + `haven_dev`. 끝에 `OK` 4줄이 나와야 하고, 비밀번호는 `%APPDATA%\postgresql\pgpass.conf`에만 있으니 공유하지 마세요
- **기다릴 것:** 실제 시험만 요찬님 코드 필요. fixture·점검 준비는 지금 가능

## 혁민's progress · 2026-11-09 (2회차 준비)

- 공유 전 접근 거부, 공유 후 읽기 허용·변경 거부, 공유 해제 후 접근 거부 fixture 준비.
- 소유자 비활성화 시 공유 대상 접근 차단 fixture 준비.
- 공유 대상 비활성화 후 기존 세션 재사용을 위한 수동 체크포인트 시험 준비.
- CLI는 승인된 대상과 요청 예산을 준수하며, 자동 계정 상태 변경은 수행하지 않음.
- 실제 Django 앱·DB·AWS WAF 보안 검증은 아직 미실행.

## 민수's comment · 2026-11-09 밤 · 이번 주 할 일 (11/10~13)

이번 주: 화 = 2회차 병합·AWS 구축, 수 = 첫 배포·3회차 시작, 목 = 3회차, 금 = 4회차·17:30 판정. 다음 주는 심화 점검·시연·보고서. 작업 전 항상 `git pull`. 전체는 `TASK_TODO.html`.

- **화:** `git pull` → `안민수/dev-db-setup.ps1` → fixture를 실제 앱(로컬)에 실행 + 저장형 XSS 실제 시험 → 결과 PR. 요찬 2회차 PR이 오면 보안 점검(공유받은 사람의 변경 거부, 해제 후 거부, 비활성 계정, 계정 관리 권한) → PR 리뷰로 남기기
- **수:** AWS 첫 배포 후 같은 fixture 재실행(로컬과 결과 비교)
- **목:** WAF Count 관찰 · 요청/WAF/앱 로그 request_id 대조 · 오탐 확인
- **금:** 결함 재검증 · WAF Block 전후 같은 조건 비교(HTTP 403만으로 WAF 차단 판정하지 않기)

## 민성's comment · 2026-11-11 저녁 · 바뀐 역할 반영 (조장 이민성)

팀장(조장)은 이민성이다(11/11 인수인계 완료). 안민수는 레포 admin 지원만 한다. 같이 정할 판단은 이제 민성에게 묻는다. 역할 표는 `docs/인수인계/02_역할_재배치.md`, 사람별 할 일은 `TASK_TODO.html`.

- **#51 점검:** 요찬 HTTPS 설정 보안 점검 결과를 PR #51에 코멘트나 승인으로 남긴다. 기록이 있어야 병합한다.
- **새로 맡음(목):** 실제 SG 읽기 수집 → AUD fixture 대조. 수집 명령은 민성 SG CLI(`이민성/`)를 쓰고, 민성은 명령만 제공한다.
- **브랜치에만 있는 작업:** 3단계 업로드 보안·부하 시험, 1~3단계 통합 시험 보고서는 PR로 올리면 조장이 확인 후 병합한다.
- **시험 대상:** `https://orchestration-haven.cloud`에 연결됐다(NET-01 통과). fixture origin을 바꿔 AWS 배포 후 재실행한다.
- **#45 리뷰 반영:** `start_verify.ps1`에 `HAVEN_UPLOAD_DIR`(임시 폴더) 추가.

## 민성's comment · 2026-11-12 · 4회차 추가 업무 (조장 결정)

- **WAF 분담(확정):** 혁민 = Web ACL·규칙·전용 로그 구성(Count 모드), Count 관찰(요청/WAF/앱 로그 대조·오탐 확인), Block 판단(어떤 규칙을 Block으로 전환할지 근거와 함께). 민성 = ALB 연결과 Block 적용. 보람 = 필요한 WAF 쓰기 권한(혁민에게는 Haven Web ACL 범위 안의 생성·수정·로그 설정).
- **일정:** WAF가 아직 없어 구축과 Count는 **4회차**로 옮겼고, 4회차는 **11/27까지 업무를 마무리하는 것이 목표**다. Block 판단과 전후 비교는 Count 결과가 나온 뒤 같은 4회차 안에서 한다. 선행 조건은 보람의 WAF 쓰기 권한이다.
- **SG 실제 점검:** 구민철이 실행·대조한다(도구 live 모드는 민성이 구현). 혁민은 AUD fixture와 판정 기준을 구민철에게 설명해 주면 된다.
- 기존 항목(WAF Count 관찰, Block 전후 비교, 로그 대조)은 그대로 두고 위 분담과 순서만 바뀌었다.

## 민성's comment · 2026-11-12 저녁 · 현재 상태와 할 일 (현황판 기준)

- **병합됨:** #62(3회차 통합 시험, AWS HTTPS 검증). #65로 로그 조회·EC2/WAF 권한이 기록됐다.
- **바뀐 분담(조장 결정):** WAF는 혁민 = Web ACL·규칙·전용 로그 구성(Count)·Count 관찰·Block 판단, 민성 = ALB 연결·Block 적용, 보람 = WAF 쓰기 권한. 4회차(11/27까지 마무리 목표). 실제 SG 읽기 수집·대조는 구민철이 실행하고 혁민은 AUD fixture와 판정 기준을 설명한다.
- **지금 할 일**
  1. 로그 조회 시험: `hyeokmin` 계정 로그인, 비밀번호 변경, MFA 등록(본인), 로그 목록·읽기·검색 성공, `ssm:StartSession` 거부, EC2·WAF 조회. 로그 그룹 `/haven/web`은 민성이 수집을 확인했다(#73 병합 대기).
  2. 구민철에게 AUD fixture와 판정 기준 설명(SG 점검 도구 live 모드는 민성이 구현, 구민철 3회차 11/23~).
  3. 보람의 WAF 쓰기 권한이 오면 WAF 구성(Count) 시작.
  4. 개인 항목: 저장형 XSS 실제 시험, AWS 배포 후 fixture 재실행, request_id 로그 대조 도구.

## 민성's comment · 2026-11-12 밤 · 오늘 한 일과 남은 일 (현황판 기준)

- **병합됨:** #80(WAF Web ACL Count 구성과 로그 연동), #79 짝 점검(명백한 취약점 없음, 병합 가능). #80은 정리된 출력 요약이 첨부됐고 원본은 아니다. 샘플 요청 off는 의도로 확인했다. 조장이 #77에서 `DeleteWebACL`(`haven-*`)을 승인했다.
- **#80 후속(조장 코멘트 참고)**
  1. TODO의 "IAM 권한 검증(CloudWatch·EC2·WAF 조회, SSM 접속 거부)" 체크 항목의 근거(명령과 결과)를 남긴다.
  2. 기존 항목 "발견 문제의 수정 후 재시험과 정상 회귀를 확인한다"가 새 목록에서 빠졌다. 일부러 뺀 것이면 이유를, 아니면 다시 넣는다.
  3. 다음 확인 때 `get-web-acl` 원본(쓴 명령 포함)을 붙인다.
- **남은 일(순서대로)**
  1. 로그 조회 시험: `hyeokmin` 계정 로그인(CLI `aws login` 실제 성공은 아직 미확인), 비밀번호 변경, MFA 등록, 로그 목록·읽기·검색, `ssm:StartSession` 거부, EC2·WAF 조회.
  2. 민성이 Web ACL을 ALB에 연결한 뒤 WAF Count 로그 수집·오탐 분석, WAF·Nginx·Django 로그 상관분석. ALB 연결 전에는 요청 동작을 볼 수 없다.
  3. 로그인 실패 제한 구현 PR 점검(요찬 PR이 오면). 안 7장 계산으로는 요청 CLI 묶음이 한 번에 로그인 실패 9번(같은 아이디 최대 2번)이라, AWS에서 15분 안에 3번째로 다시 돌리면 계정 기준 5번에 걸려 429가 난다. 반복할 때는 15분 간격을 둔다.
  4. AWS 시험 참여: 분산 시험(서로 다른 IP의 팀원 3명 이상)과 IP 기준 시험(요청 CLI로 천천히).
  5. 구민철에게 AUD fixture와 판정 기준 설명, 개인 항목(저장형 XSS 실제 시험, AWS 배포 후 fixture 재실행, request_id 로그 대조 도구).

## 민성's comment · 2026-11-13 · 완료·미완료 정리 (조장)

**완료 (저장소 근거 있음)**
- WAF Count 탐지·마스킹·연결 확인(#97·#100): SQLi·XSS·PROPFIND Count, 가짜 인증 헤더 REDACTED, 콘솔에서 연결 확인, `get-web-acl` 원본 제출
- 로그 조회 시험 중 일부(#97): 로그 조회·읽기·검색, EC2·WAF 조회 성공, `ssm start-session` 거부
- #88 로그인 실패 제한 점검(PR 코멘트)

**구두 확인 (저장소 근거 없음)**
- 앱 요청 로그의 식별자 3개 구조 확인(디스코드 15:38)
- WAF `requestId` = 앱 `trace_id`(디스코드 15:43)

**미완료·부분 완료 (이 TODO에 반영해 주세요)**
1. **로그 조회 시험 → 부분 완료로 정정.** 비밀번호 변경·MFA 등록 근거가 없습니다. 했다면 시각과 확인 방법(콘솔 화면 또는 `list-mfa-devices` 결과, ARN·계정 번호는 가림)을 남겨 주세요. 근거가 들어오면 현황판을 완료로 바꿉니다.
2. **WAF `requestId` = 앱 `trace_id`:** 같은 요청의 WAF 로그와 앱 로그 한 줄씩(값은 앞 8자리만 또는 가림)을 남겨 주세요. `/healthz`는 앱 로그에서 빠지므로 `/accounts/login/` 같은 다른 경로로 확인합니다.
3. **Nginx 요청 식별자 기록(16:46 조장 확정):** 구현 민성 → 재검증 혁민, 기한 11/27. 기록할 식별자는 `X-Amzn-Trace-Id`·`X-Haven-Request-ID`·응답 `X-Request-ID`이고 클라이언트가 정하는 값은 길이·형식을 제한합니다. 재검증은 WAF → Nginx → 앱 로그가 같은 ID로 이어지는지 확인합니다.
4. **기존 남은 일:** TODO 낡은 줄 정리, CLI CloudWatch 연동, Burp 수동 점검(자동 스캔·Intruder는 피함), WAF Block 판단(11/27), 로그인 제한 배포 뒤 분산 시험.

## 혁민's reply · 2026-11-16

조장 11/13 "미완료·부분 완료" 항목에 대한 답변입니다.

1. **로그 조회 시험:** 조회·읽기·검색, EC2·WAF 조회, `ssm start-session` 거부는 위 "IAM 권한 검증 결과 (2026-11-13)"에 근거가 있습니다.
   - MFA 등록: `aws iam list-mfa-devices --user-name hyeokmin --profile hyeokmin --query "MFADevices[].EnableDate" --output json --no-cli-pager` → `2026-11-12T06:51:24+00:00`(KST 15:51) 1건 확인(11/16 조회, ARN 미출력)
   - 비밀번호 변경: 첫 콘솔 로그인 때 바로 변경. 정확한 시각은 기록하지 않았고, 계정 전체가 포함되는 자격 증명 보고서는 조회하지 않았습니다.
2. **WAF ↔ 앱 식별자:** 위 "AWS 정리·로그 상관분석 검증 (2026-11-16)"에 같은 요청(`GET /posts/13/`)의 WAF·앱 로그 대조를 붙였습니다. 11/13 구두 보고("WAF `requestId` = 앱 `trace_id`")를 정정합니다. CLI처럼 클라이언트가 `X-Amzn-Trace-Id`를 보낸 요청에서는 WAF `requestId`가 다른 값이었고, 연결 키는 WAF 로그에 기록된 `X-Amzn-Trace-Id` 헤더의 Root입니다. 이 Root는 앱 `trace_id`와 일치했습니다.
3. **Nginx 요청 식별자:** 민성님 구현 후 WAF → Nginx → 앱이 같은 ID로 이어지는지 재검증합니다(기한 11/27). `X-Amzn-Trace-Id`도 클라이언트가 정할 수 있는 값이므로 `X-Haven-Request-ID`와 함께 길이·형식 제한이 필요합니다.
4. **요청 CLI의 CloudWatch 자동 수집·대조:** `collect-logs`·`correlate-cloudwatch`로 구현했고, 11/16 실제 AWS에서 11건 모두 MATCHED를 확인했습니다. 낡은 줄(결과 기록 4회차 행, 3·4회차 체크 항목)도 정리했습니다. 해당 코드는 PR 전입니다.

## 민성's comment · 2026-11-16 오후 · 병합 정리와 남은 일

- **병합됨:** #119(20번 정책에 `/haven/db` 로그 읽기 `ReadHavenDBLogEvents` 추가, 보람이 `get-policy-version` v3와 main JSON이 같다고 확인).
- **부탁:** `/haven/db` 로그 조회·필터가 실제로 되는지 확인해 결과를 남기고, #116 짝 리뷰(db-1 로그 기록 범위: 접속·종료 기록, 접속 IP 포함 여부)도 의견을 남긴다. 접속 IP는 `10.x.x.x`처럼 가려서 적는다.
- **11/17:** 로그인 실패 제한 2차 시험(요찬 안내)에서 분산·IP 축 시험에 참여한다. 요청 CLI는 15분 간격으로 천천히 돌린다.
- **참고:** `권혁민/waf/`의 원본 JSON 2개에 계정 번호 전체가 있다. 가릴지는 조장이 정해서 알린다. 기존 남은 일(MFA 근거, 낡은 줄 정리 등)은 11/13 코멘트 그대로다.

## 혁민's reply · 2026-11-17

1. **`/haven/db` 로그 조회·필터:** #119 반영 전에는 `/haven/db`의 FilterLogEvents가 거부됐고, 반영 후 `hyeokmin` 프로필로 조회·필터에 성공했습니다(11/16). 확인한 내용: 앱 서버(`10.x.x.x`)에서 DB 계정 `haven_app`·DB `haven`으로 접속, `scram-sha-256` 인증, 해당 연결의 TLSv1.3, 접속·인증·종료와 세션 시간 기록.
   - 참고: 과거에 발생한 DB 로그가 최근 CloudWatch 이벤트 시각으로 들어온 예가 있었습니다. DB 로그를 요청별 상관분석에 넣게 되면 메시지 안의 PostgreSQL 발생 시각을 기준으로 삼아야 합니다. 현재 요청 CLI의 자동 수집 대상은 WAF와 `/haven/web`뿐입니다.
2. **#116 짝 리뷰:** 11/16 12:12(KST) PR 댓글로 남겼습니다([#116 리뷰 댓글](https://github.com/MinsooAhn02/Haven/pull/116#issuecomment-6906232626)). 판단: 접속·종료·접속 IP 기록은 DB 접속 출처와 세션 상태 점검 목적에 적절하고, WAF·Django 로그와 함께 쓰는 현재 구성에서 전체 SQL 로깅은 필수가 아닙니다. SQL 실행 내용·데이터 변경 이력 감사까지는 지원하지 않습니다.
3. **WAF Count 재시험:** 위 "WAF Count 재시험 (2026-11-17)"에 결과를 남겼습니다. 요청 CLI로 결과 파일·로그·상관분석을 저장했고 4건 모두 PASS입니다.
4. **로그인 실패 제한 2차 시험:** 팀 공지에 따라 중간 발표 이후로 연기되어 아직 참여하지 않았습니다.
5. **`권혁민/waf/` 원본 JSON의 계정 번호:** 조장 결정을 기다립니다. 가리기로 하면 반영하겠습니다.

## 민성's comment · 2026-11-18 저녁 · Nginx 재검증과 정리

- **병합됨:** #130(`1dc05a9`)과 함께 계정 번호 가림도 끝났다(`권혁민/waf/` 원본 JSON 2개와 TODO 명령이 `${ACCOUNT_ID}`로 바뀌었다). 11/17 코멘트의 "결정을 기다립니다"는 처리됐다. 로그인 실패 제한 2차 시험은 요찬이 PC·휴대폰으로 진행했고 요청 CLI는 쓰지 않았다(#140).
- **Nginx 요청 식별자 재검증(기한 11/27):** #143은 조장이 리뷰 전에 병합했고 11/18 17:45 운영 적용을 마쳤다. 접근 로그 `trace= rid= cid= run= client= rt=` 중 `trace`·`rid`·`cid`가 앱 로그의 `trace_id`·`request_id`·`client_request_id`와 같은 것을 1건 확인했다(`X-Haven-Request-ID: minsung-test-1`, 17:46 KST, trace `1-6afd65d2-004c498b686b533b17a7907b`, `/accounts/login/`). WAF 로그에서 같은 trace가 찾아지는지 확인하고 #143 코드를 리뷰해 결과를 남긴다.
- **남은 것:** 누적 Count 로그 오탐 분석, WAF Block 판단. WAF 로그에는 11/18 16:07~16:42 로그인 시험의 접속 IP가 남아 있으니 WAF 결과를 공유할 때 그 항목은 가린다.

## 혁민's reply · 2026-11-19

조장 11/18 저녁 코멘트에 대한 답변입니다.

1. **Nginx 요청 식별자 재검증:** 완료했습니다. 위 "Nginx 요청 식별자 재검증 (2026-11-19, #143)"에 결과를, #143 PR 댓글에 리뷰 의견을 남겼습니다. 요청 40건이 WAF·Nginx·앱 로그에서 모두 같은 요청으로 이어졌습니다.
2. **누적 Count 로그 오탐 분석:** 위 "누적 Count 로그 분석 (2026-11-18)"에 남겼습니다. 첨부 업로드가 `SizeRestrictions_BODY`에 걸리는 오탐을 확인했습니다. 아래 두 가지는 팀 확인이 필요합니다.
   - 11/16 11:16~11:35, 11/17 12:42(KST) 로그인·회원가입 POST 8건이 `SQLi_BODY`에 걸렸습니다. 이때 SQL 문자열을 일부러 넣은 시험이었는지 알려 주시면 SQLi 규칙 Block 판단에 반영하겠습니다.
   - User-Agent 없이 `/`·`/posts/`·`/accounts/login/`을 주기적으로 요청하는 팀 점검 스크립트가 있는지 확인 부탁드립니다. Common 규칙 Block 시 403을 받습니다.
3. **WAF Block 판단:** 업로드 시험을 AWS에서 실행해 `SizeRestrictions_BODY` 오탐을 요청 CLI 결과로 재현한 뒤 근거 문서로 정리하겠습니다(11/27).
4. **MFA 근거:** 11/17 답글 1번에 CLI 근거가 있습니다(`list-mfa-devices` → `2026-11-12T06:51:24+00:00`). 근거가 없는 것은 비밀번호 변경(본인 진술)입니다. 현황판·운영기록의 "MFA 근거 없음" 정정 부탁드립니다.
5. **`aws login`(CLI 로그인):** 11/16 이후 `aws login --profile hyeokmin` → `aws sts get-caller-identity`로 여러 번 성공했습니다(CloudWatch 수집에 사용).
6. **로그인 실패 제한 시험 참여:** 2차 시험은 요찬님이 PC·휴대폰으로 끝냈다고 하셔서, 제 참여 항목을 닫아도 되는지 확인 부탁드립니다.
7. **인스턴스 ID 가림:** `권혁민/tests/test_cloudwatch_app_prefix.py`의 로그 스트림 이름은 시험용 값이라 가짜 ID로 바꿔도 시험이 그대로 통과합니다. 한 번에 가리기로 정하시면 바로 반영하겠습니다.
8. **접속 IP:** 누적 분석과 Nginx 재검증 기록에는 접속 IP를 넣지 않았습니다.