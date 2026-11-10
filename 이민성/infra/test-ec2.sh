#!/usr/bin/env bash
# 연결 시험용 임시 EC2 (연결확인표 NET-04·NET-04-b·NET-02-d, 결정 11번 사전 승인)
#   create: 시험용 SG(haven-sg-test, 아웃바운드 허용·인바운드 없음) + EC2 haven-test-<용도>(t3.micro, 공인 IP 없음, 디스크 8GB 암호화, SSM)
#   delete: 이름이 haven-test- 로 시작하는 EC2만 전부 삭제 → 시험용 SG 삭제 시도. 시험한 날 반드시 delete
#
# 이름 규칙 (11/10 민수 요청, 보람 IAM 조건과 같음): Name=haven-test-<용도>, Project=Haven, Owner=minsung
#   보람 정책상 EC2 삭제는 Name이 haven-test- 로 시작하는 서버만 허용 → 이 이름이 아니면 못 지운다
#   기본값 haven-test-net04. 다른 용도: TEST_NAME=haven-test-reboot bash test-ec2.sh create
#
# 안전장치
#   - 삭제 대상은 태그 Name=haven-test-* + Project + Owner 인 것만. web-1/db-1 ID와 같거나 이름이 규칙과 다르면 멈춤
#   - 이미 haven-test-* 가 있으면 새로 만들지 않음 (중복 방지)
#   - 생성·삭제 시각과 ID를 state/<리전>-test.env 에 기록 (증거용, Git 제외)
#   - SG 삭제 권한이 없으면 경고만 (SG는 무료, 다음 create 때 다시 씀)
#
# 사용
#   미리보기: DRY_RUN=1 bash test-ec2.sh create
#   만들기:   bash test-ec2.sh create
#   지우기:   bash test-ec2.sh delete
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

TEST_PREFIX=haven-test-
: "${TEST_NAME:=haven-test-net04}"
TEST_SG_NAME=haven-sg-test
TEST_STATE_FILE="$HERE/state/${AWS_REGION}-test.env"
action=${1:-}
[[ $action == create || $action == delete ]] || die "사용: bash test-ec2.sh create | delete"
[[ $TEST_NAME =~ ^haven-test-[a-z0-9][a-z0-9-]*$ ]] \
  || die "TEST_NAME은 haven-test-<용도> 형식이어야 함 (영문 소문자·숫자·-), 현재: '$TEST_NAME'. 다른 이름은 보람 정책상 삭제 못 함"

check_dry_run
load_state
if [[ $DRY_RUN == 1 ]]; then
  : "${VPC_ID:=vpc-DRYRUN}" "${SUBNET_PRIVATE_WEB:=subnet-DRYRUN-private-web}"
fi
require_vars VPC_ID SUBNET_PRIVATE_WEB TEST_INSTANCE_TYPE AMI_SSM_PARAM EC2_INSTANCE_PROFILE
check_account

note() {  # 증거 기록
  log "$*"
  if [[ $DRY_RUN == 0 ]]; then
    mkdir -p "$(dirname "$TEST_STATE_FILE")"
    printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "$TEST_STATE_FILE"
  fi
}

