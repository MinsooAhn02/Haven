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
