#!/usr/bin/env bash
# build-alb.sh 가짜 시험 (진짜 AWS·인터넷에 아무것도 보내지 않음)
#   - 가짜 aws·curl을 PATH 맨 앞에 둔다 → 스크립트가 진짜 대신 가짜를 부른다
#   - 스크립트를 임시 폴더에 복사하고 가짜 state 파일을 만든다 → 진짜 state/ 를 건드리지 않는다
#   - 진짜 AWS 로그인 정보도 막는다 (가짜가 안 잡혀도 진짜 AWS에 못 붙음)
#   - 상황은 $FK 아래 파일로 바꾼다 (예: alb_exists 파일이 있으면 "ALB가 이미 있음")
#   - 가짜 aws는 만든 것을 기억한다 (대상 그룹·ALB·리스너·A 레코드) → "중간 실패 뒤 다시 실행"을 재현
#
# 사용 (Git Bash, 이민성/infra 에서)
#   bash test/alb-fake-test.sh
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ── 준비: 스크립트 복사 + 안전장치 ────────────────────
mkdir -p "$WORK/infra" "$WORK/bin"
cp "$SRC"/*.sh "$WORK/infra/"
[[ -f $WORK/infra/build-alb.sh ]] || { echo "build-alb.sh가 없음 (infra 폴더 확인)"; exit 1; }
export AWS_CONFIG_FILE="$WORK/none" AWS_SHARED_CREDENTIALS_FILE="$WORK/none"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
export FK="$WORK/fk"

# ── 가짜 aws ──────────────────────────────────────────
cat > "$WORK/bin/aws" <<'EOF'
#!/usr/bin/env bash
args="$*"; echo "aws $args" >> "$FK/calls"
deny() { echo "An error occurred (AccessDenied) (가짜): $1" >&2; exit 254; }
main() {
case "$args" in
  *"get-caller-identity --query Arn"*)     echo "arn:aws:iam::111122223333:user/minsung" ;;
  *"get-caller-identity --query Account"*) echo 111122223333 ;;
  *"Name=tag:Name,Values=web-1"*)          echo i-web ;;
  *"State.Name"*)                          cat "$FK/web_state" ;;
  *"list-hosted-zones-by-name"*)           cat "$FK/zones" ;;
  *"list-resource-record-sets"*"AliasTarget.DNSName"*) cat "$FK/apex_alias" 2>/dev/null || true ;;
  *"list-resource-record-sets"*)           cat "$FK/apex_a" ;;
  *"describe-load-balancers"*)   [[ -f $FK/deny_elb ]] && deny DescribeLoadBalancers; cat "$FK/alb_exists" 2>/dev/null || true ;;
  *"describe-target-groups"*)    cat "$FK/tg_exists" 2>/dev/null || true ;;
  *"list-certificates"*)         cat "$FK/certs" 2>/dev/null || true ;;
  *"request-certificate"*)       touch "$FK/requested"; echo "arn:aws:acm:ap-northeast-2:111122223333:certificate/new" | tee "$FK/certs" ;;
  *"describe-certificate"*"Certificate.Status"*)
    if   [[ -f $FK/cert_failed ]]; then echo FAILED
    elif [[ -f $FK/cert_issued ]]; then echo ISSUED
    elif [[ -f $FK/cname && ! -f $FK/cert_never ]]; then echo ISSUED
    else echo PENDING_VALIDATION; fi ;;
  *"describe-certificate"*"ResourceRecord"*)
    # 첫 조회는 아직 값이 없음 (실제 ACM처럼), 두 번째부터 나옴
    if [[ ! -f $FK/rr_once ]]; then touch "$FK/rr_once"; printf 'None\tNone\n'
    else printf '_abc.orchestration-haven.cloud.\t_xyz.acm-validations.aws.\n'; fi ;;
  *"change-resource-record-sets"*)
    [[ $args == *'"Type":"CNAME"'* ]] && touch "$FK/cname"
    if [[ $args == *'"Type":"A"'* ]]; then touch "$FK/apexset"; echo 1 > "$FK/apex_a"
      x=${args#*\"DNSName\":\"}; echo "${x%%\"*}" > "$FK/apex_alias"; fi
    echo /change/C1 ;;
  *"route53 wait"*)              : ;;
  *"create-target-group"*)       echo "arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:targetgroup/haven-tg-web/t" | tee "$FK/tg_exists" ;;
  *"register-targets"*)          : ;;
  *"create-load-balancer"*)
    [[ -f $FK/deny_create_alb ]] && deny "ec2:GetSecurityGroupsForVpc"
    touch "$FK/alb_created"
    printf 'arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:loadbalancer/app/haven-alb/x\thaven-alb-1.ap-northeast-2.elb.amazonaws.com\tZALB\n' | tee "$FK/alb_exists" ;;
  *"describe-listeners"*"Port==\`443\`"*) cat "$FK/l443" 2>/dev/null || true ;;
  *"describe-listeners"*"Port==\`80\`"*)  cat "$FK/l80" 2>/dev/null || true ;;
  *"modify-load-balancer-attributes"*) : ;;
  *"wait load-balancer-available"*)    : ;;
  *"create-listener"*"--port 443"*) [[ -f $FK/deny_listener ]] && deny "CreateListener"
                                    echo "arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:listener/app/haven-alb/x/443" | tee "$FK/l443" ;;
  *"create-listener"*"--port 80"*)  echo "arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:listener/app/haven-alb/x/80" | tee "$FK/l80" ;;
  *"describe-target-health"*)    cat "$FK/health" ;;
  *) echo "가짜 aws: 모르는 명령 $args" >&2; exit 99 ;;
esac
}
# crlf 파일이 있으면 Windows aws.exe처럼 줄 끝에 \r을 붙인다
if [[ -f $FK/crlf ]]; then main | sed 's/$/\r/'; exit "${PIPESTATUS[0]}"; else main; fi
EOF

# ── 가짜 curl: --connect-to 로 443/80, 없으면 실제 DNS 접속 ──
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
args="$*"; echo "curl $args" >> "$FK/calls"
# Windows Git Bash의 curl처럼 /dev/null 에 못 씀 (11/11 실제 실행에서 발견한 문제 재현)
[[ $args == */dev/null* ]] && { echo "curl: (23) client returned ERROR on write (가짜: Windows는 /dev/null 모름)" >&2; exit 23; }
# 실제 curl처럼 본문 뒤에 -w 내용을 붙인다
case "$args" in
  *":443:haven-alb"*) [[ -f $FK/curl_https_fail ]] && { echo "curl: (35) TLS 오류 (가짜)" >&2; exit 35; }
                      cat "$FK/curl_https" ;;
  *":80:haven-alb"*)  printf '<html>301 Moved Permanently</html>\n'; cat "$FK/curl_http" ;;
  *)                  [[ -f $FK/dns_fail ]] && { echo "curl: (6) Could not resolve host (가짜)" >&2; exit 6; }
                      printf 'ok\n200' ;;
