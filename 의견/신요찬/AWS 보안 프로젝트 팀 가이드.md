# AWS 보안 프로젝트 팀 가이드

Nov 4, 2026 · @chan

## 한눈에 보기

&#91;embedded content: 서비스 구조 · 서버 4종과 계정 전체 보안 서비스\]

사용자는 로드밸런서의 WAF를 통과해야 Web에 닿고, DB는 인터넷에서 직접 접근할 수 없는 숨겨진 구역에 있습니다. DB가 업데이트를 받을 때는 NAT 서버를 거치고, 그 길목에서 IPS가 트래픽을 검사합니다. 이 그림은 11월 말(4단계 완료) 기준이며, 1주차에는 로드밸런서 없이 Web 서버에 바로 접속합니다.

## 우리가 만드는 것

**작은 회원제 게시판 하나를 만들고, 그 위에 보안을 한 겹씩 쌓아 갑니다.** 11월(기본)에 서비스와 보안 장비를 갖추고, 12월(심화)에 암호화와 인증서를 더합니다.

| 구분 | 사용 기술 | 한 줄 설명 |
| --- | --- | --- |
| 서버 OS | Ubuntu 24.04 LTS | 모든 서버를 같은 OS로 통일 |
| 웹 서비스 | Python FastAPI + HTML 템플릿 | 코드가 짧고 읽기 쉬움, 점검 스크립트와 같은 언어 |
| 웹 서버 | Nginx | HTTPS 처리, 뒤에서 FastAPI 실행 |
| DB | PostgreSQL 16 | 회원 정보와 게시글 저장, DB가 직접 접근 제어(RLS) |
| 클라우드 | AWS 서울 리전 | EC2, IAM, WAF, KMS 등 |

화면은 5개로 정해 두고 더 늘리지 않습니다. 이 5개로 모든 단계의 보안 시연이 가능합니다.

| 화면 | 기능 | 이 화면으로 보여줄 보안 |
| --- | --- | --- |
| 회원가입 | 이메일, 비밀번호, 전화번호 입력 | 비밀번호 해시, 인증 메일 |
| 로그인 | 로그인, 로그아웃 | 세션 관리, 무차별 대입 차단 |
| 내 정보 | 전화번호, 주소 조회와 수정 | 개인정보 암호화 (12월) |
| 게시판 | 글 목록, 글쓰기 | SQL 인젝션, XSS 방어 |
| 관리자 페이지 | 회원 목록 | 권한 분리, 비인가 접근 차단 |

## 일정

| 기간 | 할 일 | 리드 |
| --- | --- | --- |
| 11/4 \~ 11/10 | 1단계: 서버와 웹 서비스 구축, 도메인과 메일 연결 | ②③④⑥ |
| 11/11 \~ 11/17 | 2단계: 팀원 계정과 권한 설정 | ⑤ |
| 11/18 \~ 11/24 | 3단계: 네트워크 보안, 암호화 키 준비 | ②④ |
| 11/25 \~ 12/1 | 4단계: WAF, IPS, 자동 대응 + 기본 결과서 | ⑥ ① |
| 12/2 \~ 12/14 | 심화 1: 개인정보 암호화와 키 관리 | ③④ |
| 12/15 \~ 12/26 | 심화 2: 인증서와 HTTPS | ② |
| 12/27 \~ 1월 초 | 심화 3: 통합 검증 + 최신 보안 적용 | ⑤⑥ ① |

다음 단계 리드는 앞 단계가 진행되는 동안 미리 설계를 시작합니다. 예를 들어 ⑤는 1주차부터 권한 정책 초안을 씁니다.

## 단계별 체크리스트

각 단계는 **목표 한 줄, 할 일, 결과물** 세 가지만 기억하면 됩니다. (도전)은 선택 과제, (12월 대비)는 심화에서 다시 쓰는 작업입니다.

### 1단계: 서비스 만들기&#32;

