# 민수 IAM 추가 권한 요구(2026-11-09) — 적용 전 점검

## 1. 요청
- IAM 사용자 `minsoo`: 최초 로그인 뒤 MFA 본인 등록 및 자신의 비밀번호 변경
- 서울 리전 `ap-northeast-2`에서 AWS CloudShell 환경 생성·사용

## 2. 정책과 적용 방법
1. `09_IAM_Self_MFA_Password_Policy.json`의 `${AWS_ACCOUNT_ID}`를 해당 계정 ID로 치환한 뒤 IAM 정책으로 생성한다. `${aws:username}`은 IAM이 평가하는 정책 변수이므로 **그대로 둔다**.
2. `minsoo` 사용자에게 위 MFA·비밀번호 정책을 연결한다. 이민성 등 본인 MFA 등록이 필요한 IAM 사용자에게도 같은 정책을 재사용할 수 있다.
3. `minsoo` 사용자에게 AWS 관리형 정책 `AWSCloudShellFullAccess`를 직접 연결한다. 서울 리전에서 CloudShell 실행을 확인한다.
4. CloudShell 사용 권한은 EC2/VPC/S3 등 리소스 자체의 추가 권한을 자동 부여하지 않는다. 필요한 서비스 작업은 역할별 최소 권한 정책으로 별도 심사한다.

## 3. 현재 상태 및 시험
- **GitHub 정책 파일/안내 문서만 준비된 상태. AWS에서 위 두 권한을 아직 추가했다고 주장하지 않는다.**
- `minsoo` 담당자 보고: IAM 사용자로 로그인은 성공했으나 `iam:ListMFADevices` 거부, CloudShell 생성 거부.
- 연결 뒤 확인: 민수 본인 MFA 등록 성공, 자신 비밀번호 변경 확인, CloudShell 서울 리전 실행 성공.
- 부정 시험: `minsoo`가 **다른 IAM 사용자의 MFA·비밀번호·역할**을 수정하지 못하는지 확인한다.
- MFA 활성화 전에는 실제 인프라를 변경하는 명령 실행을 보류한다.

참고: AWS IAM 공식 자체 MFA 정책 예시 및 AWS 관리형 `AWSCloudShellFullAccess`.
