#!/usr/bin/env bash
# 아침 NAT 켜기 (결정 4번: 평일 09시, 결정 11번 사전 승인)
#   EIP 할당 → public-a에 NAT 생성 → available 대기 → rt-private 0.0.0.0/0 → 새 NAT → 확인(연결확인표 RST-02)
# 사용
#   미리보기: DRY_RUN=1 bash nat-up.sh
#   실제:     bash nat-up.sh   (build.sh가 한 번 돌아 state 파일이 있어야 함)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run
load_state
if [[ $DRY_RUN == 1 ]]; then            # 미리보기에서 state 파일이 없으면 가짜 ID로 채움
  : "${SUBNET_PUBLIC_A:=subnet-DRYRUN-public-a}"
  : "${RT_PRIVATE:=rtb-DRYRUN-private}"
fi
require_vars SUBNET_PUBLIC_A RT_PRIVATE
check_account

# 이미 켜진 NAT가 있으면 멈춘다 (두 개면 비용이 2배)
if [[ $DRY_RUN == 0 ]]; then
  running=$(aws --region "$AWS_REGION" ec2 describe-nat-gateways \
    --filter "Name=tag:Project,Values=$PROJECT_TAG" "Name=state,Values=pending,available" \
    --query 'NatGateways[].NatGatewayId' --output text)
  [[ -z $running ]] || die "이미 켜진 NAT가 있음: $running (중복 생성 방지)"
fi

# 중간에 멈추면 EIP가 남아 요금이 나갈 수 있다 → 끝날 때 알려 준다
EIP_ALLOC="" ; finished=0
trap 'if [[ $finished != 1 && -n $EIP_ALLOC && $DRY_RUN == 0 ]]; then
        log "주의: 중간에 멈춤. EIP $EIP_ALLOC 가 남아 있으면 요금이 나감 → nat-down.sh로 정리"; fi' EXIT

log "nat-up 1/4 EIP 할당"
EIP_ALLOC=$(aws_new eipalloc-DRYRUN ec2 allocate-address --domain vpc \
  --tag-specifications "$(tags elastic-ip haven-nat-eip)" --query AllocationId --output text)

log "nat-up 2/4 NAT Gateway 생성 (public-a)"
NAT_ID=$(aws_new nat-DRYRUN ec2 create-nat-gateway --subnet-id "$SUBNET_PUBLIC_A" \
  --allocation-id "$EIP_ALLOC" --tag-specifications "$(tags natgateway haven-nat)" \
  --query NatGateway.NatGatewayId --output text)

log "nat-up 3/4 NAT available 대기 (보통 1~2분)"
aws_do ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_ID"

log "nat-up 4/4 rt-private 기본 경로 → 새 NAT"
if [[ $DRY_RUN == 1 ]]; then
  existing=0
else
  existing=$(aws --region "$AWS_REGION" ec2 describe-route-tables --route-table-ids "$RT_PRIVATE" \
    --query "length(RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'])" --output text)
fi
if [[ $existing == 0 ]]; then
  aws_do ec2 create-route --route-table-id "$RT_PRIVATE" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_ID"
else
  # 어제 NAT를 지워서 blackhole이 된 경로를 새 NAT로 바꾼다 (설계 5.2)
  aws_do ec2 replace-route --route-table-id "$RT_PRIVATE" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_ID"
fi

# 확인 (연결확인표 RST-02): 기본 경로가 새 NAT를 가리키고 active인가
if [[ $DRY_RUN == 0 ]]; then
  read -r got_nat got_state < <(aws --region "$AWS_REGION" ec2 describe-route-tables --route-table-ids "$RT_PRIVATE" \
    --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'] | [0].[NatGatewayId,State]" --output text)
  [[ ${got_nat:-} == "$NAT_ID" && ${got_state:-} == active ]] \
    || die "경로 확인 실패: 0.0.0.0/0 → ${got_nat:-없음} (${got_state:-?}), 기대 $NAT_ID active"
  log "RST-02 확인: 0.0.0.0/0 → $NAT_ID active (SSM Online은 연결확인표 SSM-01로 따로 확인)"
  mkdir -p "$(dirname "$NAT_STATE_FILE")"
  printf 'NAT_ID=%q\nEIP_ALLOC=%q\nNAT_UP_AT=%q\n' "$NAT_ID" "$EIP_ALLOC" "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$NAT_STATE_FILE"
fi

finished=1
log "nat-up 완료: NAT=$NAT_ID EIP=$EIP_ALLOC"
