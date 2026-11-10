#!/usr/bin/env bash
# 아침 켜기 한 번에 (결정 4번: 평일 09시)
#   nat-up.sh → ec2-start.sh
#   NAT를 먼저 켠다: 서버가 SSM에 붙으려면 NAT(출구)가 있어야 한다.
#
# 예외 처리
#   - 주말이거나 09~21시 밖 → 멈춤 (결정 4번). 민수 허락을 받았으면 ALLOW_OFFHOURS=1
#   - NAT가 이미 켜져 있음  → nat-up 건너뛰고 EC2만 (두 번 돌려도 NAT 2개 안 생김)
#   - nat-up 실패           → EC2는 켜지 않음 (NAT 없이는 SSM·apt가 안 되고 요금만 나감)
#
# 사용
#   미리보기: DRY_RUN=1 bash morning.sh
#   실제:     bash morning.sh
#   시간 밖:  ALLOW_OFFHOURS=1 bash morning.sh   (민수 허락 후)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run

# 결정 4번 시간 확인 (이 컴퓨터 시계 기준, 한국 시간이어야 함)
dow=$(date +%u)                 # 1=월 ... 6=토 7=일
hour=$((10#$(date +%H)))
if (( dow >= 6 || hour < 9 || hour >= 21 )); then
  msg="결정 4번: 평일 09~21시만 가동. 지금은 $(date '+%m/%d(%a) %H:%M')"
  if [[ $DRY_RUN == 1 ]]; then
    log "DRY-RUN 주의: $msg (실제 실행이면 멈춤)"
  elif [[ ${ALLOW_OFFHOURS:-0} == 1 ]]; then
    log "주의: $msg → ALLOW_OFFHOURS=1 이라 진행 (민수 허락 받은 경우만)"
  else
    die "$msg. 민수 허락을 받았으면 ALLOW_OFFHOURS=1 bash morning.sh"
  fi
fi

check_account

nat_on=""
if [[ $DRY_RUN == 0 ]]; then
  nat_on=$(aws --region "$AWS_REGION" ec2 describe-nat-gateways \
    --filter "Name=tag:Project,Values=$PROJECT_TAG" "Name=state,Values=pending,available" \
    --query 'NatGateways[].NatGatewayId' --output text)
fi

log "morning 1/2 NAT 켜기"
if [[ -n $nat_on ]]; then
  log "NAT 이미 켜져 있음: $nat_on → nat-up 건너뜀"
else
  bash "$HERE/nat-up.sh" || die "nat-up 실패 → EC2는 켜지 않음. 위 로그 확인 (EIP가 남았으면 nat-down.sh)"
fi

log "morning 2/2 EC2 시작"
bash "$HERE/ec2-start.sh"
log "morning 완료: NAT + EC2 켜짐"
