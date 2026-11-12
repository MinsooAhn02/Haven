#!/usr/bin/env bash
# cw-agent-setup.sh 가짜 시험 (서버·AWS에 아무것도 보내지 않음)
#   - 가짜 id·curl·dpkg·systemctl·rsyslogd·logrotate·chown·sleep을 PATH 맨 앞에 둔다
#   - 서버 경로(/etc, /var, /opt)는 임시 폴더 아래로 바꿔서 쓴다 (CWS_TEST=1 CWS_ROOT=<임시 폴더>)
#   - 가짜 dpkg가 가짜 amazon-cloudwatch-agent-ctl을 만든다
#
# 사용 (Git Bash 또는 리눅스, 이민성/infra 에서)
#   bash test/cw-fake-test.sh
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SRC/server/cw-agent-setup.sh"
[[ -f $SCRIPT ]] || { echo "server/cw-agent-setup.sh 없음"; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
export FK="$WORK/fk" R="$WORK/root"
CTLREL=opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl

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
mk chown <<'EOF'
#!/usr/bin/env bash
echo "chown $*" >> "$FK/calls"
EOF
mk curl <<'EOF'
#!/usr/bin/env bash
echo "curl $*" >> "$FK/calls"
args="$*"
case "$args" in
  *amazon-cloudwatch-agent.deb*)
    [[ -f $FK/dlfail ]] && { echo "curl: (22) 가짜 403" >&2; exit 22; }
    out=""; while (( $# )); do [[ $1 == -o ]] && { out=$2; shift; }; shift; done
    if [[ -f $FK/dlempty ]]; then : > "$out"; else echo FAKEDEB > "$out"; fi ;;
  *127.0.0.1/healthz*)
    [[ -f $FK/hzfail ]] && exit 7
    mark=${args##*healthz?}; mark=${mark%% *}
    [[ -f $FK/noroute ]] || echo "2026-11-12T00:00:00+00:00 ip gunicorn[1]: \"GET /healthz?$mark HTTP/1.0\" 200 2" >> "$R/var/log/haven/app.log" ;;
  *) echo "가짜 curl: 모르는 요청 $args" >&2; exit 99 ;;
esac
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
    # 진짜 Agent처럼 Agent 폴더의 amazon-cloudwatch-agent.json을 없앤다 (11/12 web-1에서 확인)
    rm -f "$R/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json"
    mkdir -p "$(dirname "$aglog")"
    echo "2026-11-12T00:10:55Z I! [logagent] piping log from /haven/web/i-x/nginx-error(/var/log/nginx/error.log)" >> "$aglog"
    [[ -f $FK/denied ]] && echo "2026-11-12T00:11:00Z E! cloudwatchlogs: AccessDeniedException: not authorized to perform: logs:PutLogEvents" >> "$aglog"
    [[ -f $FK/othererr ]] && echo "2026-11-12T00:11:00Z E! [outputs.cloudwatchlogs] connection timeout" >> "$aglog"
    exit 0 ;;
  *status*)
    # 진짜처럼 여러 번 나눠 출력. 읽는 쪽이 먼저 끝나면 141로 죽는다(11/12 web-1의 pipe-rc=141 재현)
    st=stopped; [[ -f $FK/started && ! -f $FK/notrun ]] && st=running
    echo '{'
    echo "  \"status\": \"$st\","
    /usr/bin/sleep 0.2
    echo '  "configstatus": "configured"' || exit 141
    echo '}' || exit 141 ;;
esac
CTL
chmod +x "$ctl"
EOF
mk rsyslogd <<'EOF'
#!/usr/bin/env bash
echo "rsyslogd $*" >> "$FK/calls"
[[ -f $FK/n1fail ]] && { echo "rsyslogd: error during parsing (가짜)" >&2; exit 1; }
exit 0
EOF
mk logrotate <<'EOF'
#!/usr/bin/env bash
echo "logrotate $*" >> "$FK/calls"
[[ -f $FK/lrerr ]] && echo "error: haven:3 unknown option (가짜)"
echo "log does not need rotating"
EOF
mk systemctl <<'EOF'
#!/usr/bin/env bash
echo "systemctl $*" >> "$FK/calls"
case "$*" in
  "is-active rsyslog") [[ -f $FK/rsysdown ]] && echo failed || echo active ;;
  "restart rsyslog") exit 0 ;;
  *) echo "가짜 systemctl: 모르는 명령 $*" >&2; exit 99 ;;
