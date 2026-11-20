# Haven WAF Block 전환 판단

| 항목 | 내용 |
|---|---|
| 작성 | 권혁민 (WAF 구성·Count 관찰·Block 판단 담당) |
| 작성일 | 2026-11-20 (초안 11-19) |
| 대상 | Web ACL `haven-web-acl` (서울 리전, ALB 연결), 관리형 규칙 그룹 3개 |
| 적용 담당 | 이민성 (조장 결정 11/12: 혁민 = 판단, 민성 = Block 적용) |
| 상태 | **3단계 모두 적용 완료(2026-11-20).** 1단계 KnownBadInputs 11:50, 2단계 SQLi + 로그인·가입 예외 14:28:22, 3단계 Common + 업로드 예외 15:41:16. 단계마다 전후 비교 시험에서 막혀야 할 요청만 막혔고 정상 요청 403은 0건(`시험결과/2026-11-20_AWS_06~08.md`). 남은 일: 5-4 관찰, `NoUserAgent_HEADER` 후속(8절 3번) |

---

## 1. 한눈에 보는 결론

| 규칙 그룹 | 지금 | 제안 | 한 줄 이유 |
|---|---|---|---|
| **KnownBadInputs** | Count | **Block** | 스캐너 경로·헤더 공격(Log4j·Java 실행 문자열·`Host: localhost`)을 모두 잡았고 정상 요청 매칭 0건 |
| **SQLi** | Count | **Block + 예외 1개** | SQL 공격 변형을 잘 잡는다. 단 **비밀번호에 `!@#`가 이어지면 `SQLi_BODY`가 오탐**하므로, **로그인·가입 주소에서만 `SQLi_BODY`를 Block하지 않는다** |
| **Common** | Count | **Block + 예외 3개** | XSS·LFI·SSRF·악성 봇은 잘 잡는다. **`SizeRestrictions_BODY`(정상 첨부 업로드를 막음)** 와 **`NoUserAgent_HEADER`(팀 점검 스크립트)** 는 Count 유지. **`CrossSiteScripting_BODY`는 첨부 업로드 주소에서만 Block하지 않는다**(메타데이터가 든 정상 PDF를 막음) |

- 기본 동작(어떤 규칙에도 안 걸린 요청)은 지금처럼 **Allow**를 유지한다.
- **한 번에 다 바꾸지 않고 KnownBadInputs → SQLi → Common 순서로 나눠 적용**하고, 단계마다 같은 시험을 다시 돌려 확인한다(5·6절).
- WAF 로그에 요청 본문(비밀번호 포함)이 남는 문제가 있어 **로그 조회 권한·보관 기간을 함께 정한다**(7절).

---

## 2. 근거 자료

| # | 자료 | 규모 | 보고서 |
|---|---|---|---|
| 1 | 누적 Count 로그 분석 (11/13 21:00 ~ 11/18 16:15 KST) | 요청 8,753건, 규칙 매칭 1,494건 | `TODO.md` "누적 Count 로그 분석 (2026-11-18)" |
| 2 | 보안 회귀 시험 (SQLi·XSS·인가·CSRF) | 32건 | `시험결과/2026-11-19_AWS_01.md` |
| 3 | 업로드 시험 | 38건 | `시험결과/2026-11-19_AWS_02.md` |
| 4 | WAF 오탐·미탐 검증 (정상 글 9종, 공격 변형 21종, 경로·쿼리 4종) | 35건 | `시험결과/2026-11-19_AWS_03.md` |
| 5 | 저장형 XSS 브라우저 확인 + 그 요청의 WAF·앱 로그 | 브라우저 요청 37건 | `시험결과/2026-11-19_AWS_04.md`, `_AWS_05.md` 6절 |
| 6 | 남은 SEC 자동 시험 (헤더 공격, 세션·첨부, 로그인·가입·글의 특수문자, PDF 메타데이터, 8KB 경계) | 실행 7회, HTTP 189/189, 로그 대조 213/213 | `시험결과/2026-11-20_AWS_05.md` |
| 7 | 11/13 12:00~21:00 누락 구간 재집계, PROPFIND·Authorization 가림 재확인 | 요청 1,354건, curl 2건 | `시험결과/2026-11-20_AWS_05.md` 6절 |

