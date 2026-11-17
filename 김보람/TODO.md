# 4번 김보람 TODO

**브랜치:** `Boram`

**담당:** 계정 소유·IAM·개인별 접근·비용/자원 관리

**공통 순서:** [TASK_TODO.md](../TASK_TODO.md)

## 수정 범위

본인 폴더의 account/·iam/·권한 시험·비용/자원표. 실제 계정/IAM/비용 알림은 본인만 변경한다. SG·서버·WAF는 각 담당자에게 요청한다.

## 2일 단위 임무

### 1회차 · 1~2일차

- [ ] 계정 루트 MFA·복구 수단·기존 자원을 확인한다. 개인별 접근/MFA·역할과 예산/알림·비용 부담·리전·종료 책임을 확정한다. 필요한 IAM 정책과 허용/거부 시험을 준비한다.
- [x] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 2회차 · 3~4일차

- [ ] 검토한 개인별 운영/점검·서버 Role을 구성하고 필요한 작업 성공·무관 작업 거부를 확인한다. 이민성에게 승인된 서버 Role/연결 권한을 전달하고 자원/비용표를 갱신한다.
- [x] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 3회차 · 5~6일차

- [ ] SG 점검·레드팀 결과 중 IAM 문제를 수정/재시험한다. WAF·로그·메일에 필요한 권한을 범위별 검토하고 비용/권한 변경을 기록한다.
- [x] 검증 결과를 아래에 기록하고 main 통합용 PR 제출

### 4회차 · 7~8일차

- [ ] 권한 허용/거부 결과와 잔여 비용을 최종 확인한다. 보존/종료 목록을 취합하고 별도 확인 후 각 자원 담당자가 종료하도록 관리한다.
- [ ] 검증 결과를 아래에 기록하고 main 통합용 PR 제출 (최종 4회차 검증·인계 결과 기록 및 병합 확인 대기)

## 인계·완료 기준

- 이민성에게 승인된 역할/자원 범위, 안민수에게 예산·계정 결정 전달
- 루트 비밀번호·MFA·공용 키를 공유하지 않으며 비밀값은 Git에 올리지 않음
- 비용 알림은 자동 지출 차단이 아니며 EC2 중지 후 ALB/NAT/Endpoint/EBS 비용도 확인
- 본인 검증과 검토 결과가 있는 변경만 main에 합친다. 미완료 작업은 다음 회차로 넘기며 다른 담당자에게 알린다.
- 회차 통합 후 최신 main을 본인 브랜치에 반영하고 다음 회차를 시작한다.
  

&nbsp;

## 결과 기록

