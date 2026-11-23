# Haven CLI

**상태:** 로컬 Django 1~3회차 통합 시험 완료, AWS 운영 사이트 시험·CloudWatch 로그 자동 대조 완료, WAF Count 관찰과 Block 1~3단계 전환·전후 비교 완료(2026-11-20). 전체 결과는 [`시험결과/최종_시험결과.md`](시험결과/최종_시험결과.md)

## 1. 포함 파일

```text
권혁민/
├── request_verify.py             # 요청 재현(run)·로그 수집(collect-logs)·대조(correlate, correlate-cloudwatch) CLI
├── mock_server.py                # 로컬 가상 서버·가상 WAF/앱 로그
├── start_verify.ps1              # 로컬 Django 시험 서버 실행 파일
├── pdf_upload_stress_local.py    # 로컬 PDF 업로드 성능 비교
├── README.md                     # 사용법·입출력 형식·검증 범위
├── TODO.md                       # 회차별 진행 상태·검증 결과·조장 코멘트
├── Basic test plan.md            # 명세 ID별 기본 기능·보안 시험표
├── Attack test plan.md           # 공격 유형별 시험 계획(SEC-01~60)
├── fixtures/
│   ├── allowlist_local.json      # 로컬 시험 대상 허용목록
│   ├── allowlist_aws.json        # AWS 운영 사이트 허용목록
│   ├── cases_local.json          # 로컬 mock·CLI 회귀 시험
│   ├── cases_haven_template.json # 로컬 Django 1~3회차 통합 시험표
│   ├── cases_basic_*.json        # 로컬 기본 시험(공유·업로드·용량·본문 크기 등)
│   ├── cases_*_inactive.json     # 소유자·수신자 비활성(수동 체크포인트)
│   ├── cases_haven_aws.json      # AWS 게시글·첨부·공유·해제 스모크
│   ├── cases_aws_*.json          # AWS 묶음(보안 회귀·업로드·WAF 오탐/미탐·헤더·세션/첨부·남은 SEC)
│   ├── block_expectations.json   # WAF Block 단계별 기대값 프로필
│   ├── waf_*_variants.json 등    # 입력 변형(variants)·POST 입력
│   └── sample_*                  # 무해한 첨부 샘플(TXT·PDF)
├── tests/                        # CLI 단위·통합 시험(pytest)
├── waf/                          # WAF 구성 기록과 Block 판단안(WAF_Block_판단.md)
├── 시험결과/                      # 날짜별 시험 보고서와 최종 시험 결과
└── requirements.txt              # 실행·테스트 의존성
```

`fixtures/`는 주요 파일만 표시했다. Haven 앱 연동용 케이스는
실제 URL·폼 계약과 시험 데이터에 맞춰 확인·조정한 뒤 실행한다.

> **중요:** `mock_server.py`의 `synthetic_fixture=true` 로그는 AWS WAF 로그가 아니다. 이 로그로 PASS가 나오더라도 **CLI의 로그 상관분석이 정상 작동한다는 뜻만** 가진다. Django 취약점 부재, AWS WAF 차단 성공 또는 실제 침투시험 결과를 의미하지 않는다.

## 2. 설치와 로컬 실행 (VS Code 터미널 / PowerShell)

프로젝트 루트에서 `권혁민` 폴더로 이동한다. Python 3.10 이상 권장.

```powershell
cd 권혁민
python -m pip install -r requirements.txt
python -m pytest -q tests
```

**터미널 1 — 가상 서버 실행**

```powershell
python mock_server.py --port 8765 --waf-log mock_waf.jsonl --app-log mock_app.jsonl
```

**터미널 2 — 고정 테스트 실행** (테스트 출력 폴더 이름은 실행할 때마다 다르게 지정)

```powershell
python request_verify.py run --target http://127.0.0.1:8765 --allowlist fixtures/allowlist_local.json --cases fixtures/cases_local.json --fixture-dir fixtures --output-dir output_run_01 --rate 5
```

