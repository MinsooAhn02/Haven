# 1. AWS 클라우드 환경 구축 및 서비스 확장
### 필수
AWS EC2를 활용하여 클라우드 서버를 구축하고, Web 및
DB 서비스를 구성하여 클라우드 기반 서비스 운영 환경을
구현한다.
---
### 도전
도메인을 연결하고 메일, DNS 등 외부 서
비스를 연동하여 클라우드 서비스의 접근
및 운영 환경을 확장한다.
---
<img width="2432" height="1350" alt="image" src="https://github.com/user-attachments/assets/302c2bda-b52b-449c-b8ba-3249fd798501" />

---

# 2. IAM 사용자 및 권한 관리
### 필수
AWS IAM 사용자와 그룹을 생성하고, 정책을 적용하여 사
용자별 접근 권한 및 클라우드 리소스 관리 환경을 구성한
다.
---
### 도전
최소 권한 원칙을 적용하여 안전한 클라우
드 접근 통제 환경을 구축하고, 과도한 권
한 및 불필요한 접근 권한을 점검한다.
---
* IAM 그룹 설계

| 그룹 | 담당 | 적용 정책 | 권한 범위 |
|---|---|---|---|
| Admins | 전체 관리 | AdministratorAccess (AWS 관리형) | 모든 리소스 (1~2명만) |
| WebOps | 웹 서버 운영 | WebOps-EC2-Policy (사용자 지정) | EC2 조회 + `Project=myshop` 태그 인스턴스 시작/중지/재부팅 |
| DBOps | DB 백업 관리 | DBOps-S3-Backup-Policy (사용자 지정) | `myshop-db-backup` 버킷 목록 조회, 객체 읽기/쓰기 |
| Auditors | 점검·감사 | ReadOnlyAccess (AWS 관리형) | 전체 리소스 읽기 전용 |

### 사용자 배정 예시

| 사용자 | 소속 그룹 | MFA |
|---|---|---|
| admin-user | Admins | 필수 |
| web-user | WebOps | 필수 |
| db-user | DBOps | 필수 |
| audit-user | Auditors | 필수 |

### 설계 원칙
- 사용자에게 정책을 직접 연결하지 않고, **그룹 단위로만 권한 부여**
- 업무에 필요한 최소 권한만 허용 (**최소 권한 원칙**)
- 루트 계정은 MFA 적용 후 일상 작업에 사용하지 않음
- 정기적으로 자격 증명 보고서·마지막 액세스 정보를 확인하여 불필요한 권한 회수
---
## 최소 권한 정책 (사용자 지정 정책)

### 1. WebOps-EC2-Policy (WebOps 그룹)
- 목적: 웹 서버 운영자가 EC2를 **조회**하고, `Project=myshop` 태그가 붙은 인스턴스만 **시작/중지/재부팅**할 수 있도록 허용
- 제외: 인스턴스 생성·종료(Terminate), 보안 그룹·VPC 수정 등은 허용하지 않음 (명시적으로 허용하지 않으면 기본 거부)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowDescribeEC2",
      "Effect": "Allow",
      "Action": "ec2:Describe*",
      "Resource": "*"
    },
    {
      "Sid": "AllowStartStopTaggedInstances",
      "Effect": "Allow",
      "Action": [
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:RebootInstances"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/Project": "myshop"
        }
      }
    }
  ]
}
```

### 2. DBOps-S3-Backup-Policy (DBOps 그룹)
- 목적: DB 담당자가 **백업 버킷 하나만** 목록 조회, 백업 파일 다운로드/업로드할 수 있도록 허용
- 제외: 다른 버킷 접근, 버킷 삭제, 버킷 정책 변경은 불가

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowListBackupBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::myshop-db-backup"
    },
    {
      "Sid": "AllowReadWriteBackupObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::myshop-db-backup/*"
    }
  ]
}
```

