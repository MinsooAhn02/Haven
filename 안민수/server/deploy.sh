#!/usr/bin/env bash
# web-1에서 root로 실행: bash deploy.sh <40자리 commit SHA>
# 지정 commit을 releases/<sha>에 풀고 → 의존성 → migrate(haven_owner) → 전환 → /healthz 확인.
# 확인 실패 시 이전 release로 되돌린다. DB migration은 되돌리지 않는다(되돌릴 땐 백업 복원).
source "$(dirname "$0")/common.sh"

SHA="${1:-}"
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || die "usage: deploy.sh <full 40-char commit sha>"
[[ -f /etc/haven/site.conf ]] || die "/etc/haven/site.conf missing: run web-setup.sh first"
set -a; source /etc/haven/site.conf; set +a
H=/srv/haven; R=$H/releases/$SHA
as_haven() { runuser -u haven -- "$@"; }
log() { echo "$(date -Is) $SHA $*" >> "$H/deploys.log"; }

# 1) 코드: bare 저장소에 fetch 후 그 commit만 꺼낸다(작업 트리 없이, 중간 실패 시 .tmp만 남음).
[[ -d $H/repo.git ]] || as_haven git clone -q --bare "$REPO_URL" "$H/repo.git"
as_haven git --git-dir="$H/repo.git" fetch -q origin '+refs/heads/*:refs/heads/*'
as_haven git --git-dir="$H/repo.git" cat-file -e "$SHA^{commit}" 2>/dev/null || die "commit $SHA not found in $REPO_URL"
if [[ ! -d $R ]]; then
  rm -rf "$R.tmp"; as_haven mkdir "$R.tmp"
  as_haven git --git-dir="$H/repo.git" archive "$SHA" | as_haven tar -x -C "$R.tmp"
  mv "$R.tmp" "$R"
fi
[[ -f $R/$APP_SUBDIR/manage.py ]] || die "$APP_SUBDIR/manage.py not in $SHA"

# 2) 의존성(서버용 requirements는 release 안에 있어 코드와 같이 버전 관리된다).
as_haven "$H/venv/bin/pip" install -q --disable-pip-version-check -r "$R/안민수/server/requirements.txt"

# 3) 환경 파일: 비밀값을 모두 읽은 뒤에 한 번에 바꾼다(중간 실패 시 기존 파일 유지).
SECRET_KEY=$(secret django/secret_key)
APP_PW=$(secret db/app_password)
OWNER_PW=$(secret db/owner_password)
umask 027
cat > /etc/haven/haven.env.new <<EOF
DJANGO_SECRET_KEY=$SECRET_KEY
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$ALLOWED_HOSTS
DB_NAME=haven
DB_USER=haven_app
DB_PASSWORD=$APP_PW
DB_HOST=$DB_HOST
HAVEN_UPLOAD_DIR=$H/uploads
${CSRF_TRUSTED_ORIGINS:+DJANGO_CSRF_TRUSTED_ORIGINS=$CSRF_TRUSTED_ORIGINS}
EOF
chgrp haven /etc/haven/haven.env.new && mv /etc/haven/haven.env.new /etc/haven/haven.env
umask 022

# 4) migrate는 haven_owner로(haven_app은 테이블을 만들 수 없다). 앱 계정 접속은 check로 확인.
# 비밀번호는 셸 변수 → 환경으로만 넘긴다(명령 인자에 남지 않게).
manage() {  # manage <db 계정> <비밀번호> <manage.py 인자...>
  local u=$1 p=$2; shift 2
  (cd "$R/$APP_SUBDIR" && set -a && source /etc/haven/haven.env && DB_USER=$u && DB_PASSWORD=$p && set +a \
    && runuser -u haven -- "$H/venv/bin/python" manage.py "$@")
}
manage haven_owner "$OWNER_PW" migrate --noinput || die "migrate failed (nothing switched)"
manage haven_app "$APP_PW" shell -c "from django.contrib.auth import get_user_model as U; U().objects.exists()" \
  || die "haven_app cannot read migrated tables (nothing switched)"

# 5) 전환 후 확인. 실패하면 이전 release로 되돌린다.
PREV=$(readlink -f "$H/current" 2>/dev/null || true)
ln -sfn "$R" "$H/current.new" && mv -T "$H/current.new" "$H/current"
systemctl restart haven
healthy() {
  local i
  for i in $(seq 15); do
    [[ $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/healthz) == 200 ]] && return 0
    sleep 1
  done
  return 1
}
if healthy; then
  log ok; echo "OK  deployed $SHA"
else
  if [[ -n $PREV && $PREV != "$R" && -d $PREV ]]; then
    ln -sfn "$PREV" "$H/current.new" && mv -T "$H/current.new" "$H/current"
    systemctl restart haven
    if healthy; then rb="rolled back to $(basename "$PREV"), healthy"; else rb="rolled back to $(basename "$PREV") BUT IT IS ALSO UNHEALTHY"; fi
    log "FAILED, $rb"
    die "health check failed; $rb (migrations NOT reverted). See: journalctl -u haven"
  fi
  log "FAILED, no previous release"
  die "health check failed and no previous release to roll back to. See: journalctl -u haven"
fi
