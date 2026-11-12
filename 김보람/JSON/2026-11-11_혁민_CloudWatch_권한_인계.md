# 2026-11-11 권혁민 AWS 로그 조회 권한 및 Web 로그 전송 인계

## AWS 설정 완료 (보람 작업, 콘솔 화면 확인)

- IAM 사용자 `hyeokmin` 생성, 콘솔 로그인용 임시 비밀번호 및 첫 로그인 변경 설정. 비밀번호 원문은 저장소에 기재하지 않음.
- `hyeokmin` 사용자에 **총 4개 정책이 연결된 AWS 콘솔 화면 확인** (11/11, MFA 정책 추가 후).
  - `IAMUserChangePassword`: 자신의 콘솔 암호 변경
  - `Haven-IAM-Self-MFA-Password`: 자신의 MFA 등록 및 관리용 고객 관리형 정책 ([09번 정책 JSON](09_IAM_Self_MFA_Password_Policy.json)과 같은 내용으로 생성하도록 안내). **정책 연결만 확인했고, 실제 MFA 등록은 혁민님이 해야 함.**
  - `Haven-Hyeokmin-CloudWatch-Read`: 서울 로그 그룹 목록, `/haven/web` 로그 스트림·이벤트 조회
  - `Haven-Hyeokmin-EC2-WAF-LogQuery-Read`: 서울 EC2 조회(`ec2:Describe*`), `/haven/web` 로그 검색, 서울 리전 WAF Web ACL 목록·상세 조회
- EC2 역할 `haven-ec2-ssm-role`에 인라인 정책 `Haven-EC2-Web-CloudWatch-Write`가 추가된 화면 확인.
  - `/haven/web` 기존 로그 그룹의 스트림 확인·생성 및 로그 이벤트 전송 권한
  - 기존 SSM·S3·파라미터 정책은 그대로 유지
- 혁민용 두 정책에 `ssm:StartSession`은 추가하지 않음.

**04번은 이전 설계 초안:** [`04_Web_Logs_Policy.json`](04_Web_Logs_Policy.json)은 미적용 초안이고, 현재 EC2 역할에 실제 연결된 로그 쓰기 정책 기록은 **22번**임.

## 대응하는 JSON 기록

| AWS 정책 | GitHub JSON |
|---|---|
| `Haven-Hyeokmin-CloudWatch-Read` | [20_Hyeokmin_CloudWatch_Read_Policy.json](20_Hyeokmin_CloudWatch_Read_Policy.json) |
| `Haven-Hyeokmin-EC2-WAF-LogQuery-Read` | [21_Hyeokmin_EC2_WAF_LogQuery_Read_Policy.json](21_Hyeokmin_EC2_WAF_LogQuery_Read_Policy.json) |
| `Haven-EC2-Web-CloudWatch-Write` (역할 인라인) | [22_EC2_Web_CloudWatch_Write_Policy.json](22_EC2_Web_CloudWatch_Write_Policy.json) |

위 JSON은 AWS 정책 생성 시 사용하도록 안내한 내용으로 기록함. **AWS 정책 JSON 탭 원문과 문자 단위 재대조는 미수행**(정책 이름·연결 상태는 콘솔 화면으로 확인).

## 아직 확인하지 않은 항목 / 담당

- **민성:** CloudWatch Logs `/haven/web` 로그 그룹 존재 여부 확인, 없으면 생성. `web-1`에 CloudWatch Agent 또는 서버 로그 수집 설정, OUT-10 전송 시험. 현재 역할에는 `logs:CreateLogGroup` 권한 없음(기존 그룹을 전제로 함).
- **혁민:** 자신의 IAM 계정으로 로그인, 비밀번호 변경·MFA 등록, 로그 목록/읽기/검색 실제 성공 및 SSM `StartSession` 거부 확인. WAF/EC2 조회 시험도 별도.
- **보람:** 위 시험에서 정확한 `AccessDenied` 액션이 나오면 필요한 최소 권한만 검토. 사용자 콘솔 생성만으로 로그 전송·조회 성공을 주장하지 않음.

**참고:** `haven-ec2-ssm-role`은 Web/DB 공통 역할로 설계됨. 이 정책은 Web 로그 그룹에 대한 쓰기를 허용할 뿐, 서버별 에이전트 설치나 로그 수집 자체를 수행하지 않음.