**목표**: 인터넷에서 접속되는 회원제 게시판을 만든다.

- [ ] 루트 계정 MFA, 예산 경보(5만, 10만, 15만원), 밤 11시 서버 자동 중지 설정
- [ ] 네트워크 만들기: 외부에 열리는 구역(Web)과 숨겨진 구역(DB)으로 나눔
- [ ] DB 서버 설치, 회원 테이블 생성 (개인정보 칸은 처음부터 암호문 저장용으로, 12월 대비)
- [ ] 웹 서비스 화면 5개 개발 (암호화 함수 자리만 만들어 두기, 12월 대비)
- [ ] (도전) 도메인 연결, 회원가입 인증 메일 발송

**결과물**: 환경 구축 결과서, 인프라 구성도, 서비스 동작 캡처

### 2단계: 계정과 권한&#32;

**목표**: 팀원마다 필요한 권한만 갖게 한다.

- [ ] 그룹 4개 만들기: 관리자, 웹 운영, DB 운영, 감사(조회만)
- [ ] 공통 규칙 적용: MFA 필수, 서울 리전만, 작은 서버만 생성 가능
- [ ] 서버에는 비밀 키 대신 역할(Role)로 권한 부여
- [ ] 권한 테스트 표 작성: 누가, 무엇을, 허용/거부 (12월 대비)
- [ ] (도전) 일부러 과한 권한을 만든 뒤 점검 도구로 찾아 고치기

**결과물**: IAM 권한 관리 결과서, 정책 자료, (도전) 점검 및 개선 보고서

### 3단계: 네트워크 보안

**목표**: 열려야 할 문만 열고 나머지는 닫는다.

- [ ] 접근 허용표 작성 후 보안 그룹 정리 (DB는 Web에서만 접속)
- [ ] 원격 접속 포트(22번) 닫고 AWS Session Manager로 접속
- [ ] 네트워크 기록(Flow Logs) 수집
- [ ] 디스크, 로그 암호화와 DB 비밀번호 금고(Secrets Manager) 적용
- [ ] 개인정보 암호화용 키 미리 생성 (12월 대비)
- [ ] (도전) 열린 포트를 자동으로 찾는 점검 스크립트

**결과물**: 네트워크 보안 구성도, 접근 통제 결과서, (도전) 점검 스크립트와 보고서

### 4단계: 보안 장비&#32;

**목표**: 공격을 막고, 탐지하고, 자동으로 대응한다.

- [ ] 위협 탐지(GuardDuty), 보안 점수(Security Hub) 켜기
- [ ] 실습용 인증 기관(CA) 만들기 (12월 대비)
- [ ] 로드밸런서 + 웹 방화벽(WAF) 설치, SQL 인젝션과 XSS 차단 테스트
- [ ] 침입 차단 시스템(Suricata IPS) 설치
- [ ] 공격 탐지 시 IP 자동 차단과 메일 알림
- [ ] (도전) 보안 점수 개선 전후 비교

**결과물**: 보안 장비 구축 결과서, 정책 자료, (도전) 개선 보고서

## 12월 심화 미리보기

**11월에 "(12월 대비)" 작업을 해 두면, 12월에는 스위치를 켜고 검증하는 일만 남습니다.**

| 심화 단계 | 하는 일 | 11월에 미리 해 두는 것 |
| --- | --- | --- |
| 심화 1 | 전화번호, 주소를 암호화해서 저장. 관리자도 못 읽게 | 암호문용 DB 칸, 암호화 함수 자리, 암호화 키 |
| 심화 2 | 직접 만든 인증서로 HTTPS 적용 | 실습용 인증 기관(CA) |
| 심화 3 | 권한 없는 사람이 막히는지 전체 점검, 서버끼리 인증서로 서로 확인(mTLS), 회원은 자기 행만 보도록 DB에서 제한(RLS) | 권한 테스트 표, DB 구간 암호화 |