esac
EOF
export PATH="$WORK/bin:$PATH"
[[ $(command -v dpkg) == "$WORK/bin/dpkg" && $(command -v systemctl) == "$WORK/bin/systemctl" ]] || { echo "가짜 명령이 안 잡힘 → 시험 중단"; exit 1; }

# ── 시험 도구 ─────────────────────────────────────────
pass=0; fail=0; OUT=""; CODE=0
fresh() {  # 빈 web-1 상태
  rm -rf "$FK" "$R"; mkdir -p "$FK" "$R/etc/haven" "$R/var/log/nginx"; : > "$FK/calls"
  echo "DB_HOST=x" > "$R/etc/haven/haven.env"
}
run() { OUT=$(CWS_TEST=1 CWS_ROOT="$R" CWS_WAIT=15 bash "$SCRIPT" 2>&1); CODE=$?; : > "$FK/calls.keep"; cp "$FK/calls" "$FK/calls.keep"; }
called()  { grep -q -- "$1" "$FK/calls"; }
# check <이름> <기대 exit> <로그 글자> [추가 조건 (bash 식)...]
check() {
  local name=$1 want=$2 text=$3 ok=1 why="" c; shift 3
  [[ $CODE == "$want" ]] || { ok=0; why+=" exit=$CODE(기대 $want)"; }
  [[ -z $text || $OUT == *"$text"* ]] || { ok=0; why+=" 로그에 '$text' 없음"; }
  for c in "$@"; do eval "$c" || { ok=0; why+=" [$c] 거짓"; }; done
  if (( ok )); then pass=$((pass+1)); printf 'PASS  %s\n' "$name"
  else fail=$((fail+1)); printf 'FAIL  %s →%s\n' "$name" "$why"; printf '%s\n' "$OUT" | sed 's/^/      | /'; fi
}
RSYS=$R/etc/rsyslog.d/30-haven.conf; LROT=$R/etc/logrotate.d/haven
CFG=$R/usr/local/etc/haven/cloudwatch-agent.json
AGLOG=$R/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log
nbak() { find "$R" -name '*.bak-*' | wc -l; }

echo "── 정상 ──"
fresh; run
check "C1 처음 설치 → 끝까지 OK" 0 "OK  cw-agent-setup" \
  'called "dpkg -i -E"' 'called "systemctl restart rsyslog"' 'called "fetch-config -m ec2 -s"' \
  'grep -q "programname == .gunicorn. then /var/log/haven/app.log" "$RSYS"' \
  'grep -q "rotate 7" "$LROT"' \
  '[[ $(grep -c "\"log_group_name\": \"/haven/web\"" "$CFG") == 3 ]]' \
  'grep -q "{instance_id}/nginx-access" "$CFG" && grep -q "{instance_id}/nginx-error" "$CFG" && grep -q "{instance_id}/app" "$CFG"' \
  '! grep -q retention "$CFG"' 'called "chown syslog:adm"' '[[ $(nbak) == 0 ]]'
check "C1-b 내 PC 확인 명령 안내" 0 "filter-log-events"
: > "$FK/calls"; run
check "C2 다시 실행 → 내려받기·rsyslog·Agent 재시작 없이 OK" 0 "재시작 안 함" \
  '! called "amazon-cloudwatch-agent.deb"' '! called "dpkg"' '! called "systemctl restart"' '! called fetch-config' \
  '[[ $(grep -o "그대로" <<<"$OUT" | wc -l) == 3 ]]' '[[ $(nbak) == 0 ]]'

rm -f "$FK/started"; : > "$FK/calls"; run
check "C21 설정 같지만 Agent 꺼져 있음 → 설정 적용해서 다시 켬" 0 "Agent에 설정 적용" 'called fetch-config'

echo "── 실행 위치·조건 ──"
fresh; touch "$FK/notroot"; run
check "C3 root 아님 → 아무것도 안 씀" 1 "root가 아님" '[[ ! -e $RSYS && ! -e $R/var/log/haven ]]' '! called curl'
fresh; rm "$R/etc/haven/haven.env"; run
check "C4 haven.env 없음(db-1) → 멈춤" 1 "web-1이 아님" '! called curl'
fresh; OUT=$(CWS_ROOT="$R" bash "$SCRIPT" 2>&1); CODE=$?
check "C5 CWS_TEST 없이 CWS_ROOT → 멈춤 (실서버 보호)" 1 "시험(CWS_TEST=1)에서만" '! called curl'

