#!/usr/bin/env bash
# 실제 AWS 없이 서버 스크립트를 끝까지 시험한다. 서버와 같은 WSL Ubuntu-24.04에서 root로:
#   bash test-wsl.sh <git bundle> <정상 commit> <일부러 깨뜨린 commit>
# db-1과 web-1을 한 머신(127.0.0.1)에 둔다. aws는 가짜(파일에서 비밀값을 읽음). 일부러 실패하는 경우를 포함한다.
# 주의: 이 머신의 PostgreSQL·Nginx·/srv/haven을 바꾼다. 시험 전용 WSL에서만 실행.
set -uo pipefail
BUNDLE=$1 GOOD=$2 BAD=$3
D=$(cd "$(dirname "$0")" && pwd)
T=/opt/haven-test
rm -rf "$T"; mkdir -p "$T/bin" "$T/ssm/db" "$T/ssm/django"
cat > "$T/bin/aws" <<'EOF'
#!/usr/bin/env bash
# 가짜 aws: ssm get-parameter --name /haven/<x> 만. /opt/haven-test/FAIL 이 있으면 권한 거부처럼 실패.
[[ -f /opt/haven-test/FAIL ]] && { echo "AccessDeniedException (fake)" >&2; exit 254; }
while [[ $# -gt 0 ]]; do [[ $1 == --name ]] && name=$2; shift; done
cat "/opt/haven-test/ssm/${name#/haven/}"
EOF
chmod +x "$T/bin/aws"; export PATH="$T/bin:$PATH"
for n in db/owner_password db/app_password django/secret_key; do openssl rand -hex 32 | tr -d '\n' > "$T/ssm/$n"; done
APP_PW=$(cat "$T/ssm/db/app_password")

pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }
expect_ok()   { local d=$1; shift; if "$@" >"$T/out" 2>&1; then ok "$d"; else bad "$d"; tail -8 "$T/out"; fi; }
expect_fail() { local d=$1; shift; if "$@" >"$T/out" 2>&1; then bad "$d (should have failed)"; else ok "$d -> $(grep -m1 -E 'FAIL:|ERROR|FATAL' "$T/out" || tail -1 "$T/out")"; fi; }
check()       { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' -H "Host: $1" "http://127.0.0.1$2"; }
app_sql() { PGPASSWORD=$APP_PW psql -X -q -At -h 127.0.0.1 -U haven_app -d "${2:-haven}" -v ON_ERROR_STOP=1 -c "$1"; }

echo "== db-setup"
expect_fail "db-setup without WEB_IP" env -u WEB_IP bash "$D/db-setup.sh"
touch "$T/FAIL"
expect_fail "db-setup when SSM read is denied" env WEB_IP=127.0.0.1 bash "$D/db-setup.sh"
rm "$T/FAIL"
check "  ...and it changed nothing (PostgreSQL not installed)" bash -c '! command -v psql >/dev/null'
expect_ok "db-setup run 1" env WEB_IP=127.0.0.1 LISTEN_IP=127.0.0.1 bash "$D/db-setup.sh"
expect_ok "db-setup run 2 (same result)" env WEB_IP=127.0.0.1 LISTEN_IP=127.0.0.1 bash "$D/db-setup.sh"
check "pg_hba has exactly one managed copy of rules" bash -c '[[ $(grep -c "^host" /etc/postgresql/16/main/pg_hba.conf) == 4 ]]'
expect_fail "haven_app CREATE TABLE is refused" app_sql "create table t(x int)"
expect_fail "haven_app wrong password is refused" env PGPASSWORD=wrong psql -X -h 127.0.0.1 -U haven_app -d haven -c "select 1"
expect_fail "haven_app to another database is refused" app_sql "select 1" postgres
expect_fail "postgres over network is refused" env PGPASSWORD=x psql -X -h 127.0.0.1 -U postgres -d postgres -c "select 1"

echo "== web-setup"
expect_fail "web-setup without DB_HOST" env -u DB_HOST ALLOWED_HOSTS=haven.test bash "$D/web-setup.sh"
WEB_ENV=(DB_HOST=127.0.0.1 ALLOWED_HOSTS=haven.test,localhost REPO_URL="file://$T/repo.git")
expect_ok "web-setup run 1" env "${WEB_ENV[@]}" bash "$D/web-setup.sh"
expect_ok "web-setup run 2 (same result)" env "${WEB_ENV[@]}" bash "$D/web-setup.sh"
git clone -q --bare "$BUNDLE" "$T/repo.git" && chown -R haven:haven "$T/repo.git"

echo "== deploy"
expect_fail "deploy with short sha" bash "$D/deploy.sh" abc123
expect_fail "deploy with unknown commit" bash "$D/deploy.sh" "$(printf '0%.0s' {1..40})"
touch "$T/FAIL"
expect_fail "deploy when SSM read is denied" bash "$D/deploy.sh" "$GOOD"
rm "$T/FAIL"
check "  ...and nothing was switched (no current)" bash -c '[[ ! -e /srv/haven/current ]]'
expect_ok "deploy good commit" bash "$D/deploy.sh" "$GOOD"
check "healthz via ALB-style Host (server IP) = 200" [ "$(code 10.0.1.10 /healthz)" = 200 ]
check "login page with allowed Host = 200" [ "$(code haven.test /accounts/login/)" = 200 ]
check "unknown Host = 400" [ "$(code evil.example /accounts/login/)" = 400 ]
STATIC=$(cd /srv/haven/current/노푸른/static && find . -type f | head -1 | sed 's|^\./||')
check "static file served by nginx ($STATIC) = 200" [ "$(code haven.test "/static/$STATIC")" = 200 ]
check "migrated tables are owned by haven_owner" [ "$(app_sql "select count(*) from pg_tables where schemaname='public' and tableowner<>'haven_owner'")" = 0 ]
check "haven_app can read migrated tables" bash -c "PGPASSWORD=$APP_PW psql -X -q -h 127.0.0.1 -U haven_app -d haven -v ON_ERROR_STOP=1 -c 'select count(*) from auth_user' >/dev/null"
expect_fail "haven_app still cannot DROP a migrated table" app_sql "drop table auth_user"
check "env file is 640 root:haven" [ "$(stat -c '%a %U:%G' /etc/haven/haven.env)" = "640 root:haven" ]
check "uploads dir is 750 haven:haven" [ "$(stat -c '%a %U:%G' /srv/haven/uploads)" = "750 haven:haven" ]
check "env has HAVEN_UPLOAD_DIR, no CSRF line when unset" bash -c 'grep -qx "HAVEN_UPLOAD_DIR=/srv/haven/uploads" /etc/haven/haven.env && ! grep -q CSRF /etc/haven/haven.env'
check "env has DJANGO_HTTPS=0 without an https origin" grep -qx "DJANGO_HTTPS=0" /etc/haven/haven.env
GPID=$(systemctl show -p MainPID --value haven)
check "service can write uploads (ReadWritePaths)" bash -c "nsenter -t $GPID -m runuser -u haven -- touch /srv/haven/uploads/.probe && rm /srv/haven/uploads/.probe"
check "service cannot write code dir (ProtectSystem=strict)" bash -c "! nsenter -t $GPID -m runuser -u haven -- touch /srv/haven/current/.probe 2>/dev/null"
echo secret > /srv/haven/uploads/private.txt
check "nginx does not serve uploads directly" bash -c '[ "$(curl -s -o /dev/null -w "%{http_code}" -H "Host: haven.test" http://127.0.0.1/uploads/private.txt)" != 200 ] && [ "$(curl -s -o /dev/null -w "%{http_code}" -H "Host: haven.test" http://127.0.0.1/static/../uploads/private.txt)" != 200 ]'
rm /srv/haven/uploads/private.txt
check "gunicorn runs as haven, not root" [ "$(ps -o user= -C gunicorn | sort -u)" = haven ]
# 본문 한도: 경계값은 앱이 413(+X-Request-ID 로그), 훨씬 큰 요청은 Nginx가 413(앱에 안 감)
post() { head -c "$2" /dev/zero | tr '\0' a > "$T/body"; curl -s -o /dev/null -D "$T/hdr" -w '%{http_code}' -H "Host: haven.test" --data-binary @"$T/body" "http://127.0.0.1$1"; }
from_app() { grep -qi '^x-request-id:' "$T/hdr"; }
[ "$(post /posts/new/ 8193)" = 413 ] && from_app && ok "post 8193 bytes -> 413 from app (logged)" || bad "post 8193 bytes -> 413 from app"
[ "$(post /posts/new/ 20000)" = 413 ] && ! from_app && ok "post 20000 bytes -> 413 from nginx (app not reached)" || bad "post 20000 bytes -> 413 from nginx"
[ "$(post /posts/1/attachments/ 2200000)" = 413 ] && from_app && ok "upload 2.2MB -> 413 from app (logged)" || bad "upload 2.2MB -> 413 from app"
[ "$(post /posts/1/attachments/ 4000000)" = 413 ] && ! from_app && ok "upload 4MB -> 413 from nginx" || bad "upload 4MB -> 413 from nginx"
# 접근 로그 요청 식별자(11/18): trace·rid·cid·run·client. 앞부분은 combined 그대로
TR=1-5759e988-bd862e3fe1be46a994272793
idreq() { curl -s -o /dev/null -D "$T/hdr" -H "Host: haven.test" "$@" http://127.0.0.1/accounts/login/; sleep 0.3; tail -n 1 /var/log/nginx/access.log; }
L=$(idreq -H "X-Amzn-Trace-Id: Self=1-abc;Root=$TR;Sampled=1" -H "X-Haven-Request-ID: cli-req.1" -H "X-Haven-Run-ID: run:42" -H "X-Forwarded-For: 203.0.113.9, 198.51.100.7")
RID=$(grep -i '^x-request-id:' "$T/hdr" | tr -d '\r' | awk '{print $2}')
check "access log keeps combined prefix" bash -c '[[ "$1" =~ ^[0-9.]+\ -\ -\ \[[^]]+\]\ \"GET\ /accounts/login/\ HTTP/1\.1\"\ 200\  ]]' _ "$L"
check "access log trace= is the Root only" bash -c '[[ "$1" == *" trace=$2 "* ]]' _ "$L" "$TR"
check "access log rid= equals response X-Request-ID" bash -c '[[ ${#2} == 32 && "$1" == *" rid=$2 "* ]]' _ "$L" "$RID"
check "  ...and the app log has the same request_id and trace_id" bash -c 'journalctl -u haven --no-pager -n 200 | grep -F "\"request_id\":\"$1\"" | grep -qF "\"trace_id\":\"$2\""' _ "$RID" "$TR"
check "access log cid=/run= keep valid client IDs" bash -c '[[ "$1" == *" cid=cli-req.1 run=run:42 "* ]]' _ "$L"
check "access log client= is the last X-Forwarded-For entry (not the forged first one)" bash -c '[[ "$1" == *" client=198.51.100.7 rt="* && "$1" != *203.0.113.9* ]]' _ "$L"
L=$(idreq -H "X-Amzn-Trace-Id: Root=1-zz" -H 'X-Haven-Request-ID: bad id"; DROP' -H "X-Haven-Run-ID: $(head -c 200 /dev/zero | tr '\0' a)" -H 'X-Forwarded-For: 1.2.3.4, "evil')
check "bad trace/client IDs/XFF are logged as - (raw value not written)" bash -c '[[ "$1" == *" trace=- "* && "$1" == *" cid=- run=- client=- "* && "$1" != *DROP* && "$1" != *evil* ]]' _ "$L"
L=$(idreq)
check "no ID headers: trace=- cid=- run=- client=- (rid still set by app)" bash -c '[[ "$1" == *" trace=- rid="[0-9a-f]* && "$1" == *" cid=- run=- client=- "* ]]' _ "$L"
post /posts/new/ 20000 >/dev/null; sleep 0.3
check "nginx-only 413: rid=- (app not reached)" bash -c '[[ "$(tail -n 1 /var/log/nginx/access.log)" == *" 413 "*" rid=- "* ]]'
cp -p /etc/nginx/sites-available/haven "$T/haven.good"
expect_fail "web-setup with an nginx config that fails nginx -t" env "${WEB_ENV[@]}" NGINX_BREAK_FOR_TEST=1 bash "$D/web-setup.sh"
check "  ...previous nginx config restored, nginx still serves" bash -c 'cmp -s /etc/nginx/sites-available/haven "$1" && nginx -t -q && [[ $(curl -s -o /dev/null -w "%{http_code}" -H "Host: haven.test" http://127.0.0.1/accounts/login/) == 200 ]]' _ "$T/haven.good"
check "pypdf installed in venv" /srv/haven/venv/bin/python -c "import pypdf"
check "cleanup timer enabled" [ "$(systemctl is-enabled haven-cleanup.timer)" = enabled ]
expect_ok "cleanup service runs once (as haven, ReadWritePaths)" systemctl start haven-cleanup.service
check "  ...result success" [ "$(systemctl show -p Result --value haven-cleanup.service)" = success ]
expect_ok "deploy same commit again" bash "$D/deploy.sh" "$GOOD"
expect_fail "deploy broken commit (must roll back)" bash "$D/deploy.sh" "$BAD"
check "  ...current points back to good commit" [ "$(basename "$(readlink -f /srv/haven/current)")" = "$GOOD" ]
check "  ...healthz 200 after rollback" [ "$(code haven.test /healthz)" = 200 ]
systemctl restart postgresql nginx haven
check "after restarting all services: healthz 200" bash -c 'for i in $(seq 15); do [[ $(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/healthz) == 200 ]] && exit 0; sleep 1; done; exit 1'
check "app DB password not in logs" bash -c "! grep -rqF '$APP_PW' /srv/haven/deploys.log /var/log/postgresql /var/log/nginx && ! journalctl -u haven -u postgresql --no-pager | grep -qF '$APP_PW'"

echo "== result: $pass passed, $fail failed"
[[ $fail == 0 ]]
