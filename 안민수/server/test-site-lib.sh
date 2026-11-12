#!/usr/bin/env bash
# site-lib.sh(메일 설정 줄·site.conf 값 지움 방지)와 그 사용 위치를 시험한다. root·AWS·서버 없이 어디서나:
#   bash test-site-lib.sh        (Git Bash 또는 리눅스, 이 폴더에서)
# 실제 서버 동작(설치·배포)은 test-wsl.sh와 web-1 실행 기록으로 확인한다.
set -uo pipefail
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=site-lib.sh
source "$D/site-lib.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "PASS  $1"; }
bad() { fail=$((fail+1)); echo "FAIL  $1"; [[ -n ${2:-} ]] && printf '      | %s\n' "$2"; }
NL=$'\n'

# mail <이름> <주소> <리전> <기대: ok|fail> [기대 출력]
mail() {
  local name=$1 from=$2 region=$3 want=$4 expect=${5-} out rc
  out=$(mail_env_lines "$from" "$region" 2>"$T/err"); rc=$?
  if [[ $want == ok ]]; then
    if (( rc == 0 )) && [[ $out == "$expect" ]]; then ok "$name"; else bad "$name" "rc=$rc out=[$out]"; fi
  else
    if (( rc != 0 )) && [[ -z $out ]] && [[ -s $T/err ]]; then ok "$name"; else bad "$name (should fail with no output)" "rc=$rc out=[$out]"; fi
  fi
}

echo "── 메일 설정 줄 (mail_env_lines) ──"
mail "M1 주소 없음 → console 한 줄(보내지 않음)" "" ap-northeast-2 ok "HAVEN_MAIL_BACKEND=console"
mail "M2 확정 발신 주소 → ses·주소·리전 세 줄 같이" noreply@orchestration-haven.cloud ap-northeast-2 ok \
  "HAVEN_MAIL_BACKEND=ses${NL}HAVEN_MAIL_FROM=noreply@orchestration-haven.cloud${NL}HAVEN_SES_REGION=ap-northeast-2"
mail "M3 다른 리전도 그대로" a.b+c@mail.example.com us-east-1 ok \
  "HAVEN_MAIL_BACKEND=ses${NL}HAVEN_MAIL_FROM=a.b+c@mail.example.com${NL}HAVEN_SES_REGION=us-east-1"
mail "M4 주소 없음이면 리전이 비어도 console" "" "" ok "HAVEN_MAIL_BACKEND=console"
mail "M5 @ 없음" noreply.orchestration-haven.cloud ap-northeast-2 fail
mail "M6 아이디 없음" @orchestration-haven.cloud ap-northeast-2 fail
mail "M7 도메인 끝이 한 글자" a@b.c ap-northeast-2 fail
mail "M8 줄바꿈으로 다른 설정 끼워 넣기" "a@b.com${NL}DJANGO_DEBUG=1" ap-northeast-2 fail
mail "M9 공백으로 다른 설정 끼워 넣기" "a@b.com DJANGO_DEBUG=1" ap-northeast-2 fail
mail "M10 따옴표 포함" "'a@b.com'" ap-northeast-2 fail
mail "M11 앞뒤 공백" " a@b.com" ap-northeast-2 fail
mail "M12 CR 섞임(Windows 줄바꿈)" $'a@b.com\r' ap-northeast-2 fail
mail "M13 리전 비어 있음(주소는 있음)" a@b.com "" fail
mail "M14 리전 형식 틀림(숫자 없음)" a@b.com ap-northeast fail
mail "M15 리전에 줄바꿈 끼워 넣기" a@b.com "ap-northeast-2${NL}DJANGO_DEBUG=1" fail
mail "M16 리전 대문자" a@b.com AP-NORTHEAST-2 fail
# 성질: 어떤 입력이든 ses가 나오면 발신 주소 줄도 반드시 같이 나온다
prop_ok=1
for f in "" a@b.com bad "x@y.zz" "a@b.com${NL}X=1"; do
  for r in ap-northeast-2 "" bad; do
    o=$(mail_env_lines "$f" "$r" 2>/dev/null) || continue
    if [[ $o == *HAVEN_MAIL_BACKEND=ses* && $o != *HAVEN_MAIL_FROM=?* ]]; then prop_ok=0; fi
  done
done
(( prop_ok )) && ok "M17 ses만 있고 발신 주소가 빠진 출력은 없음" || bad "M17 ses만 있고 발신 주소가 빠진 출력이 나옴"

