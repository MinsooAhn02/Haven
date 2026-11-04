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
