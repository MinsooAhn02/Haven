#!/usr/bin/env bash
# db-1 로그 수집 설정: PostgreSQL 로그 → CloudWatch Agent → 로그 그룹 /haven/db (OUT-10 db-1)
#   1) Agent 설치 (이미 있으면 건너뜀)
#   2) PostgreSQL 로그 설정 3개 (ALTER SYSTEM + reload, 재시작 없음)
#        log_connections = on, log_disconnections = on, log_line_prefix에 접속 IP(%h) 추가
#      값이 이미 같으면 건드리지 않는다. reload 뒤 값이 안 맞으면 이전 값으로 되돌리고 멈춘다.
#   3) Agent 설정: /var/log/postgresql/postgresql-<버전>-main.log → /haven/db (스트림 {instance_id}/postgresql)
#   4) 확인: Agent running, Agent 로그에 이번 실행의 오류(E!) 없음, 표시 접속 기록이 PostgreSQL 로그에 들어옴
#
# 어디서: db-1, Session Manager → sudo -i (NAT가 있는 09~21시. Agent를 인터넷에서 받음)
# 로그 그룹 /haven/db(보존 30일)는 미리 만들어 둔다(11/16 민성 PC). 보존 기간은 여기서 정하지 않는다.
# 넣는 법 (web-1의 cw-agent-setup.sh와 같음, 이 파일 안에 EOF 줄이 있어서 한 줄로 옮긴다):
#   내 PC (Git Bash, 이민성/infra): sha256sum server/cw-agent-setup-db.sh; gzip -9c server/cw-agent-setup-db.sh | base64 -w0 | clip
#   db-1 (sudo -i, /root/setup):    echo '<붙여넣기>' | base64 -d | gunzip > cw-agent-setup-db.sh
#                                    echo "<내 PC 값>  cw-agent-setup-db.sh" | sha256sum -c   → OK일 때만
#   bash cw-agent-setup-db.sh
# 같은 명령을 다시 돌려도 된다: 같은 설정은 건드리지 않고, 다르면 이전 파일을
# /var/backups/haven-cw/<이름>.bak-<시각>으로 남기고 바꾼다.
# PostgreSQL 설정은 ALTER SYSTEM(postgresql.auto.conf)으로만 바꾼다. db-setup.sh(listen_addresses)와 겹치지 않음.
#
# 시험용 환경변수 (실제 서버에서는 쓰지 않음): CWS_TEST=1 일 때만 CWS_ROOT(경로 앞에 붙일 폴더)·CWS_WAIT(초) 허용
set -uo pipefail

LOG_GROUP=/haven/db
REGION=ap-northeast-2
AGENT_URL=https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
# 원하는 PostgreSQL 로그 설정 (이름 → 값). log_line_prefix 끝의 공백은 일부러 둔다(본문과 띄움)
declare -A WANT=(
  [log_connections]=on
  [log_disconnections]=on
  [log_line_prefix]='%m [%p] %q%u@%d from %h '
)
KEYS=(log_connections log_disconnections log_line_prefix)

if [[ -n ${CWS_ROOT:-} && ${CWS_TEST:-} != 1 ]]; then
  echo "ERROR: CWS_ROOT는 시험(CWS_TEST=1)에서만 쓴다" >&2; exit 1