| 회차 | 상태 | 실제 진행·검증 결과 | 관련 문서·PR | 다음 작업·인계 |
|---|---|---|---|---|
| 1 | 부분 완료 | **11/06:** 시험용 IAM 사용자 MFA·재로그인, 비용 조회 허용/정보 조회 거부 시험, 서울 리전 자원·크레딧 확인.<br>**11/08:** 루트 MFA·복구 연락처 확인. | [1회차](1~4회차/1회차.md), [결정 현황](민수_인계_결정현황.md), [PR #8](https://github.com/MinsooAhn02/Haven/pull/8) | 예비 MFA·복구 시험, 타 리전 자원 확인 |
| 2 | IAM·S3 구성 완료 / 후속 실환경 시험 일부 완료 | **11/09~10:** 민수·민성 IAM 계정, SSM·PassRole·EC2/VPC 권한, 예산·알림, S3 백업 버킷과 정책 구성. IAM 시뮬레이터 허용·거부 4건 확인.<br>**11/13 민성님 보고:** S3 백업 및 격리 복원 성공(DB 13개 테이블 행 수 일치, 업로드 7개 SHA-256 일치). web-1 전용 IAM Role 전환 후 SSM Online 및 S3·CloudWatch·배포 동작 확인. 기존 공통 Role과 새 Web Role의 권한 범위는 구분해야 함. | [2회차](1~4회차/2회차.md), [JSON 정책](JSON/), [PR #29](https://github.com/MinsooAhn02/Haven/pull/29), [PR #91](https://github.com/MinsooAhn02/Haven/pull/91), [PR #98](https://github.com/MinsooAhn02/Haven/pull/98) | 민수님 개인 SSM 허용·거부 및 MFA 시험 증빙, 민성님 EC2 삭제 DryRun·타 대상 거부 시험 확인 |
| 3 | 주요 실환경 검증 완료 / 일부 권한 시험 잔여 | **11/11~12:** SG 삭제 정책 범위 축소, Route 53·ALB·ACM·SES·WAF·CloudWatch IAM 보완, SES 도메인 DKIM 인증, 자원·종료 목록 및 누적 사용 요금 $2.72(11/12 조회) 기록. web-1 nginx·앱 로그의 CloudWatch 도착 확인(PR #76).<br>**11/13 민성님 시험:** 시험용 `haven-sg-test` 삭제 허용 1건, 운영용 SG 3개와 default SG 삭제 거부 4건(PR #98). web-1 전용 Role 교체·SSM Online 확인, WAF–ALB 연결 성공(11/13 당시 `GetWebACLForResource` 조회 거부, **11/16 민성님 CLI 재시험 조회 성공**).<br>**11/13 메일 시험:** `noreply@orchestration-haven.cloud` 발신 정책 적용, Django 메일 수신 성공(EXT-03) 및 권한 거부 시 실패 표시 확인(EXT-04). SES 자체 `MessageRejected` 경로는 미시험. 혁민님 로그 조회·EC2/WAF 조회 허용 및 SSM 시작 거부 시험 기록 있음(PR #97). | [3회차 상세 기록](1~4회차/3회차.md), [SES 인증](SES_도메인_DKIM_인증_2026-11-11.md), [PR #76](https://github.com/MinsooAhn02/Haven/pull/76), [PR #97](https://github.com/MinsooAhn02/Haven/pull/97), [PR #98](https://github.com/MinsooAhn02/Haven/pull/98) | WAF 연결 상태 조회 재시험 성공(11/16, 민성님 보고). 남은 항목: SES 자체 거부 경로·기타 미확인 IAM 시험·최신 실사용 비용 확인 |
| 4 | **최종 점검 대기** | 4회차는 최종 검증 단계. 권한 허용·거부 결과의 최종 대조, AWS 전체 잔여 비용 확인, 자원 보존·종료 승인 및 담당자별 종료 확인 **미완료**. 기존 3회차 재시험·정책 보완 결과는 회차별 상세 기록에 분리함. | [4회차 작업 기록](1~4회차/4회차.md), [자원·종료 목록](AWS_자원현황_종료확인목록_2026-11-11.md) | IAM 미확인 거부 시험, 최신 비용·크레딧·타 리전 자원, 보존·종료 승인 및 담당자 확인 후 4회차 최종 PR/병합 확인 |


세부 기능/시험은 [기본 명세](../docs/구현명세/기본프로젝트_구현명세.md)를 따른다. 비밀값과 원본 민감 로그는 기록하지 않는다.

## 2026-11-09 오늘 작업 체크 및 다음 일정

### 완료
- [x] AWS 운영 비용 추정과 크레딧 $120 중 운영 예산 $100 / 비상 예비비 $20 정리
- [x] AWS Budgets 비용 예산 $100 및 실제 사용 비용 경보 $50·$80·$95 설정
- [x] EC2 공통 역할 `haven-ec2-ssm-role` 및 프로파일 `haven-ec2-ssm-profile` 생성·연결 확인
- [x] `minsung` IAM 사용자 생성, 제한된 `iam:PassRole` 정책 연결(EC2 서비스에 `haven-ec2-ssm-role`만 전달)
- [x] `Haven-Minsung-Infra-Policy` 생성 및 `minsung`에게 연결 확인 (11/09 IAM 화면)
- [x] EC2 Role에 `ssm:GetParameter`(서울 리전 `/haven/*`) 인라인 읽기 권한 생성·연결
- [x] IAM 설계·정책 JSON 초안 제출([PR #29](https://github.com/MinsooAhn02/Haven/pull/29))
- [x] [2회차 상세 작업 기록](1~4회차/2회차.md) 작성 및 오늘 상태 반영

### 미완료·다음에 진행
- [x] AWS `minsung` 사용자에 `Haven-Minsung-Infra-Policy` 연결 확인 (4개 정책 화면)
- [ ] 이민성 구축 스크립트의 EC2/VPC 권한·태그 조건 확인 및 실제 허용·거부 시험
- [x] `minsung` 사용자에 본인 MFA 등록용 인라인 정책 `Haven-Minsung-Self-MFA-Policy` 연결 확인(11/09 사용자 제공 IAM 화면)
- [ ] 민성님 실제 MFA 등록·최초 로그인·IAM 허용/거부 시험 기록
- [x] IAM 사용자 `minsoo` 생성 및 `Haven-Minsoo-SSM-Policy` 인라인 정책 연결(서울 `/haven/*` 읽기·쓰기, 사용자 작업 완료 보고)
- [x] [08_Minsoo_SSM_Parameters_Policy.json](JSON/08_Minsoo_SSM_Parameters_Policy.json) GitHub 정책 템플릿 기록
- [x] 민수님 최초 IAM 콘솔 로그인 성공 보고 (MFA 등록 및 CloudShell 권한 부족 확인)
- [x] [09_IAM_Self_MFA_Password_Policy.json](JSON/09_IAM_Self_MFA_Password_Policy.json) 본인 MFA/비밀번호 정책 초안 작성 및 [10_Minsoo_CloudShell_권한안내.md](JSON/10_Minsoo_CloudShell_권한안내.md) 추가
- [x] AWS `minsoo` 사용자에 `Haven-IAM-Self-MFA-Password-Policy`, `AWSCloudShellFullAccess`, `Haven-Minsoo-SSM-Policy`, `IAMUserChangePassword` 총 4개 정책 연결 확인 (11/09 사용자 제공 IAM 화면)
- [ ] 민수님 본인 MFA 등록·비밀번호 변경·CloudShell 서울 리전 생성 및 SSM 허용/거부 시험
- [x] [06_DB_S3_Backup_Policy.json](JSON/06_DB_S3_Backup_Policy.json)에 `s3:PutObject`·`s3:GetObject` 초안 반영, 확정 버킷 이름 규칙 `haven-backup-${ACCOUNT_ID}` 반영
- [x] AWS 공통 EC2 Role에 `Haven-EC2-S3-Backup-Restore` 인라인 정책 연결(권한 정책 생성·연결 화면 확인)
- [ ] 실제 S3 버킷 생성 여부, 백업·복원 동작 및 Web/DB 공통 Role의 접근 범위 검증
- [x] AWS에 적용한 EC2 SSM 읽기 인라인 정책을 [07_EC2_SSM_Parameter_Read_Policy.json](JSON/07_EC2_SSM_Parameter_Read_Policy.json) 템플릿으로 기록해 PR #29 반영 (계정 ID 변수는 실제 적용 전 치환)
- [ ] 민성님에게 서버 Role/프로파일 및 적용·검증 상태 인계
- [ ] 서버 구축 후 실제 허용·거부 시험, 다른 리전/잔여 과금 자원 확인

**상태 구분:** IAM 정책 *생성*은 실제 사용자 *권한 연결* 및 *정상 작동 검증*과 다름. 완료되지 않은 작업은 완료 표시하지 않음. 11/09 Discord 일일 보고 시 위 현황과 [2회차 상세 기록](1~4회차/2회차.md)을 참조.

## 민수's comment · 2026-11-06

- IAM·비용 문서 정리를 이어가며 근거가 되는 파일 경로와 미결 결정을 목록으로 남겨 주세요: 리전, 예산·비용 담당, 개인별 접근/역할, NAT·ALB 운영 기간과 출구 경로입니다. NAT 1개와 S3 경로는 제안이며 승인된 결정으로 쓰지 말아 주세요.
- 안민수·이민성과 함께 범위와 권한을 확인한 뒤 확정된 접근·자원 범위를 두 사람에게 전달해 주세요. 현재 준비된 문서 PR은 실제 계정 승인을 기다리지 않고 별도로 제출할 수 있습니다.
- 백업 보존 기간은 백업 단계에서 정리해도 되므로 초기 앱 작업의 선행 조건으로 두지 않아도 됩니다.
- 범위 승인이 있기 전 IAM·AWS 자원 변경은 하지 말고, 키나 비밀값은 Git에 기록하지 말아 주세요.
- TODO에 현재 상태와 시험/문서 근거, 다음 담당자에게 넘길 내용 및 가능한 인계 시각을 답글로 기록해 주세요.

&nbsp;

## 보람 진행 상황 · 2026-11-07

- **현재 상태:** 시험용 IAM 사용자의 MFA 확인, IAM 권한 허용·거부 시험, 크레딧 및 비용 알림 점검을 진행했습니다. 루트 계정의 MFA·복구 수단·연락처 확인 결과는 별도 확인이 필요합니다.
- **관련 자료:** `김보람/1회차.md`, `김보람/주의사항.md`, `김보람/민수_인계_결정현황.md`
- **제안 사항:** 서울 리전, NAT Gateway 1개 + S3 Gateway Endpoint 1개 구성을 추천했으며 최종 승인 대기 중입니다.
- **미결정 사항:** 프로젝트 전체 예산, 초과 비용 부담 주체, 팀원별 IAM 권한, NAT·ALB 운영 기간 및 자원 종료 담당자입니다.
- **다음 인계:** 민수님과 민성님의 검토 및 승인 후 확정된 권한·자원 범위를 전달하겠습니다.
- **PR:** #8 제출 완료. 현재 검토 대기 중입니다.
- **인계 시점:** 현황 자료는 PR #8로 공유했으며, 나머지는 필요한 결정이 확정된 후 전달할 예정입니다.


## 민수's comment · 2026-11-09~13 실행 가이드

- **월 오전** 민성과 리전·예산·출구의 미결 항목을 확인합니다. **월 오후** 민수와 #8의 실제 자원 조회, 시험 IAM MFA 확인, 승인 대기 항목을 대조합니다. 루트 MFA·복구 수단·연락처는 확인 여부만 답하고 민감한 값을 공유하지 않습니다.
- **화** 민성과 개인 접근, IAM 허용 범위, 서버 Role과 SSM에 필요한 승인 항목을 확인표로 만듭니다. **수** 민수·민성과 리전·예산·출구·역할 승인 근거를 대조합니다.
- **목** 승인/대기와 승인자·근거가 표시된 서버 인계표를 민수·민성에게 넘깁니다. **금** 접근·출구·비용 기록과 잔여 결정을 공용 리뷰에 인계합니다.
- **완료 기준** 각 항목에 확인/제안/승인 대기, 판단 담당, 근거, 다음 행동을 적고 #8 변경과 일치하는지 확인합니다.
- **막히면** 미승인 항목은 대기로 남기고 문서 인계를 계속합니다. IAM 적용과 AWS 자원 변경은 별도 승인을 확인합니다.

[공용 일정·리뷰의 내 담당 항목](https://github.com/MinsooAhn02/Haven/blob/main/docs/팀_진행_및_리뷰.md#boram)

## 보람 추가 점검 · 2026-11-08

- **루트 계정 MFA:** 가상 MFA 장치 1개 등록 확인 완료. 시험용 IAM 사용자(sherlocked) MFA와 구분하여 기록함.
- **복구 연락 수단:** 평소 사용하는 루트 계정 이메일과 기본 연락처 전화번호·주소 등록 확인. 대체 연락처 미설정, 실제 복구 시험 미실시.
- **리전:** AWS 콘솔에서 서울 리전(ap-northeast-2) 선택 확인. 팀 운영 리전 최종 승인은 대기.
- **PR #8:** 2026-11-07 main 병합 완료. 위 2026-11-07 기록 중 '검토 대기'는 당시 상태임.
- **관련 상세 기록:** `김보람/1회차.md` 및 `김보람/민수_인계_결정현황.md`.
- **남은 작업:** 예산·출구 경로·IAM 정책/Role 승인, 다른 리전 자원 점검, 서버 구축 후 접근 허용·거부 검증. 미승인 AWS 변경은 수행하지 않음.

## 민수's comment · 2026-11-08 주간 점검

- #8·#11 병합과 루트 MFA·연락 수단 기록 잘 받았습니다. 대체 연락처·복구 시험·예비 MFA는 미검증으로 유지합니다.
- 실행 가이드의 월 오후 #8 대조는 이미 끝났으니 **민수·민성과 AWS 결정 회의**로 바꿉니다. 안건: 운영 리전, 예산 상한·초과 부담, NAT 1 + S3 Endpoint, NAT·ALB 운영 기간·종료 담당. 결정은 민수가 하고, 보람님이 `민수_인계_결정현황.md`에 승인/대기로 반영해 주세요.
- 위 결과 기록 표는 1회차 행 아래 빈 줄과 `&nbsp;` 때문에 2~4회차 행이 표 밖으로 나가 있습니다. 빈 줄을 지워 주세요.
- 11/08 웹 편집 6건이 PR 없이 main에 바로 들어갔습니다. 웹에서 편집할 때는 커밋 대상을 `Boram` 브랜치로 골라 PR로 보내 주세요(공통 규칙 #13).
- 이 코멘트를 넣으면서 `Boram`을 최신 main(#14 `0876109`)으로 맞췄습니다. 작업 전에 `git pull` 해 주세요.


## 민수's comment · 2026-11-08 이번 주 배정 (11/09~13)

운영 방식이 바뀌었습니다. 날짜별 시간표 대신 **주력과 대기열**을 드립니다. **다 못 해도 괜찮아요.** 주력이 막히거나 끝나면 대기열로 넘어가고, 남은 건 매일 저녁 다시 나눕니다. 매일 끝나면 Discord에 오늘 상황 보고 부탁드립니다. 전체 현황은 main의 `TASK_TODO.html`(git pull 후 브라우저로 열기).
- **주력:** 월 오후 AWS 결정 회의 자료 — 기간별 예상 비용표(NAT·ALB·EC2·EBS)와 결정 항목표(리전·예산 상한·초과 부담·NAT/S3·운영 기간·종료 담당) → 회의 후 `민수_인계_결정현황.md`에 승인/대기 반영
- **대기열:** 사람별 IAM 정책·서버 Role JSON 초안(적용 금지) + 허용/거부 시험 목록 → 다른 리전 자원 점검
- **⏳ 기다릴 것:** 승인 반영은 민수 결정 필요. 자료 준비와 대기열은 바로 가능.


## 민수's comment · 2026-11-09 배정 갱신

AWS 운영 결정 추천안이 main `docs/AWS_운영결정.md`에 올라갔고, 현황판 `TASK_TODO.html`도 오늘 기준으로 바꿨습니다. 다 못 해도 괜찮고, 끝나면 Discord에 오늘 상황 보고 부탁드립니다.
- **주력:** `docs/AWS_운영결정.md` 확인(이견만 알려 주기) → 비용표에 **"$100으로 며칠 운영 가능한지"** + 경보 $50/$80/$95 설정 계획 → 확정되면 `민수_인계_결정현황.md`에 승인/보류·결정자·날짜 반영
- **대기열:** IAM 정책·Role JSON 초안(계정 ID는 변수, 적용 금지) → 새 계정 접근·MFA·예산 경보 설정 절차(계정 이전 대비) → 다른 리전 자원 점검
- **⏳ 기다릴 것:** 서버 사양·대수·하루 가동 시간은 민성님께 받기

## 민수's comment · 2026-11-09 확대 배정 (AI 사용 전제)

다들 AI를 쓰니 일을 크게 잡았습니다. **이번 주(11/09~13)에 원래 1·2회차, 다음 주에 3·4회차**를 끝내는 게 목표예요. 다 못 해도 괜찮고, 위에서부터 하다가 막히면 다음 항목으로 넘어가세요. 다른 사람과 같이 정해야 하는 건 회의하지 말고 민수에게 물어보면 바로 정합니다. AWS 운영 결정은 확정됐습니다(main `docs/AWS_운영결정.md`). PR에는 실제로 돌린 명령·결과와 **일부러 실패시킨 거부 시험**을 꼭 붙여 주세요(AI 코드는 시험을 통과해도 틀릴 수 있어서). 매일 끝나면 Discord 상황 보고는 그대로 부탁드려요.

1. 비용표: Web·DB t3.small 2대(gp3 20GB) + NAT 평일 낮만(매일 밤·주말 삭제) 기준 **$100으로 며칠** + 경보 단계별 예상 날짜 → 결정현황 문서에 확정 반영
2. IAM 정책·Role JSON 전부(사람별 + Web/DB EC2 Role: SSM·로그·S3 백업), 계정 ID는 변수
3. **적용 → 사람별 되는 것/안 되는 것 실제 시험** (수요일 목표, 조장 사전 승인 — 민성님 구축 전)
4. 예산 경보 $50/$80/$95 실제 설정 + 알림 수신 확인
5. (대기열) 일별 비용 조회 스크립트(AWS CLI) → 매일 보고에 금액 → 새 계정 세팅 절차(접근·MFA·IAM·경보) → 다른 리전 점검 · 종료 시 지울 자원 목록 양식

- **짝 리뷰:** 민성님 구축 스크립트와 IAM 권한 대조
- **사전 승인 범위:** 결정 문서 범위의 IAM 적용은 따로 묻지 않고 진행. 루트·삭제처럼 되돌릴 수 없는 건 민수 확인

## 민수's comment · 2026-11-09 비용표 답변

비용표 초안 잘 받았습니다(사양 t3.small 2대·gp3 40GB 그대로 맞아요). 가동 시간이 정해져서 이 기준으로 한 번만 다시 계산 부탁드려요.
- **EC2·NAT 모두 평일 09:00~21:00(12시간)**, 밤·주말은 NAT 삭제 + EIP 해제 + EC2 중지 (`docs/AWS_운영결정.md` 4번)
- **이번 주:** ALB·WAF 없음 / **다음 주(3회차~):** ALB·WAF 추가 — 두 구간으로 나눠서 "$100으로 며칠"
- 표 5번 "NAT 삭제는 담당자와 협의 후"는 결정 11번으로 사전 승인됐습니다(민성 스크립트로 매일 실행).
- 민성님 IAM 요청 4개(SSM Role 이름·PassRole 범위, SSM 허가/일반 계정, 로그·S3 Endpoint 정책, 적용 시각)는 `이민성/network/연결확인표.md` 맨 아래에 있어요. 수요일 구축 전에 필요합니다.
- 섹션 앞 `&nbsp;`는 지워 주세요(지난번 표 깨짐 원인).

## 민수's comment · 2026-11-09 밤 · 이번 주 할 일 (11/10~13)

이번 주: 화 = 2회차 병합·AWS 구축, 수 = 첫 배포·3회차 시작, 목 = 3회차, 금 = 4회차·17:30 판정. 다음 주는 심화 점검·시연·보고서. 작업 전 항상 `git pull`. 전체는 `TASK_TODO.html`.

- **화 오전 (구축 전, 제일 먼저):** #29 마무리 → 민수 병합. 민성 계정으로 구축에 필요한 권한 허용/거부 실제 시험(MFA 로그인 포함) → 결과를 민성에게. 이게 끝나야 민성이 오후에 구축합니다
- **수:** WAF · 로그(CloudWatch) · SES 메일 · 백업 버킷(`haven-backup-<계정ID>`) 생성 권한 확인·추가
- **목~금:** IAM 수정·재시험 · 종료 시 지울 자원 목록 · 새 계정 절차
- **매일:** 비용은 일별 보고에 금액만(재계산은 필요할 때만)


## 2026-11-10 화요일 추가 확인

### 보람 IAM·S3 구성 완료(사용자 제공 AWS 화면·JSON 근거)
- [x] `minsung` EC2 시작/중지 정책 포함 확인 (서울·Project=Haven·Owner=minsung)
- [x] `minsung`에 `ssm:DescribeInstanceInformation` 권한 추가·저장
- [x] `minsung` CLI v2.39.6 확인, `SignInLocalDevelopmentAccess` 연결 확인 (장기 액세스 키 미발급)
- [x] `ec2:DescribeInstances` 서울 허용/타 리전 거부 **시뮬레이터** 시험
- [x] `iam:PassRole` 지정 EC2 Role 전달 허용/Lambda 전달 거부 **시뮬레이터** 시험
- [x] `minsoo` Session Manager 인라인 정책 생성·연결, GitHub 정책 기록
- [x] `haven-backup-${ACCOUNT_ID}` S3 버킷 생성 (서울·퍼블릭 차단·SSE-S3)
- [x] EC2 공통 Role S3 `db-backups/*`, SSM 파라미터 및 minsoo 파라미터 계정 범위 확인

### 담당자 실제 시험·인계 대기(보람이 대신 실행하지 않음)
- [ ] 민성: Git Bash `aws login`, MFA·STS 계정 확인, #34 EC2 시작·중지 및 구축 실제 허용/거부 결과
- [ ] 민수: Haven 태그 EC2 SSM 세션 접속 및 타 대상 거부, 본인 세션 종료/재개 검증
- [ ] 민수: S3 백업/복원 실제 시험 및 경로·권한 오류 결과 공유
- [ ] 보람: 시험 결과를 받아 IAM 정책 보완·필요시 재시험 및 프로젝트 종료 자원 목록 정리

세부 내용은 [2회차 11/10 추가 기록](1~4회차/2회차.md) 참조. **구성 성공과 실제 서비스 접속 시험 성공을 혼동하지 않는다.**

## 2026-11-10 오후 추가 IAM 인계

- [x] 민성님 실환경 `build.sh`와 IAM 권한 조건 대조: VPC 생성 오류 후 `Haven-Minsung-Infra-Policy` 수정, 서울 리전 인프라 작업 권한 보완. [12번 JSON](JSON/12_Minsung_Infra_Policy.json), PR #39(main 병합).
- [x] 민성님 `RunInstances` 시험 결과 확인: 태그 없는 요청 거부, 공인 IP 자동 할당 명시적 거부, 기본 SG의 Haven 태그 부재에 따른 접근 거부 확인. **시험 명령과 실제 구축 스크립트의 조건을 구분함.**
- [x] 민성님·민수님 역할 전달 설정 확인: `minsung`에 `iam:PassRole` 정책 연결, EC2용 역할 `haven-ec2-ssm-role` 및 `haven-ec2-ssm-profile` 연결, 역할에 `AmazonSSMManagedInstanceCore` 적용 확인.
- [x] 추가 요청 정책 2개를 개인 브랜치에 문서화하고 [PR #42](https://github.com/MinsooAhn02/Haven/pull/42)에 함께 제출: [13번 EC2 종료(삭제) 권한](JSON/13_Minsung_TerminateInstances_Policy.json), [14번 민성 SSM 세션 접속 권한](JSON/14_Minsung_SessionManager_Policy.json).
- [ ] **AWS 실적용 확인:** 위 13·14번 정책이 `minsung`에게 실제 연결·저장됐는지 확인. GitHub PR만으로 AWS 정책은 바뀌지 않음.
- [ ] **담당자 검증 대기:** 민성님의 Haven 서버 SSM 접속·비대상 접근 거부 시험, EC2 종료 권한 시험(실제 영구 삭제 전 민수님 승인), 21시 NAT/EIP 정리 결과 및 비용 확인.
- **권한 범위 주의:** `TerminateInstances` 정책은 서울 리전 `Project=Haven`, `Owner=minsung` 태그가 모두 붙은 서버에만 허용하지만, 시험 서버뿐 아니라 실제 Haven 서버도 삭제할 수 있음.

## 2026-11-10 민성 추가 권한 오류 및 SG 삭제 요청

- [x] 민성님 `haven-test` EC2의 `Project=Haven`, `Owner=minsung` 태그 확인 보고 수신. `ec2:TerminateInstances`는 여전히 `UnauthorizedOperation` 보고됨.
- [x] 13번 [민성 EC2 삭제 IAM 정책](JSON/13_Minsung_TerminateInstances_Policy.json)의 태그 조건 재확인. 정책 JSON 조건은 일치하나 **AWS 사용자 실제 연결 여부는 미확인**.
- [x] 민성님 요청 `haven-sg-test` SG 정리용 `ec2:DeleteSecurityGroup` 정책을 [15번 JSON](JSON/15_Minsung_DeleteSecurityGroup_Policy.json)으로 추가. 서울 리전, `Project=Haven` 태그 SG만 허용하도록 제한.
- [x] 위 추가 작업을 [PR #42](https://github.com/MinsooAhn02/Haven/pull/42)에 기록. AWS IAM 변경은 콘솔에서 별도 적용 필요.
- [ ] AWS `minsung` 사용자에게 13·14·15번 인라인 정책 연결 여부 확인 후 실환경 `--dry-run` 허용/거부 시험 결과 민성님에게 요청.
- [ ] SG에는 `Project=Haven` 태그 존재 여부를 확인하고, 실제 삭제는 민수님 승인 후 시험용 `haven-sg-test` 대상으로만 수행. 다른 Haven SG도 태그만 맞으면 정책상 삭제 가능하므로 주의.

## 2026-11-10 민수님 추가 지시 — 시험용 EC2 삭제 범위 제한 (최신)

- [x] **AWS 적용 확인:** IAM 사용자 `minsung` 권한 목록에 고객 관리형 정책 `Haven-Minsung-Delete-Policy` 연결됨(11/10 콘솔 캡처).
- [x] **AWS JSON 저장 확인:** EC2 종료(`ec2:TerminateInstances`) 조건에 `Project=Haven`, `Owner=minsung`, `Name StringLike haven-test*` 적용(11/10 정책 JSON 조회 캡처). 이 조건이 없는 이전 13번 정책보다 범위를 좁힘.
- [x] GitHub [13번 TerminateInstances 정책](JSON/13_Minsung_TerminateInstances_Policy.json)을 해당 Name 조건에 맞춰 갱신. [15번 SG 삭제 정책](JSON/15_Minsung_DeleteSecurityGroup_Policy.json)은 `Project=Haven` 조건 유지. GitHub에서는 파일을 나눠 기록하지만 AWS 실제 정책 `Haven-Minsung-Delete-Policy`에는 두 작업이 한 정책에 포함됨.
- [ ] **민성님 실제 검증 대기:** `haven-test*` 시험용 EC2 삭제 허용, `web-1`·`db-1` 삭제 거부(안전한 DryRun으로 확인), 시험용 SG `haven-sg-test` 삭제 권한 시험 결과 공유.
- [ ] 실제 시험용 EC2를 삭제할 때만 대상 Name·Instance ID 확인 후 해당 ID **하나만** 종료. `bash destroy.sh --delete` **사용 금지**.
- [ ] 매일 21시 운영 종료는 별도 `bash night.sh`만 사용(EC2 중지 + NAT 삭제 + EIP 해제). 실제 실행 및 비용 결과는 민성님 확인.
- **추가 주의:** 시험 전에는 정책 연결·JSON 저장과 실제 실행 성공을 구분한다. SG 삭제 정책은 `Project=Haven`이 붙은 운영 SG도 포함할 수 있어 대상 확인 필수.

## 2026-11-11 SG 삭제 IAM 정책 제한 — 실환경 적용 확인

- [x] AWS 고객 관리형 정책 `Haven-Minsung-Delete-Policy` JSON을 콘솔에서 수정하고 **업데이트 성공** 메시지 확인(사용자 제공 화면).
- [x] EC2 시험용 서버 영구 삭제 조건(`Project=Haven`, `Owner=minsung`, `Name=haven-test*`)은 유지.
- [x] SG 삭제 허용(`ec2:DeleteSecurityGroup`)은 `Project=Haven` **및** `Name=haven-sg-test` **리소스 태그 둘 다 있는 대상**으로 좁힘. 기존 운영용 `haven-sg-web`, `haven-sg-db`, `haven-sg-alb` 이름만으로 허용하지 않음.
- [x] GitHub [15번 SG 삭제 정책](JSON/15_Minsung_DeleteSecurityGroup_Policy.json)에 새로운 태그 조건 반영. 이 파일은 15번 부분의 기록이며, 실제 AWS 고객 관리형 정책에는 EC2 종료 권한과 SG 삭제 권한이 **함께** 있음.
- [x] **실행 시험 완료(11/13, 민성님 CLI 보고):** 시험용 `haven-sg-test` 삭제 허용 1건·운영 SG 및 default SG 삭제 거부 4건 확인. 시험용 `haven-sg-test`는 11/11 서울 리전 목록에 없었으며, 재생성은 확인되지 않음.
- [ ] **추가 안전 확인:** 다른 IAM 정책의 삭제 허용 및 SG 태그 수정 가능 범위를 점검해야 운영용 SG 삭제가 완전히 불가능하다고 결론 내릴 수 있음.
- **주의:** 이 기록은 IAM **설정 저장 성공** 확인이며 실제 삭제 허용/거부 시험 완료로 간주하지 않음. 이미 삭제된 SG나 실제 AWS SG 자체는 수정하지 않음.

## 2026-11-11 오전 추가 기록 — Route 53 및 SES

### 민성 Route 53 호스팅 영역 생성 권한
- [x] 민성님이 `route53:CreateHostedZone` 실행 시 **identity-based policy 미허용(AccessDenied)** 오류를 공유함.
- [x] AWS IAM 사용자 `minsung` 권한 목록에서 **`Haven-Minsung-Route53-...` 인라인 정책 연결** 확인(11/11 사용자 제공 IAM 콘솔 캡처).
- [x] 요청에 맞는 최소 생성 액션 `route53:CreateHostedZone`, `Resource: "*"` 정책 JSON을 AWS에 입력·저장하고 같은 내용을 [16번 JSON](JSON/16_Haven-Minsung-Route53-Create.json)에 기록.
- [ ] **민성님 실제 재시험 대기:** Route 53 호스팅 영역 생성 성공/실패 결과와 중복 생성 여부 확인. DNS 레코드 관리, ACM 검증 등에 추가 IAM 권한이 필요하면 구체적인 거부 오류를 받아 별도 검토.
- **담당 구분:** 도메인·DNS·ALB 연결은 민성님, 계정 IAM·추가 비용 기록은 보람 담당. 기존 도메인과 DNS 설정을 보람이 직접 수정하지 않음.

### SES 발신 주소 확인 및 메일 시험
- [x] 서울 리전 SES에서 테스트용 발신 이메일 자격 증명 **확인됨(Verified)** 상태 확인.
- [x] **SES 테스트 메일 발송·수신 확인**(단독 시험). 서비스 앱 연동 시험은 별도 진행 예정.
- [x] Haven 정식 발신 주소(프로젝트 도메인 사용 여부)·발송 방식의 앱 적용 입력을 요찬님과 확정하고, 그 주소에 맞춘 EC2 Role의 `ses:SendEmail` 최소 권한 설정. **정식 서비스 발신 주소는 미확정**.
- [x] 11/12(목) 요찬님과 실제 Django 이메일 발송·수신/실패 동작 검증 (SES 샌드박스 제한 여부 확인 포함).

### 다음 점검
- [ ] 민성님 SSM Session Manager 실제 접속 및 권한 거부 시험 결과 수신.
- [x] WAF·CloudWatch Logs 권한은 담당자 요청 시 확인·최소 범위 보완.
- [ ] 11/13 종료 시 지울 자원 목록 및 실사용액 재확인.

## 2026-11-11 Route 53 호스팅 영역 조회 권한 — AWS 적용 및 민성 인계

- [x] 민성님 요청: 호스팅 영역 생성 뒤 조회 오류 발생. AWS 오류에 `route53:GetHostedZoneCount` 미허용 명시됨.
- [x] 기존 `minsung` 인라인 정책 수정 시 사용자 인라인 정책 합계 **2,048자 제한 초과** 오류 확인. 기존 인라인 정책은 변경하지 않음.
- [x] 별도 **고객 관리형 정책** `Haven-Minsung-Route53-Read` 생성 성공 및 IAM 사용자 `minsung`에게 **직접 정책 연결** 완료(사용자 확인).
- [x] [17번 Route 53 조회 정책](JSON/17_Haven-Minsung-Route53-Read.json)에 AWS에 입력한 JSON 기록. `GetHostedZoneCount`, `ListHostedZones`, `ListHostedZonesByName` 및 특정 호스팅 영역 `HOSTED_ZONE_ID_MASKED`에 대한 `GetHostedZone`, `ListResourceRecordSets` 조회만 허용. DNS 레코드 변경·삭제 권한은 추가하지 않음.
- [x] 민성님이 **호스팅 영역 생성 완료**, Route 53 네임서버 4개를 공유했다고 보고함(11/11 10:42). 도메인 등록업체 NS 위임 및 외부 DNS 정상 응답까지 완료했다는 의미는 아님.
- [ ] **담당자 검증 대기:** 민성님이 `GetHostedZoneCount` 및 호스팅 영역 조회를 다시 수행한 결과/추가 거부 오류 공유. 생성 완료 보고와 개별 API 조회 권한 시험을 구분함.
- **담당:** 민성님=호스팅 영역·DNS 후속 설정 및 검증 / 보람=권한 생성·연결·기록.

## 2026-11-11 3회차 ALB·HTTPS 민성 IAM 추가 권한 — AWS 적용 기록

- [x] **민수님 지시:** 민성님 계정에 ALB(로드 밸런서·대상 그룹·리스너), ACM(`RequestCertificate`·`DescribeCertificate`·`ListCertificates`), Route 53(해당 Haven 호스팅 영역 변경·변경상태 조회) 권한 요청.
- [x] 고객 관리형 정책 `Haven-Minsung-ALB-ACM-DNS-Policy` 생성 후 IAM 사용자 `minsung`에 직접 연결(사용자 완료 보고).
- [x] 민성님 추가 요청: ALB·ACM 조회 접근 거부 해결, ACM 인증서 태그, ALB 수정·실패 시 정리용 삭제, ALB 서비스 연결 역할 생성 권한 추가.
- [x] `AWSServiceRoleForElasticLoadBalancing` 역할을 IAM 역할 검색에서 찾지 못했다고 사용자 확인. 기존 정책에 조건부 `iam:CreateServiceLinkedRole`을 추가.
- [x] 해당 고객 관리형 정책을 JSON으로 편집·저장 완료했다고 사용자 확인. AWS 권한 요약 화면에서 Certificate Manager, ELB/ELB v2, IAM, Route 53 항목 표시 확인.
- [x] AWS에 입력·저장한 정책 JSON을 [18번 파일](JSON/18_Haven-Minsung-ALB-ACM-DNS-Policy.json)에 동일하게 기록.
- **권한 범위:** ELB는 서울 `ap-northeast-2`, Haven 접두어 `haven-*`와 요청/리소스의 `Project=Haven` 태그를 조건으로 설정. ACM 요청은 `Project=Haven`, `Owner=minsung` 요청 태그 조건. Route 53 변경은 호스팅 영역 `HOSTED_ZONE_ID_MASKED`로 제한, 단 `route53:GetChange` 조회는 AWS change ARN 사용.
- [ ] **민성님 실제 검증 대기:** ALB·ACM 읽기, 인증서 요청·태그, ALB 생성·리스너 생성, DNS 변경 권한, 서비스 연결 역할 자동 생성 성공/거부와 추가 오류 공유. 저장 성공만으로 모든 API 호출 성공을 보장하지 않음.
- [ ] **삭제는 민수님 확인 후에만:** 권한에 ELB DeleteListener/TargetGroup/LoadBalancer를 포함했어도 실제 삭제 실행은 별도 승인 및 대상 식별 후 진행.
- **주의:** 새 정책은 유효성/동작 시뮬레이터 및 실제 허용·거부 시험이 아직 검증되지 않음. 세부 조건이 API 호출 시 적용되지 않거나 권한 부족이 추가로 나올 수 있으며 그 경우 최소 수정 필요. WAF 권한은 미추가.

## 2026-11-11 민성 ALB 생성 중 EC2 조회 권한 추가

- [x] 민성님: ACM 인증서·대상 그룹 생성까지 진행한 뒤 ALB `CreateLoadBalancer`에서 `AccessDenied: ec2:GetSecurityGroupsForVpc` 발생(11:37:22 오류 공유).
- [x] AWS 고객 관리형 정책 `Haven-Minsung-Infra-Policy`의 `ReadEC2InSeoul`에 `ec2:GetSecurityGroupsForVpc`를 추가. 기존 `ec2:Describe*` 및 `aws:RequestedRegion=ap-northeast-2` 조건 유지(보람 AWS JSON 편집 화면 확인).
- [x] AWS 정책 편집 후 권한 요약 화면 확인(보람 제공 캡처). **저장 완료는 보람의 확인 기준으로 기록**, 실제 EC2 조회·ALB 생성 성공은 민성님 시험이 필요.
- [x] GitHub [12번 인프라 정책](JSON/12_Minsung_Infra_Policy.json)에 동일 변경 반영. 이미 `minsung`에게 연결된 고객 관리형 정책이므로 새 연결 작업은 필요하지 않음.
- [ ] **민성님 재시험 대기:** `CreateLoadBalancer` 재시도 및 결과 공유. 추가 오류가 있으면 정확한 거부 액션을 확인 후 최소 권한으로 보완.
- **참고:** 기존 `ec2:Describe*`에 `ec2:DescribeAccountAttributes`·`ec2:DescribeInternetGateways`·`ec2:DescribeAddresses`가 포함되므로 별도 추가하지 않음.


## 민성's comment · 2026-11-11 저녁 · 바뀐 역할 반영 (조장 이민성)

팀장(조장)은 이민성이다(11/11 인수인계 완료). 안민수는 레포 admin 지원만 한다. 같이 정할 판단은 이제 민성에게 묻는다. 역할 표는 `docs/인수인계/02_역할_재배치.md`, 사람별 할 일은 `TASK_TODO.html`.

- **SES:** 설정·발신 주소 인증·권한은 보람 담당이다. 11/12 요찬과 실제 Django 발송·수신/실패를 확인한다.
- **ALB 야간 과금:** 밤에도 ALB·WAF가 켜져 있을 때 비용을 계산해 민성에게 준다(유지·삭제 결정용). #54 리뷰의 후속 확인 항목이다.
- **삭제 절차:** ALB·리스너·대상 그룹·ACM·Route 53 정리 순서는 민성이 `destroy.sh`에 추가한다. 실제 삭제는 조장 확인 후에만 한다.
- **확인 지원:** 15번(SG 삭제) 실제 허용/거부 시험은 민성이 한다. 결과를 받아 정책 기록에 반영한다.

## 2026-11-11 민성 SES 계정 조회 권한 추가

- [x] 민성님이 `ses:GetAccount` 호출 시 `AccessDenied` 오류 보고: IAM 사용자 `minsung`에 해당 조회 권한이 없음.
- [x] 보람이 AWS IAM에서 고객 관리형 정책 `Haven-Minsung-SES-Read` 생성 완료 보고.
- [x] IAM 사용자 `minsung`에 해당 정책 직접 연결 완료 보고.
- [x] 정책 JSON을 [19번 민성 SES 조회 정책](JSON/19_Minsung_SES_GetAccount_Read_Policy.json)에 기록. **허용 액션은 `ses:GetAccount`, `ses:ListRecommendations`, `ses:ListEmailIdentities`, `ses:GetEmailIdentity` 4개**이며, 이메일 자격 증명 상세 조회는 서울 리전의 SES identity ARN으로 제한. 메일 발송·SES 설정 변경 권한은 포함하지 않음.
- [x] **민성님 실제 시험 결과(11/11):** `ses:ListEmailIdentities` 15:16 목록 조회 성공, `ses:GetEmailIdentity` 15:17 CLI 조회 성공. `ses:GetAccount`·`ses:ListRecommendations`는 SES 콘솔 첫 화면 접속으로 간접 확인(각 API 직접 호출 결과는 별도 미확인). 15:51 `ses:SendEmail` AccessDenied 거부 시험 성공(발송 권한 없음). PR #60 코멘트 근거.
- [x] 11/11 민성님이 `ses:ListRecommendations` 추가 누락 오류 보고 → 보람이 동일 고객 관리형 정책에 조회 액션 추가·저장(정책 버전 2, AWS 권한 요약에 읽기 2개 표시). 추가 정책 연결은 불필요.
- [x] 11/11 민성님 추가 요청 `ses:ListEmailIdentities`·`ses:GetEmailIdentity` → 보람이 같은 정책에 추가·저장, 정책 버전 3 확인(권한 요약: SES v2 / Pinpoint Email의 나열·읽기). **민성님 실제 AWS CLI 재시험 성공:** 15:16 `ses:ListEmailIdentities` 목록 조회, 15:17 `ses:GetEmailIdentity` 상세 조회(PR #60 코멘트 근거).
- **구분:** 보람이 민성에게 조회 권한을 연결한 것과, 보람 자신의 SES 권한·`#58` DKIM 등록 후 인증 완료 여부는 **별도 확인** 대상.

### 다음 TODO (2026-11-11 기준)
1. **SES 조회 시험:** 민성님 보고 기준 목록·상세 조회 성공 및 `ses:SendEmail` 거부 확인. `GetAccount`·`ListRecommendations` 개별 호출은 별도 미확인.
2. **SES 도메인:** [PR #58](https://github.com/MinsooAhn02/Haven/pull/58)은 병합 완료. CNAME 3개 Route 53 등록을 보람이 확인했고, **11/11 15:57 민성님이 `orchestration-haven.cloud` 확인됨(Verified)·DKIM SUCCESS 보고**. 보람 SES 완료 화면 직접 재조회는 별도.
3. **11/12(목):** 요찬님과 Django 실제 메일 발송·수신·실패 시험. SES 샌드박스 수신자 인증 제한과 앱에서 사용하는 발송 권한을 별도로 확인.
4. **11/13(금):** 담당자 실제 권한 시험 결과를 받아 IAM 보완·기록하고 프로젝트 종료 시 AWS 자원 목록 및 새 계정 설정 절차 정리. **자원 삭제는 실행하지 않음**.
5. **가능할 때:** 다른 리전 자원·일별 AWS 실사용액 확인.

- **완료된 항목:** ALB·WAF 평일 밤·주말 비용표는 PR #57 병합 완료. 포트폴리오 스크린샷 분류는 수업 후 재개(프로젝트 AWS 작업 TODO와 별개).

## 2026-11-11 AWS 자원 현황 정리 (콘솔 조회 기록)

- [x] [AWS 자원 현황 및 종료 확인 목록](AWS_자원현황_종료확인목록_2026-11-11.md) 작성: EC2 2·Haven VPC 1·서브넷 4·보안 그룹 3·NAT 1·ALB 1·EBS 2(40 GiB)·S3 1·EIP/공인 IPv4 3 및 연결 대상·Route 53 1·SES 확인됨/DKIM SUCCESS(민성 보고)·WAF 조회 0개.
- [x] 기본 VPC·기본 서브넷·기본 SG와 Haven 자원을 구분하여 기록.
- [ ] 종료 전에 담당자 확인 필요: IGW/라우팅, S3 Gateway Endpoint, ACM 인증서, ALB 대상 그룹/리스너, EBS 스냅샷, CloudWatch 로그, S3 백업 객체, 다른 리전의 자원.
- **이 단계는 자원 현황 초안 및 인계 목록 작성 완료이며 실제 자원 삭제/변경 또는 종료 승인 아님.**

## 민성's comment · 2026-11-12 · 4회차 추가 업무 (조장 결정)

- **WAF 쓰기 권한(새 일, WAF 구축 시작 전, 4회차 초반):** 혁민(Web ACL 생성·수정, 규칙, 로그 설정)과 민성(ALB 연결, Block 적용을 위한 Web ACL 수정)에게 필요한 최소 권한을 정책으로 만들어 적용한다. 지금 민성 정책(12·18번)에 `wafv2` 권한이 없고 혁민은 조회만 가능하다. 범위는 Haven Web ACL·서울 리전으로 제한하고, 삭제 권한은 넣지 않는다. WAF 로그를 CloudWatch Logs로 보내는 데 필요한 로그 권한도 함께 검토한다(정확한 액션 목록은 AWS 문서로 확인).
- **구민철 SG 점검용 읽기 권한(2회차 시작 전 = 11/16 전까지):** 구민철에게 AWS IAM 사용자를 만들고 SG 읽기 전용 권한(예: EC2 조회)과 MFA 등록 권한을 부여한다. root 사용 금지. 인계서는 `구민철/SG_실제점검_인계.md`.
- 정책마다 이번처럼 콘솔 JSON과 저장소 JSON 대조 결과를 PR에 남긴다.

## 민성's comment · 2026-11-12 저녁 · 현재 상태와 할 일 (현황판 기준)

- **병합됨:** #65(로그 권한 기록과 폴더 정리), #58, #60.
- **지금 할 일(순서대로)**
  1. `김보람/민수_인계_결정현황.md`의 깨진 링크 2곳 수정(`1회차.md` → `1~4회차/1회차.md`, `AWS_비용실적_2026-11-11.md` → `비용/`).
  2. WAF 쓰기 권한: 혁민(Web ACL 생성·수정·규칙·로그 설정)과 민성(ALB 연결, Block 적용용 Web ACL 수정)에게 필요한 최소 권한을 WAF 구축 시작 전에. 삭제 권한 제외. 콘솔 JSON 대조 결과를 PR에 남긴다.
  3. 구민철 SG 읽기 전용 IAM 사용자와 MFA 등록 권한(2회차 시작 전 = 11/16 전까지, root 금지).
  4. 시험 메일: Web EC2 Role에 `ses:SendEmail`(발신 주소 하나로 제한), 요찬과 실제 발송·수신·실패 확인(요찬 코드 #64 병합됨, 민성의 서버 쪽 PR과 재배포 뒤).
  5. `TODO.md` 314행 낡은 줄 정정(재시험은 성공으로 이미 기록됨), 20~23번 정책의 허용·거부 실제 시험 결과 반영.
  6. 4회차(11/27까지): IAM 수정·재시험, 종료 시 지울 자원 목록, 새 계정 절차.

## 민성's comment · 2026-11-12 밤 · 오늘 한 일과 남은 일 (현황판 기준)

- **병합됨:** #77 (IAM 정책 기록). 혁민 24·25·20·21번, 민성 26번, 구민철 27번, 16·17·18번 정정과 파일명 정리. 조장 승인: 혁민 `wafv2:DeleteWebACL`(범위 `haven-*`), `logs:PutResourcePolicy`의 `Resource: *`(WAF 로그 전송에 필요).
- **알아 둘 것:** 콘솔 JSON 대조는 보람이 AI로 비교한 결과라고 PR에 적었다. 사람이 `diff`한 것은 아니므로 현황판에는 "보람 보고"로 적었다. 실제 허용·거부·연결 동작 시험은 담당자 결과를 기다린다.
- **남은 일(순서대로)**
  1. `ManageReferencedManagedRuleSets`가 왜 필요했는지, 리소스의 계정 자리(`${ACCOUNT_ID}`)가 AWS 관리형 규칙 세트에 맞는지 확인한다. 혁민은 이미 Web ACL을 만들었다고 보고했다(#80).
  2. `wafv2:AssociateWebACL`·`GetWebACLForResource`의 리소스 대상을 확인한다. 민성의 ALB 연결 시험에서 거부되면 ALB ARN을 추가한다.
  3. `1~4회차/3회차.md` 72행 낡은 문장(#73 "재실행 대기" 조건부 리뷰 의견)을 정정한다. #73은 닫혔고 후속 #76이 병합됐으며 최종 판 web-1 재실행은 14:44에 끝났다.
  4. 미병합 커밋 5개(28~30번: Web EC2 역할 SES·SSM·CloudWatch 정책 기록)를 PR로 올린다. 조장은 AWS에서 이를 확인하지 않았다. 대조 방법과 "허용·거부 시험은 대기"를 적는다.
  5. WAF 비용 재계산: 혁민의 Web ACL은 관리형 규칙 그룹 3개(비용표 가정은 규칙 2개), ALB는 밤에도 유지 중이다. 조장이 문의할 예정이다.
  6. `ses:SendEmail`(28번)이 실제로 적용됐는지 민성에게 알려 주면 시험 메일 EXT-03·04를 진행한다.
  7. 이전 코멘트 1번(깨진 링크 2곳)·5번(`TODO.md` 314행 정정, 20~23번 시험 결과 반영)은 그대로 남아 있다.

## 민성's comment · 2026-11-12 밤 2 · #84 이후 정정과 남은 일

- **병합됨:** #84(Web 전용 EC2 역할 `haven-ec2-web-role` 기록, 정책 28·29·30번). 답변(WAF 비용 월 약 $8·야간 유지 동의, `ManageReferencedManagedRuleSets` 이유)도 문서에 들어왔다.
- **정정(바로 위 "밤" 코멘트 6번):** `ses:SendEmail`은 옛 역할이 아니라 새 Web 역할에 만든 것이다. web-1은 아직 옛 역할 `haven-ec2-ssm-role`이라 지금은 메일을 보낼 수 없고, 시험 메일 EXT-03·04는 web-1 역할 교체 뒤에 한다. 6번의 "적용됐는지 알려 주면"은 이 문장으로 대체한다.
- **조장이 코멘트로 요청한 두 가지(#84)에 답해 준다**
  1. 새 Web 역할에 첨부 백업·복원용 S3 권한을 줄지: web-1의 `backup-uploads.sh`·`restore-uploads.sh`가 `s3://…/db-backups/`를 읽고 쓴다(현재 06번 정책: `db-backups/*`의 `PutObject`·`GetObject`).
  2. 역할 교체에 필요한 `iam:PassRole`(새 역할)과 인스턴스 프로파일 교체 권한을 누가 어디에 둘지: 02번은 옛 역할만 허용한다.
- **알아 둘 것:** 역할 교체는 11/13 백업·격리 복원 연습 뒤가 안전하다는 것이 조장 의견이다(결정은 아님). 새 역할의 콘솔 확인은 보람 보고이고 조장이 AWS에서 본 것은 아니다.
- **남은 일:** 3회차 문서 72행의 낡은 #73 문장 정정, 이전 코멘트의 깨진 링크 2곳·`TODO.md` 314행·20~23번 시험 결과 반영, `AssociateWebACL`·`GetWebACLForResource` 리소스 대상 확인(민성 연결 시험에서 거부될 때).

## 민성's comment · 2026-11-13 밤 · SG 점검 도구 짝 리뷰 요청 (#109)

- **병합됨:** #109(SG 점검 도구 0.3.0과 증거 묶음). 조장이 증거 묶음에서 계정 앞 4자리가 남은 것을 찾아 고친 뒤 병합했다.
- **짝 리뷰 부탁(병합 뒤):** ① 필요 권한이 27번 `Haven-Minchul-SG-Read` 범위와 맞는지(`DescribeInstances` 불필요). ② `sts:GetCallerIdentity`는 IAM 정책 없이도 호출되는 것으로 알고 있는데 추가가 필요한지 확인. ③ 증거 묶음의 가림 범위(ID·ARN·IP·계정)가 공개 자료 기준으로 충분한지(`이민성/sg_audit/evidence/` 참고).
- **참고:** JSON의 계정 번호 변수화(16:18 커밋)는 좋은 방향이다. 브랜치의 미병합 커밋(OUT-10 DB 로그 권한, 계정 번호 변수화 등 49개)은 PR로 올려 달라.

## 민성's comment · 2026-11-16 오후 · 병합 정리와 남은 일

- **병합됨:** #111, #113, #115, #118, #119, #121. 27번에서 `DescribeInstances`·`DescribeSubnets` 제거, 혁민 20번 `/haven/db` 읽기 추가, 계정 번호 변수화, DB 로그 수집량(30일 약 10 MB)이 main에 들어갔다.
- **11/17 조장 요청 후속 처리:** DB 로그 예상 비용(월 약 $0.008, 추정치) 기록 및 JSON 02·04·06·07·08 변수명 통일 완료. 12번 IAM `Resource: "*"` 범위는 확인 후 [민성님 검토 요청](https://github.com/MinsooAhn02/Haven/pull/127#issuecomment-6935037215) 완료(수정 결정 대기). 시험 메일 스팸 분류 건은 [#117 의견 전달](https://github.com/MinsooAhn02/Haven/pull/117#issuecomment-6935371122) 완료(재수신 및 AWS 적용 결정 대기). 세부 내용은 [3회차 작업 기록](1~4회차/3회차.md)에 기재함.
- **계속 미완료:** 시험용 EC2 삭제 허용·운영 EC2 거부 검증, AWS 최종 사용액·타 리전·잔여 과금 확인, 보존·종료 승인 및 실제 종료 확인. 4회차 완료 처리하지 않음.
