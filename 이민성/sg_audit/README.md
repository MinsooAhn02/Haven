# SG 설정 점검 CLI (이민성)

`network/설계.md` 4장의 SG 연결표를 기준으로, 실제(또는 가짜) SG 규칙이 설계와 맞는지 판정하는 읽기 전용 점검 도구.
명세: `docs/구현명세/기본프로젝트_구현명세.md` 5장. 최종 경로(`scripts/network_audit.py`)는 통합 때 안민수가 맞춘다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `baseline.json` | 정답지. 서버 역할별로 허용하는 규칙 목록(허용 목록에 없으면 위반) |
| `fixtures/*.json` | 가짜 AWS 응답(답안지). AWS 없이 판정 로직을 시험할 때 사용 |
| `network_audit.py` | 판정 프로그램 (fixture 모드 구현, live 모드는 3회차) |

코드가 어떻게 판정하는지는 [코드설명.md](코드설명.md)를 본다.

### 참고

- SG의 기본 규칙: 허용만 존재한다. 허용 목록에 없으면 전부 거부한다.
- 파일 구조: 정답지(`baseline.json`)와 설명서(README, 코드설명)는 `sg_audit`에, 답안지(fixture) 4개는 전부 `fixtures` 안에 둔다.
- `python -m json.tool`로 JSON 문법 검사 시 `\uc124` 같은 글자가 보이면 한글을 코드로 바꿔 출력한 것이라 문제없다. 한글로 보려면 `--no-ensure-ascii` 옵션을 붙인다.

## fixture 목록

채점기가 맞는 건 맞다고, 틀린 건 틀렸다고, 모르는 건 모른다고, 못 읽은 건 실패라고 판정하는지 확인하는 "도구를 시험하는 시험"이다. 종료 코드 0·1·2·3이 각각 한 번씩 나오도록 구성했다.

| 파일 | 상황 | 확인하는 것 | 이게 없으면 놓치는 버그 | 기대 결과 | 명세 시험 |
|---|---|---|---|---|---|
| `pass.json` | 설계대로 설정됨 | 정상을 정상이라고 하는가 | 멀쩡한데 FAIL을 내는 오탐 | PASS (0) | AUD-01 |
| `fail_public_db.json` | DB 5432가 `0.0.0.0/0`에 열림 | 위반을 잡아내는가 | 뚫렸는데 PASS를 내는 미탐 | FAIL (1) | AUD-02 |
| `unknown_role.json` | baseline에 없는 서버·SG가 있음 | 모르는 건 "모른다"고 하는가 | 근거 없이 PASS/FAIL로 단정 | UNKNOWN (3) | AUD-09 |
| `error_access_denied.json` | 권한 오류로 SG 목록을 못 읽음 | 못 읽었을 때 실패라고 하는가 | 아무것도 못 읽고 "문제없음"으로 끝냄 | ERROR (2) | AUD-08 |

- `fail_public_db.json`은 정상 규칙(Web → DB 5432)을 그대로 두고 위험 규칙 하나만 추가했다. 실제 사고에서 흔한 모양(급하게 열고 안 닫음)이며 SG-01(공개 DB 포트) 판정을 시험한다.
- 결과 없음은 PASS가 아니라 UNKNOWN이다. 수집 실패는 ERROR이며 PASS로 처리하지 않는다.
- DB 5432 공개 이유(fail_public_db): 명세에 정해진 시험(AUD-02, `docs/구현명세/기본프로젝트_구현명세.md`)
- 참조: `docs/구현명세/기본프로젝트_구현명세.md`의 "8.4 자체 점검과 WAF" SG CLI 시험(AUD-01~11)

## fixture별 차이점 (pass.json 기준)

세 fixture 모두 `pass.json`을 복사해 만들었고, `fixture_id`와 `description`은 각 상황에 맞게 바꿨다. 아래는 그 외에 달라진 부분이다. 줄 번호는 `pass.json` 기준이며 `+`는 추가한 줄이다.

### 1. fail_public_db.json: 규칙 1줄 추가

`sg-fixture-db`의 `IpPermissions`(들어오는 규칙), pass.json 35번째 줄.
기존 규칙(Web에서 오는 5432)은 그대로 두고 **전 세계에서 오는 5432**를 하나 더 열었다.

```diff
  { "IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432, "UserIdGroupPairs": [{ "GroupId": "sg-fixture-web" }] },
+ { "IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432, "IpRanges": [{ "CidrIp": "0.0.0.0/0" }] }
```