esac
EOF
chmod +x "$WORK/bin/aws" "$WORK/bin/curl"
export PATH="$WORK/bin:$PATH"
[[ $(command -v aws) == "$WORK/bin/aws" && $(command -v curl) == "$WORK/bin/curl" ]] \
  || { echo "가짜 aws/curl이 안 잡힘 → 시험 중단"; exit 1; }

# ── 시험 도구 ─────────────────────────────────────────
pass=0; fail=0
setup() {  # 기본값 = 모든 게 정상인 상황
  rm -rf "$FK" "$WORK/infra/state"; mkdir -p "$FK" "$WORK/infra/state"
  cat > "$WORK/infra/state/ap-northeast-2.env" <<'S'
VPC_ID=vpc-1
SUBNET_PUBLIC_A=subnet-pa
SUBNET_PUBLIC_B=subnet-pb
SG_ALB=sg-alb
SG_WEB=sg-web
WEB_ID=i-web
S
  echo running > "$FK/web_state"
  echo /hostedzone/ZTEST > "$FK/zones"
  echo 0 > "$FK/apex_a"
  printf 'healthy\tNone\n' > "$FK/health"
  printf 'ok\n200' > "$FK/curl_https"
  echo "301 https://orchestration-haven.cloud:443/" > "$FK/curl_http"
}
has() { grep -q -- "$1" "$FK/calls" 2>/dev/null; }
ok()  { pass=$((pass+1)); printf 'PASS  %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL  %s → %s\n' "$1" "$2"; [[ -n ${3:-} ]] && printf '%s\n' "$3" | sed 's/^/      | /'; }
# check <이름> <기대 exit> <로그에 있어야 할 글자> <ALB 생성 기대 yes/no> [환경변수...]
check() {
  local name=$1 want_exit=$2 want_text=$3 want_alb=$4; shift 4
  local out code why=""
  out=$(cd "$WORK/infra" && env EXPECTED_ACCOUNT_ID=111122223333 \
        CERT_WAIT_SEC=0 REC_WAIT_SEC=0 HEALTH_WAIT_SEC=0 CERT_WAIT_MAX=3 HEALTH_WAIT_MAX=3 "$@" \
        bash build-alb.sh 2>&1); code=$?
  [[ $code == "$want_exit" ]] || why+=" exit=$code(기대 $want_exit)"
  [[ $out == *"$want_text"* ]] || why+=" 로그에 '$want_text' 없음"
  if [[ $want_alb == yes ]]; then [[ -f $FK/alb_created ]] || why+=" ALB가 안 만들어짐"
  else [[ ! -f $FK/alb_created ]] || why+=" ALB가 만들어지면 안 됨"; fi
  if [[ -z $why ]]; then ok "$name"; else bad "$name" "$why" "$out"; fi
}

