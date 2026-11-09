# Haven workflow documentation plan

- [x] Update `TASK_TODO.md` with dependency flow, handoffs, status/evidence snapshot, and merge/deploy gates; reuse its existing six-owner/four-round tables.
- [x] Add the minimal `안민수/공통실행.md` known-vs-pending execution contract and link it from Minsoo TODOs.
- [x] Check local Markdown links, balanced Mermaid fences, diff whitespace/scope; retain pre-existing personal changes.

## 통합·배포할 저장소 상태

- [x] 문서 변경 검증 후 Minsoo에 커밋·푸시한다 (`5a5556a`).
- [x] 기존 PR #3 시안 기록을 정리하고 HTML 7개 링크/조각 44건 검증 후 main에 merge commit 병합한다 (`36db226`).
- [x] 기존 PR #2의 확인된 CLI 결함을 최소 수정·회귀 시험 5개 통과 후 병합한다 (`6d61d6c`).
- [x] 문서 PR #4를 생성하고 최신 main의 PR #2·#3 통합 결과와 현황을 반영한다.

문서 PR #4의 병합 결과와 최종 main/Minsoo 동기화는 GitHub PR 상태와 원격 SHA 대조로 확인한다. 위 완료 표시는 AWS 구축이나 앱/CI 구현 완료를 뜻하지 않는다.

## 민수 1회차 · 앱과 독립적인 실제 CI

- [x] 현재 SG CLI 회귀 시험을 실행하는 최소 CI와 공통 Python 개발 파일 제외 규칙을 추가한다.
- [x] 로컬 정상·실패 전파를 확인하고 실행 안내·진행 상태를 실제 결과와 일치시킨다 (SG fixture 5개 통과, 의도적 실패 exit 1).
- [x] 커밋·푸시·PR #5 생성 후 GitHub Actions 실제 실행 42210689183의 시험 5개 성공을 확인한다.

PR #5의 병합·main/Minsoo 동기화와 병합 후 CI는 실제 GitHub 결과로 확인한다. Django/DB 시험은 앱 인계 후 진행한다.

## Minsoo 브랜치 · 남은 독립 작업 마무리