2~4와 6은 요청 재현 CLI로 실행하고, WAF·Nginx·앱 로그를 요청별로 대조했다(Trace Root 기준, `correlate-cloudwatch`). SEC-01~60 중 자동으로 할 수 있는 항목은 모두 AWS에서 실행했다.

---

## 3. 규칙 그룹별 판단

### 3-1. KnownBadInputs (`Version_1.26`) → **Block**

| 관찰 | 결과 |
|---|---|
| 누적 로그 | `ExploitablePaths_URIPATH` 684건(`/.env`, `/.aws/config` 등 없는 경로), `ReactJSRCE_BODY` 12건, `PROPFIND_METHOD`·`Host_localhost_HEADER` 각 1건. **모두 외부 스캐너** |
| 헤더 공격 시험 | User-Agent·임의 헤더의 Log4j, **난독화 Log4j**(`${${lower:j}ndi…}`), Java 실행 문자열, `Host: localhost` **모두 탐지** |
| 미탐 | 헤더의 Java 직렬화 시작 문자열(base64)만. 규칙이 찾는 형태(실행 문자열)가 아니라 범위 밖 |
| 오탐 | 정상 기능 요청(글·공유·업로드·다운로드·로그인·로그아웃), 일반 브라우저 헤더 매칭 **0건** |
| 판단 | 정상 사용과 겹치는 곳이 없다. 가장 먼저 Block해도 위험이 낮다 |

### 3-2. SQLi (`Version_2.5`) → **Block + 로그인·가입 `SQLi_BODY` 예외**

| 관찰 | 결과 |
|---|---|
| 탐지 | 로그인 username SQLi 6/8, password SQLi 3/3, 경로·쿼리·공유 대상 SQL, `SLEEP`·주석 끼운 `UNION` 탐지 |
| 오탐 (없음) | 정상 글의 **SQL 설명 문장**, 따옴표(`O'Brien`), 따옴표·하이픈·SQL 단어가 섞인 비밀번호 8종, 글 제목·본문의 `!@#` 3종 → 매칭 0건 |
| **오탐 (있음)** | **비밀번호 `qwer1234!@#$`, `Haven2026!@#` → `SQLi_BODY`** (2회 실행 모두 재현). `!@`, `@#$`, `#$!@`처럼 `!`→`@`→`#`이 이어지지 않으면 안 걸림. 11/16·17 브라우저 로그인·가입 8건도 같은 원인(시험용 더미 비밀번호) |
| 미탐 | `'` 하나(정상 이름에도 쓰여 미탐이 적절), **주석형 `admin'--` 2회 연속 미탐**. 둘 다 앱이 400 거부 |
| 판단 | `Shift+1·2·3(·4)`를 차례로 누른 비밀번호는 흔하다. 그대로 Block하면 이런 사용자는 **로그인·가입이 403으로 막힌다.** 반면 로그인·가입 폼은 Django 인증(ORM)이 처리해 SQL 주입 경로가 없고, 앱 시험으로도 확인되어 있다. 그래서 **`/accounts/login/`·`/accounts/signup/`에서만 `SQLi_BODY`를 Block하지 않고**, 나머지 주소와 나머지 SQLi 규칙은 Block한다 |

- 비밀번호를 받는 곳은 이 두 주소뿐이다(앱 URL 확인. 비밀번호 변경 화면은 없고 운영자 화면도 같은 로그인을 쓴다).
- **남는 위험:** 글 본문에 `abc123!@#`처럼 쓰면 걸릴 수 있다고 보았으나, 2단계 시험에서 글 본문 5종(`qwer1234!@#$` 포함)은 `SQLi_BODY`에 걸리지 않았다(`2026-11-20_AWS_07.md` 4절). 오탐은 로그인 본문 구조에서 생기는 것으로 보이며 그 위치는 예외로 처리했다. Block 뒤 관찰에서 `/posts/` 주소의 `SQLi_BODY` BLOCK은 계속 따로 본다(5-4).

### 3-3. Common (`Version_1.23`) → **Block + 예외 3개**