echo "── 정상 ──"
setup; check "A1 정상 → 끝까지 만들고 NET-01·01-b OK" 0 "build-alb 완료" yes
has request-certificate && ok "A1-b 인증서 새로 요청함" || bad "A1-b" "request-certificate 호출 없음"
[[ -f $FK/cname && -f $FK/apexset ]] && ok "A1-c 검증 CNAME·apex A 둘 다 기록" || bad "A1-c" "Route 53 기록 빠짐"
has 'drop_invalid_header_fields.enabled,Value=true' && ok "A1-d 잘못된 헤더 차단 켬" || bad "A1-d" "속성 변경 없음"
has 'StatusCode=HTTP_301' && ok "A1-e 80 리스너는 301 리다이렉트" || bad "A1-e" "리다이렉트 설정 없음"
has 'ELBSecurityPolicy-TLS13-1-2' && ok "A1-f TLS 1.2 이상 정책" || bad "A1-f" "SSL 정책 없음"
grep -q '^ALB_ARN=' "$WORK/infra/state/ap-northeast-2-alb.env" && ! grep -q '^ALB_ARN=' "$WORK/infra/state/ap-northeast-2.env" \
  && ok "A1-g ID는 alb 전용 state에만 기록" || bad "A1-g" "state 기록 위치 이상"

echo "── 시작 전 확인에서 멈춤 (아무것도 안 만듦) ──"
setup; echo "arn:...:loadbalancer/app/haven-alb/old" > "$FK/alb_exists"
       check "B1 ALB 이미 있음(이 스크립트 기록에 없음) → 멈춤" 1 "기록과 다름" no
has request-certificate && bad "B1-b" "멈춰야 하는데 인증서를 요청함" || ok "B1-b 인증서도 요청 안 함"
setup; echo "arn:...:targetgroup/haven-tg-web/old" > "$FK/tg_exists"
       check "B2 대상 그룹 이미 있음(이 스크립트 기록에 없음) → 멈춤" 1 "기록과 다름" no
setup; echo stopped > "$FK/web_state"
       check "B3 web-1 꺼짐 → 멈춤" 1 "running이 아님" no
setup; : > "$FK/zones"
       check "B4 호스팅 영역 0개 → 멈춤" 1 "0개" no
setup; echo "/hostedzone/Z1 /hostedzone/Z2" > "$FK/zones"
       check "B5 호스팅 영역 2개 → 멈춤" 1 "2개" no
setup; echo 1 > "$FK/apex_a"
       check "B6 도메인에 A 레코드 이미 있음 → 덮어쓰지 않음" 1 "덮어쓰지 않도록" no
setup; touch "$FK/deny_elb"
       check "B7 ELB 읽기 권한 없음 → 권한 안내하고 멈춤" 1 "DescribeLoadBalancers 권한" no
