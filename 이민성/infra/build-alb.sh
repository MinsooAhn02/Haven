#!/usr/bin/env bash
# 3회차: ALB·ACM·HTTPS·도메인 연결 (민수 11/11 지시 순서)
#   ① ACM 인증서 요청(서울, DNS 검증) + 검증 CNAME을 Route 53에 → 발급까지 대기
#   ② 대상 그룹 haven-tg-web (web-1:80, 상태 검사 /healthz)
#   ③ ALB haven-alb (public 2개, sg-alb, 잘못된 헤더 차단)
#   ④ 443 HTTPS 리스너(인증서) → 대상 그룹 / 80 → 443 301 리다이렉트
#   ⑤ Route 53 apex A Alias → ALB
#   ⑥ 확인: 대상 healthy → NET-01(https) · NET-01-b(http→https) 결과 출력
#
# 전제
#   - build.sh 결과 state 파일에 VPC_ID, SUBNET_PUBLIC_A/B, SG_ALB, WEB_ID가 있다
#   - web-1이 켜져 있고 앱이 배포돼 있다 (healthz ok)
#   - 도메인의 공개 호스팅 영역이 Route 53에 정확히 1개 있고, 네임서버가 연결돼 있다
#   - 보람님 IAM: ELB·ACM 읽기/쓰기, 해당 호스팅 영역 레코드 변경
#
# 다시 실행해도 되는 경우
#   - 인증서 검증 대기 시간이 끝나 멈췄을 때: 같은 도메인 인증서(검증 중/발급됨)를 찾아 재사용한다
#   - ALB·대상 그룹이 이미 있으면 중복 생성하지 않고 멈춘다 (지우는 건 민수 확인 사항)
#   - 2~5단계 중간에 실패한 뒤(예: 권한 부족) 다시 실행하면 이어서 한다: 이미 있는 대상 그룹·ALB·리스너가
#     state/…-alb.env에 이 스크립트가 적은 ID와 **같으면** 재사용하고, 다르면(남이 만든 것) 멈춘다
#     도메인 A 레코드도 이 ALB를 가리키는 것이면 이어서 하고, 다른 곳을 가리키면 멈춘다
#     (11/11 실제 실행에서 ALB 생성 권한 부족으로 대상 그룹까지만 만들어진 뒤 추가)
#
# 알아둘 점
#   - destroy.sh는 ALB를 모른다. ALB가 있으면 sg-alb·public 서브넷 삭제가 실패하니 ALB를 먼저 정리해야 한다
#   - 밤에 EC2를 끄면 ALB는 502/503을 낸다 (정상). ALB 자체는 켜 둔다 (민수 11/11, 유지 여부는 보람님 비용 판단)
#
# 사용 (이민성/infra 에서)
#   미리보기: DRY_RUN=1 bash build-alb.sh
#   실제:     EXPECTED_ACCOUNT_ID=<팀 계정 12자리> bash build-alb.sh 2>&1 | tee ~/alb-$(date +%m%d).log
#   ※ 로그에 계정 번호가 든 ARN이 나온다. PR·증거에 붙일 때는 가린다
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"

# ── 설정 (환경변수로 덮어쓸 수 있음) ───────────────────
: "${DOMAIN:=orchestration-haven.cloud}"          # 11/11 확정
: "${ALB_NAME:=haven-alb}"
: "${TG_NAME:=haven-tg-web}"
: "${HEALTH_PATH:=/healthz}"                       # 민수 Nginx가 이 경로만 Host를 도메인으로 바꿔 넘김 (web-setup.sh)
: "${SSL_POLICY:=ELBSecurityPolicy-TLS13-1-2-2021-06}"   # TLS 1.2 이상만
: "${CERT_WAIT_MAX:=60}"  ; : "${CERT_WAIT_SEC:=30}"     # 인증서 발급 대기 최대 30분
: "${REC_WAIT_MAX:=12}"   ; : "${REC_WAIT_SEC:=5}"      # 검증 레코드 값이 나올 때까지 최대 1분
: "${HEALTH_WAIT_MAX:=40}"; : "${HEALTH_WAIT_SEC:=15}"  # healthy 대기 최대 10분
ALB_STATE_FILE="$HERE/state/${AWS_REGION}-alb.env"

