# Haven CLI

**상태:** Python CLI 및 **로컬 가상 fixture 시험 구현 완료**. Django 서비스·실제 AWS WAF에 대한 보안 검증은 **미실행**이다.  

## 1. 포함 파일

```text
권혁민/
├── request_verify.py                # run / correlate CLI
├── mock_server.py                   # 외부 네트워크를 사용하지 않는 가상 앱 + 가상 WAF 로그
├── README.md                        # 사용법, 입력/출력 계약
├── fixtures/
│   ├── allowlist_local.json         # 허용 서버 주소, 현재는 테스트 서버만 있고, Haven 주소 등록 필요
│   ├── cases_body_boundary.json     # APP-11, 8191/8192/8193 정확한 요청 크기
│   ├── cases_haven_template.json    # 실제 Haven 앱 개발 후 사용할 테스트 (그대로 실행 금지, 실제 서버 개발 후 수정)
│   ├── cases_local.json             # 테스트 서버용 동작 실행 파일 (나중에 삭제 예정)
│   ├── pad_8191.json, pad_8192.json, pad_8193.json # 글 작성 최대 크기 경계 테스트
│   ├── post_without_csrf.json       # csrf 누락 post
│   ├── sample.txt                   # 업로드용 sample 파일
│   ├── sec_dummy_php_upload.json    # php 파일 업로드 테스트
│   ├── sec_foreign_origin.json      # 외부 origin 요청 테스트
│   ├── sec_login_sql_username.json  # SQL injection 공격 테스트
│   └── sec_stored_xss.json          # stored XSS 공격 테스트
├── tests/test_request_verify.py     # requests_verify.py 검사용 테스트 파일
└── requirements.txt                 # CLI 실행에 필요한 python 라이브러리
```

> **중요:** `mock_server.py`의 `synthetic_fixture=true` 로그는 AWS WAF 로그가 아니다. 이 로그로 PASS가 나오더라도 **CLI의 로그 상관분석이 정상 작동한다는 뜻만** 가진다. Django 취약점 부재, AWS WAF 차단 성공 또는 실제 침투시험 결과를 의미하지 않는다.

## 2. 설치와 로컬 실행 (VS Code 터미널 / PowerShell)

프로젝트 루트에서 `권혁민` 폴더로 이동한다. Python 3.10 이상 권장.

```powershell
cd 권혁민
python -m pip install -r requirements-cli.txt
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

## 3. Case JSON 계약

명세에서 요구한 루트/케이스 필드를 유지하고, 시험 편의를 위한 옵션 1개(`verification_mode`)를 추가하였다.

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
- `origin_mode`: `absent`(기본), `same`(대상 origin), `foreign`(고정 `https://attacker.invalid`를 **Origin 헤더 값**으로만 사용; 그 호스트로 요청 전송하지 않음).
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

## 5. 아직 추가 구현·통합이 필요한 점

- **팀 확인:** 공통 `scripts/request_verify.py` 경로로 통합하는 작업은 1번 안민수와 협의. 1회차에는 개인 폴더에서 개발.
- **Django 연동:** 실제 필드명, 가입/로그인 CSRF 폼, POST 성공 리다이렉트, 운영자 권한, 감사 로그 스키마를 5번 신요찬과 확인한 뒤 케이스 기대값 확정.
- **WAF 연동:** AWS WAF 실제 로그의 규칙 액션/Count 형식과 앱 로그, UTC 시간, request_id 필드를 대조. `COUNT`는 WAF 탐지 이벤트이지 실제 차단이 아니다.
- **검증 범위:** SQLi·XSS·IDOR·파일 조작 결과는 HTTP만으로 결론 내리지 않고 DB 스냅샷, 출력 렌더링, 파일 위치/권한 등의 별도 증거가 있어야 한다. 여기서 작성한 코드는 **브라우저 JS 실행 판정·DB 읽기·실제 AWS 자동 정책 변경·동시 업로드 부하 시험을 수행하지 않는다.**
- **공격 시험:** `cases_haven_template.json`은 시작점이 되는 **수동 조정용 예시**다. 실제 데이터 P1 ID·공유 여부·업로드 제한·로그 수집이 확정되기 전에는 실행하지 않는다. `sec_login_sql_username.json`은 예시 fixture로만 제공하며, 로그인 오류 시 기대 HTTP 코드는 담당자와 계약을 맞춰야 한다.
- **출력/비밀 관리:** 실제 AWS WAF 및 앱 원본 로그는 접근 제한된 로컬 저장소에 두고 Git에 업로드하지 않는다. 개인 `.gitignore`를 이용해 output, `*.jsonl` 등을 제외한다.

## 6. 1회차 완료 체크

- [x] Python CLI 기본 구현 및 실행 옵션/상태 저장
- [x] 로컬 mock fixture 서버 구성
- [x] 대상/fixture path 검증, 부분 결과, 상관분석 단위·통합 테스트
- [x] APP-11의 serialized body 8191/8192/8193 바이트 실제 길이 시험
- [ ] 실제 Django 앱·AWS WAF에서 실행 (**2~4회차 의존 작업**)
- [ ] 팀의 경로/인증/로그 필드 합의 후 `TODO.md`에 시험 환경·명령·결과 기록
- [ ] `Hyeokmin`에 commit/push 및 `main` 대상 PR 제출
