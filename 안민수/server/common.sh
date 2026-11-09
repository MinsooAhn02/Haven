# 서버 스크립트 공통. 각 스크립트가 source 한다.
set -euo pipefail
die() { echo "FAIL: $*" >&2; exit 1; }
need() { [[ -n "${!1:-}" ]] || die "$1 is empty"; }
[[ $EUID -eq 0 ]] || die "run as root (sudo)"

PARAM_PREFIX="${PARAM_PREFIX:-/haven}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"

# 비밀값은 SSM Parameter Store(SecureString)에서만 읽는다. Git·명령 인자·로그에 남기지 않기 위해.
secret() {
  local v
  v=$(aws ssm get-parameter --region "$AWS_REGION" --with-decryption \
        --name "$PARAM_PREFIX/$1" --query Parameter.Value --output text) \
    || die "cannot read SSM $PARAM_PREFIX/$1 (IAM ssm:GetParameter? NAT up?)"
  [[ -n $v && $v != None ]] || die "SSM $PARAM_PREFIX/$1 is empty"
  printf '%s' "$v"
}

# DB의 표별 행 수("표 행수" 한 줄씩). 백업 manifest와 복원 결과 비교에 쓴다.
counts() {
  runuser -u postgres -- psql -X -q -At -F' ' -v ON_ERROR_STOP=1 -d "$1" <<'SQL'
SELECT format('SELECT %L, count(*) FROM %I.%I', tablename, schemaname, tablename)
  FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename \gexec
SQL
}
