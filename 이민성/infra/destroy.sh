#!/usr/bin/env bash
# 전체 삭제: 태그 Project=Haven, Owner=minsung 인 자원만 찾아 지운다
#   되돌릴 수 없는 작업이라 결정 11번 사전 승인 범위가 아니다 → 실행 전 반드시 민수 확인
#
# 사용
#   목록만 보기 (기본, 아무것도 안 지움):  bash destroy.sh
#   삭제 명령 미리보기:                    DRY_RUN=1 bash destroy.sh --delete
#   실제 삭제 (민수 확인 후):               bash destroy.sh --delete   → 확인 문구를 직접 입력해야 진행
#
# 지우는 순서 (의존 관계 때문에 순서가 중요)
#   EC2 → NAT → EIP → S3 Endpoint → SG 규칙·SG → 라우팅 테이블 → 서브넷 → IGW → VPC
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

MODE=list
case "${1:-}" in
  "")       MODE=list ;;
  --delete) MODE=delete ;;
  *)        die "알 수 없는 옵션: $1 (목록만: 옵션 없음 / 삭제: --delete)" ;;
esac
CONFIRM_TEXT="haven 삭제"

check_dry_run
check_account

TAGF=("Name=tag:Project,Values=$PROJECT_TAG" "Name=tag:Owner,Values=$OWNER_TAG")
q() { aws --region "$AWS_REGION" "$@" --output text; }   # 조회 전용

# ── 1. 지울 목록 찾기 (state 파일이 아니라 태그로 찾는다: 중간에 실패해 기록이 없어도 찾을 수 있게) ──
if [[ $DRY_RUN == 1 ]]; then
  log "DRY-RUN: 실제 목록은 조회하지 않고 가짜 ID로 순서만 보여 준다"
  INST="i-DRYRUN-web-1 i-DRYRUN-db-1"; NATS="nat-DRYRUN"; EIPS="eipalloc-DRYRUN"
  VPCES="vpce-DRYRUN"; SGS="sg-DRYRUN-sg-alb sg-DRYRUN-sg-web sg-DRYRUN-sg-db"
  RTS="rtb-DRYRUN-public rtb-DRYRUN-private"
  SUBNETS="subnet-DRYRUN-public-a subnet-DRYRUN-public-b subnet-DRYRUN-private-web subnet-DRYRUN-private-db"
  IGWS="igw-DRYRUN"; VPCS="vpc-DRYRUN"