echo "── site.conf 값 지움 방지 (keep_or_die) ──"
# keep <이름> <site.conf 내용(없으면 NOFILE)> <키> <새 값> <기대 ok|fail> [ALLOW_CLEAR]
keep() {
  local name=$1 content=$2 key=$3 new=$4 want=$5 allow=${6-} conf="$T/site.conf" rc
  rm -f "$conf"; [[ $content != NOFILE ]] && printf '%s' "$content" > "$conf"
  ALLOW_CLEAR=$allow keep_or_die "$key" "$new" "$conf" 2>"$T/err"; rc=$?
  if [[ $want == ok ]]; then (( rc == 0 )) && ok "$name" || bad "$name" "$(cat "$T/err")"
  else (( rc != 0 )) && [[ -s $T/err ]] && ok "$name" || bad "$name (should fail)"; fi
}
SITE=$'DB_HOST=10.0.0.1\nCSRF_TRUSTED_ORIGINS=https://orchestration-haven.cloud\nAWS_REGION=ap-northeast-2\nMAIL_FROM=noreply@orchestration-haven.cloud\n'
OLD=$'DB_HOST=10.0.0.1\nCSRF_TRUSTED_ORIGINS=https://orchestration-haven.cloud\nAWS_REGION=ap-northeast-2\n'
keep "K1 site.conf 없음(첫 설치) → 진행" NOFILE CSRF_TRUSTED_ORIGINS "" ok
keep "K2 CSRF 있던 값을 빠뜨림 → 멈춤 (HTTPS 꺼짐 방지)" "$SITE" CSRF_TRUSTED_ORIGINS "" fail
keep "K3 MAIL_FROM 있던 값을 빠뜨림 → 멈춤" "$SITE" MAIL_FROM "" fail
keep "K4 같은 값 다시 넣음 → 진행" "$SITE" CSRF_TRUSTED_ORIGINS https://orchestration-haven.cloud ok
keep "K5 다른 값으로 바꿈 → 진행" "$SITE" MAIL_FROM other@orchestration-haven.cloud ok
keep "K6 일부러 비움(ALLOW_CLEAR=1) → 진행" "$SITE" MAIL_FROM "" ok 1
keep "K7 예전 서버(MAIL_FROM 줄 자체가 없음) + 빈 값 → 진행" "$OLD" MAIL_FROM "" ok
keep "K8 예전 값이 빈 줄(CSRF_TRUSTED_ORIGINS=) + 빈 값 → 진행" $'CSRF_TRUSTED_ORIGINS=\n' CSRF_TRUSTED_ORIGINS "" ok
keep "K9 비슷한 이름(XMAIL_FROM)은 무시" $'XMAIL_FROM=a@b.com\n' MAIL_FROM "" ok
keep "K10 CRLF로 저장된 site.conf도 값 인식 → 멈춤" $'MAIL_FROM=a@b.com\r\n' MAIL_FROM "" fail
keep "K11 ALLOW_CLEAR가 1이 아니면(yes) 멈춤" "$SITE" MAIL_FROM "" fail yes
keep "K12 CRLF로 저장된 빈 값(CSRF_TRUSTED_ORIGINS=\\r) + 빈 값 → 진행 (잘못 멈추지 않음)" $'CSRF_TRUSTED_ORIGINS=\r\n' CSRF_TRUSTED_ORIGINS "" ok

echo "── 사용 위치 (서버를 바꾸기 전에 검사하는지) ──"
line() { grep -n -m1 -F -- "$2" "$D/$1" | cut -d: -f1; }
dl_src=$(line deploy.sh 'source "$(dirname "$0")/site-lib.sh"'); dl_mail=$(line deploy.sh 'MAIL_LINES=$(mail_env_lines')
dl_write=$(line deploy.sh 'cat > /etc/haven/haven.env.new'); dl_use=$(line deploy.sh '$MAIL_LINES')
dl_switch=$(line deploy.sh 'ln -sfn "$R" "$H/current.new"')
[[ -n $dl_src && -n $dl_mail && -n $dl_write && $dl_src -lt $dl_mail && $dl_mail -lt $dl_write ]] \
  && ok "S1 deploy.sh: 메일 줄 검사가 haven.env 쓰기 전" || bad "S1 deploy.sh 순서" "src=$dl_src mail=$dl_mail write=$dl_write"
grep -q 'MAIL_LINES=$(mail_env_lines .*|| die' "$D/deploy.sh" \
  && ok "S2 deploy.sh: 형식 틀리면 die (전환 안 함)" || bad "S2 deploy.sh: 실패 시 die 없음"
