#!/usr/bin/env bash
# 밤 NAT 끄기 (결정 4번: 평일 21시·주말, 결정 11번 사전 승인)
#   태그 Project=Haven NAT 삭제 → deleted 대기 → 남은 EIP 해제 → 확인(연결확인표 RST-03)
#   rt-private의 0.0.0.0/0 경로는 지우지 않는다. blackhole로 남고, 다음 날 nat-up.sh가 새 NAT로 바꾼다.
#
# 예외 처리 (2026-11-09 이민성 결정)
#   1) NAT도 EIP도 없음          → "이미 꺼져 있음" 알리고 정상 종료 (여러 번 돌려도 같은 결과)
#   2) NAT 없음 + 안 붙은 EIP    → 요금이 나가므로 해제하고 알림
#   3) 어딘가에 붙어 있는 EIP     → 우리가 모르는 곳에서 쓰는 중일 수 있으므로 멈추고 알림 (사람 확인)
#
# 사용
#   미리보기: DRY_RUN=1 bash nat-down.sh
#   실제:     bash nat-down.sh
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run
check_account

# NAT가 deleted가 될 때까지 기다린다 (최대 10분). EIP는 NAT가 완전히 지워져야 해제할 수 있다.
wait_nat_deleted() {
  local id=$1 state="" i
  for i in $(seq 1 60); do
    state=$(aws --region "$AWS_REGION" ec2 describe-nat-gateways --nat-gateway-ids "$id" \
      --query 'NatGateways[0].State' --output text)
    [[ $state == deleted ]] && return 0
    sleep 10
  done
  die "NAT $id 삭제 대기 시간 초과 (마지막 상태: $state). EIP는 아직 해제하지 않았음"
}

# ── 1. NAT 삭제 ───────────────────────────────────────
log "nat-down 1/3 NAT 삭제"
if [[ $DRY_RUN == 1 ]]; then
  nats="nat-DRYRUN"
else
  nats=$(aws --region "$AWS_REGION" ec2 describe-nat-gateways \
    --filter "Name=tag:Project,Values=$PROJECT_TAG" "Name=state,Values=pending,available,deleting" \
    --query 'NatGateways[].NatGatewayId' --output text)
fi
if [[ -z $nats ]]; then
  log "NAT 없음 (이미 꺼져 있음)"
else
  for nat in $nats; do
    aws_do ec2 delete-nat-gateway --nat-gateway-id "$nat"
    if [[ $DRY_RUN == 1 ]]; then
      log "DRY-RUN: $nat 이(가) deleted 될 때까지 대기"
    else
      log "$nat 삭제 대기 (보통 1분 안팎)"
      wait_nat_deleted "$nat"
      log "$nat deleted"
    fi
  done
fi

# ── 2. 남은 EIP 해제 ──────────────────────────────────
log "nat-down 2/3 EIP 해제"
if [[ $DRY_RUN == 1 ]]; then
  eips=$'eipalloc-DRYRUN\tNone'
else
  eips=$(aws --region "$AWS_REGION" ec2 describe-addresses \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" \
    --query 'Addresses[].[AllocationId,AssociationId]' --output text)
fi
attached=()
released=0
while read -r alloc assoc; do
  [[ -n ${alloc:-} ]] || continue
  if [[ -z ${assoc:-} || $assoc == None ]]; then
    aws_do ec2 release-address --allocation-id "$alloc"
    log "EIP $alloc 해제"
    released=$((released + 1))
  else
    attached+=("$alloc(연결 $assoc)")
  fi
done <<< "$eips"
if (( ${#attached[@]} > 0 )); then
  die "어딘가에 붙어 있는 EIP가 있어 멈춤: ${attached[*]} → 무엇에 붙었는지 콘솔에서 확인 후 민수에게 알릴 것"
fi
(( released > 0 )) || log "해제할 EIP 없음"

# ── 3. 확인 (연결확인표 RST-03) ───────────────────────
log "nat-down 3/3 확인"
if [[ $DRY_RUN == 0 ]]; then
  left_nat=$(aws --region "$AWS_REGION" ec2 describe-nat-gateways \
    --filter "Name=tag:Project,Values=$PROJECT_TAG" "Name=state,Values=pending,available,deleting" \
    --query 'NatGateways[].NatGatewayId' --output text)
  left_eip=$(aws --region "$AWS_REGION" ec2 describe-addresses \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" --query 'Addresses[].AllocationId' --output text)
  [[ -z $left_nat ]] || die "RST-03 실패: 아직 남은 NAT $left_nat"
  [[ -z $left_eip ]] || die "RST-03 실패: 아직 남은 EIP $left_eip (요금 발생 중)"
  rm -f "$NAT_STATE_FILE"
  log "RST-03 확인: 태그된 NAT 없음, 태그된 EIP 없음"
fi
log "nat-down 완료. EC2 중지는 따로 (결정 4번)"