실행 직후 WAF·앱 로그와 대조하지 않은 상태이므로 **종료 코드 3(`UNKNOWN`/`PENDING_LOG`)이 정상**이다. HTTP 응답을 받았다고 곧바로 WAF 차단/앱 보안 PASS로 기록하지 않는다.

**터미널 2 — 가상 로그 상관분석**

```powershell
python request_verify.py correlate --run-json output_run_01/results.json --waf-log mock_waf.jsonl --app-log mock_app.jsonl --output-dir output_corr_01
```

별도 폴더에 `correlated_results.json`과 `correlated_summary.csv`가 생성된다. 정상 fixture만 있는 예제이므로 **correlate 종료 코드 0**이 기대된다. 원본 `results.json`은 덮어쓰지 않는다.

**APP-11 크기 경계 시험:**

```powershell
python request_verify.py run --target http://127.0.0.1:8765 --allowlist fixtures/allowlist_local.json --cases fixtures/cases_body_boundary.json --fixture-dir fixtures --output-dir output_body_01 --rate 5
python request_verify.py correlate --run-json output_body_01/results.json --waf-log mock_waf.jsonl --app-log mock_app.jsonl --output-dir output_body_corr_01
```

`response_summary.request_body_bytes`가 **8191, 8192, 8193**이고 모의 응답이 **302, 302, 413**인지 확인한다. 실제 Django 및 Nginx의 크기 정책은 별개 시험 대상이다.

### 실제 Django 로컬 시험

`start_verify.ps1 -Mode Reset`으로 `haven_verify` DB와 전용 업로드 저장소를 초기화한 뒤 Django 서버를 실행한다.

재시험 시에는 기존 서버를 종료하고 다시 초기화한다.

```powershell
.\start_verify.ps1 -Mode Reset
```

## 3. Case JSON 계약

명세에서 요구한 루트/케이스 필드를 유지하고, 시험 편의를 위해 `verification_mode`와 선택 필드 `phase`를 추가하였다.

```json
{
  "schema_version": 1,
  "suite_id": "test-suite-001",
  "suite_kind": "regression",
  "cases": [
    {
      "case_id": "APP-03",
      "category": "authorization",
      "method": "GET",
      "path": "/posts/1/",
      "auth_role": "member_c",
      "input_reference": null,
      "expected_app": {"http_status": 404},
      "expected_waf": "NOT_APPLICABLE",
      "max_requests": 1,
      "verification_mode": "manual_required",
      "note": "ID 1은 member_a 소유, member_c 미공유 기록이어야 한다"
    }
  ]
}
```

`auth_role`은 `anonymous`, `member_a`, `member_b`, `member_c`, `operator` 중 하나. `expected_waf`는 `ALLOW`, `BLOCK`, `COUNT`, `NOT_APPLICABLE` 중 하나. `http_status`는 정수 1개이며 추가 `expected_app` 선택 속성은 `redirect_path`, `body_bytes`, `sha256`, `headers_contain`(예: `{"Cache-Control":"no-store"}`).

- `verification_mode="manual_required"` (**기본값**): HTTP 응답과 로그가 일치하더라도 DB·파일·브라우저·권한 검증을 자동으로 확정할 수 없으므로 최종 결과를 `UNKNOWN`으로 유지한다. **공격 시험 및 SEC 테스트에 권장**한다.
- `verification_mode="http_only"`: 검증 범위가 HTTP 상태·헤더·길이·SHA-256 등으로 충분한 명시적 케이스용. 로그까지 정상 연결되면 PASS 가능. **보안 공격 전체의 성공/실패를 HTTP 코드만으로 판단한다는 뜻이 아니다.**
- `max_requests`: 케이스의 **실제 시험 요청**에 대한 상한(현재 케이스당 1회 전송). 로그인과 CSRF 준비는 **전역 총 요청 수/속도/시간 한도**에 함께 포함한다.
- 모든 상태 변경은 이미 존재하는 **가상 시험 기록·계정**으로만 수행하고, 삭제·공유 등 케이스의 순서와 DB 사전 조건은 반드시 명시한다.

