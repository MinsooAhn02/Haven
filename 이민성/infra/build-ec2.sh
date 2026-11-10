#!/usr/bin/env bash
# 구축 재개: build.sh 8단계(EC2 2대)만 실행한다
#   언제: build.sh가 1~6단계는 끝냈는데 7단계 이후 멈췄을 때 (다시 build.sh를 돌리면 중복 방지로 멈춤)
#   11/10 실제 구축에서 nat-up 확인 오탐(Windows \r)으로 7단계에서 멈춰서 추가.
#   내용은 build.sh 8단계와 같다 (고칠 때 둘 다 고칠 것)
#
# 전제
#   - state 파일에 서브넷·SG ID가 있다 (build.sh 1~6단계 결과)
#   - NAT가 켜져 있다 (먼저 bash nat-up.sh). NAT 없이 만들면 SSM이 안 붙는다
#   - web-1, db-1이 아직 없다
#
# 사용
#   미리보기: DRY_RUN=1 bash build-ec2.sh
#   실제:     bash build-ec2.sh
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

check_dry_run
load_state
if [[ $DRY_RUN == 1 ]]; then   # 미리보기에서 state가 없으면 가짜 ID
  : "${SUBNET_PRIVATE_WEB:=subnet-DRYRUN-private-web}" "${SUBNET_PRIVATE_DB:=subnet-DRYRUN-private-db}"
  : "${SG_WEB:=sg-DRYRUN-sg-web}" "${SG_DB:=sg-DRYRUN-sg-db}"
fi
require_vars SUBNET_PRIVATE_WEB SUBNET_PRIVATE_DB SG_WEB SG_DB \
  INSTANCE_TYPE ROOT_VOLUME_GB AMI_SSM_PARAM EC2_INSTANCE_PROFILE
check_account

if [[ $DRY_RUN == 0 ]]; then
  # 중복 방지: 이미 만든 EC2가 있으면 멈춤
  [[ -z ${WEB_ID:-} && -z ${DB_ID:-} ]] || die "state 파일에 이미 EC2 ID가 있음 (WEB_ID=${WEB_ID:-}, DB_ID=${DB_ID:-})"
  existing=$(aws --region "$AWS_REGION" ec2 describe-instances \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" "Name=tag:Name,Values=web-1,db-1" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)
  [[ -z $existing ]] || die "web-1/db-1이 이미 있음: $existing (중복 생성 방지)"
  # NAT가 켜져 있어야 SSM이 붙는다
  nat=$(aws --region "$AWS_REGION" ec2 describe-nat-gateways \
    --filter "Name=tag:Project,Values=$PROJECT_TAG" "Name=state,Values=available" \
    --query 'NatGateways[].NatGatewayId' --output text)
  [[ -n $nat ]] || die "켜진 NAT가 없음 → 먼저 bash nat-up.sh"
  log "확인: EC2 없음, NAT 켜짐($nat)"
fi

# ── 8. EC2 2대 (build.sh 8단계와 같음) ──────────────
log "8/8 EC2 2대 (web-1, db-1)"
if [[ $DRY_RUN == 1 ]]; then
  show ssm get-parameter --name "$AMI_SSM_PARAM" --query Parameter.Value --output text
  AMI_ID=ami-DRYRUN
  ROOT_DEVICE=/dev/sda1
else
  AMI_ID=$(aws --region "$AWS_REGION" ssm get-parameter --name "$AMI_SSM_PARAM" --query Parameter.Value --output text)
  ROOT_DEVICE=$(aws --region "$AWS_REGION" ec2 describe-images --image-ids "$AMI_ID" --query 'Images[0].RootDeviceName' --output text)
fi
[[ $AMI_ID == ami-* ]] || die "AMI 조회 실패: '$AMI_ID' (Git Bash면 MSYS_NO_PATHCONV 확인)"
AMI_LOOKUP_AT=$(date '+%Y-%m-%dT%H:%M:%S%z')
remember AMI_ID
remember AMI_LOOKUP_AT

make_ec2() {  # make_ec2 <이름> <서브넷> <SG>
  local id
  id=$(aws_new "i-DRYRUN-$1" ec2 run-instances --image-id "$AMI_ID" --instance-type "$INSTANCE_TYPE" \
    --subnet-id "$2" --security-group-ids "$3" --no-associate-public-ip-address \
    --iam-instance-profile "Name=$EC2_INSTANCE_PROFILE" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --block-device-mappings "[{\"DeviceName\":\"$ROOT_DEVICE\",\"Ebs\":{\"VolumeSize\":$ROOT_VOLUME_GB,\"VolumeType\":\"gp3\",\"Encrypted\":true,\"DeleteOnTermination\":true}}]" \
    --tag-specifications "$(tags instance "$1")" "$(tags volume "$1-root")" \
    --query 'Instances[0].InstanceId' --output text)
  echo "$id"
}
WEB_ID=$(make_ec2 web-1 "$SUBNET_PRIVATE_WEB" "$SG_WEB"); remember WEB_ID
DB_ID=$(make_ec2 db-1 "$SUBNET_PRIVATE_DB" "$SG_DB");    remember DB_ID
aws_do ec2 wait instance-running --instance-ids "$WEB_ID" "$DB_ID"

# 공인 IP가 붙지 않았는지 바로 확인 (설계 2절, 연결확인표 NET-02-a)
if [[ $DRY_RUN == 0 ]]; then
  pub=$(aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$WEB_ID" "$DB_ID" \
    --query 'Reservations[].Instances[].PublicIpAddress' --output text)
  [[ -z $pub || $pub == None ]] || die "공인 IP가 붙었음: $pub (설계 2절 위반, 확인 필요)"
fi

log "EC2 완료: web-1 $WEB_ID, db-1 $DB_ID (AMI $AMI_ID, 조회 $AMI_LOOKUP_AT)"
log "다음: 연결확인표 SSM-01 (EC2가 SSM에 Online 되기까지 몇 분 걸릴 수 있음)"
