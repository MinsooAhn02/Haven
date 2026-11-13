# SG 설정 점검 CLI (이민성)

`network/설계.md` 4장의 SG 연결표를 기준으로, 실제(또는 가짜) SG 규칙이 설계와 맞는지 판정하는 읽기 전용 점검 도구.
명세: `docs/구현명세/기본프로젝트_구현명세.md` 5장. 최종 경로(`scripts/network_audit.py`)는 통합 때 조장(이민성)이 맞춘다(11/11 조장 인계).

## 파일 구성

| 파일 | 역할 |
|---|---|
| `baseline.json` | 정답지. 서버 역할별로 허용하는 규칙 목록(허용 목록에 없으면 위반) |
| `fixtures/*.json` | 가짜 AWS 응답(답안지). AWS 없이 판정 로직을 시험할 때 사용 |
| `network_audit.py` | 판정 프로그램 (fixture 모드, live 모드 11/13 구현·명세 5.1 맞춤) |
| `test_network_audit.py` | fixture 모드 회귀 시험(unittest). 1회차 PR 리뷰에서 팀장 보완 시 추가, 11/13 1개 추가 |
| `test_live.py` | live 모드 시험(가짜 EC2·STS, boto3 없이). L1~L20 + 명령 형식 시험 |
| `make_evidence.py` | 결과 폴더로 공개용 증거 묶음 `evidence/<run-id>/`을 만든다(명세 9장) |
| `test_evidence.py` | 증거 묶음 시험(가림·manifest·전후 비교·덮어쓰기 금지) |
| `baseline.live.json` | (Git 제외) live용 baseline. `baseline.json`을 복사해 실제 SG ID를 넣는다 |

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
| `assets[].expected_sg_ids` | 그 서버에 붙어 있어야 하는 SG ID. `baseline.json`은 fixture용 가짜 ID(`sg-fixture-...`). live는 이 파일을 복사한 `baseline.live.json`에 실제 ID를 넣어 쓴다(명세 5.1: "assets는 expected_sg_ids로 실제 자산 역할을 매핑"). 실제 ID가 든 파일은 `.gitignore`로 Git에서 뺀다 |
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
| web | egress | TCP 80 → `0.0.0.0/0` | Ubuntu apt 저장소(HTTP). 설계 4.2에 11/09 추가, baseline은 11/13 반영 |
| db | ingress | TCP 5432 ← web | Web에서만 DB 접속 |
| db | egress | TCP 443 → `0.0.0.0/0` | NAT/S3 경유 SSM·패키지·백업 |
| db | egress | TCP 80 → `0.0.0.0/0` | Ubuntu apt 저장소(HTTP). 설계 4.2에 11/09 추가, baseline은 11/13 반영 |

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
| SG-06 | baseline에 없는 자산(live: 기대 SG가 없는 ENI), baseline 자산의 수집 결과 없음, 연결되지 않은 SG, 역할을 모르는 SG 참조, SG 규칙 수집 결과 없음, 한 ENI에 여러 자산의 기대 SG(역할 미확정), ENI 수집 실패로 자산 접근 결과를 모름 | UNKNOWN |
| SG-07 | (live `--vpc-id`만) VPC의 `default` SG에 규칙이 하나라도 있음. 비어 있으면 PASS. default SG는 SG-06 "연결되지 않은 SG"에서 뺀다 | FAIL |

- baseline 규칙과 정확히 일치하는 규칙은 PASS로 기록한다.
- fixture에 `errors`가 있으면 수집된 개별 finding은 보존하고 전체 판정은 ERROR로 끝낸다. baseline의 기대 자산이 수집 결과에서 누락되면 UNKNOWN으로 남긴다.

## 실행 방법

요구 사항: Python 3.10 이상(시험 환경 3.13.2). `fixture` 모드와 시험은 추가 패키지 없음. `live` 모드만 `boto3`가 필요하다(`pip install boto3`).

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

