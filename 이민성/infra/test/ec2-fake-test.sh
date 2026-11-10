#!/usr/bin/env bash
# EC2 중지·시작 스크립트 가짜 시험 (진짜 AWS에 아무것도 보내지 않음)
#   - 가짜 aws 명령을 만들어 PATH 맨 앞에 둔다 → 스크립트가 진짜 aws 대신 가짜를 부른다
#   - 스크립트를 임시 폴더에 복사해서 돌린다 → 진짜 state/ 파일을 읽거나 지우지 않는다
#   - 진짜 AWS 로그인 정보도 막는다 (혹시 가짜가 안 잡혀도 진짜 AWS에 못 붙음)
#
# 사용 (Git Bash, 이민성/infra 에서)
#   bash test/ec2-fake-test.sh
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ── 준비: 스크립트 복사 + 안전장치 ────────────────────
mkdir -p "$WORK/infra" "$WORK/bin" "$WORK/st"
cp "$SRC"/*.sh "$WORK/infra/"
grep -q 'find_server()' "$WORK/infra/common.sh" || { echo "common.sh에 find_server가 없음 (붙여 넣기 확인)"; exit 1; }
export AWS_CONFIG_FILE="$WORK/none" AWS_SHARED_CREDENTIALS_FILE="$WORK/none"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
export FK="$WORK"

# ── 가짜 aws: 서버 상태를 $FK/st/<ID> 파일에 저장 ─────
cat > "$WORK/bin/aws" <<'EOF'
#!/usr/bin/env bash
args="$*"; echo "aws $args" >> "$FK/calls"
idof() { local x=${args#*--instance-ids }; echo "${x%% *}"; }
case "$args" in
  *"get-caller-identity --query Arn"*)     echo "arn:aws:iam::111122223333:user/minsung" ;;
  *"get-caller-identity --query Account"*) echo 111122223333 ;;
  *"Name=tag:Name,Values=web-1"*)          cat "$FK/web_ids" ;;
  *"Name=tag:Name,Values=db-1"*)           cat "$FK/db_ids" ;;
  *"describe-instances --filters Name=tag:Project"*) cat "$FK/others" 2>/dev/null || true ;;
  *"State.Name"*)        cat "$FK/st/$(idof)" ;;
  *"stop-instances"*)    echo stopping > "$FK/st/$(idof)" ;;
  *"start-instances"*)   echo pending  > "$FK/st/$(idof)" ;;
  *"wait instance-stopped"*) [[ -f $FK/stuck ]] && exit 255; echo stopped > "$FK/st/$(idof)" ;;
  *"wait instance-running"*) echo running > "$FK/st/$(idof)" ;;
  *PublicIpAddress*)     cat "$FK/pub" 2>/dev/null || echo None ;;
  *PrivateIpAddress*)    printf 'web-1\t10.20.10.11\ndb-1\t10.20.20.22\n' ;;
  *"describe-instance-information"*)
    if [[ -f $FK/ssmdeny ]]; then echo "AccessDeniedException (가짜)" >&2; exit 254; fi
    echo "i-web i-db" ;;
  *"describe-nat-gateways --nat-gateway-ids"*) echo deleted ;;
  *"describe-nat-gateways"*) cat "$FK/nat" 2>/dev/null || true ;;
  *"delete-nat-gateway"*)    rm -f "$FK/nat" ;;
  *"describe-addresses"*)    : ;;
  *) echo "가짜 aws: 모르는 명령 $args" >&2; exit 99 ;;
esac
EOF
# 가짜 date: 시·요일만 FH/FU로 바꿈 (morning 시간 시험용)
cat > "$WORK/bin/date" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in +%H) echo "${FH:-10}" ;; +%u) echo "${FU:-2}" ;; *) /usr/bin/date "$@" ;; esac
EOF
chmod +x "$WORK/bin/aws" "$WORK/bin/date"
export PATH="$WORK/bin:$PATH"
[[ $(command -v aws) == "$WORK/bin/aws" ]] || { echo "가짜 aws가 안 잡힘 → 시험 중단"; exit 1; }

# ── 시험 도구 ─────────────────────────────────────────
pass=0; fail=0
setup() {  # setup <web 상태> <db 상태>
  rm -f "$FK"/{stuck,ssmdeny,pub,nat,others,calls}; rm -rf "$FK/st" "$WORK/infra/state"; mkdir -p "$FK/st"
  echo i-web > "$FK/web_ids"; echo i-db > "$FK/db_ids"
  echo "$1" > "$FK/st/i-web"; echo "$2" > "$FK/st/i-db"
}
# check <번호·이름> <스크립트> <기대 exit> <기대 web> <기대 db> [로그에 있어야 할 글자]
check() {
  local name=$1 script=$2 want_exit=$3 want_web=$4 want_db=$5 want_text=${6:-} out code ok=1 why=""
  out=$(cd "$WORK/infra" && EXPECTED_ACCOUNT_ID=111122223333 bash "$script" 2>&1); code=$?
  [[ $code == "$want_exit" ]] || { ok=0; why+=" exit=$code(기대 $want_exit)"; }
  [[ $(cat "$FK/st/i-web") == "$want_web" ]] || { ok=0; why+=" web=$(cat "$FK/st/i-web")(기대 $want_web)"; }
  [[ $(cat "$FK/st/i-db")  == "$want_db"  ]] || { ok=0; why+=" db=$(cat "$FK/st/i-db")(기대 $want_db)"; }
  [[ -z $want_text || $out == *"$want_text"* ]] || { ok=0; why+=" 로그에 '$want_text' 없음"; }
  if (( ok )); then pass=$((pass+1)); printf 'PASS  %s\n' "$name"
  else fail=$((fail+1)); printf 'FAIL  %s →%s\n' "$name" "$why"; printf '%s\n' "$out" | sed 's/^/      | /'; fi
}

echo "── ec2-stop ──"
setup running running;  check "S1 둘 다 켜짐 → 둘 다 중지"       ec2-stop.sh 0 stopped stopped "ec2-stop 완료"
setup stopped stopped;  check "S2 이미 꺼짐 → 아무것도 안 함"     ec2-stop.sh 0 stopped stopped "이미 중지됨"
setup pending stopping; check "S3 켜지는 중/꺼지는 중 → 기다려 중지" ec2-stop.sh 0 stopped stopped "running 된 뒤 중지"
setup running running;  : > "$FK/db_ids"
                        check "S4 db-1 없음 → 하나도 안 끔"       ec2-stop.sh 1 running running "0대"
setup running running;  echo "i-db i-db2" > "$FK/db_ids"
                        check "S5 db-1 2대 → 하나도 안 끔"        ec2-stop.sh 1 running running "2대"
setup running running;  mkdir -p "$WORK/infra/state"; echo 'WEB_ID=i-OLD' > "$WORK/infra/state/ap-northeast-2.env"
                        check "S6 state 파일 ID와 다름 → 멈춤"     ec2-stop.sh 1 running running "state 파일"
setup running running;  touch "$FK/stuck"
                        check "S7 10분 안에 안 꺼짐 → 멈춤"        ec2-stop.sh 1 stopping running "안 꺼짐"

echo "── ec2-start ──"
setup stopped stopped;  check "T1 둘 다 꺼짐 → 둘 다 시작"        ec2-start.sh 0 running running "SSM Online 2대"
setup running running;  check "T2 이미 켜짐 → 아무것도 안 함"     ec2-start.sh 0 running running "이미 켜짐"
setup stopping stopped; check "T3 꺼지는 중 → 다 꺼진 뒤 시작"     ec2-start.sh 0 running running "다 꺼진 뒤 시작"
setup stopped stopped;  echo 3.3.3.3 > "$FK/pub"
                        check "T4 공인 IP 붙음 → 멈춤"            ec2-start.sh 1 running running "공인 IP"
setup stopped stopped;  touch "$FK/ssmdeny"
                        check "T5 SSM 권한 없음 → 경고만"         ec2-start.sh 0 running running "SSM 상태 조회 실패"

echo "── night / morning ──"
setup running running;  echo nat-1 > "$FK/nat"
                        check "N1 정상 → EC2 중지 + NAT 삭제"     night.sh 0 stopped stopped "night 완료"
setup running running;  echo nat-1 > "$FK/nat"; touch "$FK/stuck"; printf 'i-test\thaven-test\n' > "$FK/others"
                        check "N2 EC2 중지 실패 → NAT는 끄고 실패 알림" night.sh 1 stopping running "시험용이면"
[[ ! -f $FK/nat ]] && { pass=$((pass+1)); echo "PASS  N2-b 그때도 NAT는 삭제됨"; } || { fail=$((fail+1)); echo "FAIL  N2-b NAT가 남음"; }
setup stopped stopped;  echo nat-1 > "$FK/nat"
                        check "M1 NAT 이미 켜짐 → nat-up 건너뛰고 EC2 시작" morning.sh 0 running running "nat-up 건너뜀"
setup stopped stopped;  check "M2 nat-up 실패 → EC2 안 켬"        morning.sh 1 stopped stopped "EC2는 켜지 않음"
setup stopped stopped;  FH=22 FU=2 check "M3 화 22시 → 멈춤"       morning.sh 1 stopped stopped "평일 09~21시"
setup stopped stopped;  FH=10 FU=6 check "M4 토요일 → 멈춤"        morning.sh 1 stopped stopped "평일 09~21시"
setup stopped stopped;  FH=8  FU=2 check "M5 화 08시 → 멈춤"       morning.sh 1 stopped stopped "평일 09~21시"

echo
echo "결과: PASS $pass / FAIL $fail"
(( fail == 0 ))