fi
R=${CWS_ROOT:-}
WAIT=${CWS_WAIT:-60}
CWA=$R/opt/aws/amazon-cloudwatch-agent
CTL=$CWA/bin/amazon-cloudwatch-agent-ctl
CFG=$R/usr/local/etc/haven/cloudwatch-agent-db.json   # 원본. Agent 폴더 안에 두면 fetch-config 뒤 사라짐(11/12 web-1)
AGLOG=$CWA/logs/amazon-cloudwatch-agent.log
PGLOGDIR=$R/var/log/postgresql
BAKDIR=$R/var/backups/haven-cw
STAMP=$(date +%Y%m%d-%H%M%S)

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# PostgreSQL에 postgres 사용자로 한 줄 질의. 결과는 값만(-At). 실패하면 1
# (cd /: root 홈(/root)에서 postgres로 바꾸면 "could not change directory" 경고가 남)
pg() { (cd / && runuser -u postgres -- psql -XAtq -d "dbname=postgres${PGAPP:+ application_name=$PGAPP}" -c "$1"); }
sqlq() { local v=${1//\'/\'\'}; printf "'%s'" "$v"; }   # SQL 문자열로 감싸기 (' → '')

agent_running() {   # 출력을 변수에 다 받은 뒤 본다 (11/12 web-1: 파이프 141 문제)
  local st
  st=$("$CTL" -a status 2>/dev/null) || true
  [[ $st =~ \"status\":[[:space:]]*\"running\" ]]
}

PREV=""
put() {   # 같으면 0, 바꿨으면 10
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

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# ── 0. 어디서 돌리는지 ────────────────────────────────
[[ $(id -u) == 0 ]] || die "root가 아님 → sudo -i 뒤 실행"
[[ -f $R/etc/haven/haven.env ]] && die "/etc/haven/haven.env 있음 → web-1로 보임. db-1에서만 실행 (web-1은 cw-agent-setup.sh)"
command -v psql >/dev/null && command -v runuser >/dev/null || die "psql·runuser 없음 → db-1이 아님"
pg "select 1" >/dev/null 2>&1 || die "PostgreSQL에 접속 못 함 (systemctl status postgresql 확인)"
# 로그가 Ubuntu 기본 위치(stderr → /var/log/postgresql/postgresql-<버전>-main.log)에 쌓이는지
[[ $(pg "show logging_collector") == off ]] || die "logging_collector가 on → 로그 위치가 다름. 이 스크립트 대상 아님(확인 필요)"
[[ $(pg "show log_destination") == *stderr* ]] || die "log_destination에 stderr 없음 → 로그 위치가 다름"
shopt -s nullglob
files=("$PGLOGDIR"/postgresql-*-main.log)
shopt -u nullglob
(( ${#files[@]} == 1 )) || die "PostgreSQL 로그 파일이 ${#files[@]}개 (${PGLOGDIR#$R}/postgresql-*-main.log) → 1개여야 함"
PGLOG=${files[0]}
log "PostgreSQL 로그 파일: ${PGLOG#$R}"

# ── 1. Agent 설치 ─────────────────────────────────────
log "1/4 CloudWatch Agent 설치"
if [[ -x $CTL ]]; then
  log "  이미 설치됨 → 건너뜀"
else
  deb=$TMP/amazon-cloudwatch-agent.deb
  curl -fsSL --retry 2 -o "$deb" "$AGENT_URL" || die "Agent 내려받기 실패 (NAT 있는 시간인지, sg-db 443 출구 확인)"
  [[ -s $deb ]] || die "내려받은 파일이 비어 있음"
  dpkg -i -E "$deb" || die "dpkg 설치 실패"
  [[ -x $CTL ]] || die "설치 뒤에도 amazon-cloudwatch-agent-ctl 없음"
  log "  설치 완료"
fi

# ── 2. PostgreSQL 로그 설정 ───────────────────────────
log "2/4 PostgreSQL 로그 설정 (접속·종료 기록, 접속 IP)"
declare -A OLD=()
revert() {   # 바꾼 것만 이전 값으로 되돌리고 reload
  local k
  for k in "${!OLD[@]}"; do
    pg "ALTER SYSTEM SET $k = $(sqlq "${OLD[$k]}")" >/dev/null && log "  되돌림: $k → '${OLD[$k]}'"
  done
  (( ${#OLD[@]} )) && pg "select pg_reload_conf()" >/dev/null
  return 0
}
for k in "${KEYS[@]}"; do
  cur=$(pg "show $k") || die "$k 값을 읽지 못함"
  if [[ $cur == "${WANT[$k]}" ]]; then
    log "  그대로: $k"
  else
    # 앞에서 바꾼 것이 있으면 되돌린다(reload 전이라도 postgresql.auto.conf에 남으면 다음 reload 때 적용됨)
    pg "ALTER SYSTEM SET $k = $(sqlq "${WANT[$k]}")" >/dev/null || { revert; die "ALTER SYSTEM $k 실패 → 되돌리고 멈춤 (값 확인)"; }
    OLD[$k]=$cur
    log "  바꿈: $k  '$cur' → '${WANT[$k]}'"
  fi
done

if (( ${#OLD[@]} )); then
  [[ $(pg "select count(*) from pg_file_settings where error is not null") == 0 ]] \
    || { revert; die "PostgreSQL 설정 파일에 오류 → 되돌리고 멈춤 (select * from pg_file_settings where error is not null)"; }
  [[ $(pg "select pg_reload_conf()") == t ]] || { revert; die "reload 실패 → 되돌리고 멈춤"; }
  sleep 1
  for k in "${!OLD[@]}"; do
    now=$(pg "show $k")
    [[ $now == "${WANT[$k]}" ]] || { revert; die "reload 뒤에도 $k = '$now' (기대 '${WANT[$k]}') → 되돌리고 멈춤"; }
  done
  log "  reload로 적용 (재시작 없음, 새 접속부터 기록)"
fi

# ── 3. Agent 설정 → /haven/db ─────────────────────────
log "3/4 Agent 설정 → $LOG_GROUP"
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
          { "file_path": "${PGLOG#$R}", "log_group_name": "$LOG_GROUP",
            "log_stream_name": "{instance_id}/postgresql", "timezone": "UTC" }
        ]
      }
    }
  }
}
EOF
put "$CFG" "$TMP/cfg"; rc=$?
mkdir -p "$(dirname "$AGLOG")"; touch "$AGLOG"
before=$(wc -l < "$AGLOG")
if (( rc == 10 )) || ! agent_running; then
  "$CTL" -a fetch-config -m ec2 -s -c "file:$CFG" >"$TMP/fc" 2>&1 || { tail -5 "$TMP/fc" >&2; die "Agent 설정 적용 실패"; }
  grep -q 'Configuration validation succeeded' "$TMP/fc" || { tail -5 "$TMP/fc" >&2; die "Agent 설정 검사 통과 문구 없음"; }
  log "  Agent에 설정 적용(재시작)"
else
  log "  설정 같고 Agent running → 재시작 안 함"
fi

# ── 4. 확인 ───────────────────────────────────────────
log "4/4 확인 (최대 ${WAIT}초)"
ok=0
for ((i = 0; i < WAIT; i += 5)); do
  if agent_running; then ok=1; break; fi
  sleep 5
done
(( ok )) || die "Agent가 ${WAIT}초 안에 running 아님 → ${AGLOG#$R} 확인"
log "  Agent running"
sleep 10
new_err=$(tail -n +"$((before + 1))" "$AGLOG" | grep ' E! ' || true)
if [[ -n $new_err ]]; then
  printf '%s\n' "$new_err" | tail -5 >&2
  if grep -qiE 'AccessDenied|not authorized' <<<"$new_err"; then
    die "Agent 권한 오류 → db-1 역할(haven-ec2-ssm-role) 05번 권한(logs:CreateLogStream·PutLogEvents·DescribeLogStreams, /haven/db) 확인 (김보람)"
  fi
  die "Agent 오류(E!) 있음 → 위 줄 확인"
fi
log "  Agent 로그에 이번 실행 오류 없음"

MARK="cws-$(date +%s)"
PGAPP=$MARK pg "select 1" >/dev/null || die "표시 접속 실패"
found=0
for ((i = 0; i < 10; i++)); do
  if grep -q "$MARK" "$PGLOG" 2>/dev/null; then found=1; break; fi
  sleep 1
done
(( found )) || die "표시 접속 $MARK 이 ${PGLOG#$R}에 안 들어옴 → log_connections 적용 확인 (show log_connections)"
log "  표시 접속이 PostgreSQL 로그에 들어옴: $MARK"

log "OK  cw-agent-setup-db (로그 그룹 $LOG_GROUP)"
log "내 PC 확인(OUT-10, 30초쯤 뒤): MSYS_NO_PATHCONV=1 aws logs filter-log-events --region $REGION --log-group-name $LOG_GROUP --filter-pattern '\"$MARK\"' --query 'events[].logStreamName' --output text"
log "  → …/postgresql 한 줄이 나오면 통과"
