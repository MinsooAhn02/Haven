#!/usr/bin/env bash
# 조장 PC(Git Bash)에서 한 번: bash put-secrets.sh
# SSM Parameter Store에 SecureString 3개를 만든다. 이미 있으면 그대로 둔다(덮어쓰지 않음). 값은 출력하지 않는다.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # /haven/... 을 Windows 경로로 바꾸지 않게
P="${PARAM_PREFIX:-/haven}"; R="${AWS_REGION:-ap-northeast-2}"
f=$(mktemp); trap 'rm -f "$f"' EXIT
for n in db/owner_password db/app_password django/secret_key; do
  if aws ssm get-parameter --region "$R" --name "$P/$n" >/dev/null 2>&1; then echo "keep    $P/$n (exists)"; continue; fi
  openssl rand -hex 32 | tr -d '\n' > "$f"   # hex: env 파일·SQL에서 따옴표 문제가 없게
  aws ssm put-parameter --region "$R" --name "$P/$n" --type SecureString --value "file://$f" --no-overwrite >/dev/null
  echo "created $P/$n"
done
