#!/usr/bin/env bash
# web-1 로그 수집 설정: CloudWatch Agent → 로그 그룹 /haven/web (OUT-10)
#   1) Agent 설치 (이미 있으면 건너뜀)
#   2) 앱 로그 파일: journald의 gunicorn 기록 → /var/log/haven/app.log (rsyslog 규칙)
#   3) app.log 정리 규칙 (logrotate, 7일)
#   4) Agent 설정: nginx access·error, app.log → /haven/web (스트림 {instance_id}/nginx-access 등)
#   5) 확인: Agent running, Agent 로그에 이번 실행의 오류(E!) 없음, 표시 요청이 app.log에 들어옴
#
# 어디서: web-1, Session Manager → sudo -i (NAT가 있는 09~21시. Agent를 인터넷에서 받음)
# 넣는 법 (이 파일 안에 EOF 줄이 있어서 cat <<'EOF' 붙여넣기는 중간에 끊긴다 → 한 줄로 옮긴다):
#   내 PC (Git Bash, 이민성/infra): sha256sum server/cw-agent-setup.sh; gzip -9c server/cw-agent-setup.sh | base64 -w0 | clip
#   web-1 (sudo -i, /root/setup):  echo '<붙여넣기>' | base64 -d | gunzip > cw-agent-setup.sh
#                                   echo "<내 PC 값>  cw-agent-setup.sh" | sha256sum -c   → OK일 때만
#   bash cw-agent-setup.sh
# 같은 명령을 다시 돌려도 된다: 내용이 같은 파일은 건드리지 않고, 다르면 이전 파일을
# /var/backups/haven-cw/<이름>.bak-<시각>으로 남기고 바꾼다 (설정 폴더 안에 두면 logrotate가 백업까지 읽음).
# 보존 기간은 여기서 정하지 않는다 (로그 그룹 쪽 30일 그대로, Agent 로그의 retention -1 = 건드리지 않음).
#
# 시험용 환경변수 (실제 서버에서는 쓰지 않음): CWS_TEST=1 일 때만 CWS_ROOT(경로 앞에 붙일 폴더)·CWS_WAIT(초) 허용
set -uo pipefail

LOG_GROUP=/haven/web
REGION=ap-northeast-2
AGENT_URL=https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
HOST_HDR=orchestration-haven.cloud

if [[ -n ${CWS_ROOT:-} && ${CWS_TEST:-} != 1 ]]; then
  echo "ERROR: CWS_ROOT는 시험(CWS_TEST=1)에서만 쓴다" >&2; exit 1