| 규칙 | 관찰 | 제안 |
|---|---|---|
| **`SizeRestrictions_BODY`** | 누적 로그: 팀원의 **정상 첨부 업로드 27건**. 시험: **정확히 2 MiB 정상 업로드(앱 302)** 에서 재현. 본문이 8KB를 넘으면 무조건 걸림 | **Count 유지 (예외)** |
| **`NoUserAgent_HEADER`** | 534건 대부분 해외 스캐너. KR에서 User-Agent 없이 주기적으로 요청한 것은 **팀 점검 스크립트**(조장 확인 11/19). 시험에서도 User-Agent 없는 요청을 탐지 | **점검 스크립트에 User-Agent를 붙인 뒤 Block.** 그 전까지 Count 유지 |
| `UserAgent_BadBots_HEADER` | zgrab·masscan·360Spider 등 120건, 시험의 Nmap User-Agent 탐지. 일반 Chrome User-Agent 0 | Block |
| `CrossSiteScripting_QUERYARGUMENTS` | 쿼리 XSS 변형, 재표시 XSS 탐지. 정상 쿼리 0 | Block |
| **`CrossSiteScripting_BODY`** | 본문 XSS 변형 11/11, 파일명 XSS, **브라우저 수동 시험의 XSS 글·첨부 7/7** 탐지. 정상 글(HTML 태그 설명 포함) 0. **그러나 XMP 메타데이터가 앞부분에 있는 정상 PDF 업로드가 걸림**(11/13 팀원 업로드 2건, 재현 시험 1/1). 메타데이터 없는 PDF는 안 걸림 | **Block하되 첨부 업로드 주소(`/posts/<번호>/attachments/`)는 예외.** 글 작성·수정 등 다른 주소의 본문 XSS는 Block |
| `GenericLFI_*`·`GenericRFI_*`·`EC2MetaDataSSRF_*` | `../` 파일명, `?file=../../etc/passwd`, `?url=169.254.169.254` 탐지. 정상 글(`/etc/hosts`·`C:\Users` 언급) 0 | Block |
| `RestrictedExtensions_*` | `.bak`·`.php.bak` 등 스캐너 63건 | Block |
| `SizeRestrictions_QUERYSTRING`·`_URIPATH`·`_Cookie_HEADER` | 관찰·시험에서 매칭 없음. Haven의 주소·쿠키는 짧음 | Block (전후 비교에서 정상 기능 재확인) |

---

## 4. Block으로도 막지 못하는 것 (앱이 계속 담당)

| 항목 | 이유 | 현재 방어 (시험 결과) |
|---|---|---|
| 주석형 SQL (`admin'--`) | 관리형 SQLi 규칙이 2회 연속 미탐 | Django ORM, 인증 실패 400 |
| 로그인·가입의 SQL 문자열 | 3-2의 예외로 `SQLi_BODY`를 보지 않음 | Django 인증(ORM), 앱 시험 400 |
| 업로드 형식 공격 (`.php`·`.exe`·`.txt.php`·`.html`·`.svg`, 손상·암호화 PDF 등 11종) | WAF는 파일 형식을 판단하지 않음(11종 모두 매칭 없음) | 앱 형식·내용 검사 400 |
| 요청 본문 8KB 뒤의 내용 | ALB에 붙은 WAF는 본문 앞 8KB만 검사. 시험: 파일 앞의 XSS는 탐지, **8KB 뒤의 XSS는 미탐**(`SizeRestrictions_BODY`만 매칭, 이 규칙은 Count 예외) | 앱 업로드 검사(크기·개수·형식·파일명·권한), 다운로드 전용 제공(`attachment`·`nosniff`) |
| 인가(IDOR)·CSRF·세션 | WAF 규칙 대상이 아님 | 앱 404·403. 세션 고정·로그아웃 재사용·첨부/공유 ID 조작 모두 PASS(`_AWS_05.md`) |
| 첨부 업로드의 XSS (파일명·내용) | 3-3의 예외로 업로드 주소의 `CrossSiteScripting_BODY`를 보지 않음 | 파일명은 화면에서 이스케이프(SEC-14 브라우저 확인), 엔티티 형태 파일명 400 거부, 내용은 다운로드 전용(`attachment`·`nosniff`) |
| 템플릿 문자열(`{{ … }}`) | 이것만 잡는 관리형 규칙 없음 | Django 템플릿이 입력을 평가하지 않음 |
| 프록시 헤더 조작(`X-Forwarded-*`) | WAF 규칙 대상이 아님 | 앱·Nginx가 조작 값을 믿지 않음(SEC-55 PASS) |

---

## 5. 적용안 (민성님 작업용)

