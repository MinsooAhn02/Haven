#!/usr/bin/env bash
# 밤 EC2 중지 (결정 4번: 평일 21시·주말, 결정 11번 사전 승인)
#   web-1 먼저(앱) → db-1 나중(DB). 앱이 켜진 채 DB가 먼저 꺼지는 일을 막는다.
#   중지해도 사설 IP·디스크(EBS)는 그대로. 인스턴스 요금만 멈추고 디스크 요금은 계속 나간다.
#
# 예외 처리
#   - 이미 stopped        → "이미 중지됨" 알리고 넘어감 (여러 번 돌려도 같은 결과)
#   - stopping            → 중지 요청 없이 끝날 때까지 기다림
#   - pending(켜지는 중)  → running 될 때까지 기다린 뒤 중지
#   - 서버가 없거나 2대 이상, state 파일 ID와 다름 → 아무것도 끄기 전에 멈춤
#   - 10분 안에 안 꺼짐   → 멈추고 알림 (콘솔 확인)
#
# 사용
#   미리보기: DRY_RUN=1 bash ec2-stop.sh
#   실제:     bash ec2-stop.sh
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run
load_state
check_account

stop_one() {  # stop_one <이름> <ID>
  local name=$1 id=$2 st
  if [[ $DRY_RUN == 1 ]]; then
    aws_do ec2 stop-instances --instance-ids "$id"
    log "DRY-RUN: $name stopped 될 때까지 대기 후 확인"
    return
  fi
  st=$(server_state "$id")
  case $st in
    stopped)
      log "$name($id) 이미 중지됨"; return ;;
    stopping)
      log "$name 이미 중지 중 → 끝날 때까지 대기" ;;
    pending)
      log "$name 켜지는 중 → running 된 뒤 중지"
      aws --region "$AWS_REGION" ec2 wait instance-running --instance-ids "$id"
      aws_do ec2 stop-instances --instance-ids "$id" ;;
    running)
      aws_do ec2 stop-instances --instance-ids "$id" ;;
    *)
      die "$name 상태가 예상 밖: $st (콘솔 확인)" ;;
  esac
  log "$name 중지 대기 (보통 1분 안팎, 최대 10분)"
  aws --region "$AWS_REGION" ec2 wait instance-stopped --instance-ids "$id" \
    || die "$name 10분 안에 안 꺼짐 (콘솔 확인)"
  st=$(server_state "$id")
  [[ $st == stopped ]] || die "$name 확인 실패: 상태 $st"
  log "$name stopped 확인"
}

# 둘 다 먼저 찾는다 → 한 대라도 이상하면 아무것도 끄지 않고 멈춤
WEB_ID=$(find_server web-1 WEB_ID)
DB_ID=$(find_server db-1 DB_ID)

log "ec2-stop 1/2 web-1 (앱 먼저)"
stop_one web-1 "$WEB_ID"
log "ec2-stop 2/2 db-1"
stop_one db-1 "$DB_ID"
log "ec2-stop 완료: web-1, db-1 중지 (사설 IP·디스크 유지)"