fi
R=${CWS_ROOT:-}
WAIT=${CWS_WAIT:-60}
CWA=$R/opt/aws/amazon-cloudwatch-agent
CTL=$CWA/bin/amazon-cloudwatch-agent-ctl
CFG=$R/usr/local/etc/haven/cloudwatch-agent.json   # 원본. Agent 폴더 안에 두면 fetch-config 뒤 사라짐(11/12 확인)
AGLOG=$CWA/logs/amazon-cloudwatch-agent.log
RSYS=$R/etc/rsyslog.d/30-haven.conf
LROT=$R/etc/logrotate.d/haven
LOGDIR=$R/var/log/haven
APPLOG=$LOGDIR/app.log
BAKDIR=$R/var/backups/haven-cw
STAMP=$(date +%Y%m%d-%H%M%S)

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# running이면 0. 출력을 변수에 다 받은 뒤 본다
# (11/12 web-1: 상태 출력을 파이프로 grep -q에 넘기면 grep이 먼저 끝나 ctl이 141로 죽고,
#  pipefail 때문에 running인데도 실패로 봄)
agent_running() {
  local st
  st=$("$CTL" -a status 2>/dev/null) || true
  [[ $st =~ \"status\":[[:space:]]*\"running\" ]]
}

# put <대상 파일> <새 내용 파일>: 같으면 0(바뀜 없음), 바꿨으면 10. 이전 파일은 PREV에 경로 기록
PREV=""
put() {
  local dst=$1 new=$2
  PREV=""
  if [[ -f $dst ]] && cmp -s "$dst" "$new"; then log "  그대로 (내용 같음): ${dst#$R}"; return 0; fi
  mkdir -p "$(dirname "$dst")"
  if [[ -f $dst ]]; then
    mkdir -p "$BAKDIR"; PREV="$BAKDIR/$(basename "$dst").bak-$STAMP"
    cp -p "$dst" "$PREV"; log "  이전 파일 보관: ${PREV#$R}"
  fi
  cp "$new" "$dst"; chmod 0644 "$dst"; log "  씀: ${dst#$R}"
  return 10
}
# undo <대상 파일>: put 직전 상태로 되돌림
undo() {
  if [[ -n $PREV ]]; then mv -f "$PREV" "$1"; log "  되돌림: 이전 파일 복구 ${1#$R}"
  else rm -f "$1"; log "  되돌림: 새 파일 삭제 ${1#$R}"; fi
}

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# ── 0. 어디서 돌리는지 ────────────────────────────────
[[ $(id -u) == 0 ]] || die "root가 아님 → sudo -i 뒤 실행"
[[ -f $R/etc/haven/haven.env ]] || die "/etc/haven/haven.env 없음 → web-1이 아님(db-1 등). web-1에서만 실행"
command -v rsyslogd >/dev/null || die "rsyslogd 없음"
command -v logrotate >/dev/null || die "logrotate 없음"

# ── 1. Agent 설치 ─────────────────────────────────────
log "1/5 CloudWatch Agent 설치"
if [[ -x $CTL ]]; then
  log "  이미 설치됨 → 건너뜀"
else
  deb=$TMP/amazon-cloudwatch-agent.deb
  curl -fsSL --retry 2 -o "$deb" "$AGENT_URL" || die "Agent 내려받기 실패 (NAT 있는 시간인지, sg-web 443 출구 확인)"
  [[ -s $deb ]] || die "내려받은 파일이 비어 있음"
  dpkg -i -E "$deb" || die "dpkg 설치 실패"
  [[ -x $CTL ]] || die "설치 뒤에도 amazon-cloudwatch-agent-ctl 없음"
  log "  설치 완료"
fi

# ── 2. 앱 로그 파일 (rsyslog) ─────────────────────────
log "2/5 앱 로그 → ${APPLOG#$R}"
mkdir -p "$LOGDIR"; chmod 0750 "$LOGDIR"; chown syslog:adm "$LOGDIR" || die "로그 폴더 소유자 변경 실패"
cat > "$TMP/rsys" <<'EOF'
# Haven: gunicorn(앱) 기록을 파일로도 남김 → CloudWatch Agent가 /haven/web으로 보냄 (이민성/infra/server/cw-agent-setup.sh)
if $programname == 'gunicorn' then /var/log/haven/app.log
EOF
put "$RSYS" "$TMP/rsys"; rc=$?
if (( rc == 10 )); then
  if ! rsyslogd -N1 >"$TMP/n1" 2>&1; then
    cat "$TMP/n1" >&2; undo "$RSYS"; die "rsyslog 설정 검사 실패 → 되돌리고 멈춤 (rsyslog 재시작 안 함)"
  fi
  systemctl restart rsyslog || die "rsyslog 재시작 실패"
fi
[[ $(systemctl is-active rsyslog) == active ]] || die "rsyslog가 active 아님"

# ── 3. app.log 정리 규칙 (logrotate) ──────────────────
log "3/5 app.log 정리 규칙 (매일, 7개 보관)"
cat > "$TMP/lrot" <<'EOF'
/var/log/haven/app.log {
    daily
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
EOF
put "$LROT" "$TMP/lrot"; rc=$?
if (( rc == 10 )); then
  logrotate -d "$LROT" >"$TMP/lr" 2>&1
  if grep -qi 'error' "$TMP/lr"; then
    grep -i 'error' "$TMP/lr" >&2; undo "$LROT"; die "logrotate 규칙 검사 실패 → 되돌리고 멈춤"
  fi
fi

# ── 4. Agent 설정 → /haven/web ────────────────────────
log "4/5 Agent 설정 → $LOG_GROUP"
cat > "$TMP/cfg" <<EOF
{
  "agent": {
    "run_as_user": "root",
    "region": "$REGION"
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          { "file_path": "/var/log/nginx/access.log", "log_group_name": "$LOG_GROUP",
            "log_stream_name": "{instance_id}/nginx-access", "timezone": "UTC" },
          { "file_path": "/var/log/nginx/error.log",  "log_group_name": "$LOG_GROUP",
            "log_stream_name": "{instance_id}/nginx-error",  "timezone": "UTC" },
          { "file_path": "/var/log/haven/app.log",    "log_group_name": "$LOG_GROUP",
            "log_stream_name": "{instance_id}/app",          "timezone": "UTC" }
        ]
      }
    }
  }
}
EOF
put "$CFG" "$TMP/cfg"; rc=$?
mkdir -p "$(dirname "$AGLOG")"; touch "$AGLOG"
before=$(wc -l < "$AGLOG")   # 이번 실행 전 줄 수 → 이전 오류는 보지 않음
# 설정이 바뀌었거나 Agent가 안 돌 때만 적용(재시작). 같은 설정으로 다시 돌리면 Agent를 건드리지 않음
if (( rc == 10 )) || ! agent_running; then
  "$CTL" -a fetch-config -m ec2 -s -c "file:$CFG" >"$TMP/fc" 2>&1 || { tail -5 "$TMP/fc" >&2; die "Agent 설정 적용 실패"; }
  grep -q 'Configuration validation succeeded' "$TMP/fc" || { tail -5 "$TMP/fc" >&2; die "Agent 설정 검사 통과 문구 없음"; }
  log "  Agent에 설정 적용(재시작)"