### live 모드 실행 (실제 AWS, 읽기 전용)

명세 5.1 형식. AWS에 IAM 사용자로 로그인한 터미널에서 `sg_audit` 폴더로 가서 실행한다. Describe* API와 STS `GetCallerIdentity`(누구로 로그인했는지 확인)만 부르고 아무것도 바꾸지 않는다.

처음 한 번: live용 baseline을 만든다(Git에 안 올라감).

```bash
cd 이민성/sg_audit
cp baseline.json baseline.live.json
# baseline.live.json을 열어 alb·web-1·db-1의 expected_sg_ids를 실제 SG ID(sg-...)로 바꾼다
```

실행(둘 중 하나):

```bash
# VPC 전체
python network_audit.py live --region ap-northeast-2 --profile default --vpc-id <VPC ID> --baseline baseline.live.json --output-dir out/live-$(date +%Y%m%d-%H%M)
# SG 지정(여러 개면 --sg-id를 반복)
python network_audit.py live --region ap-northeast-2 --profile default --sg-id <SG ID> --baseline baseline.live.json --output-dir out/live-$(date +%Y%m%d-%H%M)
echo $?
```

| 옵션 | 뜻 |
|---|---|
| `--region` | (필수) AWS 리전 |
| `--profile` | (필수) AWS CLI 프로필 이름. 따로 만든 적 없으면 `default` (`aws configure list-profiles`로 확인) |
| `--baseline` | (필수) 실제 SG ID가 든 baseline(`baseline.live.json`). `sg-fixture-...`가 남아 있으면 AWS를 읽기 전에 ERROR(2) |
| `--output-dir` | (필수) 결과를 저장할 새 폴더. 차 있으면 **AWS를 읽기 전에** ERROR(2) |
| `--vpc-id` | 점검할 VPC. 그 VPC의 SG·ENI를 전부 읽는다. `--sg-id`와 같이 쓰면 안 된다 |
| `--sg-id` | 점검할 SG(반복 가능). 그 SG가 붙은 ENI와, **같은 ENI에 붙은 다른 SG까지** 읽어 합집합으로 판정한다. default SG 판정(SG-07)은 하지 않는다 |

- 시작할 때 `대상 계정: 1234********  리전: ...  범위: ...`을 찍는다. 계정이 예상과 다르면 결과를 쓰지 말고 다시 로그인한다.
- 필요한 권한: `ec2:DescribeVpcs`·`DescribeSecurityGroups`·`DescribeNetworkInterfaces`(보람 27번 `Haven-Minchul-SG-Read` 범위). `DescribeInstances`는 0.3.0부터 쓰지 않는다. `sts:GetCallerIdentity`는 IAM 권한 없이 된다.
- 설치: `python -m pip install --user "boto3[crt]==1.43.120"`. AWS CLI에 `aws login`(브라우저 로그인)으로 들어가 있으면 `[crt]`가 꼭 필요하다. 없으면 `MissingDependencyException` ERROR(2).
- 결과의 계정 번호는 앞 4자리만 남긴다. **SG·VPC·ENI ID는 결과 파일에 그대로 남는다**(대조용, `out/`은 Git 제외). 공개할 때는 아래 증거 묶음을 쓴다.
- AWS 오류는 코드(예: `UnauthorizedOperation`)만 남기고 원문은 남기지 않는다(원문에 ARN·계정 번호가 들어 있음).

### 증거 묶음 만들기 (명세 9장)

```bash
python make_evidence.py --results-dir out/live-YYYYMMDD-HHMM --baseline baseline.live.json [--before out/<이전 실행>] [--omission "알려진 누락"]
```

`evidence/<run-id>/`에 아래 6개 파일을 만든다. 같은 run-id 폴더가 있으면 덮어쓰지 않고 ERROR(2).