### 3. DB-EC2-Backup-Role-Policy (DB EC2에 연결하는 IAM 역할)
- 목적: DB 서버가 자동 백업 파일을 S3에 **업로드만** 할 수 있도록 허용
- 제외: 읽기·삭제 불가 → 서버가 탈취되어도 기존 백업을 지우거나 빼낼 수 없음
- 신뢰 관계: `ec2.amazonaws.com`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowUploadBackupOnly",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::myshop-db-backup/*"
    }
  ]
}
```
### 정책 적용 요약

| 정책 | 연결 대상 | 허용 | 거부(기본) |
|---|---|---|---|
| WebOps-EC2-Policy | WebOps 그룹 | EC2 조회, 태그 인스턴스 시작/중지/재부팅 | 생성·종료, 네트워크 변경 |
| DBOps-S3-Backup-Policy | DBOps 그룹 | 백업 버킷 조회·읽기·쓰기 | 다른 버킷, 버킷 삭제·정책 변경 |
| DB-EC2-Backup-Role-Policy | DB EC2 (IAM 역할) | 백업 버킷 업로드 | 읽기·삭제 |
---
<img width="1266" height="1046" alt="image" src="https://github.com/user-attachments/assets/02553e47-b3ff-4aa5-b571-0fb04759cfed" />

---

# 3. 클라우드 네트워크 보안 설정 및 접근 통제
### 필수 
VPC, 서브넷, 보안 그룹 및 네트워크 접근 설정을 구성하고
, 클라우드 서비스에 대한 외부 및 내부 접근 통제 환경을
구축한다.
---
### 도전
보안 그룹 및 네트워크 설정을 점검하여 불
필요하게 허용된 외부 접근과 개방 포트를
자동으로 확인하는 기능을 구현한다.
---

## 1. VPC와 서브넷 구성

### 네트워크 구성

| 항목 | 값 | 설명 |
|---|---|---|
| VPC | `10.0.0.0/16` | 전체 사설 네트워크 |
| 퍼블릭 서브넷 | `10.0.1.0/24` | Web EC2, NAT 게이트웨이 배치 |
| 프라이빗 서브넷 | `10.0.2.0/24` | DB EC2 배치 (퍼블릭 IP 없음) |
| 인터넷 게이트웨이 | VPC에 연결 | 퍼블릭 서브넷의 인터넷 출입구 |
| NAT 게이트웨이 | 퍼블릭 서브넷에 생성 | 프라이빗 서브넷의 외부 **아웃바운드만** 허용 (패키지 설치용) |
| S3 게이트웨이 엔드포인트 | 프라이빗 라우팅 테이블에 연결 | DB → S3 백업 시 인터넷을 거치지 않고 AWS 내부망으로 전송 |

### 라우팅 테이블

**퍼블릭 라우팅 테이블** (퍼블릭 서브넷 연결)

| 대상 | 타겟 | 설명 |
|---|---|---|
| `10.0.0.0/16` | local | VPC 내부 통신 |
| `0.0.0.0/0` | 인터넷 게이트웨이 | 인터넷 양방향 통신 |

**프라이빗 라우팅 테이블** (프라이빗 서브넷 연결)

| 대상 | 타겟 | 설명 |
|---|---|---|
| `10.0.0.0/16` | local | VPC 내부 통신 (Web ↔ DB) |
| `0.0.0.0/0` | NAT 게이트웨이 | 외부로 나가는 트래픽만 허용 |
| S3 접두사 목록 (`pl-xxxx`) | S3 게이트웨이 엔드포인트 | S3 백업 전용 경로 |

### 설계 의도
- **외부 접근 통제**: DB는 프라이빗 서브넷에 두고 퍼블릭 IP를 부여하지 않아 인터넷에서 직접 접근할 수 없음
- **내부 통신**: 같은 VPC 안의 서브넷끼리는 `local` 경로로 자동 통신 → Web EC2가 DB EC2의 사설 IP로 접속
- **아웃바운드 제한**: NAT 게이트웨이는 내부 → 외부 요청만 허용하고, 외부 → 내부 접속은 차단
- **비용 및 보안**: S3 엔드포인트로 백업 트래픽이 인터넷에 노출되지 않으며 NAT 데이터 처리 비용도 절감

---

## 2. 보안 그룹 (인스턴스 단위 접근 통제)

### Web-SG (Web EC2)

| 방향 | 프로토콜 | 포트 | 소스/대상 | 이유 |
|---|---|---|---|---|
| 인바운드 | TCP | 80 | `0.0.0.0/0` | HTTP 웹 서비스 공개 |
| 인바운드 | TCP | 443 | `0.0.0.0/0` | HTTPS 웹 서비스 공개 |
| 인바운드 | TCP | 22 | 관리자 IP `/32` | 관리자만 SSH 접속 |
| 아웃바운드 | 전체 | 전체 | `0.0.0.0/0` | 기본값 (응답 및 외부 요청) |

### DB-SG (DB EC2)

| 방향 | 프로토콜 | 포트 | 소스/대상 | 이유 |
|---|---|---|---|---|
| 인바운드 | TCP | 3306 | Web-SG | 웹 서버만 DB 접근 |
| 인바운드 | TCP | 22 | Web-SG | 점프 서버(Web EC2) 경유 SSH만 허용 |
| 아웃바운드 | 전체 | 전체 | `0.0.0.0/0` | 기본값 (NAT·S3 엔드포인트 경유) |

### 설계 의도
- 소스를 IP가 아닌 **보안 그룹(Web-SG)으로 지정** → Web EC2의 IP가 바뀌어도 규칙 유지
- DB는 퍼블릭 IP가 없고 보안 그룹도 Web-SG만 허용 → **외부에서 DB 직접 접근 불가**
- SSH(22)는 `0.0.0.0/0`으로 열지 않고 관리자 IP로 제한
- 보안 그룹은 **상태 저장(stateful)** → 허용된 요청의 응답은 자동 허용

---

## 3. 네트워크 ACL (서브넷 단위, 이중 방어)

> NACL은 **상태 비저장(stateless)** → 응답 트래픽용 임시 포트(1024-65535)를 인바운드·아웃바운드 모두 허용해야 함.
> 규칙 번호가 낮은 순서대로 평가되며, 마지막에 기본 거부(`*` DENY) 규칙이 적용됨.

### Public-NACL (퍼블릭 서브넷)

| 방향 | 규칙 번호 | 포트 | 소스/대상 | 허용/거부 |
|---|---|---|---|---|
| 인바운드 | 100 | 80 | `0.0.0.0/0` | 허용 |
| 인바운드 | 110 | 443 | `0.0.0.0/0` | 허용 |
| 인바운드 | 120 | 22 | 관리자 IP `/32` | 허용 |
| 인바운드 | 130 | 1024-65535 | `0.0.0.0/0` | 허용 (응답 트래픽) |
| 인바운드 | * | 전체 | `0.0.0.0/0` | 거부 |
| 아웃바운드 | 100 | 80, 443 | `0.0.0.0/0` | 허용 |
| 아웃바운드 | 110 | 3306, 22 | `10.0.2.0/24` | 허용 (DB 접속) |
| 아웃바운드 | 120 | 1024-65535 | `0.0.0.0/0` | 허용 (응답 트래픽) |
| 아웃바운드 | * | 전체 | `0.0.0.0/0` | 거부 |

### Private-NACL (프라이빗 서브넷)

| 방향 | 규칙 번호 | 포트 | 소스/대상 | 허용/거부 |
|---|---|---|---|---|
| 인바운드 | 100 | 3306 | `10.0.1.0/24` | 허용 (Web → DB) |
| 인바운드 | 110 | 22 | `10.0.1.0/24` | 허용 (점프 서버 SSH) |
| 인바운드 | 120 | 1024-65535 | `0.0.0.0/0` | 허용 (NAT·S3 응답) |
| 인바운드 | * | 전체 | `0.0.0.0/0` | 거부 |
| 아웃바운드 | 100 | 80, 443 | `0.0.0.0/0` | 허용 (NAT·S3 엔드포인트) |
| 아웃바운드 | 110 | 1024-65535 | `10.0.1.0/24` | 허용 (Web으로 응답) |
| 아웃바운드 | * | 전체 | `0.0.0.0/0` | 거부 |

### 보안 그룹 vs NACL

| 구분 | 보안 그룹 | 네트워크 ACL |
|---|---|---|
| 적용 단위 | 인스턴스(ENI) | 서브넷 |
| 상태 | Stateful (응답 자동 허용) | Stateless (응답 포트 별도 허용) |
| 규칙 | 허용만 가능 | 허용·거부 모두 가능 |
| 평가 | 모든 규칙 종합 | 번호 순서대로 평가 |

---

## 4. 개방 포트 자동 점검 기능

### 동작 구조
```
EventBridge (매일 실행)
   ↓