else
  log "  설정 같고 Agent running → 재시작 안 함"
fi

# ── 5. 확인 ───────────────────────────────────────────
log "5/5 확인 (최대 ${WAIT}초)"
ok=0
for ((i = 0; i < WAIT; i += 5)); do
  if agent_running; then ok=1; break; fi
  sleep 5
done
(( ok )) || die "Agent가 ${WAIT}초 안에 running 아님 → ${AGLOG#$R} 확인"
log "  Agent running"
sleep 10   # 첫 전송 시도까지 기다림
new_err=$(tail -n +"$((before + 1))" "$AGLOG" | grep ' E! ' || true)
if [[ -n $new_err ]]; then
  printf '%s\n' "$new_err" | tail -5 >&2
  if grep -qiE 'AccessDenied|not authorized' <<<"$new_err"; then
    die "Agent 권한 오류 → web-1 역할 권한(logs:CreateLogStream·PutLogEvents·DescribeLogStreams) 확인 (김보람)"
  fi
  die "Agent 오류(E!) 있음 → 위 줄 확인"
fi
log "  Agent 로그에 이번 실행 오류 없음"

MARK="cws-$(date +%s)"
curl -s -o /dev/null -H "Host: $HOST_HDR" "http://127.0.0.1/healthz?$MARK" || die "web-1 healthz 요청 실패 (haven·nginx 확인)"
found=0
for ((i = 0; i < 10; i++)); do
  if grep -q "$MARK" "$APPLOG" 2>/dev/null; then found=1; break; fi
  sleep 1
done
(( found )) || die "표시 요청 $MARK 이 app.log에 안 들어옴 → rsyslog 규칙 확인 (journalctl -u haven -n 3)"
log "  표시 요청이 app.log에 들어옴: $MARK"

log "OK  cw-agent-setup (로그 그룹 $LOG_GROUP)"
log "내 PC 확인(OUT-10, 30초쯤 뒤): aws logs filter-log-events --region $REGION --log-group-name $LOG_GROUP --filter-pattern '\"$MARK\"' --query 'events[].logStreamName' --output text"
log "  → …/nginx-access 와 …/app 두 줄이 나오면 통과"