| 파일 | 내용 |
|---|---|
| `manifest.json` | commit(커밋 안 된 변경 여부 포함), 환경(Python·OS·boto3), 도구 버전, 규칙 버전(baseline SHA-256), 대상 범위, 실행 시각, 알려진 누락 |
| `masking.json` | 가림 설정: ARN·`sg-`/`vpc-`/`eni-`/`i-` 등 ID·IPv4·IPv6를 `<종류>-#<해시 8자>`로 바꿈. 계정 번호는 앞 4자리도 남기지 않고 `account-masked`(경우의 수가 적어 해시로는 되찾을 수 있음). `0.0.0.0/0`·`::/0`은 판정 근거라 그대로 |
| `results.json`, `findings.csv` | 가린 시험 결과 |
| `masking_log.json` | 종류별로 몇 개 가렸는지(원래 값은 없음) |
| `comparison.md` | `--before`를 주면 판정이 바뀐 항목 표(예: SG-07 FAIL → PASS). 범위가 다르면 경고 |

- 같은 값은 언제나 같은 가림 값이 되어 전후 비교가 된다. 원래 값 ↔ 가림 값 대응표(`masking_map.json`)는 공개 묶음이 아니라 `--results-dir`(raw 위치)에 둔다.
- 가린 뒤에도 ID·IP 모양이 남아 있으면 묶음을 만들지 않고 ERROR(2)로 멈춘다.
- 알려진 누락은 자동으로 채운다: SG 허용만 본 결과라 실제 인터넷 도달은 별도 시험, `--sg-id` 범위면 VPC 전체 아님, 수집 오류, UNKNOWN 개수.

## 시험 결과

환경: Windows, Python 3.13.2, `network_audit.py` 0.1.0, 2026-11-06 실행.

| 시험 ID | fixture | 결과 개수 | 기대 | 실제 | 종료 코드 |
|---|---|---|---|---|---|
| AUD-01 | `pass.json` | PASS 8 | PASS | PASS | 0 |
| AUD-02 | `fail_public_db.json` | PASS 8, FAIL 1 | FAIL | FAIL (SG-01: 인터넷 전체에 PostgreSQL 5432 개방) | 1 |
| AUD-09 | `unknown_role.json` | PASS 8, UNKNOWN 1 | UNKNOWN | UNKNOWN (SG-06: tmp-1은 baseline에 없는 자산) | 3 |
| AUD-08 | `error_access_denied.json` | UNKNOWN 3, ERROR 1 | ERROR | ERROR (DescribeSecurityGroups: UnauthorizedOperation). 수집 결과가 없어 alb·web-1·db-1은 UNKNOWN으로 보존 | 2 |

회귀 시험은 저장소 루트(`C:\Git4\Haven`)에서 실행한다.

```powershell
python -B -m unittest discover -s 이민성/sg_audit -p "test_*.py" -v
```

2026-11-09 실행 결과: 5개 통과(OK)

### 2026-11-13 baseline 갱신 (설계 4.2 web·db outbound TCP 80)

- 발견: 구민철(3회차 SG 점검 준비 중). baseline은 11/06 기준이라 11/09 설계 4.2에 추가된 web·db outbound TCP 80(`0.0.0.0/0`, Ubuntu apt)이 없었다. 그대로 실제 AWS를 점검하면 정상 규칙이 SG-05 FAIL로 나온다(오탐).
- 고친 것: `baseline.json`에 2줄, `fixtures/pass.json`·`fail_public_db.json`·`unknown_role.json`의 sg-web·sg-db egress에 같은 규칙, 시험의 PASS 개수 8 → 10, 새 시험 `test_outbound_80_must_match_baseline`(80이 빠짐 / 8080으로 열림 / `10.0.0.0/8`로 열림 → 모두 FAIL SG-05).
- 확인: 회귀 시험 6개 통과(OK). 고친 baseline을 예전 것으로 되돌리면 시험 3개가 실패하는 것도 확인(시험이 이 누락을 잡는다). 옛 baseline + 새 pass fixture는 PASS 8·FAIL 2(SG-05 web-1·db-1)로 오탐이 재현됨.