### 5-1. 공통 주의

- 적용 직전에 `get-web-acl`로 **현재 설정과 LockToken을 새로 받는다.** 이 문서는 11/13 원본(`waf/2026-11-13_get-web-acl_raw.json`)과 11/20까지의 관찰 기준이다.
- 지금은 그룹 단위(`OverrideAction: Count`)와 규칙 단위(`RuleActionOverrides`의 `Count`) **두 겹으로 Count**가 걸려 있다. Block하려면 **둘 다 풀어야** 한다.
  - 그룹: `"OverrideAction": {"Count": {}}` → `"OverrideAction": {"None": {}}` (관리형 규칙의 원래 동작 = Block)
  - 규칙: Block할 규칙은 `RuleActionOverrides`에서 **빼고**, 예외로 남길 규칙만 `Count`로 둔다.
- 규칙 버전은 지금처럼 **고정**한다(Common `Version_1.23`, SQLi `Version_2.5`, KnownBadInputs `Version_1.26`).
- 단계별 적용 시각을 기록해 두면 전후 비교 때 로그 구간을 정확히 나눌 수 있다.

### 5-2. 단계

| 단계 | 바꿀 것 | 바뀐 뒤 설정 | 확인 |
|---|---|---|---|
| 1 | KnownBadInputs | `OverrideAction: None`, `RuleActionOverrides` 제거 | `/.env`·Log4j 헤더가 WAF 403이고 앱·Nginx 로그 없음. 정상 기능 회귀 |
| 2 | SQLi + 예외 규칙 | `OverrideAction: None`, `RuleActionOverrides`는 `SQLi_BODY` Count 하나. **SQLi 그룹 바로 뒤에 예외 규칙 추가**(아래) | 글·쿼리의 SQLi가 WAF 403. **`qwer1234!@#$` 로그인은 403 없이 앱 400**, 정상 로그인 성공 |
| 3 | Common + 예외 규칙 | `OverrideAction: None`, `RuleActionOverrides`는 아래 3개만. **Common 그룹 바로 뒤에 업로드 예외 규칙 추가**(아래) | 글의 XSS·LFI·SSRF가 WAF 403. **2 MiB 정상 업로드와 메타데이터 PDF 업로드 302 유지** |

**2단계 SQLi 그룹의 `RuleActionOverrides`:**

```json
"RuleActionOverrides": [
  { "Name": "SQLi_BODY", "ActionToUse": { "Count": {} } }
]
```

**2단계 예외 규칙 (SQLi 그룹보다 우선순위 숫자가 큰 새 규칙):** `SQLi_BODY`는 Count로 두면 매칭 표시(레이블)만 남긴다. 이 규칙이 그 레이블을 보고 **로그인·가입이 아닌 주소에서만** Block한다.

```json
{
  "Name": "haven-sqli-body-except-auth",
  "Priority": "<SQLi 그룹 우선순위 + 1>",
  "Statement": {
    "AndStatement": {
      "Statements": [
        { "LabelMatchStatement": { "Scope": "LABEL", "Key": "awswaf:managed:aws:sql-database:SQLi_Body" } },
        { "NotStatement": { "Statement": {
            "RegexMatchStatement": {
              "RegexString": "^/accounts/(login|signup)/$",
              "FieldToMatch": { "UriPath": {} },
              "TextTransformations": [ { "Priority": 0, "Type": "NONE" } ]
            } } } }
      ]
    }
  },
  "Action": { "Block": {} },
  "VisibilityConfig": {
    "SampledRequestsEnabled": false,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "haven-sqli-body-except-auth"
  }
}
```

- 레이블 이름(`…:SQLi_Body`)은 적용 전에 AWS 콘솔의 SQLi 규칙 그룹 설명에서 **다시 확인**한다.
- 우선순위 숫자는 SQLi 그룹보다 커야 한다. 레이블은 앞에서 평가된 규칙만 볼 수 있다.

**3단계 Common의 `RuleActionOverrides` (예외만 남김):**

```json
"RuleActionOverrides": [
  { "Name": "SizeRestrictions_BODY",   "ActionToUse": { "Count": {} } },
  { "Name": "NoUserAgent_HEADER",      "ActionToUse": { "Count": {} } },
  { "Name": "CrossSiteScripting_BODY", "ActionToUse": { "Count": {} } }
]
```

