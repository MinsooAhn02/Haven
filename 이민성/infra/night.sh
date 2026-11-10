#!/usr/bin/env bash
# 밤 정리 한 번에 (결정 4번: 평일 21시·주말 전)
#   ec2-stop.sh → nat-down.sh
#   하나가 실패해도 다른 하나는 끝까지 한다 (비용을 하나라도 더 멈추기 위해). 실패가 있으면 마지막에 알리고 exit 1.
#   끝나고 아직 켜진 Haven 서버(시험용 EC2 등)가 있으면 알림.
#
# 사용
#   미리보기: DRY_RUN=1 bash night.sh
#   실제:     bash night.sh
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run
check_account

failed=()
log "night 1/2 EC2 중지"
bash "$HERE/ec2-stop.sh" || failed+=(ec2-stop)
log "night 2/2 NAT 끄기"
bash "$HERE/nat-down.sh" || failed+=(nat-down)

if [[ $DRY_RUN == 0 ]]; then
  others=$(aws --region "$AWS_REGION" ec2 describe-instances \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" "Name=instance-state-name,Values=pending,running" \
    --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`]|[0].Value]' --output text)
  [[ -z $others ]] || log "주의: 아직 켜진 Haven 서버: $(tr '\n\t' '; ' <<< "$others") → 시험용이면 결정 11번대로 당일 삭제"
fi

(( ${#failed[@]} == 0 )) || die "night 실패: ${failed[*]} → 위 로그 확인. 요금이 나가는 것이 남았을 수 있음"
log "night 완료: EC2 중지 + NAT 삭제 + EIP 해제"