| 시험 ID | fixture | 결과 개수 | 판정 | 종료 코드 |
|---|---|---|---|---|
| AUD-01 | `pass.json` | PASS 10 | PASS | 0 |
| AUD-02 | `fail_public_db.json` | PASS 10, FAIL 1 | FAIL (SG-01) | 1 |
| AUD-09 | `unknown_role.json` | PASS 10, UNKNOWN 1 | UNKNOWN (SG-06) | 3 |
| AUD-08 | `error_access_denied.json` | UNKNOWN 3, ERROR 1 | ERROR | 2 |

위 11/06 표는 그때 실행 기록이라 그대로 둔다.

2026-11-13 15:20 민성 PC(Windows, Git Bash) 실행: `python -B -m unittest discover -s 이민성/sg_audit -p test_network_audit.py -v` → 6개 통과(OK, 1.356s).

추가 확인:
- 같은 `--output-dir`로 다시 실행하면 덮어쓰지 않고 ERROR(2)로 멈춘다.
- 없는 파일을 지정하면 ERROR(2)로 멈춘다.

미구현(다음 회차): `live` 모드(실제 AWS 읽기 전용 수집, 3회차 — 설계는 아래 "live 모드 설계" 절), AUD-03~07·10·11 추가 fixture.

## live 모드 설계·실행 (2026-11-13)

명세 5.1. 실제 AWS에서 SG를 **읽기만** 해서 fixture와 같은 모양으로 바꾼 뒤, 기존 판정 코드(`audit`)로 baseline과 비교한다. AWS 설정은 바꾸지 않는다.

- 실행 주체: 구현·첫 실행 이민성, 3회차 실행·대조 구민철(보람 27번 `Haven-Minchul-SG-Read`).
- 필요 패키지: `boto3[crt]`(live 모드만). fixture 모드와 시험은 boto3 없이 돈다.

### 0.2.0 → 0.3.0: 명세 5.1에 맞춤 (11/13 17시)

0.2.0은 VPC를 `Project=Haven` 태그로, 서버를 `Name` 태그로, SG를 이름(`expected_sg_names`)으로 찾았다. 명세 5.1과 어긋나 고쳤다.

| 명세 5.1 | 0.2.0 | 0.3.0 |
|---|---|---|
| `--region`·`--profile`·`--baseline`·`--output-dir` 필수, `--vpc-id`와 반복 `--sg-id` 중 하나만 | `--profile`·`--vpc-id`·`--sg-id` 없음, `--project`·`--alb-name` | 명세 형식 그대로(둘 다 주거나 둘 다 빼면 명령 오류 2) |
| STS로 대상 계정 확인 후 리전·범위와 함께 시작 시 출력 | 없음 | `GetCallerIdentity` → `대상 계정: 1234****…` 출력. 실패하면 EC2를 읽지 않고 ERROR |
| assets는 `expected_sg_ids`로 실제 자산 역할을 매핑 | `expected_sg_names`(이름) | `baseline.live.json`의 `expected_sg_ids`(Git 제외) |
| 이름/태그만으로 자산 역할을 추정하지 않음 | `Name` 태그·ALB 이름·SG 이름으로 추정 | 기대 SG ID가 붙은 ENI를 그 자산으로 본다. 이름·태그는 보지 않는다(이름만 같은 SG는 무시) |
| SG ID 선택 시 같은 자산의 추가 SG도 합집합 검사 | 해당 없음 | `--sg-id` → 그 SG가 붙은 ENI의 다른 SG까지 읽음 |
| 연결 정보가 없으면 SG 규칙 결과와 자산 접근 결과를 나누고 후자는 UNKNOWN | 해당 단계 ERROR만 | ENI 수집 실패 시 기대 SG 규칙만 판정 + 자산마다 UNKNOWN + ERROR |

