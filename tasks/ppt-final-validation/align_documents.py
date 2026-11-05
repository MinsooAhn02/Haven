# coding: utf-8
from pathlib import Path
p=Path('docs/발표/통합계획_제작/build_haven_20261105.cjs');s=p.read_text(encoding='utf-8')
s=s.replace('조회: 소유자 또는 활성 공유 / 변경: 소유자만. 미공유·해제·없는 ID는 같은 404로 거부한다.','파일: TXT/PDF · 2MiB/개 · 3개/기록 · 10MiB/계정. 비공개 저장하고 인가 후 다운로드합니다.')
s=s.replace('입력 label, 키보드, 대비, 좁은 화면과 오류 안내를 시험한다.','입력 label, 키보드, 대비, 좁은 화면과 오류 안내를 시험한다. 첨부 제안 상한은 TXT/PDF, 파일당 2MiB, 기록당 3개, 계정당 10MiB다. 텍스트 body 8192바이트와 별도 multipart 2162688바이트를 구분한다. 파일 형식과 크기를 검사하고 UUID 비공개 저장, attachment/nosniff/no-store 응답과 임시/고아 정리를 적용한다. 형식 검증은 악성 파일 부재를 보장하지 않는다.')
s=s.replace('업로드 경로의 필요한 body 규칙만 조정하고 앱 검증을 유지한다. 403만으로 차단을 확정하지 않는다.','파일 요청은 전체 검사가 보장되지 않아 앱의 파일 검증도 수행합니다. 차단 원인은 로그와 함께 확인합니다.')
p.write_text(s,encoding='utf-8')
p=Path('기본프로젝트_계획.md');s=p.read_text(encoding='utf-8-sig')
old='작업별 변경 범위와 기대 시험을 PR에 적는다. M1부터 구현된 앱 시험과 SG fixture를 검사하고 Django 설정, pip-audit 등으로 확장한다. Action 버전/권한을 검토하고 외부 PR에 운영 Secret을 제공하지 않는다. 기본 CI와 AWS 자동 배포는 분리한다.'
new='''GitHub에서 기능과 시험 작업을 나누고 변경과 검증 결과를 공유하며 구현할 계획이다. 아래는 사용할 협업 절차이며 Issue, 브랜치 규칙, Actions가 이미 구성됐다는 뜻은 아니다. 담당자는 팀에서 정하고 문서에서 임의로 배정하지 않는다.

| 순서 | 협업 방법 | 공유할 내용과 완료 조건 |
|---|---|---|
| 1. 작업 정리 | GitHub Issues | 기능/설정/시험의 작업 범위와 완료 조건, 결정된 담당, 관련 계획 |
| 2. 개별 구현 | 작업별 브랜치 | 앱/설정/도구/문서를 해당 작업 범위에서 변경 |
| 3. 변경 공유 | PR | 관련 Issue, 변경 이유와 영향, 실행한 시험, 필요한 가림 화면/설정 자료 |
| 4. 검토와 검사 | 다른 팀원 검토와 준비된 자동 검사 | 기능/권한/기존 동작에 대한 검토, 시험 결과, 미확인 항목 |
| 5. 통합 | 검토 후 main에 합치기 | 필요한 검사 통과와 수정 의견 반영, 변경/시험 기록 유지 |
| 6. 실제 시험과 개선 | AWS 통합 결과를 Issue/PR에 연결 | 실제 정상/거부/복원 결과와 공개 가능한 증거, 잔여 한계와 다음 작업 |

M1부터 구현된 앱 시험과 SG fixture를 검사하고 Django 설정과 pip-audit 등으로 확장한다. Action 버전과 최소 권한을 검토하고 외부 PR에 운영 Secret을 제공하지 않는다. CI 통과와 실제 AWS 연결/배포/서비스 검증은 구분한다. main 통합이 자동 배포를 뜻하지 않으며 AWS 반영은 별도 절차로 수행한다. 비밀값, 세션/쿠키, 민감한 원본 로그는 공유하지 않고 가림 자료만 올린다.'''
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=Path('README.md');s=p.read_text(encoding='utf-8-sig')
anchor='## 기본 필수/선택 대응'
collab='''## GitHub 협업 계획

**Issue로 작업 정리 → 작업별 브랜치에서 구현 → PR로 변경과 시험 공유 → 팀원 검토와 준비된 자동 검사 → main 통합 → 실제 AWS 시험과 증거 공유** 순서로 진행할 계획입니다.

각 작업의 완료 조건과 담당은 팀에서 정합니다. PR에는 변경 이유와 영향, 관련 Issue, 시험 결과를 남깁니다. 자동 검사는 구현된 앱과 설정 점검용 시험 데이터부터 확장하며 CI 통과를 실제 AWS 동작 확인으로 대신하지 않습니다. main 통합과 AWS 반영도 구분합니다. 비밀값과 민감한 원본 로그는 올리지 않고 공개 가능한 가림 자료만 공유합니다.

구체적인 절차는 [기본 계획서의 협업 계획](기본프로젝트_계획.md#91-협업과-최소-pr-검사)에 정리했습니다. Issue나 Actions가 이미 구성됐다는 뜻은 아닙니다.

'''
assert anchor in s;s=s.replace(anchor,collab+anchor)
s=s.replace('[기본 프로젝트 계획서 PPT 초안](docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx): 새 기본 계획서를 바탕으로 만든 14장 발표 자료입니다. 기술과 구성은 팀 검토용 권고안이며 구현 완료를 뜻하지 않습니다.','[기본 프로젝트 계획서 PPT 최종 정리본](docs/발표/Haven_프로젝트_계획서_최종.pptx): 개요, 전체 시스템과 Public/Private 배치, 구현/복원, 사용자/운영 권한, 점검과 GitHub 협업을 정리한 14장입니다. 기술과 구성은 팀 검토용 계획이며 구현 완료를 뜻하지 않습니다.\n\n[14장 발표 대본](docs/발표/Haven_프로젝트_계획서_발표대본.md)도 함께 제공합니다.')
p.write_text(s,encoding='utf-8')
print('Final UI/file safeguards, GitHub plan, README final links aligned.')