setup; printf 'arn:aws:acm:ap-northeast-2:111122223333:certificate/a\tarn:aws:acm:ap-northeast-2:111122223333:certificate/b\n' > "$FK/certs"
       check "B8 같은 도메인 인증서 2개 → 모호해서 멈춤" 1 "2개" no
setup; check "B9 도메인 형식 이상(대문자·끝 점) → 멈춤" 1 "형식이 이상" no DOMAIN=Orchestration-Haven.cloud.
setup; check "B10 이름이 haven- 아님 → 멈춤" 1 "haven- 으로" no ALB_NAME=my-alb
[[ ! -f $FK/calls ]] && ok "B10-b 이름 검사는 AWS 부르기 전에 함" || bad "B10-b" "AWS를 불렀음"

echo "── 인증서 ──"
setup; touch "$FK/cert_never"
       check "C1 인증서 검증 시간 초과 → 다시 실행 안내, ALB 안 만듦" 1 "다시 실행" no
grep -q '^CERT_ARN=' "$WORK/infra/state/ap-northeast-2-alb.env" && ok "C1-b 인증서 ARN은 기록됨" || bad "C1-b" "CERT_ARN 기록 없음"
setup; echo "arn:aws:acm:ap-northeast-2:111122223333:certificate/old" > "$FK/certs"
       check "C2 다시 실행: 기존 인증서 재사용" 0 "기존 인증서 재사용" yes
has request-certificate && bad "C2-b" "재사용해야 하는데 새로 요청함" || ok "C2-b 새 인증서 요청 안 함"
setup; echo "arn:aws:acm:ap-northeast-2:111122223333:certificate/old" > "$FK/certs"; touch "$FK/cert_issued"
       check "C3 이미 발급된 인증서 → 검증 CNAME 건너뜀" 0 "build-alb 완료" yes
[[ ! -f $FK/cname ]] && ok "C3-b CNAME 다시 안 씀" || bad "C3-b" "발급된 인증서인데 CNAME을 씀"
setup; touch "$FK/cert_failed"
       check "C4 인증서 상태 FAILED → 멈춤" 1 "FAILED" no

echo "── 확인 단계 ──"
setup; printf 'unhealthy\tTarget.ResponseCodeMismatch\n' > "$FK/health"
       check "D1 web-1 unhealthy → 성공이라 하지 않고 이유 출력" 1 "ResponseCodeMismatch" yes
setup; touch "$FK/curl_https_fail"
       check "D2 https 연결 오류 → NET-01 실패" 1 "NET-01 실패" yes
setup; printf 'Bad Gateway\n502' > "$FK/curl_https"
       check "D3 https 502 → NET-01 실패" 1 "NET-01 실패" yes
setup; echo "200 " > "$FK/curl_http"
       check "D4 http가 리다이렉트 안 함 → NET-01-b 실패" 1 "NET-01-b 실패" yes
setup; echo "301 https://evil.example/" > "$FK/curl_http"
       check "D5 다른 주소로 리다이렉트 → NET-01-b 실패" 1 "NET-01-b 실패" yes
setup; echo "302 https://orchestration-haven.cloud:443/" > "$FK/curl_http"
       check "D7 301이 아닌 302 → NET-01-b 실패 (영구 리다이렉트만 인정)" 1 "NET-01-b 실패" yes
setup; echo "301 https://orchestration-haven.cloud.evil.example/" > "$FK/curl_http"
       check "D8 도메인 뒤에 다른 주소를 붙인 리다이렉트 → NET-01-b 실패" 1 "NET-01-b 실패" yes
setup; touch "$FK/dns_fail"
       check "D6 DNS 전파 전 → 경고만, 완료" 0 "DNS 전파 대기" yes

echo "── 중간 실패 뒤 다시 실행 (11/11 실제 상황) ──"
ALBENV="$WORK/infra/state/ap-northeast-2-alb.env"
setup; touch "$FK/deny_create_alb"
       check "F1 ALB 생성 권한 없음 → 대상 그룹까지 만들고 멈춤" 1 "GetSecurityGroupsForVpc" no
grep -q '^TG_ARN=' "$ALBENV" && ok "F1-b 대상 그룹 ID는 기록됨" || bad "F1-b" "TG_ARN 기록 없음"
rm -f "$FK/deny_create_alb" "$FK/calls"
       check "F2 권한 받은 뒤 같은 명령 다시 → 대상 그룹 재사용, ALB부터 이어서 완료" 0 "대상 그룹 재사용" yes
