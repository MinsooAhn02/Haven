# coding: utf-8
from pathlib import Path
p=Path('기본프로젝트_계획.md');s=p.read_text(encoding='utf-8')
s=s.replace('작성자 참조, 제목, 본문, 생성/수정 시각 | 작성자는 서버 세션,','작성자 참조, 제목, 본문, 생성/수정 시각, ACTIVE/DELETING 상태 | 작성자는 서버 세션,')
s=s.replace('매 요청 글 조회 권한 재검사, 비공개 저장에서만 읽기','매 요청 글 조회 권한 재검사, 비공개 저장에서만 읽기')
s=s.replace('`Content-Disposition: attachment`와 `nosniff`, 공개 media URL/inline 미제공','`Content-Disposition: attachment`, `nosniff`, `Cache-Control: private, no-store`; 공개 media URL/inline 미제공')
s=s.replace('기록/첨부 삭제 시 먼저 인가상 접근을 막고 실제 파일 삭제 실패는 정리 대상으로 남긴다.','기록 삭제는 같은 DB transaction에서 DELETING 상태, 공유 제거, 첨부 DELETE_PENDING으로 먼저 접근을 막는다. 파일 정리가 끝나기 전 cascade로 메타데이터를 지우지 않고 소유자/용량/정리 대상을 보존한다. 실제 파일 삭제 실패는 재시도 대상으로 남기고 정리 후 최종 삭제한다.')
s=s.replace('공유 해제는 확인 후 POST로 수행하며 이미 내려받은 파일이나 이미 전송된 바이트를 회수하는 기능은 아니다.','공유 해제는 확인 후 POST로 수행하며 이미 내려받은 사본을 회수하거나 진행 중인 전송을 중단하는 보장은 아니다. 이후 새 요청에서 접근을 거부한다.')
s=s.replace('        D-->>B: 기록 본문 또는 인가한 파일 다운로드','        D->>F: 첨부 요청이면 서버 저장 키로 파일 읽기\n        F-->>D: 허용된 활성 파일\n        D-->>B: 기록 본문 또는 인가한 파일 다운로드')
p.write_text(s,encoding='utf-8')
p=Path('README.md');s=p.read_text(encoding='utf-8');s=s.replace('첨부합니다.  운영자는','첨부합니다. 운영자는');p.write_text(s,encoding='utf-8')