### POST payload fixture

`input_reference`는 `--fixture-dir` 아래 **상대 JSON 파일**이다. 파일 이름, 내용, MIME은 의도적으로 무해한 고정 fixture로만 작성한다. 세션·실제 비밀번호·토큰은 넣지 않는다.

```json
{
  "csrf_mode": "valid",
  "origin_mode": "absent",
  "fields": {"title": "시범 제목", "body": "시범 본문"}
}
```

- `csrf_mode`: `valid`(세션의 CSRF 토큰), `missing`(토큰 제외), `invalid`(고정 잘못된 토큰).
- `origin_mode`: `same`(기본), `absent`(Origin 헤더 생략), `foreign`(고정 `https://attacker.invalid`를 **Origin 헤더 값**으로만 사용).
- `pad_form_body_to`: 숫자 1~8193. `body` 문자열 필드에 ASCII 패딩을 추가해 **실제 form-encoded POST Body가 목표 바이트 수**가 되게 함. 파일 multipart와 동시 사용하지 않음. CSRF 인코딩 오버헤드 포함.
- `file`: `{ "field_name":"attachment", "local_fixture_path":"sample.txt", "filename":"harmless.txt", "content_type":"text/plain" }`. 실제 파일 내용은 결과에 저장하지 않음.
- 업로드 경계 시험은 **전체 multipart 직렬화 길이**를 `response_summary.request_body_bytes`로 확인할 수 있지만, 현재 `pad_form_body_to`는 multipart 정확한 크기 자동 맞춤 기능이 아니다.
- GET payload는 `null`. GET의 고정 쿼리 입력은 상대 `path`에 포함한다.

**안전한 대상 검증:** `--target`은 `https://host[:port]` 또는 **명시적 승인된** `http://127.0.0.1:port` 같은 loopback만 지원한다. `allowlist.json`에 **정확한 원점(scheme+host+port)** 이 있어야 하며, 다른 origin·절대 URL·`//` path·자동 redirect는 거부된다. `requests`의 TLS 인증서 검증 해제는 제공하지 않는다. 입력 fixture 경로·심볼릭 링크가 허용 루트 밖을 가리키면 중단한다.

## 4. CLI 한도와 출력

| 옵션 | 기본값 | 최대값 |
|---|---:|---:|
| `--timeout` | 10초 | 30초 |
| `--max-requests` | 100 | 1000 |
| `--rate` | 초당 1 | 초당 5 |
| `--max-duration` | 300초 | 900초 |
| `--max-response-bytes` | 2097152 | 2097152 |

### 회차별 케이스 선택

`run`에 `--phase 1`을 지정하면 케이스의 `phase`가 1인 항목만
파일에 정의된 순서대로 실행한다. 옵션을 생략하면 전체 케이스를 실행한다.

- 허용 값: 1, 2, 3, 4
- 회차 선택 시 모든 케이스에 `phase`가 있어야 한다.
- 선택한 회차에 케이스가 없으면 요청 전 오류로 종료한다.
- 결과 JSON에 selected_phase, total_suite_cases,
  selected_cases, excluded_cases를 기록한다.
- 제외된 다른 회차 케이스는 미실행 오류로 계산하지 않는다.

`cases_haven_template.json`에 1~3회차 시험을 통합했다.