**3단계 예외 규칙 (Common 그룹보다 우선순위 숫자가 큰 새 규칙):** 2단계와 같은 방식이다. `CrossSiteScripting_BODY`의 레이블을 보고 **첨부 업로드 주소가 아닌 곳에서만** Block한다.

```json
{
  "Name": "haven-xss-body-except-upload",
  "Priority": "<Common 그룹 우선순위 + 1>",
  "Statement": {
    "AndStatement": {
      "Statements": [
        { "LabelMatchStatement": { "Scope": "LABEL", "Key": "awswaf:managed:aws:core-rule-set:CrossSiteScripting_Body" } },
        { "NotStatement": { "Statement": {
            "RegexMatchStatement": {
              "RegexString": "^/posts/[0-9]+/attachments/$",
              "FieldToMatch": { "UriPath": {} },
              "TextTransformations": [ { "Priority": 0, "Type": "NONE" } ]
            } } } }
      ]
    }
  },
  "Action": { "Block": {} },
  "VisibilityConfig": {
    "SampledRequestsEnabled": false,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "haven-xss-body-except-upload"
  }
}
```

- 레이블 이름(`…:CrossSiteScripting_Body`)도 적용 전에 콘솔의 Common 규칙 그룹 설명에서 다시 확인한다.

### 5-3. 되돌리기

문제가 생기면 해당 규칙 그룹만 `"OverrideAction": {"Count": {}}`로 되돌린다(규칙 단위 설정은 그대로 둬도 Count로 동작). 2·3단계 예외 규칙은 Action을 `{"Count": {}}`로 바꾼다. 되돌린 시각과 이유를 기록한다.

### 5-4. 적용 뒤 관찰

- CloudWatch 지표 `BlockedRequests`(Web ACL·규칙 그룹·예외 규칙별)를 24시간 본다.
- Logs Insights로 **BLOCK된 요청 중 실제 기능 주소**(`/`, `/accounts/`, `/posts/`, `/admin/`)를 찾아 정상 사용이 막혔는지 확인한다.
- 특히 **`/posts/` 주소의 `SQLi_BODY` BLOCK**(3-2의 남는 위험), **로그인·가입의 BLOCK**, **첨부 업로드 주소의 BLOCK**(두 예외가 제대로 동작하는지)을 따로 본다.
- 참고: 현재 Web ACL은 `SampledRequestsEnabled: false`라 콘솔의 샘플 요청 화면은 비어 있다. 전용 로그 그룹(`aws-waf-logs-haven`)으로 확인한다.

---

## 6. 전후 비교 계획 (SEC-59, WAF-03·04·08)

단계마다 Block **전**에 실행해 둔 시험을 같은 조건(대상·계정·속도·입력)으로 다시 실행한다.

| 시험 묶음 | Block 후 기대 변화 |
|---|---|
| WAF Count 재시험 (`cases_aws_waf_count.json`) | 정상 2건 그대로(200). SQLi·XSS 쿼리는 **WAF 403, 앱 로그 없음** |
| WAF 오탐·미탐 검증 (`cases_aws_waf_verify.json`) | 정상 글 9종 그대로(302). 탐지되던 공격 변형은 **403**. `admin'--`는 그대로(미탐 유지). 로그인 password SQLi는 예외 때문에 **앱 400 유지** |
| 보안 회귀 (`cases_aws_security_phase2.json`) | 인가·CSRF 시험은 그대로(404·403). 글·쿼리의 SQL·XSS 문자열 요청은 **403** |
| 업로드 (`cases_aws_upload.json`) | **2 MiB 정상 업로드 302 유지**(예외 확인). HTML 모양 파일명은 업로드 예외 때문에 WAF를 지나 **앱 결과 그대로**(엔티티는 400, 나머지는 저장 후 화면 이스케이프). `../` 파일명은 `GenericLFI_BODY`로 403. 형식 공격은 그대로 앱 400 |
| 남은 SEC (`cases_aws_sec_remaining.json`) | 로그인·가입 정상 입력과 **`!@#` 비밀번호 그대로 앱 400**(예외 확인). 글의 `!@#` 그대로 302. 파일 앞 XSS 업로드와 **메타데이터 PDF** 업로드는 업로드 예외 때문에 302 유지, 8KB 뒤 XSS 업로드도 302 |
| 헤더 (`cases_aws_header.json`) | 정상 헤더 그대로(200). Log4j·Java 실행 문자열·`Host: localhost`·스캐너 UA는 **403**. User-Agent 없음은 예외 때문에 200 유지 |
| 세션·첨부 (`cases_aws_session_attach.json`) | 모두 그대로(정상 흐름이 Block에 걸리지 않아야 함) |
| 공유·정리 스모크 (`cases_haven_aws.json`) | 모두 그대로 |