[[ -n $dl_use && $dl_use -gt $dl_write && $dl_use -lt $dl_switch ]] \
  && ok "S3 deploy.sh: 메일 줄이 haven.env 안에 들어감" || bad "S3 deploy.sh: \$MAIL_LINES 위치" "use=$dl_use"
ws_chk=$(line web-setup.sh 'mail_env_lines "$MAIL_FROM"'); ws_k1=$(line web-setup.sh 'keep_or_die CSRF_TRUSTED_ORIGINS')
ws_k2=$(line web-setup.sh 'keep_or_die MAIL_FROM'); ws_apt=$(line web-setup.sh 'apt-get update')
[[ -n $ws_chk && -n $ws_k1 && -n $ws_k2 && -n $ws_apt && $ws_chk -lt $ws_apt && $ws_k1 -lt $ws_apt && $ws_k2 -lt $ws_apt ]] \
  && ok "S4 web-setup.sh: 입력 검사 3개가 설치(apt) 전" || bad "S4 web-setup.sh 순서" "chk=$ws_chk k1=$ws_k1 k2=$ws_k2 apt=$ws_apt"
awk '/cat > \/etc\/haven\/site.conf/{f=1} f&&/^EOF$/{exit} f' "$D/web-setup.sh" | grep -qx 'MAIL_FROM=$MAIL_FROM' \
  && ok "S5 web-setup.sh: site.conf에 MAIL_FROM 줄" || bad "S5 web-setup.sh: site.conf에 MAIL_FROM 없음"
req=$(tr -d '\r' < "$D/requirements.txt")
b3=$(sed -n 's/^boto3==//p' <<<"$req"); bc=$(sed -n 's/^botocore==//p' <<<"$req")
[[ $b3 == 1.43.120 && $bc == 1.43.120 ]] && ok "S6 requirements: boto3·botocore 1.43.120 고정 (앱계약 E5)" || bad "S6 requirements" "boto3=$b3 botocore=$bc"
syn=1; for f in site-lib.sh deploy.sh web-setup.sh; do bash -n "$D/$f" || syn=0; done
(( syn )) && ok "S7 bash -n (site-lib·deploy·web-setup)" || bad "S7 문법 오류"

# S8: deploy.sh의 환경 파일 쓰기 부분만 떼어 임시 폴더에서 실행해, 실제로 만들어지는 haven.env 내용을 본다
render() {  # render <MAIL_FROM> → 만들어진 env 파일 내용 (실패하면 FAILED)
  local snip="$T/snip.sh"
  awk '/^HTTPS_ON=0;/{f=1} f{print} f&&/^EOF$/{exit}' "$D/deploy.sh" \
    | sed "s#/etc/haven/haven.env.new#$T/haven.env#" > "$snip"
  ( die() { echo "DIE: $*" >&2; exit 9; }
    SECRET_KEY=s APP_PW=p ALLOWED_HOSTS=h DB_HOST=d H=/srv/haven AWS_REGION=ap-northeast-2
    CSRF_TRUSTED_ORIGINS=https://orchestration-haven.cloud MAIL_FROM=$1
    source "$snip" ) 2>/dev/null && tr -d '\r' < "$T/haven.env" || echo FAILED
}
e1=$(render "")
e2=$(render noreply@orchestration-haven.cloud)
e3=$(render "a@b.com${NL}DJANGO_DEBUG=1")
[[ $e1 == *$'DJANGO_HTTPS=1\nHAVEN_MAIL_BACKEND=console'* && $e1 != *HAVEN_MAIL_FROM* ]] \
  && ok "S8a deploy.sh 실제 출력: MAIL_FROM 없음 → console, HTTPS=1 그대로" || bad "S8a" "$e1"
[[ $e2 == *$'HAVEN_MAIL_BACKEND=ses\nHAVEN_MAIL_FROM=noreply@orchestration-haven.cloud\nHAVEN_SES_REGION=ap-northeast-2'* && $e2 == *DJANGO_HTTPS=1* ]] \
  && ok "S8b deploy.sh 실제 출력: MAIL_FROM 있음 → ses 세 줄 + HTTPS=1" || bad "S8b" "$e2"
[[ $e3 == FAILED ]] && ok "S8c deploy.sh 실제 출력: 끼워 넣기 주소 → 멈춤(env 안 만듦)" || bad "S8c" "$e3"

echo
echo "결과: PASS $pass / FAIL $fail"
(( fail == 0 ))