### 수집 순서 (27번 권한 안에서만)

| 순서 | API | `--vpc-id` | `--sg-id` | 실패하면 |
|---|---|---|---|---|
| 0 | `sts:GetCallerIdentity` | 계정 확인 | 계정 확인 | ERROR, EC2는 안 읽음 |
| 1 | `ec2:DescribeVpcs` | 지정 VPC 1개(없거나 다른 계정 것이면 ERROR) | 부르지 않음 | ERROR |
| 2 | `ec2:DescribeNetworkInterfaces` | 그 VPC의 ENI 전부, 모든 페이지 | 지정 SG가 붙은 ENI | ERROR + 자산 UNKNOWN(SG 규칙은 판정) |
| 3 | `ec2:DescribeSecurityGroups` | 그 VPC의 SG 전부, 모든 페이지 | 지정 SG + 같은 ENI의 다른 SG | ERROR |

자산 연결 판정:
- ENI에 붙은 SG 중 baseline `expected_sg_ids`에 있는 것으로 주인 자산을 정하고, 그 ENI의 SG 전부를 그 자산의 연결로 본다(ALB ENI 2개처럼 여러 개면 합침).
- 한 ENI에 서로 다른 자산의 기대 SG가 같이 있으면 **역할 미확정 UNKNOWN**(SG-06).
- 기대 SG가 하나도 없는 ENI(VPC 엔드포인트, 새로 바뀐 SG 등)는 `eni:<ID>` 자산으로 두어 **baseline에 없는 자산 UNKNOWN**.
- default SG는 AWS가 정한 이름 `default`로 찾는다(역할 추정이 아니라 AWS 고정값). SG-07은 `--vpc-id`에서만 판정한다.
- 요청 제한(Throttling)·일시 오류는 3번까지 시도하고, 그래도 실패하면 ERROR. 결과의 계정 번호는 앞 4자리만 남긴다.

### 일부러 실패시키는 시험 (`test_live.py`, 가짜 EC2·STS, boto3 없이)

| ID | 상황 | 기대 |
|---|---|---|
| L1 | 설계대로 + default SG 비어 있음 | PASS (0), 시작 줄에 가린 계정·리전·범위 |
| L2 | default SG에 기본 규칙 있음 | FAIL SG-07 (1) |
| L3 | `DescribeSecurityGroups` 권한 거부 | ERROR (2), PASS 0개 |
| L4 | `DescribeNetworkInterfaces`만 거부 | ERROR (2), SG 규칙 결과는 남고 자산 3개는 UNKNOWN |
| L5 / L5-b / L5-c | 로그인 만료(STS 실패) / boto3 없음 / 없는 프로필 | ERROR (2), EC2 안 읽음, Traceback 없음 |
| L6 | 지정 VPC 없음 / 다른 계정 VPC | ERROR (2), 더 읽지 않음 |
| L7 / L8 | web-1 ENI 없음 / ALB ENI 없음 | UNKNOWN (3) |
| L9 | SG·ENI가 여러 페이지 | 마지막 페이지까지 읽고 PASS |
| L10 | 지우는 걸 잊은 SG | UNKNOWN SG-06 (3) |
| L11 | 한 ENI에 web·db SG가 같이 | 역할 미확정 UNKNOWN (3) |
| L11-b | SG 이름이 바뀜 + 이름만 같은 가짜 SG | 판정 그대로(PASS 11), 가짜는 연결 없음 UNKNOWN |
| L12 | Throttling 2번 후 성공 / 계속 | PASS / 3번 시도 후 ERROR |
| L13 | IPv6 `::/0` 22번·prefix list | FAIL SG-01 / SG-05 |
| L14 | 출력 폴더가 이미 차 있음 | STS·EC2 모두 읽기 전에 ERROR (2) |
| L15 | ALB ENI 2개(같은 SG) | 중복 없이 판정 |
| L16 / L16-b / L16-c | `--sg-id` web: 같은 ENI의 22번 공개 SG / 정상 / default SG가 같이 붙음 | FAIL SG-01(합집합, AUD-11) / PASS 4 / SG-07 판정 안 함 |
| L17 | 없는 `--sg-id` | ERROR (2) |
| L18 | `sg-fixture-...` baseline 그대로 | AWS 읽기 전 ERROR (2) |
| L19 | db SG가 새 SG로 바뀜 | db-1 UNKNOWN + 모르는 ENI UNKNOWN (PASS 아님) |
| L20 | VPC 엔드포인트 ENI | UNKNOWN `eni:...` |
| CLI 4개 | `--profile`·`--region` 빠짐 / 범위 없음 / `--vpc-id`+`--sg-id` | 명령 오류 (2) |