has create-target-group && bad "F2-b" "대상 그룹을 또 만듦" || ok "F2-b 대상 그룹 다시 안 만듦"
has request-certificate && bad "F2-c" "인증서를 또 요청함" || ok "F2-c 인증서도 재사용"
setup; touch "$FK/deny_listener"
       check "F3 443 리스너에서 실패 → 멈춤" 1 "443 리스너 생성 실패" yes
rm -f "$FK/deny_listener" "$FK/calls" "$FK/alb_created"
       check "F4 다시 실행 → ALB 재사용, 리스너부터 이어서 완료" 0 "ALB 재사용" no
has create-load-balancer && bad "F4-b" "ALB를 또 만듦" || ok "F4-b ALB 다시 안 만듦"
setup; check "F5 (준비) 끝까지 완료" 0 "build-alb 완료" yes
rm -f "$FK/calls" "$FK/alb_created"; printf 'unhealthy\tTarget.Timeout\n' > "$FK/health"
       check "F6 완료 뒤 다시 실행: 전부 재사용, A 레코드도 이 ALB라 통과, 확인 단계에서 unhealthy면 실패" 1 "이미 이 ALB를 가리킴" no
has 'create-' && bad "F6-b" "다시 실행인데 새로 만듦" || ok "F6-b 아무것도 새로 안 만듦"
setup; echo "arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:targetgroup/haven-tg-web/t" > "$FK/tg_exists"
       echo "TG_ARN=arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:targetgroup/haven-tg-web/OTHER" > "$ALBENV"
       check "F7 대상 그룹 ID가 기록과 다름 → 멈춤" 1 "기록과 다름" no
setup; check "F8 (준비) 끝까지 완료" 0 "build-alb 완료" yes
rm -f "$FK/tg_exists" "$FK/alb_created"
       check "F9 ALB는 있는데 대상 그룹이 사라짐 → 멈춤" 1 "상태가 이상" no
setup; check "F10 (준비) 끝까지 완료" 0 "build-alb 완료" yes
echo "dualstack.someone-else.ap-northeast-2.elb.amazonaws.com." > "$FK/apex_alias"; rm -f "$FK/alb_created"
       check "F11 A 레코드가 다른 ALB를 가리킴 → 덮어쓰지 않고 멈춤" 1 "덮어쓰지 않도록" no
setup; check "F12 (준비) 끝까지 완료" 0 "build-alb 완료" yes
echo "arn:aws:elasticloadbalancing:ap-northeast-2:111122223333:listener/app/haven-alb/x/OTHER" > "$FK/l443"; rm -f "$FK/alb_created"
       check "F13 443 리스너 ID가 기록과 다름 → 멈춤" 1 "기록과 다름" no

echo "── Windows curl ──"
setup; check "W1 /dev/null 을 모르는 curl에서도 NET-01-b 통과 (본문이 있어도 마지막 줄로 판단)" 0 "NET-01-b OK" yes
has 'curl.*/dev/null' && bad "W1-b" "curl에 /dev/null을 넘김" || ok "W1-b curl에 /dev/null 안 넘김"

echo "── 기타 ──"
setup; touch "$FK/crlf"
       check "E1 Windows CRLF 출력 → 오탐 없이 완료" 0 "build-alb 완료" yes
setup; rm -f "$WORK/infra/state/ap-northeast-2.env"
       check "E2 DRY_RUN=1 (state 없음) → 명령만 출력" 0 "DRY-RUN 끝" no DRY_RUN=1
has 'create-' && bad "E2-b" "DRY_RUN인데 생성 명령을 보냄" || ok "E2-b DRY_RUN은 AWS에 생성 명령 안 보냄"
setup; rm -f "$WORK/infra/state/ap-northeast-2.env"
       check "E3 state 파일 없음(실제 실행) → 멈춤" 1 "값이 비어 있음" no
setup; check "E4 DRY_RUN 값 이상 → 멈춤" 1 "0 또는 1" no DRY_RUN=yes

echo
echo "결과: PASS $pass / FAIL $fail"
(( fail == 0 ))
