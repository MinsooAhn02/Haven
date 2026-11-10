#!/usr/bin/env bash
# 모든 스크립트가 공유하는 함수 (build.sh, nat-up.sh, nat-down.sh, destroy.sh, ec2-stop.sh, ec2-start.sh, night.sh, morning.sh)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "$HERE/config.sh"

# Windows aws.exe는 출력 끝에 \r(CRLF)을 붙여 bash 비교가 깨진다 (11/10 실제 구축 때 RST-02 오탐으로 발견)
# 모든 aws 출력에서 \r을 지운다. pipefail이 켜져 있어 aws 실패 코드는 그대로 전달된다
aws() { command aws "$@" | tr -d '\r'; }

STATE_FILE="$HERE/state/${AWS_REGION}.env"       # build.sh가 만든 자원 ID (Git에 올리지 않음, .gitignore)
NAT_STATE_FILE="$HERE/state/${AWS_REGION}-nat.env" # 오늘 켠 NAT·EIP ID (nat-up.sh가 매번 새로 씀)

# 다른 스크립트(nat-up.sh 등)를 부를 때도 같은 값이 넘어가게 한다
export AWS_REGION PROJECT_TAG OWNER_TAG DRY_RUN EXPECTED_ACCOUNT_ID

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# DRY-RUN이면 실행할 명령을 보기 좋게 출력만 한다
show() {
  local a out="aws --region $AWS_REGION"
  for a in "$@"; do
    if [[ $a =~ ^[A-Za-z0-9_./:=@%+,-]+$ ]]; then out+=" $a"; else out+=" '$a'"; fi
  done
  printf 'DRY-RUN: %s\n' "$out" >&2
}

# 변경 명령 (결과 값이 필요 없음)
aws_do() {
  if [[ $DRY_RUN == 1 ]]; then show "$@"; else aws --region "$AWS_REGION" "$@" >/dev/null; fi
}

# 생성 명령: 새 자원 ID를 출력한다. DRY-RUN이면 첫 인자(가짜 ID)를 대신 출력
aws_new() {
  local fake=$1; shift
  if [[ $DRY_RUN == 1 ]]; then show "$@"; echo "$fake"; else aws --region "$AWS_REGION" "$@"; fi
}

# --tag-specifications 값 만들기: tags <자원종류> <이름>
tags() {
  printf 'ResourceType=%s,Tags=[{Key=Name,Value=%s},{Key=Project,Value=%s},{Key=Owner,Value=%s}]' \
    "$1" "$2" "$PROJECT_TAG" "$OWNER_TAG"
}

# 만든 자원 ID를 바로바로 상태 파일에 적는다 (중간에 실패해도 어디까지 만들었는지 남음)
remember() {
  local name=$1
  if [[ $DRY_RUN == 1 ]]; then log "DRY-RUN: $name=${!name}"; return; fi
  mkdir -p "$(dirname "$STATE_FILE")"
  printf '%s=%q\n' "$name" "${!name}" >> "$STATE_FILE"
  log "기록: $name=${!name}"
}

# 필요한 값이 비어 있으면 아무것도 만들기 전에 멈춘다
require_vars() {
  local v
  for v in "$@"; do
    [[ -n ${!v:-} ]] || die "$v 값이 비어 있음 (config.sh 또는 환경변수 확인)"
  done
}

# DRY_RUN 값 확인
check_dry_run() {
  [[ $DRY_RUN == 0 || $DRY_RUN == 1 ]] || die "DRY_RUN은 0 또는 1이어야 함 (현재: $DRY_RUN)"
}

# 저장해 둔 자원 ID 불러오기 (없으면 그냥 넘어감)
load_state() {
  if [[ -f $STATE_FILE ]]; then source "$STATE_FILE"; fi
  if [[ -f $NAT_STATE_FILE ]]; then source "$NAT_STATE_FILE"; fi
  return 0
}

# 실제 실행 전: 로그인 확인 + root 금지 + 허용한 팀 계정인지 확인
check_account() {
  if [[ $DRY_RUN == 1 ]]; then log "DRY-RUN: 계정 확인 생략"; return; fi
  require_vars EXPECTED_ACCOUNT_ID
  local arn acct
  arn=$(aws sts get-caller-identity --query Arn --output text) \
    || die "AWS 로그인 정보가 없음 (aws configure / SSO 확인)"
  acct=$(aws sts get-caller-identity --query Account --output text)
  [[ $arn != *":root" ]] || die "root 계정으로 실행하지 않는다. 김보람이 만든 IAM 사용자로 로그인할 것"
  [[ $acct == "$EXPECTED_ACCOUNT_ID" ]] \
    || die "허용한 팀 계정이 아님 (현재 ${acct:0:4}********, 기대 ${EXPECTED_ACCOUNT_ID:0:4}********). 개인 계정 비용 방지"
  log "계정 확인 OK: ${arn##*/} (계정 ${acct:0:4}********)"
}

# ── EC2 중지·시작용 (ec2-stop.sh, ec2-start.sh) ─────────

# 이름(web-1/db-1)으로 서버 ID 찾기. 정확히 1대여야 하고, state 파일 ID와도 같아야 한다. 
# 즉, web 1대 , db 1대 총 2대 각각 한대여야한다는 뜻
#   사용: WEB_ID=$(find_server web-1 WEB_ID)
find_server() {
  local name=$1 var=$2 ids n
  if [[ $DRY_RUN == 1 ]]; then echo "${!var:-i-DRYRUN-$name}"; return; fi
  ids=$(aws --region "$AWS_REGION" ec2 describe-instances \
    --filters "Name=tag:Name,Values=$name" "Name=tag:Project,Values=$PROJECT_TAG" \
              "Name=tag:Owner,Values=$OWNER_TAG" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)
  n=$(wc -w <<< "$ids")
  (( n == 1 )) || die "$name 서버가 ${n}대 (기대 1대): ${ids:-없음} → build.sh 실행 여부·콘솔 확인"
  if [[ -n ${!var:-} && ${!var} != "$ids" ]]; then
    die "$name ID가 state 파일($var=${!var})과 다름: $ids → 서버를 다시 만들었는지 확인"
  fi
  echo "$ids"
}

# 서버 하나의 현재 상태 (pending/running/stopping/stopped ...)
server_state() {
  aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$1" \
    --query 'Reservations[0].Instances[0].State.Name' --output text
}