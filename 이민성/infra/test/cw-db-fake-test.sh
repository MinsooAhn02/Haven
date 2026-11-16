#!/usr/bin/env bash
# cw-agent-setup-db.sh 가짜 시험 (서버·AWS·DB에 아무것도 보내지 않음)
#   - 가짜 id·curl·dpkg·runuser·psql·sleep을 PATH 맨 앞에 둔다
#   - 가짜 psql은 설정 값을 임시 폴더의 파일로 흉내 낸다(ALTER SYSTEM → 대기, reload → 적용)
#   - 서버 경로는 임시 폴더 아래로 바꿔서 쓴다 (CWS_TEST=1 CWS_ROOT=<임시 폴더>)
#
# 사용 (Git Bash 또는 리눅스, 이민성/infra 에서)
#   bash test/cw-db-fake-test.sh
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SRC/server/cw-agent-setup-db.sh"
[[ -f $SCRIPT ]] || { echo "server/cw-agent-setup-db.sh 없음"; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
export FK="$WORK/fk" R="$WORK/root"

# ── 가짜 명령 ─────────────────────────────────────────
mk() { cat > "$WORK/bin/$1"; chmod +x "$WORK/bin/$1"; }
mk id <<'EOF'
#!/usr/bin/env bash
[[ $1 == -u ]] && { [[ -f $FK/notroot ]] && echo 1000 || echo 0; exit 0; }
/usr/bin/id "$@"
EOF
mk sleep <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
mk runuser <<'EOF'
#!/usr/bin/env bash
while (( $# )) && [[ $1 != -- ]]; do shift; done; shift
exec "$@"
EOF
mk psql <<'EOF'
#!/usr/bin/env bash
# 가짜 PostgreSQL: $FK/pg/<이름> = 적용된 값, $FK/pend/<이름> = ALTER SYSTEM 뒤 reload 전 값
conn="" sql=""
while (( $# )); do case $1 in -d) conn=$2; shift;; -c) sql=$2; shift;; esac; shift; done
echo "psql $sql" >> "$FK/calls"
[[ -f $FK/pgdown ]] && { echo "psql: connection refused (가짜)" >&2; exit 2; }
if [[ $conn == *application_name=* && ! -f $FK/nolog ]]; then
  app=${conn##*application_name=}
  on=$(cat "$FK/pg/log_connections")
  [[ $on == on ]] && echo "2026-11-16 00:50:00.000 UTC [999] postgres@postgres from [local] LOG:  connection authorized: user=postgres database=postgres application_name=$app" >> "$PGLOG"
fi
case $sql in
  "select 1") echo 1 ;;
  "show "*) k=${sql#show }; cat "$FK/pg/$k" ;;
  "ALTER SYSTEM SET "*)
    k=${sql#ALTER SYSTEM SET }; k=${k%% =*}
    v=${sql#*= \'}; v=${v%\'}; v=${v//\'\'/\'}
    [[ -f $FK/alterfail ]] && { echo "ERROR: 가짜 ALTER 실패" >&2; exit 1; }
    [[ -f $FK/alterfail2 && $k == log_disconnections && ! -f $FK/pend/log_disconnections.reverted ]] && { touch "$FK/pend/log_disconnections.reverted"; echo "ERROR: 가짜 ALTER 실패" >&2; exit 1; }
    mkdir -p "$FK/pend"; printf '%s' "$v" > "$FK/pend/$k" ;;
  "select count(*) from pg_file_settings where error is not null") [[ -f $FK/fileerr ]] && echo 1 || echo 0 ;;
  "select pg_reload_conf()")
    [[ -f $FK/reloadfail ]] && { echo f; exit 0; }
    if [[ ! -f $FK/noapply ]]; then for f in "$FK"/pend/*; do [[ -f $f ]] && mv "$f" "$FK/pg/$(basename "$f")"; done; fi
    rm -f "$FK"/pend/* ; echo t ;;
  *) echo "가짜 psql: 모르는 질의 $sql" >&2; exit 99 ;;
esac
EOF
mk curl <<'EOF'
#!/usr/bin/env bash
echo "curl $*" >> "$FK/calls"
[[ -f $FK/dlfail ]] && { echo "curl: (22) 가짜 403" >&2; exit 22; }
out=""; while (( $# )); do [[ $1 == -o ]] && { out=$2; shift; }; shift; done
if [[ -f $FK/dlempty ]]; then : > "$out"; else echo FAKEDEB > "$out"; fi
EOF
mk dpkg <<'EOF'
#!/usr/bin/env bash
echo "dpkg $*" >> "$FK/calls"
[[ -f $FK/dpkgfail ]] && { echo "dpkg: 가짜 실패" >&2; exit 1; }
ctl="$R/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl"
mkdir -p "$(dirname "$ctl")"
cat > "$ctl" <<'CTL'
#!/usr/bin/env bash
echo "ctl $*" >> "$FK/calls"
aglog="$R/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log"
case "$*" in
  *fetch-config*)
    [[ -f $FK/fcfail ]] && { echo "가짜 설정 실패" >&2; exit 1; }
    echo "Configuration validation succeeded"
    touch "$FK/started"
    mkdir -p "$(dirname "$aglog")"
    echo "2026-11-16T00:50:55Z I! [logagent] piping log from /haven/db/i-x/postgresql" >> "$aglog"
    [[ -f $FK/denied ]] && echo "2026-11-16T00:51:00Z E! cloudwatchlogs: AccessDeniedException: not authorized to perform: logs:PutLogEvents" >> "$aglog"
    [[ -f $FK/othererr ]] && echo "2026-11-16T00:51:00Z E! [outputs.cloudwatchlogs] connection timeout" >> "$aglog"
    exit 0 ;;
  *status*)
    st=stopped; [[ -f $FK/started && ! -f $FK/notrun ]] && st=running
    echo '{'; echo "  \"status\": \"$st\","; echo '  "configstatus": "configured"'; echo '}' ;;
esac
CTL
chmod +x "$ctl"
EOF
export PATH="$WORK/bin:$PATH"
[[ $(command -v psql) == "$WORK/bin/psql" && $(command -v dpkg) == "$WORK/bin/dpkg" ]] || { echo "가짜 명령이 안 잡힘 → 시험 중단"; exit 1; }

# ── 시험 도구 ─────────────────────────────────────────
pass=0; fail=0; OUT=""; CODE=0
export PGLOG="$R/var/log/postgresql/postgresql-16-main.log"
PREFIX0='%m [%p] %q%u@%d '        # Ubuntu 기본(11/16 db-1 확인)
PREFIX1='%m [%p] %q%u@%d from %h '
setpg() { printf '%s' "$2" > "$FK/pg/$1"; }
fresh() {  # 빈 db-1 상태 (11/16 실제 값)
  rm -rf "$FK" "$R"; mkdir -p "$FK/pg" "$FK/pend" "$R/var/log/postgresql"; : > "$FK/calls"
  : > "$PGLOG"
  setpg logging_collector off; setpg log_destination stderr
  setpg log_connections off; setpg log_disconnections off; setpg log_line_prefix "$PREFIX0"
}
run() { OUT=$(CWS_TEST=1 CWS_ROOT="$R" CWS_WAIT=15 bash "$SCRIPT" 2>&1); CODE=$?; }
called() { grep -q -- "$1" "$FK/calls"; }
ncalled() { grep -c -- "$1" "$FK/calls"; }
val() { cat "$FK/pg/$1"; }
check() {
  local name=$1 want=$2 text=$3 ok=1 why="" c; shift 3
  [[ $CODE == "$want" ]] || { ok=0; why+=" exit=$CODE(기대 $want)"; }
  [[ -z $text || $OUT == *"$text"* ]] || { ok=0; why+=" 로그에 '$text' 없음"; }
  for c in "$@"; do eval "$c" || { ok=0; why+=" [$c] 거짓"; }; done
  if (( ok )); then pass=$((pass+1)); printf 'PASS  %s\n' "$name"
  else fail=$((fail+1)); printf 'FAIL  %s →%s\n' "$name" "$why"; printf '%s\n' "$OUT" | sed 's/^/      | /'; fi
}
CFG=$R/usr/local/etc/haven/cloudwatch-agent-db.json
AGLOG=$R/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log
nbak() { find "$R" -name '*.bak-*' | wc -l; }
unchanged0() { [[ $(val log_connections) == off && $(val log_disconnections) == off && $(val log_line_prefix) == "$PREFIX0" ]]; }

echo "── 정상 ──"
fresh; run
check "D1 처음 설치 → 끝까지 OK" 0 "OK  cw-agent-setup-db" \
  'called "dpkg -i -E"' 'called "fetch-config -m ec2 -s"' \
  '[[ $(ncalled "ALTER SYSTEM") == 3 && $(ncalled pg_reload_conf) == 1 ]]' \
  '[[ $(val log_connections) == on && $(val log_disconnections) == on ]]' \
  '[[ $(val log_line_prefix) == "$PREFIX1" ]]' \
  '[[ $(grep -c "\"log_group_name\": \"/haven/db\"" "$CFG") == 1 ]]' \
  'grep -q "\"file_path\": \"/var/log/postgresql/postgresql-16-main.log\"" "$CFG"' \
  'grep -q "{instance_id}/postgresql" "$CFG"' '! grep -q retention "$CFG"' \
  'grep -q "application_name=cws-" "$PGLOG"' '[[ $(nbak) == 0 ]]'
check "D1-b 내 PC 확인 명령 안내 (MSYS_NO_PATHCONV 포함)" 0 "MSYS_NO_PATHCONV=1 aws logs filter-log-events"
: > "$FK/calls"; run
check "D2 다시 실행 → 설치·ALTER·reload·Agent 재시작 없이 OK" 0 "재시작 안 함" \
  '! called dpkg' '! called "ALTER SYSTEM"' '! called pg_reload_conf' '! called fetch-config' \
  '[[ $(grep -o "그대로" <<<"$OUT" | wc -l) == 4 ]]' '[[ $(nbak) == 0 ]]'
rm -f "$FK/started"; : > "$FK/calls"; run
check "D3 설정 같지만 Agent 꺼져 있음 → 설정 적용해서 다시 켬" 0 "Agent에 설정 적용" 'called fetch-config' '! called "ALTER SYSTEM"'
fresh; setpg log_connections on; run
check "D4 하나만 다름 → 다른 2개만 바꿈" 0 "그대로: log_connections" \
  '[[ $(ncalled "ALTER SYSTEM") == 2 ]]' '! called "ALTER SYSTEM SET log_connections"'
fresh; setpg log_line_prefix "%m [%p] it's "; run
check "D5 기존 값에 작은따옴표 → 바꾸기 OK" 0 "OK  cw-agent-setup-db" '[[ $(val log_line_prefix) == "$PREFIX1" ]]'

echo "── 실행 위치·조건 (아무것도 안 바꿈) ──"
fresh; touch "$FK/notroot"; run
check "D6 root 아님" 1 "root가 아님" '! called curl' '! called "ALTER SYSTEM"'
fresh; mkdir -p "$R/etc/haven"; echo x > "$R/etc/haven/haven.env"; run
check "D7 haven.env 있음(web-1) → 멈춤" 1 "web-1로 보임" '! called curl' '! called "ALTER SYSTEM"'
fresh; OUT=$(CWS_ROOT="$R" bash "$SCRIPT" 2>&1); CODE=$?
check "D8 CWS_TEST 없이 CWS_ROOT → 멈춤 (실서버 보호)" 1 "시험(CWS_TEST=1)에서만" '! called psql'
fresh; touch "$FK/pgdown"; run
check "D9 PostgreSQL 접속 안 됨 → 멈춤" 1 "PostgreSQL에 접속 못 함" '! called curl'
fresh; rm "$PGLOG"; run
check "D10 로그 파일 없음 → 멈춤" 1 "0개" '! called curl' '! called "ALTER SYSTEM"'
fresh; : > "$R/var/log/postgresql/postgresql-15-main.log"; run
check "D11 로그 파일 2개(버전 2개) → 멈춤" 1 "2개" '! called curl' '! called "ALTER SYSTEM"'
fresh; setpg logging_collector on; run
check "D12 logging_collector on(로그 위치 다름) → 멈춤" 1 "logging_collector가 on" '! called curl' 'unchanged0'
fresh; setpg log_destination csvlog; run
check "D13 log_destination에 stderr 없음 → 멈춤" 1 "stderr 없음" '! called curl' 'unchanged0'

echo "── 설치 실패 ──"
fresh; touch "$FK/dlfail"; run
check "D14 내려받기 실패 → dpkg·ALTER 안 부름" 1 "내려받기 실패" '! called dpkg' 'unchanged0'
fresh; touch "$FK/dlempty"; run
check "D15 빈 파일 받음 → 멈춤" 1 "비어 있음" '! called dpkg'
fresh; touch "$FK/dpkgfail"; run
check "D16 dpkg 실패 → 멈춤, DB 설정 그대로" 1 "dpkg 설치 실패" 'unchanged0'

echo "── PostgreSQL 설정 실패 → 되돌림 ──"
fresh; touch "$FK/alterfail"; run
check "D17 ALTER SYSTEM 실패 → 멈춤, reload 안 함" 1 "ALTER SYSTEM log_connections 실패" '! called pg_reload_conf' 'unchanged0'
fresh; touch "$FK/alterfail2"; run
check "D17-b 두 번째 ALTER 실패 → 첫 번째도 되돌림(다음 reload 때 몰래 적용 안 되게)" 1 "ALTER SYSTEM log_disconnections 실패" \
  'called "ALTER SYSTEM SET log_connections = '"'"'off'"'"'"' '[[ ! -s $FK/pend/log_connections || $(cat "$FK/pend/log_connections" 2>/dev/null) == off ]]' 'unchanged0'
fresh; touch "$FK/fileerr"; run
check "D18 설정 파일 오류 → 되돌리고 멈춤, Agent 설정 안 함" 1 "설정 파일에 오류" 'unchanged0' '[[ ! -e $CFG ]]' \
  '[[ $(cat "$FK/pend/log_connections" 2>/dev/null) != on ]]'
fresh; touch "$FK/reloadfail"; run
check "D19 reload 실패 → 되돌리고 멈춤" 1 "reload 실패" '[[ ! -e $CFG ]]' 'called "ALTER SYSTEM SET log_connections = '"'"'off'"'"'"'
fresh; touch "$FK/noapply"; run
check "D20 reload 뒤에도 값 안 바뀜 → 되돌리고 멈춤" 1 "reload 뒤에도" 'unchanged0' '[[ ! -e $CFG ]]'

echo "── Agent 확인 ──"
fresh; touch "$FK/fcfail"; run
check "D21 Agent 설정 적용 실패 → 멈춤" 1 "Agent 설정 적용 실패"
fresh; touch "$FK/notrun"; run
check "D22 running 안 됨 → 멈춤" 1 "running 아님"
fresh; touch "$FK/denied"; run
check "D23 권한 없음(AccessDenied) → db-1 역할 05번 안내" 1 "05번 권한" '! grep -q application_name "$PGLOG"'
fresh; touch "$FK/othererr"; run
check "D24 다른 오류(E!) → 멈춤" 1 "Agent 오류(E!)"
fresh; mkdir -p "$(dirname "$AGLOG")"; echo "2026-11-15T00:00:00Z E! 어제 오류 AccessDenied" > "$AGLOG"; run
check "D25 이번 실행 전 오류는 무시 → OK" 0 "OK  cw-agent-setup-db"
fresh; touch "$FK/nolog"; run
check "D26 표시 접속이 로그에 없음 → 멈춤" 1 "에 안 들어옴"

echo "── 기존 설정 바꾸기 ──"
fresh; mkdir -p "$(dirname "$CFG")"; echo '{"old":1}' > "$CFG"; run
check "D27 다른 Agent 설정 있음 → .bak에 남기고 바꿈(설정 폴더 밖)" 0 "이전 파일 보관" \
  '[[ $(nbak) == 1 ]]' '[[ $(find "$R/usr" -name "*.bak-*" | wc -l) == 0 ]]' 'grep -q /haven/db "$CFG"'

echo
echo "결과: PASS $pass / FAIL $fail"
(( fail == 0 ))