find_test() {  # 살아 있는 haven-test-* 서버: "ID 이름" 한 줄씩
  aws --region "$AWS_REGION" ec2 describe-instances \
    --filters "Name=tag:Name,Values=${TEST_PREFIX}*" "Name=tag:Project,Values=$PROJECT_TAG" \
              "Name=tag:Owner,Values=$OWNER_TAG" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`]|[0].Value]' --output text
}

find_test_sg() {
  aws --region "$AWS_REGION" ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=$TEST_SG_NAME" \
    --query 'SecurityGroups[].GroupId' --output text
}

if [[ $action == create ]]; then
  # ── 중복 방지 ──
  if [[ $DRY_RUN == 0 ]]; then
    existing=$(find_test)
    [[ -z $existing ]] || die "시험용 EC2가 이미 있음: $(tr '\n\t' '; ' <<< "$existing") → 시험 후 bash test-ec2.sh delete"
  fi

  # ── 1. 시험용 SG (있으면 다시 씀) ──
  log "test 1/3 시험용 SG ($TEST_SG_NAME)"
  SG_TEST=""
  [[ $DRY_RUN == 1 ]] || SG_TEST=$(find_test_sg)
  if [[ -n $SG_TEST ]]; then
    log "이미 있음: $SG_TEST (다시 씀)"
  else
    # 인바운드 없음, 아웃바운드는 AWS 기본값(전부 허용) 그대로 → 출발지 쪽에서 막히지 않게 (연결확인표 머리말)
    SG_TEST=$(aws_new sg-DRYRUN-test ec2 create-security-group --vpc-id "$VPC_ID" \
      --group-name "$TEST_SG_NAME" --description "Haven connection test (delete same day)" \
      --tag-specifications "$(tags security-group "$TEST_SG_NAME")" --query GroupId --output text)
    note "SG 생성 $SG_TEST"
  fi

  # ── 2. 시험용 EC2 ──
  log "test 2/3 시험용 EC2 ($TEST_NAME, $TEST_INSTANCE_TYPE, private-web, 공인 IP 없음)"
  if [[ $DRY_RUN == 1 ]]; then
    show ssm get-parameter --name "$AMI_SSM_PARAM" --query Parameter.Value --output text
    AMI=ami-DRYRUN
    ROOT_DEVICE=/dev/sda1
  else
    AMI=$(aws --region "$AWS_REGION" ssm get-parameter --name "$AMI_SSM_PARAM" --query Parameter.Value --output text)
    ROOT_DEVICE=$(aws --region "$AWS_REGION" ec2 describe-images --image-ids "$AMI" --query 'Images[0].RootDeviceName' --output text)
  fi
  [[ $AMI == ami-* ]] || die "AMI 조회 실패: '$AMI'"
  TEST_ID=$(aws_new i-DRYRUN-test ec2 run-instances --image-id "$AMI" --instance-type "$TEST_INSTANCE_TYPE" \
    --subnet-id "$SUBNET_PRIVATE_WEB" --security-group-ids "$SG_TEST" --no-associate-public-ip-address \
    --iam-instance-profile "Name=$EC2_INSTANCE_PROFILE" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --block-device-mappings "[{\"DeviceName\":\"$ROOT_DEVICE\",\"Ebs\":{\"VolumeSize\":8,\"VolumeType\":\"gp3\",\"Encrypted\":true,\"DeleteOnTermination\":true}}]" \
    --tag-specifications "$(tags instance "$TEST_NAME")" "$(tags volume "$TEST_NAME-root")" \
    --query 'Instances[0].InstanceId' --output text)
  note "EC2 생성 $TEST_ID (AMI $AMI)"
  aws_do ec2 wait instance-running --instance-ids "$TEST_ID"

  # ── 3. 확인 + SSM Online 대기 (최대 5분) ──
  log "test 3/3 확인"
  if [[ $DRY_RUN == 0 ]]; then
    pub=$(aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$TEST_ID" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
    [[ -z $pub || $pub == None ]] || die "시험용 EC2에 공인 IP가 붙었음: $pub → 바로 bash test-ec2.sh delete"
    ok=""
    for i in $(seq 1 30); do
      st=$(aws --region "$AWS_REGION" ssm describe-instance-information \
        --filters "Key=InstanceIds,Values=$TEST_ID" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
      if [[ $st == Online ]]; then ok=1; break; fi
      sleep 10
    done
    [[ -n $ok ]] && log "SSM Online" || log "주의: 5분 안에 SSM Online 안 됨 (조금 더 기다리거나 콘솔에서 확인)"
    web_ip=$(aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$WEB_ID" \
      --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
    db_ip=$(aws --region "$AWS_REGION" ec2 describe-instances --instance-ids "$DB_ID" \
      --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
  else
    web_ip=WEB_IP; db_ip=DB_IP
  fi
  cat >&2 <<MSG

시험용 EC2 준비 완료: $TEST_ID
콘솔 → EC2 → $TEST_NAME → 연결 → Session Manager 로 접속 후, 아래를 붙여 넣기 (셋 다 timeout(exit=124)이어야 통과)
------------------------------------------------------------
echo "== NET-04   test -> db-1:5432";  timeout 5 bash -c '</dev/tcp/$db_ip/5432'; echo "exit=\$?"
echo "== NET-04-b test -> db-1:22";    timeout 5 bash -c '</dev/tcp/$db_ip/22';   echo "exit=\$?"
echo "== NET-02-d test -> web-1:80";   timeout 5 bash -c '</dev/tcp/$web_ip/80';  echo "exit=\$?"
------------------------------------------------------------
시험이 끝나면 반드시: bash test-ec2.sh delete
MSG
fi

if [[ $action == delete ]]; then
  log "test 삭제 1/2 시험용 EC2 (${TEST_PREFIX}*)"
  if [[ $DRY_RUN == 1 ]]; then
    found=$'i-DRYRUN-test\thaven-test-net04'
  else
    found=$(find_test)
  fi
  ids=""
  while read -r id name; do
    [[ -n ${id:-} ]] || continue
    # 이중 안전장치: 진짜 서버 ID이거나 이름 규칙이 다르면 하나도 지우지 않음
    [[ $id != "${WEB_ID:-x}" && $id != "${DB_ID:-x}" ]] || die "삭제 대상 $id 가 web-1/db-1 ID와 같음 → 멈춤 (태그 확인)"
    [[ ${name:-} == ${TEST_PREFIX}* ]] || die "삭제 대상 $id 이름이 '${name:-}' (규칙 ${TEST_PREFIX}* 아님) → 멈춤"
    log "삭제 대상: $id ($name)"
    ids+="$id "
  done <<< "$found"
  ids=${ids% }
  if [[ -z $ids ]]; then
    log "시험용 EC2 없음 (이미 지워짐)"
  else
    aws_do ec2 terminate-instances --instance-ids $ids
    note "EC2 삭제 요청 $ids"
    aws_do ec2 wait instance-terminated --instance-ids $ids
    note "EC2 삭제 완료 $ids"
  fi

  log "test 삭제 2/2 시험용 SG ($TEST_SG_NAME)"
  sg=""
  [[ $DRY_RUN == 1 ]] && sg=sg-DRYRUN-test || sg=$(find_test_sg)
  if [[ -z $sg ]]; then
    log "시험용 SG 없음"
  elif [[ $DRY_RUN == 1 ]]; then
    show ec2 delete-security-group --group-id "$sg"
  elif aws --region "$AWS_REGION" ec2 delete-security-group --group-id "$sg" >/dev/null 2>&1; then
    note "SG 삭제 $sg"
  else
    log "주의: 시험용 SG $sg 삭제 못 함 (권한 없음일 수 있음). SG는 무료이고 다음 create 때 다시 씀"
  fi
  log "test 삭제 완료"
fi