check_dry_run
[[ $DOMAIN =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] \
  || die "DOMAIN 형식이 이상함: '$DOMAIN' (소문자 도메인만, 끝에 점·공백 없이)"
[[ $ALB_NAME =~ ^haven-[a-z0-9-]+$ && $TG_NAME =~ ^haven-[a-z0-9-]+$ ]] \
  || die "ALB/대상 그룹 이름은 haven- 으로 시작해야 함 (보람님 IAM 이름 조건)"
for n in CERT_WAIT_MAX CERT_WAIT_SEC REC_WAIT_MAX REC_WAIT_SEC HEALTH_WAIT_MAX HEALTH_WAIT_SEC; do
  [[ ${!n} =~ ^[0-9]+$ ]] || die "$n 은 숫자여야 함 (현재: ${!n})"
done

load_state
if [[ $DRY_RUN == 1 ]]; then   # 미리보기에서 state가 없으면 가짜 ID
  : "${VPC_ID:=vpc-DRYRUN}" "${SUBNET_PUBLIC_A:=subnet-DRYRUN-public-a}" "${SUBNET_PUBLIC_B:=subnet-DRYRUN-public-b}"
  : "${SG_ALB:=sg-DRYRUN-sg-alb}" "${WEB_ID:=i-DRYRUN-web-1}"
fi
require_vars VPC_ID SUBNET_PUBLIC_A SUBNET_PUBLIC_B SG_ALB WEB_ID
check_account

# 이후 remember는 ALB 전용 state 파일에 적는다 (build.sh state와 섞지 않음)
STATE_FILE="$ALB_STATE_FILE"
if [[ $DRY_RUN == 0 ]]; then
  mkdir -p "$(dirname "$STATE_FILE")"
  printf '# build-alb 실행 %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$STATE_FILE"
fi

# 이전 실행 때 이 스크립트가 적은 값 (없으면 빈 값). 같은 이름이 여러 번 적혔으면 마지막 것
prev() { [[ -f $ALB_STATE_FILE ]] || return 0; grep "^$1=" "$ALB_STATE_FILE" | tail -n 1 | cut -d= -f2- || true; }
REUSE_TG=0; REUSE_ALB=0; LISTENER_HTTPS=""; LISTENER_HTTP=""

elb_tags() {  # elb_tags <이름>  → --tags 값들
  echo "Key=Name,Value=$1" "Key=Project,Value=$PROJECT_TAG" "Key=Owner,Value=$OWNER_TAG"
}
r53() { aws --region "$AWS_REGION" route53 "$@"; }
r53_upsert() {  # r53_upsert <change-batch JSON> <설명>  → 반영 완료까지 대기
  local change
  if [[ $DRY_RUN == 1 ]]; then show route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "$1"; return; fi
  change=$(r53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "$1" \
    --query ChangeInfo.Id --output text) || die "Route 53 레코드 변경 실패 ($2) → 권한(route53:ChangeResourceRecordSets) 확인"
  r53 wait resource-record-sets-changed --id "$change" || die "Route 53 반영 대기 실패 ($2)"
  log "Route 53 반영: $2"
}

# ── 0. 시작 전 확인 (하나라도 걸리면 아무것도 만들지 않음) ─────
if [[ $DRY_RUN == 1 ]]; then
  ZONE_ID=Z-DRYRUN; CERT_ARN=""; CERT_STATUS=""
else
  # web-1이 1대뿐이고 state와 같으며 켜져 있는지
  WEB_ID=$(find_server web-1 WEB_ID)
  st=$(server_state "$WEB_ID")
  [[ $st == running ]] || die "web-1이 running이 아님($st) → bash morning.sh 또는 ec2-start.sh 먼저 (꺼진 채 만들면 unhealthy)"

  # 공개 호스팅 영역이 정확히 1개
  zones=$(r53 list-hosted-zones-by-name --dns-name "$DOMAIN" \
    --query "HostedZones[?Name=='${DOMAIN}.' && Config.PrivateZone==\`false\`].Id" --output text) \
    || die "호스팅 영역 조회 실패 → route53 읽기 권한 확인"
  n=$(wc -w <<< "$zones")
  (( n == 1 )) || die "$DOMAIN 공개 호스팅 영역이 ${n}개 (기대 1개): ${zones:-없음} → 콘솔 Route 53 확인"
  ZONE_ID=${zones##*/}

  # 대상 그룹·ALB: 없으면 새로 만들고, 있으면 이 스크립트가 만든 것(state 기록과 같은 ID)일 때만 이어서 쓴다
  x=$(aws --region "$AWS_REGION" elbv2 describe-target-groups \
    --query "TargetGroups[?TargetGroupName=='$TG_NAME'].TargetGroupArn" --output text) \
    || die "대상 그룹 조회 실패 → elasticloadbalancing:DescribeTargetGroups 권한 확인"
  if [[ -n $x && $x != None ]]; then
    [[ $x == "$(prev TG_ARN)" ]] \
      || die "$TG_NAME 이 이미 있는데 이 스크립트 기록과 다름: $x (남이 만든 것일 수 있어 멈춤. 지우려면 민수 확인)"
    TG_ARN=$x; REUSE_TG=1
  fi
  x=$(aws --region "$AWS_REGION" elbv2 describe-load-balancers \
    --query "LoadBalancers[?LoadBalancerName=='$ALB_NAME'].[LoadBalancerArn,DNSName,CanonicalHostedZoneId]" --output text) \
    || die "ALB 조회 실패 → elasticloadbalancing:DescribeLoadBalancers 권한 확인 (보람님)"
  if [[ -n $x && $x != None ]]; then
    IFS=$'\t' read -r a_arn a_dns a_zone <<< "$x"
    [[ $a_arn == "$(prev ALB_ARN)" ]] \
      || die "$ALB_NAME 이 이미 있는데 이 스크립트 기록과 다름: $a_arn (남이 만든 것일 수 있어 멈춤. 지우려면 민수 확인)"
    (( REUSE_TG )) || die "ALB는 있는데 대상 그룹이 없음 → 상태가 이상해 멈춤 (콘솔 확인 후 민수와 결정)"
    ALB_ARN=$a_arn; ALB_DNS=$a_dns; ALB_ZONE=$a_zone; REUSE_ALB=1
  fi

  # 도메인 자리(apex) A 레코드: 없으면 OK, 이 ALB를 가리키면(이전 실행이 만든 것) OK, 그 밖에는 덮어쓰지 않는다
  n=$(r53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
    --query "length(ResourceRecordSets[?Name=='${DOMAIN}.' && Type=='A'])" --output text) \
    || die "레코드 조회 실패 → route53:ListResourceRecordSets 권한 확인"
  if [[ $n != 0 ]]; then
    cur=$(r53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
      --query "ResourceRecordSets[?Name=='${DOMAIN}.' && Type=='A'].AliasTarget.DNSName" --output text)
    cur=${cur,,}; cur=${cur%.}; cur=${cur#dualstack.}
    [[ $REUSE_ALB == 1 && $cur == "${ALB_DNS,,}" ]] \
      || die "$DOMAIN 에 A 레코드가 이미 있음(${cur:-별칭 아님}) → 남의 설정을 덮어쓰지 않도록 멈춤 (콘솔 확인 후 민수와 결정)"
    log "도메인 A 레코드는 이미 이 ALB를 가리킴 (이전 실행) → 그대로 둠"
  fi

  # 같은 도메인 인증서가 이미 있으면 재사용 (검증 대기 시간 초과 뒤 다시 실행한 경우)
  certs=$(aws --region "$AWS_REGION" acm list-certificates \
    --certificate-statuses PENDING_VALIDATION ISSUED \
    --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn" --output text) \
    || die "인증서 조회 실패 → acm:ListCertificates 권한 확인 (보람님)"
  n=$(wc -w <<< "$certs")
  (( n <= 1 )) || die "$DOMAIN 인증서가 ${n}개 (검증 중/발급됨) → 어느 걸 쓸지 모호해서 멈춤. 콘솔 ACM 확인"
  CERT_ARN=$certs; CERT_STATUS=""
  log "확인: web-1 running, 호스팅 영역 1개, 기존 인증서 ${n}개, 이어서 쓰기: 대상 그룹 $( ((REUSE_TG)) && echo 예 || echo 아니오), ALB $( ((REUSE_ALB)) && echo 예 || echo 아니오)"
fi

# ── 1. ACM 인증서 ─────────────────────────────────────
log "1/5 ACM 인증서 ($DOMAIN, DNS 검증)"
if [[ -n $CERT_ARN ]]; then
  log "기존 인증서 재사용: $CERT_ARN"
else
  CERT_ARN=$(aws_new "arn:aws:acm:$AWS_REGION:000000000000:certificate/DRYRUN" acm request-certificate \
    --domain-name "$DOMAIN" --validation-method DNS --idempotency-token havenalb \
    --tags $(elb_tags haven-cert) --query CertificateArn --output text) \
    || die "인증서 요청 실패 → acm:RequestCertificate·AddTagsToCertificate 권한 확인"
fi
[[ $CERT_ARN == arn:aws:acm:* ]] || die "인증서 ARN이 이상함: '$CERT_ARN'"
remember CERT_ARN

if [[ $DRY_RUN == 0 ]]; then
  CERT_STATUS=$(aws --region "$AWS_REGION" acm describe-certificate --certificate-arn "$CERT_ARN" \
    --query Certificate.Status --output text)
fi
if [[ $DRY_RUN == 1 || $CERT_STATUS != ISSUED ]]; then
  # 검증 레코드 값은 요청 직후 몇 초 뒤에 나온다
  if [[ $DRY_RUN == 1 ]]; then
    rec_name="_DRYRUN.$DOMAIN."; rec_value="_DRYRUN.acm-validations.aws."
  else
    for ((i = 1; ; i++)); do
      read -r rec_name rec_value < <(aws --region "$AWS_REGION" acm describe-certificate --certificate-arn "$CERT_ARN" \
        --query 'Certificate.DomainValidationOptions[0].ResourceRecord.[Name,Value]' --output text) || true
      [[ -n ${rec_name:-} && $rec_name != None && -n ${rec_value:-} && $rec_value != None ]] && break
      (( i < REC_WAIT_MAX )) || die "인증서 검증 레코드 값이 안 나옴 → 잠시 뒤 다시 실행 (인증서는 재사용됨)"
      sleep "$REC_WAIT_SEC"
    done
    [[ $rec_name == *".$DOMAIN." ]] || die "검증 레코드 이름이 도메인 밖: $rec_name (멈춤)"
  fi
  r53_upsert "{\"Changes\":[{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$rec_name\",\"Type\":\"CNAME\",\"TTL\":300,\"ResourceRecords\":[{\"Value\":\"$rec_value\"}]}}]}" \
    "ACM 검증 CNAME"

  if [[ $DRY_RUN == 0 ]]; then
    log "인증서 발급 대기 (최대 $((CERT_WAIT_MAX * CERT_WAIT_SEC / 60))분, 네임서버 연결돼 있으면 보통 몇 분)"
    for ((i = 1; ; i++)); do
      CERT_STATUS=$(aws --region "$AWS_REGION" acm describe-certificate --certificate-arn "$CERT_ARN" \
        --query Certificate.Status --output text)
      case $CERT_STATUS in
        ISSUED) break ;;
        PENDING_VALIDATION) ;;
        *) die "인증서 상태가 $CERT_STATUS → 콘솔 ACM에서 실패 이유 확인 (새로 요청해야 할 수 있음, 민수와 상의)" ;;
      esac
      (( i < CERT_WAIT_MAX )) || die "인증서가 아직 검증 중 → 몇 분 뒤 같은 명령으로 다시 실행 (인증서는 재사용, ALB는 아직 안 만듦)"
      sleep "$CERT_WAIT_SEC"
    done
  fi
fi
[[ $DRY_RUN == 1 ]] || log "인증서 발급됨"

# ── 2. 대상 그룹 + web-1 등록 ─────────────────────────
log "2/5 대상 그룹 $TG_NAME (web-1:80, 상태 검사 $HEALTH_PATH)"
if (( REUSE_TG )); then
  log "이전 실행에서 만든 대상 그룹 재사용: $TG_ARN"
else
TG_ARN=$(aws_new "arn:aws:elasticloadbalancing:DRYRUN:targetgroup/$TG_NAME" elbv2 create-target-group \
  --name "$TG_NAME" --protocol HTTP --port 80 --vpc-id "$VPC_ID" --target-type instance \
  --health-check-protocol HTTP --health-check-port traffic-port --health-check-path "$HEALTH_PATH" \
  --matcher HttpCode=200 --health-check-interval-seconds 15 \
  --healthy-threshold-count 2 --unhealthy-threshold-count 3 \
  --tags $(elb_tags "$TG_NAME") --query 'TargetGroups[0].TargetGroupArn' --output text) \
  || die "대상 그룹 생성 실패 → elasticloadbalancing:CreateTargetGroup·AddTags 권한 확인"
remember TG_ARN
fi
# 등록은 다시 해도 같은 결과 (이미 등록돼 있으면 그대로)
aws_do elbv2 register-targets --target-group-arn "$TG_ARN" --targets "Id=$WEB_ID,Port=80" \
  || die "web-1 등록 실패 → elasticloadbalancing:RegisterTargets 권한 확인"

# ── 3. ALB ────────────────────────────────────────────
log "3/5 ALB $ALB_NAME (인터넷용, public-a/b, sg-alb)"
if (( REUSE_ALB )); then
  log "이전 실행에서 만든 ALB 재사용: $ALB_ARN"
else
out=$(aws_new "arn:aws:elasticloadbalancing:DRYRUN:loadbalancer/app/$ALB_NAME	$ALB_NAME-DRYRUN.$AWS_REGION.elb.amazonaws.com	Z-DRYRUN-ALB" \
  elbv2 create-load-balancer --name "$ALB_NAME" --type application --scheme internet-facing \
  --ip-address-type ipv4 --subnets "$SUBNET_PUBLIC_A" "$SUBNET_PUBLIC_B" --security-groups "$SG_ALB" \
  --tags $(elb_tags "$ALB_NAME") \
  --query 'LoadBalancers[0].[LoadBalancerArn,DNSName,CanonicalHostedZoneId]' --output text) \
  || die "ALB 생성 실패 → elasticloadbalancing:CreateLoadBalancer, ELB가 내부에서 부르는 ec2:GetSecurityGroupsForVpc·ec2:Describe*, 서비스 연결 역할(iam:CreateServiceLinkedRole) 권한 확인. 권한 받은 뒤 같은 명령으로 다시 실행하면 이어서 함"
IFS=$'\t' read -r ALB_ARN ALB_DNS ALB_ZONE <<< "$out"
[[ ${ALB_ARN:-} == arn:aws:elasticloadbalancing:* && -n ${ALB_DNS:-} && -n ${ALB_ZONE:-} ]] \
  || die "ALB 생성 결과가 이상함: '$out'"
remember ALB_ARN; remember ALB_DNS; remember ALB_ZONE
fi
# 속성 변경·대기는 다시 해도 같은 결과
aws_do elbv2 modify-load-balancer-attributes --load-balancer-arn "$ALB_ARN" \
  --attributes Key=routing.http.drop_invalid_header_fields.enabled,Value=true \
  || die "ALB 속성 변경 실패 → elasticloadbalancing:ModifyLoadBalancerAttributes 권한 확인"
aws_do elbv2 wait load-balancer-available --load-balancer-arns "$ALB_ARN" || die "ALB가 active가 안 됨 (콘솔 확인)"

# ── 4. 리스너 ─────────────────────────────────────────
log "4/5 리스너: 443 HTTPS → $TG_NAME, 80 → 443 (301)"
if (( REUSE_ALB )); then   # 이전 실행에서 리스너까지 만들었는지
  for port in 443 80; do
    x=$(aws --region "$AWS_REGION" elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
      --query "Listeners[?Port==\`$port\`].ListenerArn" --output text) \
      || die "리스너 조회 실패 → elasticloadbalancing:DescribeListeners 권한 확인"
    [[ -z $x || $x == None ]] && continue
    v=LISTENER_HTTPS; [[ $port == 80 ]] && v=LISTENER_HTTP
    [[ $x == "$(prev $v)" ]] || die "$port 리스너가 이미 있는데 이 스크립트 기록과 다름: $x (멈춤, 민수 확인)"
    printf -v "$v" '%s' "$x"; log "이전 실행에서 만든 $port 리스너 재사용"
  done
fi
if [[ -z $LISTENER_HTTPS ]]; then
LISTENER_HTTPS=$(aws_new "arn:aws:elasticloadbalancing:DRYRUN:listener/443" elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" --protocol HTTPS --port 443 \
  --certificates "CertificateArn=$CERT_ARN" --ssl-policy "$SSL_POLICY" \
  --default-actions "Type=forward,TargetGroupArn=$TG_ARN" \
  --tags $(elb_tags haven-listener-443) --query 'Listeners[0].ListenerArn' --output text) \
  || die "443 리스너 생성 실패 → elasticloadbalancing:CreateListener 권한, 인증서 상태 확인"
remember LISTENER_HTTPS
fi
if [[ -z $LISTENER_HTTP ]]; then
LISTENER_HTTP=$(aws_new "arn:aws:elasticloadbalancing:DRYRUN:listener/80" elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 \
  --default-actions 'Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}' \
  --tags $(elb_tags haven-listener-80) --query 'Listeners[0].ListenerArn' --output text) \
  || die "80 리스너 생성 실패 → elasticloadbalancing:CreateListener 권한 확인"
remember LISTENER_HTTP
fi

# ── 5. Route 53 apex → ALB ────────────────────────────
log "5/5 Route 53: $DOMAIN A Alias → ALB"
r53_upsert "{\"Changes\":[{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$DOMAIN.\",\"Type\":\"A\",\"AliasTarget\":{\"HostedZoneId\":\"$ALB_ZONE\",\"DNSName\":\"dualstack.$ALB_DNS.\",\"EvaluateTargetHealth\":false}}}]}" \
  "apex A Alias → ALB"

if [[ $DRY_RUN == 1 ]]; then
  log "DRY-RUN 끝: 실제로 만든 것 없음"
  exit 0
fi

# ── 6. 확인 ───────────────────────────────────────────
log "확인 1: web-1 상태 검사 healthy 대기 (최대 $((HEALTH_WAIT_MAX * HEALTH_WAIT_SEC / 60))분)"
for ((i = 1; ; i++)); do
  IFS=$'\t' read -r h_state h_reason < <(aws --region "$AWS_REGION" elbv2 describe-target-health \
    --target-group-arn "$TG_ARN" \
    --query 'TargetHealthDescriptions[0].TargetHealth.[State,Reason]' --output text) || true
  [[ ${h_state:-} == healthy ]] && break
  (( i < HEALTH_WAIT_MAX )) || die "web-1이 healthy가 안 됨 (상태 ${h_state:-없음}, 이유 ${h_reason:-없음}, 조회 권한 DescribeTargetHealth도 확인) → web-1에서 'systemctl is-active haven nginx'·healthz curl, sg-alb→sg-web 80 확인. ALB는 남겨 둠"
  sleep "$HEALTH_WAIT_SEC"
done
log "web-1 healthy"

# curl 결과는 변수로 받고 마지막 줄만 쓴다. -o /dev/null 은 쓰지 않는다:
#   Windows Git Bash의 curl은 Windows 프로그램이라 /dev/null을 모르고, config.sh가 경로 변환도 꺼 둬서
#   "(23) ERROR on write"로 실패한다 (11/11 실제 실행에서 NET-01-b가 이걸로 멈춤)
# DNS 전파와 상관없이 ALB 자체를 시험: 도메인 이름(SNI·인증서 검사)은 그대로, 연결만 ALB 주소로
log "확인 2: NET-01 https://$DOMAIN$HEALTH_PATH (ALB로 직접 연결)"
res=$(curl -sS --max-time 15 -w '\n%{http_code}' --connect-to "$DOMAIN:443:$ALB_DNS:443" \
  "https://$DOMAIN$HEALTH_PATH" 2>&1) || die "NET-01 실패: https 연결 오류 → $res"
code=${res##*$'\n'}; body=${res%$'\n'*}; body=${body//$'\r'/}
[[ $code == 200 && $body == ok ]] || die "NET-01 실패: 응답 $code '$body' (기대 200 ok)"
log "NET-01 OK: 200 ok, 인증서 검사 통과"

log "확인 3: NET-01-b http://$DOMAIN/ → https 리다이렉트"
res=$(curl -sS --max-time 15 -w '\n%{http_code} %{redirect_url}' \
  --connect-to "$DOMAIN:80:$ALB_DNS:80" "http://$DOMAIN/" 2>&1) || die "NET-01-b 실패: http 연결 오류 → $res"
res=${res//$'\r'/}; res=${res##*$'\n'}   # 마지막 줄 = "코드 리다이렉트주소"
loc=${res#* }
# 도메인 뒤는 끝, ':포트', '/경로'만 인정 (https://orchestration-haven.cloud.evil.com 같은 주소 통과 방지)
[[ ${res%% *} == 301 && ( $loc == "https://$DOMAIN" || $loc == "https://$DOMAIN:"* || $loc == "https://$DOMAIN/"* ) ]] \
  || die "NET-01-b 실패: '$res' (기대 301 https://$DOMAIN...)"
log "NET-01-b OK: $res"

log "확인 4: 실제 DNS로 접속 (전파 전이면 실패할 수 있음, 경고만)"
code=$(curl -sS --max-time 15 -w '\n%{http_code}' "https://$DOMAIN$HEALTH_PATH" 2>&1) || code=""
code=${code//$'\r'/}; code=${code##*$'\n'}
if [[ $code == 200 ]]; then
  log "DNS OK: https://$DOMAIN 접속됨"
else
  log "주의: DNS로는 아직 안 됨(${code:-연결 실패}) → 몇 분 뒤 curl -I https://$DOMAIN 다시 확인 (DNS 전파 대기)"
fi

log "build-alb 완료: $ALB_NAME → $TG_NAME(web-1), https://$DOMAIN"
log "기록: $STATE_FILE · 다음: 연결확인표 NET-01, NET-01-b / 밤에 EC2를 끄면 ALB는 502·503을 낸다 (정상)"
