#!/usr/bin/env bash
# Haven 구축 1부: VPC → 서브넷 → IGW → 라우팅 → SG  (설계.md 1~4절)
# Haven 구축 2부: S3 Gateway Endpoint → NAT(nat-up.sh) → EC2 2대  (설계 3·5절, 5.4절)
#
# 사용
#   미리보기: DRY_RUN=1 bash build.sh   (AWS에 아무것도 보내지 않고 명령만 출력)
#   실제 구축: bash build.sh            (AWS_운영결정 11번 사전 승인 범위)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

# ── 0. 사전 확인 ──────────────────────────────────────
check_dry_run
require_vars AWS_REGION PROJECT_TAG OWNER_TAG VPC_CIDR AZ_A AZ_B \
  PUBLIC_A_CIDR PUBLIC_B_CIDR PRIVATE_WEB_CIDR PRIVATE_DB_CIDR \
  INSTANCE_TYPE ROOT_VOLUME_GB AMI_SSM_PARAM EC2_INSTANCE_PROFILE
command -v aws >/dev/null || die "aws CLI가 없음"
log "리전=$AWS_REGION 태그=Project:$PROJECT_TAG,Owner:$OWNER_TAG DRY_RUN=$DRY_RUN"

check_account
if [[ $DRY_RUN == 0 ]]; then
  [[ ! -e $STATE_FILE ]] || die "상태 파일이 이미 있음: $STATE_FILE (이미 구축됐는지 확인)"
  existing=$(aws --region "$AWS_REGION" ec2 describe-vpcs \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" --query 'Vpcs[].VpcId' --output text)
  [[ -z $existing ]] || die "태그 Project=$PROJECT_TAG VPC가 이미 있음: $existing (중복 구축 방지)"
fi

# ── 1. VPC (설계 1절) ─────────────────────────────────
log "1/8 VPC"
VPC_ID=$(aws_new vpc-DRYRUN ec2 create-vpc --cidr-block "$VPC_CIDR" \
  --tag-specifications "$(tags vpc haven-vpc)" --query Vpc.VpcId --output text)
remember VPC_ID
aws_do ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support '{"Value":true}'
aws_do ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames '{"Value":true}'

# ── 2. 서브넷 4개, 공인 IP 자동 할당 끔 (설계 2절) ────
log "2/8 서브넷"
make_subnet() {  # make_subnet <이름> <CIDR> <AZ>
  local id
  id=$(aws_new "subnet-DRYRUN-$1" ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "$2" \
    --availability-zone "$3" --tag-specifications "$(tags subnet "haven-$1")" \
    --query Subnet.SubnetId --output text)
  aws_do ec2 modify-subnet-attribute --subnet-id "$id" --no-map-public-ip-on-launch
  echo "$id"
}
SUBNET_PUBLIC_A=$(make_subnet public-a "$PUBLIC_A_CIDR" "$AZ_A");          remember SUBNET_PUBLIC_A
SUBNET_PUBLIC_B=$(make_subnet public-b "$PUBLIC_B_CIDR" "$AZ_B");          remember SUBNET_PUBLIC_B
SUBNET_PRIVATE_WEB=$(make_subnet private-web "$PRIVATE_WEB_CIDR" "$AZ_A"); remember SUBNET_PRIVATE_WEB
SUBNET_PRIVATE_DB=$(make_subnet private-db "$PRIVATE_DB_CIDR" "$AZ_A");    remember SUBNET_PRIVATE_DB

# ── 3. 인터넷 게이트웨이 ──────────────────────────────
log "3/8 인터넷 게이트웨이"
IGW_ID=$(aws_new igw-DRYRUN ec2 create-internet-gateway \
  --tag-specifications "$(tags internet-gateway haven-igw)" \
  --query InternetGateway.InternetGatewayId --output text)
remember IGW_ID
aws_do ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"

# ── 4. 라우팅 테이블 (설계 3절) ───────────────────────
log "4/8 라우팅 테이블"
RT_PUBLIC=$(aws_new rtb-DRYRUN-public ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications "$(tags route-table haven-rt-public)" --query RouteTable.RouteTableId --output text)
remember RT_PUBLIC
aws_do ec2 create-route --route-table-id "$RT_PUBLIC" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID"
aws_do ec2 associate-route-table --route-table-id "$RT_PUBLIC" --subnet-id "$SUBNET_PUBLIC_A"
aws_do ec2 associate-route-table --route-table-id "$RT_PUBLIC" --subnet-id "$SUBNET_PUBLIC_B"

RT_PRIVATE=$(aws_new rtb-DRYRUN-private ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications "$(tags route-table haven-rt-private)" --query RouteTable.RouteTableId --output text)
remember RT_PRIVATE
aws_do ec2 associate-route-table --route-table-id "$RT_PRIVATE" --subnet-id "$SUBNET_PRIVATE_WEB"
aws_do ec2 associate-route-table --route-table-id "$RT_PRIVATE" --subnet-id "$SUBNET_PRIVATE_DB"
# rt-private의 0.0.0.0/0 → NAT 경로는 nat-up.sh가 매일 아침 추가한다. 지금은 VPC 내부(local) 경로만 있다.

# ── 5. 보안 그룹 (설계 4절) ───────────────────────────
log "5/8 보안 그룹"
make_sg() {  # make_sg <이름> <설명(영문)>
  local id
  id=$(aws_new "sg-DRYRUN-$1" ec2 create-security-group --vpc-id "$VPC_ID" \
    --group-name "haven-$1" --description "$2" \
    --tag-specifications "$(tags security-group "haven-$1")" --query GroupId --output text)
  # 새 SG에 기본으로 들어 있는 '아웃바운드 전체 허용'을 지운다 → 설계 4.2 허용 목록만 남김
  aws_do ec2 revoke-security-group-egress --group-id "$id" \
    --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'
  echo "$id"
}
in_cidr()  { aws_do ec2 authorize-security-group-ingress --group-id "$1" --ip-permissions "IpProtocol=tcp,FromPort=$2,ToPort=$2,IpRanges=[{CidrIp=$3}]"; }
in_sg()    { aws_do ec2 authorize-security-group-ingress --group-id "$1" --ip-permissions "IpProtocol=tcp,FromPort=$2,ToPort=$2,UserIdGroupPairs=[{GroupId=$3}]"; }
out_cidr() { aws_do ec2 authorize-security-group-egress  --group-id "$1" --ip-permissions "IpProtocol=tcp,FromPort=$2,ToPort=$2,IpRanges=[{CidrIp=$3}]"; }
out_sg()   { aws_do ec2 authorize-security-group-egress  --group-id "$1" --ip-permissions "IpProtocol=tcp,FromPort=$2,ToPort=$2,UserIdGroupPairs=[{GroupId=$3}]"; }

SG_ALB=$(make_sg sg-alb "Haven ALB");      remember SG_ALB
SG_WEB=$(make_sg sg-web "Haven web-1");    remember SG_WEB
SG_DB=$(make_sg sg-db "Haven db-1");       remember SG_DB

# 4.1 Inbound
in_cidr "$SG_ALB" 443 0.0.0.0/0        # 사용자 HTTPS
in_cidr "$SG_ALB" 80  0.0.0.0/0        # HTTPS redirect 전용
in_sg   "$SG_WEB" 80  "$SG_ALB"        # ALB → Nginx만
in_sg   "$SG_DB"  5432 "$SG_WEB"       # Web → PostgreSQL만
# 4.2 Outbound
out_sg   "$SG_ALB" 80   "$SG_WEB"      # 요청 전달·health check
out_sg   "$SG_WEB" 5432 "$SG_DB"       # DB 연결
out_cidr "$SG_WEB" 443  0.0.0.0/0      # SSM·패키지·AWS API·메일 API
out_cidr "$SG_WEB" 80   0.0.0.0/0      # Ubuntu apt (결정 5번)
out_cidr "$SG_DB"  443  0.0.0.0/0      # SSM·패키지·백업
out_cidr "$SG_DB"  80   0.0.0.0/0      # Ubuntu apt (결정 5번)


# ── 6. S3 Gateway Endpoint (설계 3절·5.1) ─────────────
log "6/8 S3 Gateway Endpoint"
S3_ENDPOINT=$(aws_new vpce-DRYRUN ec2 create-vpc-endpoint --vpc-id "$VPC_ID" \
  --vpc-endpoint-type Gateway --service-name "com.amazonaws.${AWS_REGION}.s3" \
  --route-table-ids "$RT_PRIVATE" \
  --tag-specifications "$(tags vpc-endpoint haven-s3-endpoint)" \
  --query VpcEndpoint.VpcEndpointId --output text)
remember S3_ENDPOINT
# Endpoint 정책(지정 버킷·prefix만 허용, 확인표 OUT-11)은 김보람 IAM 범위. 지금은 기본 정책.

# ── 7. NAT Gateway (설계 3절·5.2, 결정 3·4번) ─────────
# 매일 아침 쓰는 nat-up.sh를 그대로 불러 쓴다 → 구축 날부터 같은 코드가 검증된다
log "7/8 NAT Gateway (nat-up.sh)"
SUBNET_PUBLIC_A="$SUBNET_PUBLIC_A" RT_PRIVATE="$RT_PRIVATE" bash "$HERE/nat-up.sh"

# ── 8. EC2 2대 (설계 5.4절, 결정 5·10번) ──────────────
log "8/8 EC2 2대 (web-1, db-1)"
# AMI는 실행할 때 Canonical 공식 경로에서 최신 ID를 조회한다. 실제 쓴 ID와 시각을 기록(민수 요청)
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

log "구축 완료: VPC·서브넷·IGW·라우팅·SG·S3 Endpoint·NAT·EC2 2대 (AMI $AMI_ID, 조회 $AMI_LOOKUP_AT)"
log "다음: 연결확인표 SSM-01 (EC2가 SSM에 Online 되기까지 몇 분 걸릴 수 있음)"
