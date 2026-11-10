#!/usr/bin/env bash
# 아침 EC2 시작 (결정 4번: 평일 09시, 결정 11번 사전 승인)
#   db-1 먼저(DB) → web-1 나중(앱). 앱이 켜질 때 DB가 이미 받을 준비가 되게 한다.
#   시작 후 확인: 공인 IP 없음(설계 2절), 사설 IP 출력(민수 전달용, 중지·시작해도 안 바뀜),
#                 SSM Online 2대(연결확인표 SSM-01 사전 확인, NAT가 켜져 있어야 함)
#
# 예외 처리
#   - 이미 running        → "이미 켜짐" 알리고 넘어감
#   - pending             → 시작 요청 없이 running 될 때까지 기다림
#   - stopping            → 다 꺼진 뒤 시작
#   - 서버가 없거나 2대 이상, state 파일 ID와 다름 → 아무것도 켜기 전에 멈춤
#   - 공인 IP가 붙어 있음 → 멈추고 알림
#   - SSM 조회 권한이 없음 → 경고만 하고 넘어감 (SSM-01로 직접 확인)
#   - 5분 안에 SSM Online 안 됨 → 멈추고 알림 (nat-up 확인)
#
# 사용
#   미리보기: DRY_RUN=1 bash ec2-start.sh
#   실제:     bash ec2-start.sh   (보통 morning.sh가 nat-up 다음에 부른다)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run
load_state
check_account

start_one() {  # start_one <이름> <ID>
  local name=$1 id=$2 st
  if [[ $DRY_RUN == 1 ]]; then
    aws_do ec2 start-instances --instance-ids "$id"
    log "DRY-RUN: $name running 될 때까지 대기 후 확인"
    return
  fi
  st=$(server_state "$id")
  case $st in
    running)
      log "$name($id) 이미 켜짐"; return ;;
    pending)
      log "$name 이미 켜지는 중 → 끝날 때까지 대기" ;;
    stopping)
      log "$name 꺼지는 중 → 다 꺼진 뒤 시작"
      aws --region "$AWS_REGION" ec2 wait instance-stopped --instance-ids "$id"
      aws_do ec2 start-instances --instance-ids "$id" ;;
    stopped)
      aws_do ec2 start-instances --instance-ids "$id" ;;
    *)
      die "$name 상태가 예상 밖: $st (콘솔 확인)" ;;
  esac
  log "$name 시작 대기 (보통 1분 안팎, 최대 10분)"
  aws --region "$AWS_REGION" ec2 wait instance-running --instance-ids "$id" \
    || die "$name 10분 안에 안 켜짐 (콘솔 확인)"
  st=$(server_state "$id")
  [[ $st == running ]] || die "$name 확인 실패: 상태 $st"
  log "$name running 확인"
}

# SSM Online 확인 (최대 5분). 권한이 없으면 경고만.
check_ssm() {
  local ids="$1,$2" out cnt i
  for i in $(seq 1 30); do
    if ! out=$(aws --region "$AWS_REGION" ssm describe-instance-information \
        --filters "Key=InstanceIds,Values=$ids" \
        --query 'InstanceInformationList[?PingStatus==`Online`].InstanceId' --output text 2>&1); then
      log "주의: SSM 상태 조회 실패 (권한 없음일 수 있음) → 연결확인표 SSM-01로 직접 확인"
      log "  $out"
      return 0
    fi
    cnt=$(wc -w <<< "$out")
    if (( cnt == 2 )); then log "SSM Online 2대 확인"; return 0; fi
    sleep 10
  done
  die "5분 안에 SSM Online 2대가 안 됨 (Online: ${out:-없음}) → NAT가 켜졌는지(nat-up) 확인"
}

WEB_ID=$(find_server web-1 WEB_ID)
DB_ID=$(find_server db-1 DB_ID)

log "ec2-start 1/3 db-1 (DB 먼저)"
start_one db-1 "$DB_ID"
log "ec2-start 2/3 web-1"
start_one web-1 "$WEB_ID"

log "ec2-start 3/3 확인"
if [[ $DRY_RUN == 0 ]]; then
  pub=$(aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$WEB_ID" "$DB_ID" \
    --query 'Reservations[].Instances[].PublicIpAddress' --output text)
  [[ -z $pub || $pub == None ]] || die "공인 IP가 붙었음: $pub (설계 2절 위반, 확인 필요)"
  aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$WEB_ID" "$DB_ID" \
    --query 'Reservations[].Instances[].[Tags[?Key==`Name`]|[0].Value,PrivateIpAddress]' --output text \
    | while read -r n ip; do log "사설 IP: $n $ip"; done
  check_ssm "$WEB_ID" "$DB_ID"
fi
log "ec2-start 완료"