Lambda (모든 보안 그룹 검사)
   ↓  0.0.0.0/0 에 80·443 외 포트가 열려 있으면
SNS (관리자에게 경고 메일 발송)
```

### 점검 기준
- `0.0.0.0/0` 또는 `::/0`(전체 인터넷)에 열린 규칙만 검사
- **허용 포트**: 80, 443 (웹 서비스)
- **탐지 대상**: 그 외 모든 포트 (예: 22, 3306, 전체 포트 개방)

### ① SNS 설정
1. SNS → 주제 생성 → 유형: 표준 → 이름: `sg-alert`
2. 구독 생성 → 프로토콜: 이메일 → 관리자 이메일 입력
3. 수신한 메일에서 **구독 확인(Confirm subscription)** 클릭

### ② Lambda 함수 (Python 3.12)
- 함수 이름: `sg-open-port-checker`
- 환경 변수: `TOPIC_ARN` = SNS 주제 ARN

```python
import boto3, os

ALLOWED_PUBLIC_PORTS = {80, 443}
ec2 = boto3.client('ec2')
sns = boto3.client('sns')

def lambda_handler(event, context):
    findings = []
    for page in ec2.get_paginator('describe_security_groups').paginate():
        for sg in page['SecurityGroups']:
            for p in sg['IpPermissions']:
                public = any(r.get('CidrIp') == '0.0.0.0/0' for r in p.get('IpRanges', [])) \
                      or any(r.get('CidrIpv6') == '::/0' for r in p.get('Ipv6Ranges', []))
                if not public:
                    continue
                name = f"{sg['GroupId']} ({sg['GroupName']})"
                if p['IpProtocol'] == '-1':
                    findings.append(f"{name}: 모든 포트가 전체 개방됨")
                else:
                    fr, to = p.get('FromPort'), p.get('ToPort')
                    if not (fr == to and fr in ALLOWED_PUBLIC_PORTS):
                        findings.append(f"{name}: {p['IpProtocol']} {fr}-{to} 포트가 전체 개방됨")
    if findings:
        sns.publish(
            TopicArn=os.environ['TOPIC_ARN'],
            Subject='[경고] 보안 그룹 개방 포트 점검 결과',
            Message='\n'.join(findings)
        )
    return {'count': len(findings), 'findings': findings}