echo "── 설치 실패 ──"
fresh; touch "$FK/dlfail"; run
check "C6 내려받기 실패 → dpkg 안 부름" 1 "내려받기 실패" '! called dpkg' '[[ ! -e $RSYS ]]'
fresh; touch "$FK/dlempty"; run
check "C7 빈 파일 받음 → 멈춤" 1 "비어 있음" '! called dpkg'
fresh; touch "$FK/dpkgfail"; run
check "C8 dpkg 실패 → 멈춤" 1 "dpkg 설치 실패" '[[ ! -e $RSYS ]]'

echo "── 설정 검사 실패 → 되돌림 ──"
fresh; touch "$FK/n1fail"; run
check "C9 rsyslog 검사 실패(새 파일) → 파일 지우고 재시작 안 함" 1 "rsyslog 설정 검사 실패" \
  '[[ ! -e $RSYS ]]' '! called "systemctl restart"'
fresh; mkdir -p "$(dirname "$RSYS")"; echo "# 예전 규칙" > "$RSYS"; touch "$FK/n1fail"; run
check "C10 rsyslog 검사 실패(기존 파일) → 예전 내용 복구" 1 "이전 파일 복구" \
  '[[ $(cat "$RSYS") == "# 예전 규칙" ]]' '[[ $(nbak) == 0 ]]' '! called "systemctl restart"'
fresh; touch "$FK/rsysdown"; run
check "C11 rsyslog가 active 아님 → 멈춤" 1 "active 아님"
fresh; touch "$FK/lrerr"; run
check "C12 logrotate 규칙 오류 → 파일 지우고 멈춤" 1 "logrotate 규칙 검사 실패" '[[ ! -e $LROT ]]' '! called fetch-config'
fresh; touch "$FK/fcfail"; run
check "C13 Agent 설정 적용 실패 → 멈춤" 1 "Agent 설정 적용 실패"

echo "── Agent 확인 ──"
fresh; touch "$FK/notrun"; run
check "C14 running 안 됨 → 멈춤" 1 "running 아님"
fresh; touch "$FK/denied"; run
check "C15 권한 없음(AccessDenied) → 권한 안내" 1 "권한 오류" '! called "127.0.0.1/healthz"'
fresh; touch "$FK/othererr"; run
check "C16 다른 오류(E!) → 멈춤" 1 "Agent 오류(E!)"
fresh; mkdir -p "$(dirname "$AGLOG")"; echo "2026-11-11T00:00:00Z E! 어제 오류 AccessDenied" > "$AGLOG"; run
check "C17 이번 실행 전 오류는 무시 → OK" 0 "OK  cw-agent-setup"
fresh; touch "$FK/noroute"; run
check "C18 표시 요청이 app.log에 없음 → 멈춤" 1 "app.log에 안 들어옴"
fresh; touch "$FK/hzfail"; run
check "C19 healthz 요청 실패 → 멈춤" 1 "healthz 요청 실패"

echo "── 기존 설정 바꾸기 ──"
fresh; mkdir -p "$(dirname "$CFG")"; echo '{"old":1}' > "$CFG"; run
check "C20 다른 Agent 설정 있음 → .bak에 남기고 바꿈" 0 "이전 파일 보관" \
  '[[ $(nbak) == 1 ]]' 'grep -q "\"old\":1" "$(find "$R" -name "*.bak-*")"' 'grep -q /haven/web "$CFG"'

fresh; mkdir -p "$(dirname "$LROT")"; echo "# 예전 logrotate 규칙" > "$LROT"; run
check "C22 다른 logrotate 규칙 있음 → 백업은 설정 폴더 밖에 (logrotate가 백업까지 읽지 않게)" 0 "이전 파일 보관" \
  '[[ $(find "$R/etc" -name "*.bak-*" | wc -l) == 0 ]]' \
  '[[ $(cat "$R"/var/backups/haven-cw/haven.bak-*) == "# 예전 logrotate 규칙" ]]' 'grep -q "rotate 7" "$LROT"'

echo
echo "결과: PASS $pass / FAIL $fail"
(( fail == 0 ))