- 시험 파일의 기대값은 지금(Count) 기준이라, Block 후에는 공격 요청이 **불일치(403)** 로 나온다. 전후 비교용 "Block 후 기대값(앱 403·WAF BLOCK)" 묶음은 혁민이 따로 준비한다.
- 정리 단계(글 삭제·공유 해제)가 Block에 걸리지 않는지 함께 확인한다.

---

## 7. 함께 정할 것: WAF 로그의 본문 조각 (SEC-53)

규칙에 걸린 요청은 WAF 로그의 `ruleMatchDetails.matchedData`에 **요청 본문의 일부가 그대로 저장**된다. WAF 로그 가리기 설정은 헤더·URI·쿼리만 지원하고 본문은 가릴 수 없다. 실제로 11/16·17 로그인·가입 8건의 로그에 비밀번호(이번에는 시험용 더미값)가 평문으로 남아 있었다.

- 3-2의 예외를 적용하면 로그인·가입의 `SQLi_BODY`는 Count로 남으므로 **여전히 로그에 기록된다.** 예외는 차단을 막을 뿐 기록을 막지 않는다.
- 보관 기간: `aws-waf-logs-haven`은 **30일**(2026-11-20 `describe-log-groups`로 확인). 30일은 그대로 두고, 30일이 지난 기간의 원본은 혁민이 저장소 밖에 개인 보관한다(팀 결정). 11/13 로그는 12/13쯤부터 지워지므로 그 전에 받는다.
- 조회 권한: 팀원 IAM 정책 중 이 로그 그룹을 읽을 수 있는 것은 혁민 정책(`김보람/JSON/20`·`21`)뿐이다(관리자·루트 계정 제외, 저장소 정책 파일 기준). 개인 보관본도 저장소·팀 채팅에 올리지 않고, 분석할 때 `matchedData`를 화면·문서에 옮기지 않는다.
- 필요하면 WAF 로깅 필터로 로그인·가입 주소의 Count 기록을 줄이는 방법도 검토할 수 있다(이 경우 오탐 관찰 근거도 줄어든다).

---

## 8. 적용 전 팀 확인

1. ~~로그인 `SQLi_BODY` 8건~~ → **원인 확인(비밀번호의 `!@#` 오탐), 2회 재현.** 3-2의 예외로 반영.
2. ~~PDF 업로드 `CrossSiteScripting_BODY`~~ → **11/13 누락 구간 재집계에서 발견, 재현 확인.** 3-3의 업로드 예외로 반영.
3. **`NoUserAgent_HEADER`:** 팀 점검 스크립트 담당자가 요청에 User-Agent를 붙이면 Count 예외를 풀고 Block한다(3단계 뒤 별도로).
4. **WAF 로그 조회 권한·보관 기간(7절):** 조장·민성 결정 필요.

---

## 9. 한계

- 관찰 기간은 약 1주이고 사용자는 팀원·시험 계정뿐이다. 실제 사용자가 생기면 오탐 분석을 다시 해야 한다.
- 누적 로그 집계는 규칙 그룹마다 첫 매칭 규칙만 셌다(최소 건수). 빠졌던 11/13 12:00~21:00 KST 구간은 11/20에 다시 집계했다(요청 1,354건).
- `!@#` 오탐은 시험한 모양(비밀번호 10종, 글 3종)으로만, PDF 오탐은 시험용 PDF 2종으로만 범위를 확인했다. 다른 특수문자 조합이나 다른 파일 내용에도 비슷한 오탐이 있을 수 있어 5-4 관찰로 보완한다.
- 시험 결과는 이번 시험 요청 기준의 관찰이며 방어율이 아니다.
- 화면 이스케이프(XSS)처럼 사람이 확인한 항목은 브라우저 수동 확인(`_AWS_04.md`)을 근거로 했다.