```

### ③ Lambda 실행 역할 (최소 권한)
- `AWSLambdaBasicExecutionRole` (CloudWatch 로그 기록용)
- 사용자 지정 정책:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadSecurityGroups",
      "Effect": "Allow",
      "Action": "ec2:DescribeSecurityGroups",
      "Resource": "*"
    },
    {
      "Sid": "PublishAlert",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:ap-northeast-2:계정ID:sg-alert"
    }
  ]
}
```

### ④ EventBridge 스케줄
- EventBridge → 일정(Scheduler) → 일정 생성
- 일정 패턴: `rate(1 day)` (또는 cron `0 9 * * ? *` → 매일 오전 9시 UTC)
- 대상: Lambda → `sg-open-port-checker`

### ⑤ 테스트 시나리오

| 단계 | 작업 | 기대 결과 |
|---|---|---|
| 1 | 테스트용 보안 그룹에 22번을 `0.0.0.0/0`으로 개방 | - |
| 2 | Lambda **테스트** 실행 | `count: 1`, 경고 메일 수신 |
| 3 | 해당 규칙 삭제 후 재실행 | `count: 0`, 메일 미발송 |
| 4 | CloudWatch Logs 확인 | 실행 기록 확인 |

### 기대 효과
- 실수로 열린 SSH·DB 포트 등 **불필요한 외부 개방을 자동 탐지**
- 사람이 매번 확인하지 않아도 **매일 정기 점검**
- 점검용 Lambda 역시 **읽기 + 알림 권한만** 부여하여 최소 권한 원칙 유지