- 뮤테이션 확인(11/13, 0.3.0): 합집합 안 읽기, 역할 미확정 무시, VPC 소유 계정 무시, 모르는 ENI 무시, `--sg-id` 범위 밖 자산을 UNKNOWN으로 셈, ENI 실패를 PASS로, SG 범위에서 SG-07 판정, 계정 번호 안 가림, fixture baseline 허용 — 9가지 모두 시험이 잡음.

### 실행 기록 — 0.2.0 (11/13, 민성 PC Windows Git Bash, IAM 사용자 minsung)

0.2.0(태그·이름으로 찾던 방식)으로 실행한 기록이다. 판정 대상 규칙은 같지만 명세 5.1 형식이 아니라 0.3.0으로 다시 실행한다(아래).

| 시각 | 한 일 | 결과 |
|---|---|---|
| 15:38 | 전체 시험 `python -B -m unittest discover -s 이민성/sg_audit -p "test_*.py" -v` | 27개 통과(OK, 1.518s) |
| 15:41 | live 첫 실행 (boto3만 설치) | ERROR(2) `setup: MissingDependencyException`. `aws login` 로그인 정보를 읽으려면 `botocore[crt]`가 필요. AWS는 읽지 않음 |
| 15:42~15:45 | `python -m pip install --user "boto3[crt]==1.43.120"` (web-1과 같은 버전) | `boto3.client("ec2")` 생성 OK |
| 15:45 | live 실행 | COMPLETE, PASS 10, FAIL 2(SG-07 default SG 기본 규칙 2개), 종료 코드 1. 우리 SG 3개 규칙 10개는 설계 4장과 일치 |
| 15:48 | default SG 사용처 확인(읽기 전용): ENI·EC2(중지 포함)에 붙은 곳, 다른 SG 규칙의 참조 | ENI 0, EC2 0, 참조는 default 자기 자신(기본 규칙)뿐 → 비워도 영향받는 리소스 없음 |
| 16:14 | 보람이 default SG 하나에 한정한 규칙 삭제 권한 추가 → 삭제 전 규칙 확인 | 들어옴 `-1` ← 자기 자신, 나감 `-1` → `0.0.0.0/0` 두 개뿐 |
| 16:15 | `revoke-security-group-ingress`·`revoke-security-group-egress` → 다시 확인 | 두 규칙 삭제, `[[], []]`(비어 있음) |
| 16:15 | live 실행 | **COMPLETE, PASS 11, FAIL 0, UNKNOWN 0, ERROR 0, 종료 코드 0** |

- 기록에는 계정 번호·VPC·SG ID를 적지 않는다(결과 파일 `out/live-*`에는 남아 있고 `out/`은 Git 제외).
- 되돌리기: 같은 두 규칙을 `authorize-security-group-ingress`·`authorize-security-group-egress`로 다시 넣는다.
- default SG 규칙 삭제(16:15)는 AWS 설정 변경이라 0.3.0으로 다시 실행해도 그대로 유지된다.

