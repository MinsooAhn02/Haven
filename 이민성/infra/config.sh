#!/usr/bin/env bash
# Haven 구축 설정값 (설계.md 1~5.4절, docs/AWS_운영결정.md 기준)
# 다른 계정에서 쓸 때는 이 파일 값만 바꾸거나, 실행 전에 같은 이름의 환경변수로 덮어쓴다.
#   예) AWS_REGION=us-east-1 ./build.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1        # Git Bash: /aws/service/... 경로가 Windows 경로로 바뀌는 것 방지 (민수 지시)
export MSYS2_ARG_CONV_EXCL='*'   # MSYS2에서 실행할 때도 같은 문제 방지

# ── 공통 ─────────────────────────────────────────────
: "${AWS_REGION:=ap-northeast-2}"           # 결정 1번: 서울
: "${PROJECT_TAG:=Haven}"                   # 모든 자원 태그 (nat-down·전체 삭제 대상 식별)
: "${OWNER_TAG:=minsung}"
: "${DRY_RUN:=0}"                           # 1이면 AWS에 보내지 않고 명령만 출력

# ── VPC·서브넷 (설계.md 1~2절) ───────────────────────
: "${VPC_CIDR:=10.20.0.0/16}"
: "${AZ_A:=${AWS_REGION}a}"
: "${AZ_B:=${AWS_REGION}c}"                 # 두 번째 AZ (ALB용, 3회차)
: "${PUBLIC_A_CIDR:=10.20.0.0/24}"          # ALB + NAT
: "${PUBLIC_B_CIDR:=10.20.1.0/24}"          # ALB
: "${PRIVATE_WEB_CIDR:=10.20.10.0/24}"      # web-1
: "${PRIVATE_DB_CIDR:=10.20.20.0/24}"       # db-1

# ── EC2 (설계.md 5.4절, 결정 10번) ───────────────────
: "${INSTANCE_TYPE:=t3.small}"
: "${ROOT_VOLUME_GB:=20}"
: "${AMI_SSM_PARAM:=/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id}"
: "${EC2_INSTANCE_PROFILE=haven-ec2-ssm-profile}"   # 민수 확정 11/09, 김보람이 생성. 비면 EC2 만들기 전에 멈춤

# ── 시험용 임시 EC2 (결정 11번) ───────────────────────
: "${TEST_INSTANCE_TYPE:=t3.micro}"

# ── 계정 안전장치 ─────────────────────────────────────
: "${EXPECTED_ACCOUNT_ID=}"                 # 팀 계정 번호 12자리(김보람). 실제 실행 때만 필요. 실행할 때 환경변수로 넣는다