else
  INST=$(q ec2 describe-instances --filters "${TAGF[@]}" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId')
  NATS=$(q ec2 describe-nat-gateways --filter "${TAGF[@]}" "Name=state,Values=pending,available,deleting" \
    --query 'NatGateways[].NatGatewayId')
  EIPS=$(q ec2 describe-addresses --filters "${TAGF[@]}" --query 'Addresses[].AllocationId')
  VPCES=$(q ec2 describe-vpc-endpoints --filters "${TAGF[@]}" --query 'VpcEndpoints[?State!=`deleted`].VpcEndpointId')
  SGS=$(q ec2 describe-security-groups --filters "${TAGF[@]}" --query 'SecurityGroups[].GroupId')
  RTS=$(q ec2 describe-route-tables --filters "${TAGF[@]}" --query 'RouteTables[].RouteTableId')
  SUBNETS=$(q ec2 describe-subnets --filters "${TAGF[@]}" --query 'Subnets[].SubnetId')
  IGWS=$(q ec2 describe-internet-gateways --filters "${TAGF[@]}" --query 'InternetGateways[].InternetGatewayId')
  VPCS=$(q ec2 describe-vpcs --filters "${TAGF[@]}" --query 'Vpcs[].VpcId')
fi

count() { local n=0 x; for x in $1; do n=$((n + 1)); done; echo "$n"; }
printf '\n지울 목록 (리전 %s, 태그 Project=%s Owner=%s)\n' "$AWS_REGION" "$PROJECT_TAG" "$OWNER_TAG" >&2
printf '  %-14s %2s개  %s\n' \
  "EC2"          "$(count "$INST")"    "$INST" \
  "NAT"          "$(count "$NATS")"    "$NATS" \
  "EIP"          "$(count "$EIPS")"    "$EIPS" \
  "S3 Endpoint"  "$(count "$VPCES")"   "$VPCES" \
  "SG"           "$(count "$SGS")"     "$SGS" \
  "라우팅 테이블" "$(count "$RTS")"     "$RTS" \
  "서브넷"        "$(count "$SUBNETS")" "$SUBNETS" \
  "IGW"          "$(count "$IGWS")"    "$IGWS" \
  "VPC"          "$(count "$VPCS")"    "$VPCS" >&2
printf '\n' >&2

total=$(count "$INST $NATS $EIPS $VPCES $SGS $RTS $SUBNETS $IGWS $VPCS")
if (( total == 0 )); then log "지울 자원 없음"; exit 0; fi
if [[ $MODE == list ]]; then
  log "목록만 출력하고 끝냄 (아무것도 지우지 않음). 지우려면 민수 확인 후: bash destroy.sh --delete"
  exit 0
fi

# ── 2. 확인 문구 (실제 삭제일 때만) ───────────────────
if [[ $DRY_RUN == 0 ]]; then
  log "되돌릴 수 없는 삭제입니다. 민수에게 확인받았나요? DB 데이터 백업(민수 dump)은 끝났나요?"
  read -r -p "진행하려면 '$CONFIRM_TEXT' 를 그대로 입력: " answer
  [[ $answer == "$CONFIRM_TEXT" ]] || die "확인 문구가 다름. 아무것도 지우지 않고 끝냄"
fi

wait_nat_deleted() {  # NAT가 deleted가 될 때까지 (최대 10분)
  local id=$1 state="" i
  [[ $DRY_RUN == 1 ]] && { log "DRY-RUN: $id deleted 대기"; return; }
  for i in $(seq 1 60); do
    state=$(q ec2 describe-nat-gateways --nat-gateway-ids "$id" --query 'NatGateways[0].State')
    [[ $state == deleted ]] && return 0
    sleep 10
  done
  die "NAT $id 삭제 대기 시간 초과 (마지막 상태: $state)"
}

# ── 3. 순서대로 삭제 ─────────────────────────────────
log "삭제 1/9 EC2"
if [[ -n $INST ]]; then
  aws_do ec2 terminate-instances --instance-ids $INST
  aws_do ec2 wait instance-terminated --instance-ids $INST
fi

log "삭제 2/9 NAT"
for id in $NATS; do aws_do ec2 delete-nat-gateway --nat-gateway-id "$id"; wait_nat_deleted "$id"; done

log "삭제 3/9 EIP"
for id in $EIPS; do aws_do ec2 release-address --allocation-id "$id"; done

log "삭제 4/9 S3 Endpoint"
[[ -z $VPCES ]] || aws_do ec2 delete-vpc-endpoints --vpc-endpoint-ids $VPCES

log "삭제 5/9 SG (서로를 가리키는 규칙을 먼저 지워야 SG를 지울 수 있음)"
for sg in $SGS; do
  if [[ $DRY_RUN == 1 ]]; then
    show ec2 revoke-security-group-ingress --group-id "$sg" --security-group-rule-ids "<인바운드 규칙 ID들>"
    show ec2 revoke-security-group-egress  --group-id "$sg" --security-group-rule-ids "<아웃바운드 규칙 ID들>"
    continue
  fi
  in_rules=$(q ec2 describe-security-group-rules --filters "Name=group-id,Values=$sg" \
    --query 'SecurityGroupRules[?IsEgress==`false`].SecurityGroupRuleId')
  out_rules=$(q ec2 describe-security-group-rules --filters "Name=group-id,Values=$sg" \
    --query 'SecurityGroupRules[?IsEgress==`true`].SecurityGroupRuleId')
  [[ -z $in_rules ]]  || aws_do ec2 revoke-security-group-ingress --group-id "$sg" --security-group-rule-ids $in_rules
  [[ -z $out_rules ]] || aws_do ec2 revoke-security-group-egress  --group-id "$sg" --security-group-rule-ids $out_rules
done
for sg in $SGS; do aws_do ec2 delete-security-group --group-id "$sg"; done

log "삭제 6/9 라우팅 테이블 (서브넷 연결을 먼저 끊음)"
for rt in $RTS; do
  if [[ $DRY_RUN == 1 ]]; then
    show ec2 disassociate-route-table --association-id "<$rt 의 연결 ID들>"
  else
    assocs=$(q ec2 describe-route-tables --route-table-ids "$rt" \
      --query 'RouteTables[0].Associations[?Main!=`true`].RouteTableAssociationId')
    for a in $assocs; do aws_do ec2 disassociate-route-table --association-id "$a"; done
  fi
  aws_do ec2 delete-route-table --route-table-id "$rt"
done

log "삭제 7/9 서브넷"
for id in $SUBNETS; do aws_do ec2 delete-subnet --subnet-id "$id"; done

log "삭제 8/9 IGW (VPC에서 떼고 삭제)"
for igw in $IGWS; do
  for v in $VPCS; do aws_do ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$v"; done
  aws_do ec2 delete-internet-gateway --internet-gateway-id "$igw"
done

log "삭제 9/9 VPC"
for id in $VPCS; do aws_do ec2 delete-vpc --vpc-id "$id"; done

if [[ $DRY_RUN == 0 ]]; then
  rm -f "$STATE_FILE" "$NAT_STATE_FILE"
  log "state 파일 삭제. 다시 'bash destroy.sh'로 목록이 비었는지 확인할 것"
fi
log "destroy 완료"