- 논리 케이스 153개, 실제 HTTP 시험 197건
- 당시 pytest 251개 통과 (PR #62 리뷰 M1~M8 보강, 11/20 기준 전체 511개)
- 로컬 Django 시험 HTTP 기대값 197/197 일치, 복구 완료
- 이 파일은 DB를 초기화한 로컬 환경 기준이다. AWS 운영 사이트는 아래 "AWS 운영 시험"의 `cases_aws_*.json`으로 시험했다

AWS에서는 `cases_haven_auth_smoke.json`을 우선 실행한다. 전체 `cases_haven_template.json`은 시험 계정·게시글 ID와 DB 초기 상태를 확인한 후 실행한다. 해당 시험에는 데이터 변경·삭제가 포함된다.

### 계정 비활성화 수동 체크포인트

`--manual-checkpoints` 옵션은 계정 상태 변경 등
시험 중 사람의 개입이 필요한 경우에만 사용한다.

SH-06 시험은 다음 순서로 진행한다.

1. 활성 계정 member_b로 로그인한다.
2. 공유받은 P1에 접근하여 정상 조회를 확인한다.
3. CLI가 체크포인트에서 중단되면 별도 관리자 화면에서
   member_b를 비활성화한다.
4. 터미널에 `DEACTIVATED`를 입력한다.
5. 기존 세션을 유지한 채 P1과 공유 목록에 재접근한다.

실행 예시:

```cmd
python request_verify.py run --target https://YOUR-APP-HOST --allowlist allowlist.json --cases fixtures/cases_member_inactive.json --fixture-dir fixtures --output-dir output_member_inactive --manual-checkpoints
```

주의사항:

- 옵션이 없으면 체크포인트가 필요한 시험은 실행 전에 거부한다.
- CLI는 계정을 직접 비활성화하지 않는다.
- 확인 문자열 입력만으로 실제 계정 상태 변경이 증명되지는 않는다.
- 실제 비활성 여부와 접근 거부는 Django/DB에서 별도로 검증한다.
- 전체 요청 수·속도·실행 시간 제한은 계속 적용된다.
- 시험은 승인된 테스트 환경과 가상 계정에서만 수행한다.

### 인증과 결과 기록

--prompt-seed-password를 통해 공통 비밀번호 1회 입력 및 역할별 세션을 재사용한다.

인증된 role이 있으면 최초 실행 시 username과 비밀번호를 **대화형**으로 입력받는다. 비밀번호는 화면에 표시하지 않는다. 각 role의 쿠키와 CSRF는 메모리 세션에만 유지하며, 기존 `accounts/login/` 경로의 실제 필드/동작은 신요찬 담당자와 합의해야 한다. 현재 로컬 mock는 실제 Django 인증이 아니며 가상 요청 동작만 구현한다.

출력에는 명세 필수 필드인 `run_id`, `request_id`, `case_id`, UTC 시각, 응답시간, HTTP status, redirect 대상, `expected_app`, `expected_waf`, `app_observed`, `waf_action`, `rule_id`, `waf_verdict`, `app_validity`, `transport_status`, `correlation_status`, `evidence_path` 등을 포함한다. `X-Haven-Request-ID`와 `X-Haven-Run-ID`를 요청 헤더에 넣어 대응 로그에서 식별한다. **응답 본문 원문·다운로드 파일·비밀번호·세션/CSRF 토큰은 출력하지 않는다.**

로그와 상관분석 하기 전 `waf_verdict=UNKNOWN`, `correlation_status=PENDING_LOG`; 로그 누락/중복/시각 충돌 시 `UNRESOLVED` 및 `UNKNOWN`이다. `run`에서 확인한 HTTP 코드만으로 WAF의 진짜 차단으로 판정하지 않는다. **Ctrl+C, 요청 초과, 네트워크/인증 준비 실패**는 부분 기록을 남기고 중단한다.

### 종료 코드

- `0`: 증거가 충분하고 자동 확인 조건과 모두 일치
- `1`: 확인된 기대 조건 불일치(FAIL)
- `2`: 입력/실행/준비/출력 오류 또는 중단(ERROR)
- `3`: 근거 미확정·로그 대기·수동 검증 필요(UNKNOWN)

우선순위는 **2 > 3 > 1 > 0**. Windows PowerShell에서는 직후 `$LASTEXITCODE`로 확인할 수 있다.

### 상관분석용 JSONL 최소 필드

```jsonl
{"run_id":"실제-run-id","request_id":"실제-request-id","timestamp_utc":"2026-11-06T00:00:00Z","action":"ALLOW","rule_id":"example"}
{"run_id":"실제-run-id","request_id":"실제-request-id","timestamp_utc":"2026-11-06T00:00:00Z","http_status":200,"observed":true}
```

첫 줄 형식은 WAF 로그 파일에, 두 번째 줄 형식은 앱 로그 파일에 각각 기록한다. 이는 **필드 예시**다. 실제 값은 실행 결과에 발급된 요청 ID와 해당 시각이어야 한다.

AWS WAF의 원본 JSONL은 `httpRequest.headers`의 `X-Haven-Request-ID`, `timestamp`(밀리초), `action`, `terminatingRuleId`, `nonTerminatingMatchingRules`를 읽는다. 실환경에서는 로깅 설정/RedactedFields로 상관 ID가 **실제로 제공되는지** 먼저 확인해야 한다. Django 앱 구조화 로그에도 해당 ID·시간·처리 상태의 기록이 필요하므로 신요찬 담당자와 협의해야 한다. 타임스탬프는 요청 시각 기준 ±120초 범위만 연결하고 원본 결과는 덮어쓰지 않는다.

### AWS Trace ID 기반 실제 로그 상관분석

실제 Django 및 AWS WAF 로그는 `X-Amzn-Trace-Id`의
`Root` 값을 기준으로 연결한다.

- CLI는 각 시험 요청에 고유한 Trace Root를 생성한다.
- ALB가 `Self`를 추가하더라도 `Root`만 추출하여 비교한다.
- Django 로그는 `request_id`, `ts`, `status` 필드를 사용한다.
- AWS WAF 로그는 `httpRequest.headers`의
  `X-Amzn-Trace-Id`, `timestamp`, `action`을 사용한다.
- 로그가 누락되거나 중복되거나 식별자가 일치하지 않으면
  `UNKNOWN`으로 남긴다.
- 기존 `X-Haven-Request-ID` 비교는 과거 결과 및
  `synthetic_fixture=true` 로컬 mock과의 호환성에 사용한다.

실제 Django·AWS WAF 로그를 연결하려면 각 시스템에서
Trace ID가 정상 전달되고 로깅되는지 확인해야 한다.
로그의 Root 일치만으로 보안 시험 PASS가 확정되는 것은 아니다.

### AWS 운영 시험 (2026-11-16~)

운영 DB를 초기화하지 않으므로 AWS용 묶음(`cases_haven_aws.json`, `cases_aws_*.json`)은 로컬 묶음과 다르게 만든다.

- 고정 글 번호 대신 시험 중 A가 글을 만들고 응답에서 ID를 얻는다(`capture_post_id` → 뒤 케이스의 `post_reference`). 첨부·공유 ID도 같은 방식이다(`capture_attachment_id`·`attachment_reference`, `share_reference`·`share_post_reference`).
- 시험이 만든 글·공유·첨부는 `cleanup_cases`로 지우고 상세 주소 404로 확인한다(정리 검증은 HTTP 수준, DB·파일 물리 삭제는 확인하지 않음).
- 소유자가 아닌 계정의 변경 요청은 기대 결과가 404일 때만 허용한다. 비로그인 가입은 400을 기대할 때만 허용한다.
- 고정 시험 계정은 `member_a`·`member_b`·`member_c`이고, 로그인 정보는 실행할 때 화면에 표시하지 않고 입력한다.

**실행 순서** (작업 디렉터리 `권혁민/`, 결과는 저장소 밖 또는 `output/` 아래에 두고 커밋하지 않는다)

```cmd
python request_verify.py aws-check --profile hyeokmin --region ap-northeast-2 --expected-account ${ACCOUNT_ID}

python request_verify.py run --target https://orchestration-haven.cloud --allowlist fixtures/allowlist_aws.json --cases fixtures/cases_aws_upload.json --fixture-dir fixtures --output-dir output/aws_upload_01 --max-requests 150 --max-duration 400

python request_verify.py collect-logs --run-json output/aws_upload_01/results.json --profile hyeokmin --region ap-northeast-2 --expected-account ${ACCOUNT_ID} --output-dir output/aws_upload_logs_01

python request_verify.py correlate-cloudwatch --run-json output/aws_upload_01/results.json --logs-dir output/aws_upload_logs_01 --expected-account ${ACCOUNT_ID} --output-dir output/aws_upload_corr_01
```

| 명령 | 하는 일 |
|---|---|
| `aws-check` | AWS 프로필 인증과 프로젝트 계정 일치 확인(`--expected-account`) |
| `run` | 승인된 케이스를 순차 실행. 요청마다 고유 Trace Root를 붙인다 |
| `collect-logs` | 실행 시간 범위(앞뒤 `--padding-seconds`, 기본 120초)의 WAF·앱 CloudWatch 로그 수집 |
| `correlate-cloudwatch` | 수집한 로그에서 이 실행의 요청만 골라 Trace Root로 대조 |
| `recover` | 중단된 AWS 시험의 정리 계획 확인(`--dry-run`)과 실행(`--apply`) |
| `inspect-accounts` | 관리자 로그인 뒤 시험 계정 ID·활성 상태 조회(`--username` 반복) |

- 실행 직후 로그가 아직 도착하지 않았으면 `UNRESOLVED`가 나온다. 몇 분 뒤 `collect-logs`부터 다시 한다.
- 계정 번호는 명령에 직접 쓰고, 문서·출력 파일을 저장소에 올리지 않는다(`${ACCOUNT_ID}`는 자리 표시).

**AWS 묶음에서 추가로 쓰는 케이스 필드**

| 필드 | 뜻 |
|---|---|
| `request_headers` | 비로그인 GET에서 허용된 헤더만 바꾼다(ASCII, 256자 이하). `User-Agent: null`이면 User-Agent를 보내지 않는다 |
| `session_fixation_probe` | 로그인 전에 가짜 세션 쿠키를 심고, 로그인 뒤 교체 여부와 쿠키 속성만 기록한다(값은 기록하지 않음) |
| `logout_then_reuse` | 로그아웃한 뒤 이전 세션 쿠키로 다시 요청한다 |
| `capture_attachment_id` / `attachment_reference` | 업로드 전후 첨부 목록을 비교해 새 첨부 ID를 얻고 뒤 케이스에서 쓴다 |
| `share_post_reference` | 다른 글의 공유 ID를 해제 주소에 섞는다 |
| `input_reference`의 `variants` | 한 케이스를 입력 변형(P01, P02 …)마다 따로 실행한다. 변형 수가 `max_requests`보다 많으면 실행 전에 오류로 멈춘다 |

### WAF Block 전후 비교

같은 묶음을 Block 단계마다 다시 실행할 때 기대값 프로필을 쓴다.

```cmd
python request_verify.py run ... --expect-profile fixtures/block_expectations.json --block-stage 2
```

- 프로필에 적힌 케이스는 해당 단계에서 `expected_waf=BLOCK`, HTTP 403을 기대한다. 나머지는 `ALLOW`와 원래 앱 응답을 기대한다.
- 단계는 누적이다(1 KnownBadInputs → 2 SQLi → 3 Common). 기대 막힘 수는 6 → 25 → 44건이었다.
- 막혀야 할 글 작성은 글이 생기지 않으므로(`blocked_creation`), 정리 단계는 표식 글이 없는지만 확인한다(`expect_absent`, `creation_blocked_absent_verified`).
- 프로필을 쓰면 판정이 `http_only`가 되어 로그 대조 뒤 CLI가 PASS/FAIL을 낸다. `--dry-run`으로 단계별 기대 막힘 수를 먼저 확인한다.
- 결과: `시험결과/2026-11-20_AWS_06~08.md`.

## 5. 한계와 주의

- **WAF 판정:** `COUNT`는 WAF 탐지 기록이지 차단이 아니다. 403만으로 WAF 차단이라고 단정하지 않고 WAF 로그 `action`과 앱 로그 도달 여부를 함께 본다. ALB가 WAF보다 먼저 거부하는 요청(예: `/../` 경로, `Server: awselb/2.0` 400)은 로그가 없다.
- **WAF 로그의 본문 조각:** 규칙에 걸린 요청은 `matchedData`에 본문 일부(로그인이면 비밀번호 일부)가 남는다. 분석할 때 이 값을 화면·문서에 옮기지 않는다.
- **검증 범위:** SQLi·XSS·IDOR·파일 조작 결과는 HTTP만으로 결론 내리지 않고 DB 스냅샷, 출력 렌더링, 파일 위치/권한 등의 별도 증거가 있어야 한다. 여기서 작성한 코드는 **브라우저 JS 실행 판정·DB 읽기·실제 AWS 자동 정책 변경·동시 업로드 부하 시험을 수행하지 않는다.**
- **시험 환경:** 통합 시험은 초기화된 `haven_verify` DB와 시험용 파일 저장소를 기준으로 실행한다.
- **출력/비밀 관리:** 실제 AWS WAF 및 앱 원본 로그는 접근 제한된 로컬 저장소에 두고 Git에 업로드하지 않는다. 개인 `.gitignore`를 이용해 output, `*.jsonl` 등을 제외한다.

## 6. 1회차 완료 체크

- [x] Python CLI 기본 구현 및 실행 옵션/상태 저장
- [x] 로컬 mock fixture 서버 구성
- [x] 대상/fixture path 검증, 부분 결과, 상관분석 단위·통합 테스트
- [x] APP-11의 serialized body 8191/8192/8193 바이트 실제 길이 시험
- [x] 실제 Django 앱에서 1~3회차 로컬 HTTP 통합 시험
- [x] AWS WAF Count 및 실제 앱/WAF 로그 상관분석 (11/13 수동, 11/16부터 자동)
- [x] 팀의 경로/인증/로그 필드 합의 후 `TODO.md`에 시험 환경·명령·결과 기록
- [x] `Hyeokmin`에 commit/push 및 `main` 대상 PR 제출

## 7. AWS WAF 구성 (2026-11-12 구성, 11/20 Block 전환)

### 구성 완료

- Web ACL: `haven-web-acl`
- 리전: `ap-northeast-2` / REGIONAL
- 기본 동작: Allow
- 관리형 규칙 3개: CommonRuleSet, SQLiRuleSet, KnownBadInputsRuleSet
- 규칙 그룹 모두 Count 모드 적용
- 사전 WCU 확인: 1,100
- CloudWatch 로그 그룹: `aws-waf-logs-haven`
- 로그 보존 기간: 30일
- Authorization, Cookie 헤더 마스킹 적용

### 검증 결과

- `create-web-acl`: 성공
- `get-web-acl`: 기본 Allow 및 규칙 그룹 Count 확인
- `put-logging-configuration`: 성공
- CloudWatch 로그 그룹 및 30일 보존 설정 확인

### 이후 진행

- [x] ALB에 Web ACL 연결 (11/13, 이민성)
- [x] 실제 WAF Count 로그 수집 및 오탐 분석 (11/13~19)
- [x] WAF·Nginx·Django 로그 상관분석 (11/16 WAF↔Django 자동, 11/19 Nginx 포함)
- [x] Block 전환 대상 선정 및 적용 전후 검증 (`waf/WAF_Block_판단.md`, 11/20 조장 적용, `시험결과/2026-11-20_AWS_06~08.md`)

현재 설정(11/20 이후): 세 규칙 그룹 모두 Block, 기본 동작 Allow. Count로 남긴 규칙은 `SizeRestrictions_BODY`·`NoUserAgent_HEADER`이고, `SQLi_BODY`(로그인·가입 주소 예외)와 `CrossSiteScripting_BODY`(첨부 업로드 주소 예외)는 사용자 예외 규칙 2개가 대신 막는다. 자세한 내용은 판단안 3절.