- [x] 최신 원격·개발 도구를 확인하고 개인 TODO의 완료·부분 완료·인계 대기를 실제 근거와 맞췄다.
- [x] `.venv` Python 3.13.15와 추적 소스 격리 재현에서 SG 시험 5개 통과; runner 정상 0·실패 1·시험 0건 1과 비밀값/캐시 제외를 확인했다.
- [x] DB·배포·재시작·복귀·백업/복원 준비 절차와 담당별 인계 항목을 정리했다. 자원·DB 변경은 실행하지 않았다.
- [x] 민수 소유 변경을 `391d51f`로 커밋·Minsoo에 푸시하고 [브랜치 CI 42217699407](https://github.com/MinsooAhn02/Haven/actions/runs/42217699407)의 성공을 확인했다. 원격 main은 `dd0a826`으로 유지했다.

## 팀원별 TODO와 다음 인계 검토

- [x] 각 개인 브랜치의 최신 TODO·산출물을 대조했다 (Minsoo 9c70454, Yochan f2130f9, Pureun c5002cd, Boram f8410e6, Minsung 864a847, Hyeokmin aa7c0f3).
- [x] 다음 행동·선행조건·인계 대상·완료 기준과 main 운영 규칙의 일치 여부를 평가했다.
- [x] 담당자별 유지할 내용·최소 보완점·즉시 다음 행동을 정리했다. 개인 TODO 수정·팀원 전달은 이번 분석에 포함하지 않았다.

## 개인 브랜치 코멘트·공용 다음 작업 반영

- [x] 여섯 개인 TODO에 날짜가 있는 `민수's comment`를 추가했다. 기존 본문과 체크 상태를 보존했다.
- [x] 팀원 5개 브랜치에 해당 TODO만 커밋·푸시했다: Yochan `b9c42b7`, Pureun `b2f9124`, Boram `25ed1c1`, Minsung `df520b1`, Hyeokmin `8788338`. 미완성 개인 작업은 main에 일괄 병합하지 않았다.
- [x] 공용 TODO에 담당별 다음 행동·선행조건·인계 대상·완료 기준을 추가했다.
- [x] 문서 변경과 개인 브랜치 반영을 검증하고 공용 PR #6을 생성했다. `899e283`의 브랜치 CI 42237217279가 성공했다. main 반영·Minsoo 동기화·병합 후 CI는 PR #6의 실제 병합 결과로 최종 확인한다.

## 로컬 팀장 업무 인계 기록

- [x] Git에서 제외되는 로컬 인계 기록과 다음 세션 진입점을 만들었다.
- [x] 이번 세션의 결정·검증 근거·미완료 작업·일일 점검 순서를 기록하고 Codex 메모리에 위치를 남겼다.
- [x] 로컬 기록 4개가 존재하고 Git에서 제외·미추적되는 것을 확인했다. 비밀값과 대화 원문 전체는 저장하지 않았다.

## 2026-11-07 신요찬 작업 검토

- [x] 원격 브랜치·PR·최근 활동에서 검토할 변경의 위치와 SHA를 확인했다.
- [ ] 변경이 있으면 diff와 연결 코드를 팀 인계 기준에 대조하고 검증 가능한 항목을 확인한다.
- [x] 검토 결과와 미확인 범위를 로컬 인계 기록에 남겼다.

검토 기록 · 원격 브랜치·PR·최근 활동과 diff 확인 완료. Yochan 앱 변경을 찾지 못해 구현 검증은 산출물 인계 후 진행. 병합 기준과 현황은 Git 제외 로컬 세션 기록에 보관.

## 2026-11-07 팀원 변경과 병합 순서 검토

- [x] 원격 SHA·PR·리뷰·CI와 main 반영 여부를 담당별로 확인했다.
- [x] 열린 #7·#8의 범위와 병합 전 이슈를 검토하고 요청 CLI 시험을 재현했다.
- [x] 독립 PR과 앱 의존 작업의 병합 순서를 정리하고 로컬 기록에 남겼다.

## 2026-11-07 주간 운영 계획 실행

- [x] 공용 주간 현황과 리뷰 양식을 #9로 검증·병합했다.
- [x] 개인 브랜치 여섯 곳에 해당 TODO 가이드 커밋을 푸시했다.
- [x] #8과 #7을 별도 커밋으로 수정·검증하고 병합 결과를 #10으로 반영했다.
- [x] 원격 SHA·검사·링크와 로컬 인계 기록을 확인했다.

## 2026-11-08 보람 추가 점검 인계
- [x] #11 병합과 main CI 확인 후 #12로 공용 리뷰를 갱신했다.

## 민수 2회차 · 서버 설치·배포 스크립트 (계획 2026-11-09, 수요일 구축·목/금 첫 배포 대비)

위치 `안민수/server/` (bash, `set -euo pipefail`, LF). SSM으로 서버에서 실행. AWS 자원은 만들지 않는다(민성 담당).

- [x] `db-setup.sh` (db-1): PostgreSQL 16 설치, `listen_addresses`=사설 IP, DB `haven` + `haven_owner`(소유·migrate)/`haven_app`(CRUD만), pg_hba는 web-1 IP/32에서 두 계정만 scram 허용·나머지 reject. 두 번 실행해도 같은 결과
- [x] `web-setup.sh` (web-1): Python 3.12 venv, `haven` 비root 계정, Gunicorn(127.0.0.1:8000, systemd), Nginx(:80 → Gunicorn, static 직접 제공, `/healthz`는 Host 고정해 ALB 검사 통과)
- [x] `deploy.sh` (web-1): 지정 commit 받기 → pip 설치 → migrate(haven_owner) → haven_app 읽기 확인 → 재시작 → `/healthz` 200 확인, 실패 시 이전 commit으로 복귀. 배포 commit 기록
- [x] 비밀값 공급: SSM Parameter Store `/haven/*` (`put-secrets.sh`)
- [x] 검증(33/33 통과, 2026-11-09): WSL Ubuntu에서 db/web 스크립트 실제 실행(2회 실행 포함), 일부러 실패(빈 값, haven_app으로 CREATE TABLE 거부, 잘못된 commit → 복귀, postgres 원격 접속 거부)
- [x] static은 Nginx가 `노푸른/static` 직접 제공 → 요찬 요청 불필요. gunicorn은 `안민수/server/requirements.txt`
- [ ] PR (스크립트는 조장도 PR)

결정(조장 11/09): 코드는 읽기 전용 deploy key, 비밀값은 SSM Parameter Store, 시험은 WSL Ubuntu-24.04.
