# 이민성 조장용 Claude 프롬프트

Claude Code를 `Haven/` 레포 루트에서 열고, 세션을 처음 시작할 때 아래 블록을 그대로 붙여 넣는다. 매번 붙여 넣기 번거로우면 레포 밖 본인 설정(`~/.claude/CLAUDE.md`)에 넣어도 된다.

```text
나는 KT 사이버보안 과정 "Orchestration" 팀(6명)의 Haven 프로젝트 조장 이민성이다.
안민수에게서 조장을 이어받는다(11/11 인수인계, 민수가 빠지기 전까지는 같이). 원래 담당은 AWS 네트워크·EC2·SSM·ALB/HTTPS·SG CLI이고,
이제 조장 일과 서버 배포·백업·복원도 맡는다.

Haven: 회원이 비공개 기록을 쓰고 지정한 회원에게만 읽기 공유하는 Django 웹 서비스(AWS 서울, 계정 ACCOUNT_ID_MASKED).
만든 뒤 IDOR·CSRF·WAF·SG 점검 같은 보안 시험을 한다. 범위는 기본프로젝트_계획.md §10, 심화프로젝트_계획.md 그대로이고 줄이지 않는다.

먼저 이 순서로 읽어:
1. docs/인수인계/README.md 와 01~08 (일하는 방식은 08_AI_작업방식.md 그대로)
2. TASK_TODO.html 의 DATA (사람별 할 일), TASK_TODO.md
3. docs/조장_운영기록/README.md 와 가장 최근 날짜 파일
4. 배포할 때는 안민수/공통실행.md, 안민수/server/
5. 인프라는 이민성/infra/

반드시 지킬 것:
- 커밋·PR에 AI 표기(Co-Authored-By 등) 넣지 않기
- 비밀번호·키·토큰을 Git·문서·메시지에 쓰지 않기. 내 브라우저에 자격 증명을 대신 입력하지 않기
- force push 금지. 조장 기록(TASK_TODO.*, docs/조장_운영기록/, docs/인수인계/)만 main 직접 push, 코드는 PR
- 다른 팀원 폴더는 고치지 않기
- 되돌릴 수 없는 AWS 삭제(EC2 terminate, DB, 백업, 버킷, IAM 사용자)는 실행 전에 나에게 확인
- done/완료는 실제로 돌려서 확인한 것만. PR 병합·CI 통과와 실제 서버 동작을 구분해서 보고
- 팀 Discord 공지는 한 글로: 기본은 "6개 브랜치 main 최신으로 맞춰뒀습니다. pull 받고 TODO 이어서 하시면 됩니다."
  할 일은 메시지가 아니라 TASK_TODO.html 사람별 todo에 넣고, 새 문제·안전 경고만 @이름으로 한 줄. "확인했어요/잘했어요" 금지
- 팀 공유 글에 일정을 앞당겼다/압축했다는 표현 쓰지 않기

PR이 올라오면 할 일 (docs/인수인계/01_조장_업무절차.md):
PR 확인(설명·diff·PR에 적힌 로컬 시험 결과·짝 리뷰·거부 시험. GitHub Actions는 11/11부터 꺼져 있음) → 필요하면 main과 합쳐 시험 → 병합 → 6개 브랜치(Minsoo, Minsung, Boram, Yochan, Pureun, Hyeokmin) 동기화 후 뒤처진 수 출력
→ TASK_TODO.html DATA, TASK_TODO.md, docs/조장_운영기록/<오늘>.md 갱신 → 공지 초안.

지금 상태를 먼저 확인해 줘: git fetch 후 브랜치별 앞/뒤 커밋 수, 열린 PR, 오늘 운영기록의 "다음 조장 확인 사항".
```

## 참고

- 서버 작업(Session Manager)은 Claude가 직접 들어가지 않는다. Claude가 붙여넣을 내용과 sha256 값을 만들어 주고, 민성이 콘솔에서 실행한 뒤 결과를 붙여 넣는 방식으로 했다.
- AWS CLI를 Claude에게 실행시킬 때는 조회(describe/list/get)부터 하고, 바꾸는 명령은 내용을 보고 승인한다.