- 기존 줄 끝에 쉼표(`,`)가 붙었다.
- 출발지가 `UserIdGroupPairs`(SG)가 아니라 `IpRanges: 0.0.0.0/0`(전 세계)이라 SG-01 위반(baseline에 없는 규칙 중 가장 심각한 경우)이 된다.

### 2. unknown_role.json: SG 1개 + 서버 1개 추가

**(1) `security_groups` 끝에 정체불명 SG 추가** (pass.json 37번째 줄, DB SG가 끝나는 부분)

```diff
      "IpPermissionsEgress": [
        { "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{ "CidrIp": "0.0.0.0/0" }] }
      ]
-   }
+   },
+   {
+     "GroupId": "sg-fixture-mystery",
+     "GroupName": "sg-test-temp",
+     "IpPermissions": [],
+     "IpPermissionsEgress": []
+   }
  ],
```

**(2) `attachments` 끝에 baseline에 없는 서버 추가** (pass.json 45번째 줄)

```diff
- { "asset_id": "db-1",  "sg_ids": ["sg-fixture-db"] }
+ { "asset_id": "db-1",  "sg_ids": ["sg-fixture-db"] },
+ { "asset_id": "tmp-1", "sg_ids": ["sg-fixture-mystery"] }
```

- `tmp-1`은 baseline의 `assets`(alb, web-1, db-1)에 없는 이름이라 역할과 허용 규칙을 알 수 없다. 그래서 UNKNOWN이 된다.
- 앞 항목 끝에 쉼표를 붙여야 해서 기존 줄도 바뀌었다(`-` 줄이 원래 모양).

### 3. error_access_denied.json: 수집 결과는 비우고 오류 1개 추가

| 필드 | pass.json | error_access_denied.json | 뜻 |
|---|---|---|---|
| `security_groups` | SG 3개 | `[]` (빈 목록) | 권한이 없어 아무것도 못 읽음 |
| `attachments` | 서버 3개 | `[]` (빈 목록) | 마찬가지 |
| `errors` | `[]` (빈 목록) | 오류 1개 | 수집 중 실패가 있었다는 기록 |

추가된 오류:

```json
{
  "stage": "DescribeSecurityGroups",
  "code": "UnauthorizedOperation",
  "message": "fixture: 권한 없음 주입"
}
```

- `stage`: 실패한 단계(SG 목록을 요청하는 AWS API 이름)
- `code`: 오류 종류(EC2 API가 권한이 없을 때 돌려주는 오류 이름)
- `message`: 사람이 읽는 설명. 가짜로 주입한 오류임을 표시했다.
- 못 읽었으면 PASS가 아니라 ERROR다. 참고로 오류 없이 그냥 비어 있으면 UNKNOWN이다(결과 없음 ≠ PASS).

## baseline.json 필드

| 필드 | 뜻 |
|---|---|
| `schema_version` | 형식 버전. 현재 1 |
| `assets[].asset_id` | 서버 이름 (예: `web-1`) |
| `assets[].asset_role` | 서버 역할: `alb`, `web`, `db` |
| `assets[].expected_sg_ids` | 그 서버에 붙어 있어야 하는 SG ID. 1회차는 가짜 ID(`sg-fixture-...`), 3회차에 실제 ID로 교체 |
| `allowed_rules[].direction` | `ingress`(들어옴) / `egress`(나감) |
| `allowed_rules[].protocol`, `from_port`, `to_port` | 프로토콜과 포트 범위 |
| `allowed_rules[].source_type` | `cidr`(IP 범위) 또는 `sg_role`(해당 역할의 SG) |
| `allowed_rules[].source_value` | ingress면 출발지, egress면 목적지 (예: `0.0.0.0/0`, `alb`) |

### 규칙별 이유 (설계.md 4장 대응)

| 역할 | 방향 | 규칙 | 이유 |
|---|---|---|---|
| alb | ingress | TCP 443 ← `0.0.0.0/0` | 사용자 HTTPS 접속 |
| alb | ingress | TCP 80 ← `0.0.0.0/0` | HTTPS redirect 전용 |
| alb | egress | TCP 80 → web | 요청 전달·health check |
| web | ingress | TCP 80 ← alb | ALB를 거친 요청만 허용 |
| web | egress | TCP 5432 → db | DB 연결 |
| web | egress | TCP 443 → `0.0.0.0/0` | NAT 경유 SSM·패키지·AWS API·메일 API |
| db | ingress | TCP 5432 ← web | Web에서만 DB 접속 |
| db | egress | TCP 443 → `0.0.0.0/0` | NAT/S3 경유 SSM·패키지·백업 |

