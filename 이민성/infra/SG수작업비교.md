# build.sh 1부 수작업 비교: 보안 그룹 규칙

`DRY_RUN=1`로 출력한 명령이 [설계.md](../network/설계.md) 4절 SG 표와 같은지 사람이 한 줄씩 대조한 기록이다.

- **확인자**: 이민성
- **날짜**: 2026-11-09
- **실행 명령** (`이민성/infra`에서): `DRY_RUN=1 bash build.sh`
- **AWS 호출**: 없음 (DRY_RUN은 명령을 출력만 한다)
- **확인 방법**: 이민성 수작업 대조 (이민성 전부 설명가능 SG부분만 설계.md 의 4절과 터미널에서 나온 로그 하나씩 비교함)

## 1. 출력 한 줄을 읽는 법

예시:

```
aws ... ec2 authorize-security-group-ingress --group-id sg-DRYRUN-sg-alb --ip-permissions 'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]'
```

| 부분 | 뜻 |
|---|---|
| `authorize-security-group-ingress` | 인바운드 규칙 추가 (남이 이 서버로 먼저 거는 연결) |
| `authorize-security-group-egress` | 아웃바운드 규칙 추가 (이 서버가 밖으로 먼저 거는 연결) |
| `--group-id sg-DRYRUN-sg-alb` | 규칙을 넣을 SG (받는 쪽 문지기) |
| `FromPort=443,ToPort=443` | 포트 |
| `IpRanges=[{CidrIp=...}]` | 상대가 IP 범위 |
| `UserIdGroupPairs=[{GroupId=...}]` | 상대가 다른 SG (그 SG가 붙은 서버) |

- 인바운드면 상대는 출발지, 아웃바운드면 상대는 목적지다.
- SG는 트래픽을 보내지 않고, 들어오고 나가는 것을 허용할지만 정한다. 목록에 없으면 막는다.
- 상태 저장(stateful)이라 내가 먼저 시작한 연결의 답장은 규칙 없이 통과한다.

## 2. 출력 구조

| 출력 줄 | 내용 | 대조 대상 |
|---|---|---|
| 35 | `5/5 보안 그룹` 제목 | — |
| 36~44 | SG 3개 생성(`create-security-group`) + 각자 기본 아웃바운드 전체 허용 삭제(`revoke-security-group-egress`) + ID 기록 | SG 이름 |
| 45~48 | `authorize-...-ingress` 4줄 | 설계 4.1 |
| 49~54 | `authorize-...-egress` 6줄 | 설계 4.2 |

SG 3개를 먼저 다 만드는 이유: 규칙이 서로의 SG ID를 가리키기 때문이다(예: sg-web 인바운드의 출발지가 sg-alb).

## 3. 대조 결과

출력 줄 번호는 2026-11-09 14:06 실행 결과 기준이다.

### 3.1 인바운드 (설계 4.1)

| 출력 줄 | SG | 포트 | 출발지 | 설계 4.1 | 일치 |
|---|---|---|---|---|---|
| 45 | sg-alb | 443 | 0.0.0.0/0 | sg-alb · TCP 443 · 0.0.0.0/0 (사용자 HTTPS) | ✅ |
| 46 | sg-alb | 80 | 0.0.0.0/0 | sg-alb · TCP 80 · 0.0.0.0/0 (HTTPS redirect) | ✅ |
| 47 | sg-web | 80 | sg-alb | sg-web · TCP 80 · sg-alb (ALB → Nginx만) | ✅ |
| 48 | sg-db | 5432 | sg-web | sg-db · TCP 5432 · sg-web (Web → PostgreSQL만) | ✅ |

### 3.2 아웃바운드 (설계 4.2)

| 출력 줄 | SG | 포트 | 목적지 | 설계 4.2 | 일치 |
|---|---|---|---|---|---|
| 49 | sg-alb | 80 | sg-web | sg-alb · TCP 80 · sg-web (요청 전달·health check) | ✅ |
| 50 | sg-web | 5432 | sg-db | sg-web · TCP 5432 · sg-db (DB 연결) | ✅ |
| 51 | sg-web | 443 | 0.0.0.0/0 | sg-web · TCP 443 · 0.0.0.0/0 (SSM·패키지·AWS API·메일 API) | ✅ |
| 52 | sg-web | 80 | 0.0.0.0/0 | sg-web · TCP 80 · 0.0.0.0/0 (Ubuntu apt) | ✅ |
| 53 | sg-db | 443 | 0.0.0.0/0 | sg-db · TCP 443 · 0.0.0.0/0 (SSM·패키지·백업) | ✅ |
| 54 | sg-db | 80 | 0.0.0.0/0 | sg-db · TCP 80 · 0.0.0.0/0 (Ubuntu apt) | ✅ |

### 3.3 반대 방향 확인

출력에 있는 규칙만 보면, 설계에 있는데 출력에서 빠진 규칙을 놓친다. 그래서 설계 표를 기준으로도 한 번 더 본다.

| 확인 | 결과 |
|---|---|
| 설계 4.1·4.2에 있는데 출력에 없는 규칙 | 없음 (설계 10줄 모두 출력에 짝이 있음) |
| 출력에 있는데 설계에 없는 규칙 | 없음 |
| 기본 아웃바운드 전체 허용 삭제 (`revoke`) | SG 3개 모두 있음 (37·40·43줄) |
| 한 연결의 양쪽 문이 모두 열림 | ALB→Web 80: 49줄(alb 아웃) + 47줄(web 인) / Web→DB 5432: 50줄(web 아웃) + 48줄(db 인) |

## 4. 결론

- 인바운드 4줄, 아웃바운드 6줄이 설계 4.1·4.2와 모두 일치한다. 빠진 규칙도, 설계에 없는 규칙도 없다.
- 새 SG의 기본 아웃바운드 전체 허용은 3개 모두 삭제되어, 설계에 적은 허용 목록만 남는다.

## 5. 이 비교로 확인하지 못한 것

- 실제 AWS가 이 명령을 받아들이는지: 수요일 구축 때 확인
- 구축 후 실제 SG 상태: `describe-security-groups` 또는 SG CLI live 모드로 다시 대조
- 22·3389가 없다는 것(SG-01): 출력에 22·3389 규칙이 없음은 확인했지만, 구축 후 실제 SG에서 다시 확인 (연결확인표 SSM-04)