심화 필수를 마치면 남는 시간에 **최신 보안 2\~3개**를 골라 추가합니다.

- **양자내성 HTTPS**: 미래의 양자컴퓨터 해독에 대비한 암호. 로드밸런서 설정만 바꾸면 적용됩니다.
- **패스키 로그인**: 비밀번호 대신 지문이나 얼굴로 로그인. 피싱에 강합니다.
- **키 교체 시연**: 서비스를 멈추지 않고 암호화 키를 새것으로 바꾸기.

## 팀 규칙과 자주 막히는 곳

### 팀 규칙 5가지

1. **루트 계정은 팀장만** 보관합니다. 모두 개인 계정과 MFA로 작업합니다.
2. 만든 리소스에는 **태그 3개**를 꼭 붙입니다: `Project=cloud-sec`, `Owner=이름`, `AutoStop=true`.
3. 코드와 설정은 **Git에 올리고**, 다른 팀원 1명이 확인한 뒤 합칩니다.
4. 캡처는 `docs/evidence/날짜_작업명/` 폴더에 모읍니다. 결과서 쓸 때 시간이 크게 줄어듭니다.
5. 주 2회, 15분 회의로 진행 상황과 막힌 점을 공유합니다.

### 자주 막히는 곳

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| 서버에서 메일이 안 나감 | AWS가 25번 포트를 기본 차단 | 메일은 SES로 발송 |
| 이번 달 요금이 갑자기 늘었음 | NAT Gateway, 로드밸런서를 켜 둔 채 방치 | 작업 끝나면 끄기, 예산 경보 확인 |
| 새 팀원이 아무것도 못 함 | MFA를 아직 등록하지 않음 | 첫 로그인 후 MFA부터 등록 |
| Session Manager 접속이 안 됨 | 서버 역할 권한 또는 인터넷 출구(NAT) 없음 | 역할에 SSM 권한 확인, NAT 켜기 |
| Web에서 DB 접속이 거부됨 | pg\_hba.conf에 Web 구역 허용 줄이 없거나 listen\_addresses 미설정 | 두 설정 확인 후 PostgreSQL 재시작 |
| 암호화한 데이터가 안 읽힘 | 암호화 키를 삭제 예약함 | **KMS 키는 절대 삭제하지 않기** |

## 부록: 처음 설치 명령 모음