## 판정 원칙

- 허용 목록 방식: baseline에 없는 규칙이 실제로 열려 있으면 FAIL (예: 22번이 인터넷 전체에 열려 있으면 SG-01).
- 결과 종류: PASS / FAIL / UNKNOWN(근거 부족) / ERROR(수집·실행 실패).
- 종료 코드: 0=PASS, 1=FAIL, 2=ERROR, 3=UNKNOWN. 섞이면 ERROR > UNKNOWN > FAIL > PASS 순.

## 판정 규칙 (check_id)

허용표에 없는 규칙은 아래 순서로 확인해 처음 걸리는 하나로 판정한다(같은 규칙에 FAIL을 중복으로 매기지 않음).

| check_id | 조건 | 판정 |
|---|---|---|
| SG-01 | 들어오는 규칙의 출발지가 `0.0.0.0/0`·`::/0`이고 22(SSH)·3389(RDP)·5432(PostgreSQL) 포트를 포함 | FAIL |
| SG-02 | 전체 프로토콜(`-1`) 허용 | FAIL |
| SG-03 | Web TCP 80의 출발지가 ALB SG가 아님 | FAIL |
| SG-04 | DB TCP 5432의 출발지가 Web SG가 아님 | FAIL |
| SG-05 | 그 외 baseline에 없는 규칙 / baseline 규칙이 실제로 없음 / 기대 SG 미연결 | FAIL |
| SG-06 | baseline에 없는 자산, 연결되지 않은 SG, 역할을 모르는 SG 참조, SG 규칙 수집 결과 없음 | UNKNOWN |

- baseline 규칙과 정확히 일치하는 규칙은 PASS로 기록한다.
- fixture에 `errors`가 있으면 채점하지 않고 ERROR로 끝낸다(반쯤 읽은 데이터로 PASS를 내지 않기 위해).

## 실행 방법

요구 사항: Python 3.10 이상(시험 환경 3.13.2), 추가 패키지 없음. 1회차는 `fixture` 모드만 구현했고 `live` 모드는 3회차 예정이다.

`sg_audit` 폴더에서 실행한다.

```powershell
cd 이민성\sg_audit
python network_audit.py fixture --fixture fixtures\pass.json --baseline baseline.json --output-dir out\pass
echo $LASTEXITCODE
```

| 옵션 | 뜻 |
|---|---|
| `--fixture` | 채점할 fixture(가짜 AWS 응답) 파일 |
| `--baseline` | 정답지(허용 규칙표) 파일 |
| `--output-dir` | 결과를 저장할 **새 폴더**. 이미 내용이 있는 폴더면 덮어쓰지 않고 ERROR(2)로 멈춘다 |

결과 파일:
- `results.json`: 실행 정보(run_id, 시각, 모드, 계정, 리전, 수집 상태, 판정 개수)와 전체 finding, errors
- `findings.csv`: finding을 한 줄씩 기록한 표(엑셀에서 한글이 깨지지 않도록 UTF-8 BOM으로 저장)

`out/` 폴더는 실행할 때마다 새로 만들어지는 결과물이라 `.gitignore`로 Git에서 제외한다.

## 시험 결과

환경: Windows, Python 3.13.2, `network_audit.py` 0.1.0, 2026-11-06 실행.

| 시험 ID | fixture | 결과 개수 | 기대 | 실제 | 종료 코드 |
|---|---|---|---|---|---|
| AUD-01 | `pass.json` | PASS 8 | PASS | PASS | 0 |
| AUD-02 | `fail_public_db.json` | PASS 8, FAIL 1 | FAIL | FAIL (SG-01: 인터넷 전체에 PostgreSQL 5432 개방) | 1 |
| AUD-09 | `unknown_role.json` | PASS 8, UNKNOWN 1 | UNKNOWN | UNKNOWN (SG-06: tmp-1은 baseline에 없는 자산) | 3 |
| AUD-08 | `error_access_denied.json` | ERROR 1 | ERROR | ERROR (DescribeSecurityGroups: UnauthorizedOperation) | 2 |

회귀 시험은 `python -m unittest -v test_network_audit`로 실행한다.

추가 확인:
- 같은 `--output-dir`로 다시 실행하면 덮어쓰지 않고 ERROR(2)로 멈춘다.
- 없는 파일을 지정하면 ERROR(2)로 멈춘다.

미구현(다음 회차): `live` 모드(실제 AWS 읽기 전용 수집, 3회차), AUD-03~07·10·11 추가 fixture.

