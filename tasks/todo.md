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