1주차에 바로 쓰는 명령만 모았습니다. 권한 정책 JSON, 키 정책, WAF와 IPS 같은 2\~4단계 세부 설정은 [상세 구축 가이드](https://claude.ai/artifact/8Adia2wGXaw693BGh44Psg)를 참고하고, 그 문서의 1단계(PHP, Amazon Linux)는 이 부록으로 대체합니다.

### Web 서버 (Ubuntu 24.04)

```bash
sudo apt update && sudo apt install -y nginx python3-venv
mkdir -p ~/app && cd ~/app
python3 -m venv .venv && . .venv/bin/activate
pip install fastapi "uvicorn[standard]" jinja2 python-multipart "psycopg[binary]" argon2-cffi itsdangerous
uvicorn main:app --host 127.0.0.1 --port 8000   # 동작 확인 후 systemd 서비스로 등록
```

```text
app/
├── main.py        # 화면 5개 라우팅
├── crypto.py      # 암호화 함수 자리 (12월에 내용만 교체)
├── db.py          # DB 연결
└── templates/     # signup, login, me, board, admin .html
```

```python
# main.py — 최소 시작 코드
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # 운영에서는 API 설명 페이지 끄기
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})
```

```python
# crypto.py — 11월 버전: 암호화 없이 BYTEA 칸에 맞게 bytes로만 바꿔 통과
def encrypt_field(plain, aad):
    return {"ct": plain.encode() if plain else None, "iv": None, "kv": 0}

def decrypt_field(ct, iv, kv, aad):
    return bytes(ct).decode() if ct else None   # 12월: kv가 1 이상이면 AES-256-GCM 복호화
```

Nginx는 우선 80번으로 FastAPI에 연결하고, HTTPS는 4단계에서 붙입니다. 파일 위치는 `/etc/nginx/sites-available/app`이며 `sites-enabled`에 링크합니다.

```nginx
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Ubuntu 24.04의 Nginx는 1.24라서, 4단계에서 HTTPS를 붙일 때 `http2 on;` 대신 `listen 443 ssl http2;`로 씁니다.

### DB 서버 (Ubuntu 24.04)

```bash
sudo apt update && sudo apt install -y postgresql      # Ubuntu 24.04 기본은 PostgreSQL 16

# 1) 접속 받을 주소: /etc/postgresql/16/main/postgresql.conf
#    listen_addresses = '<DB 사설 IP>'
# 2) 접속 허용 규칙: /etc/postgresql/16/main/pg_hba.conf 맨 아래에 한 줄 추가
#    hostssl  appdb  app  10.0.1.0/24  scram-sha-256
sudo systemctl restart postgresql
```

`hostssl`은 "암호화된 접속만 허용"이라는 뜻입니다. Ubuntu는 설치할 때 임시 인증서로 TLS를 켜 두기 때문에 1주차부터 바로 쓸 수 있고, 4단계에서 우리 CA가 발급한 인증서로 바꿉니다.

```sql
-- sudo -u postgres psql 로 접속해서 실행
CREATE ROLE app LOGIN PASSWORD '<강한 비밀번호>';
CREATE DATABASE appdb;
\c appdb

CREATE TABLE users (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,                 -- 비밀번호는 암호화가 아니라 해시(argon2)
  role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  phone_enc     BYTEA,                         -- 12월 암호화 대비
  phone_iv      BYTEA,
  address_enc   BYTEA,
  address_iv    BYTEA,
  key_version   INT NOT NULL DEFAULT 0,        -- 0 = 평문(11월), 1 이상 = 암호화
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE posts (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id),
  title      TEXT NOT NULL,
  body       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT CONNECT ON DATABASE appdb TO app;
GRANT USAGE ON SCHEMA public TO app;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, posts TO app;
```

테이블 주인은 `postgres`이고 웹 앱은 `app` 계정으로만 접속합니다. 테이블 주인은 행 단위 접근 제어(RLS)를 기본적으로 건너뛰기 때문에, 앱 계정을 주인으로 만들지 않아야 12월에 켜는 RLS가 제대로 동작합니다.

```python
# db.py — Web에서 DB 연결
import psycopg

conn = psycopg.connect(
    host="db.internal",      # 프라이빗 DNS를 아직 안 만들었다면 DB 사설 IP
    dbname="appdb", user="app", password=DB_PASSWORD,   # 비밀번호는 3단계부터 Secrets Manager에서 읽기
    sslmode="require",       # 4단계부터 verify-full + 우리 CA 인증서로 강화
)
```

12월 상호 인증(mTLS)은 `pg_hba.conf` 줄 끝에 `clientcert=verify-full`만 붙이면 됩니다. 이때 Web 서버의 클라이언트 인증서 CN은 DB 사용자 이름인 `app`과 같아야 합니다.

### NAT 서버 (Ubuntu 24.04, t4g.nano)

DB 서버가 패키지를 내려받을 인터넷 출구입니다. EC2 설정에서 "소스/대상 확인"을 끈 뒤 실행합니다. 4단계에서 이 서버에 Suricata IPS를 함께 올립니다.

```bash
sudo apt update && sudo apt install -y iptables-persistent
echo 'net.ipv4.ip_forward = 1' | sudo tee /etc/sysctl.d/90-nat.conf && sudo sysctl --system
sudo iptables -t nat -A POSTROUTING -o ens5 -j MASQUERADE   # 인터페이스 이름은 ip addr 로 확인
sudo netfilter-persistent save
```
