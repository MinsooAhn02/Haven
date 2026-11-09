#!/usr/bin/env bash
# db-1에서 root로 실행: WEB_IP=<web-1 사설 IP> bash db-setup.sh
# PostgreSQL 16 설치, DB와 두 계정(haven_owner: 테이블 소유·migrate / haven_app: CRUD만),
# web-1에서 오는 두 계정 접속만 허용(나머지·postgres 원격 접속은 거부). 여러 번 실행해도 같은 결과.
source "$(dirname "$0")/common.sh"

need WEB_IP
LISTEN_IP="${LISTEN_IP:-$(hostname -I | awk '{print $1}')}"
DB_NAME="${DB_NAME:-haven}"
ipv4='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
[[ $WEB_IP =~ $ipv4 ]] || die "WEB_IP must be an IPv4 address: $WEB_IP"
[[ $LISTEN_IP =~ $ipv4 ]] || die "LISTEN_IP must be an IPv4 address: $LISTEN_IP"
[[ $DB_NAME =~ ^[a-z_][a-z0-9_]*$ ]] || die "bad DB_NAME: $DB_NAME"

# 설치 전에 비밀값부터 읽는다: 못 읽으면 아무것도 바꾸지 않고 멈춘다.
OWNER_PW=$(secret db/owner_password)
APP_PW=$(secret db/app_password)

if ! command -v psql >/dev/null; then
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -yq postgresql-16
fi
CONF=/etc/postgresql/16/main
[[ -d $CONF ]] || die "PostgreSQL 16 config not found at $CONF"
systemctl enable --now postgresql >/dev/null

psql_su() { runuser -u postgres -- psql -X -q -At -v ON_ERROR_STOP=1 -v db="$DB_NAME" "$@"; }

# 비밀번호는 환경변수로 psql에만 넘기고 \getenv로 읽는다(명령 인자에 남지 않게).
OWNER_PW="$OWNER_PW" APP_PW="$APP_PW" psql_su -d postgres <<'SQL'
\getenv owner_pw OWNER_PW
\getenv app_pw APP_PW
SELECT 'CREATE ROLE haven_owner LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'haven_owner') \gexec
SELECT 'CREATE ROLE haven_app LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'haven_app') \gexec
ALTER ROLE haven_owner PASSWORD :'owner_pw';
ALTER ROLE haven_app PASSWORD :'app_pw';
SELECT format('CREATE DATABASE %I OWNER haven_owner', :'db')
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db') \gexec
SQL

# haven_app: 테이블을 만들거나 지울 수 없고 행 CRUD만. 새 테이블은 기본 권한으로 자동 부여.
psql_su -d "$DB_NAME" <<'SQL'
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO haven_owner, haven_app;
ALTER SCHEMA public OWNER TO haven_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO haven_app;
ALTER DEFAULT PRIVILEGES FOR ROLE haven_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO haven_app;
ALTER DEFAULT PRIVILEGES FOR ROLE haven_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO haven_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO haven_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO haven_app;
SQL

# pg_hba는 통째로 관리한다(원본은 처음 한 번 .orig로 보관). 위에서부터 첫 일치 규칙이 적용된다.
cp -n "$CONF/pg_hba.conf" "$CONF/pg_hba.conf.orig"
cat > "$CONF/pg_hba.conf" <<EOF
# managed by 안민수/server/db-setup.sh — 손으로 고치지 말 것
local  all       postgres                  peer
host   $DB_NAME  haven_app    $WEB_IP/32   scram-sha-256
host   $DB_NAME  haven_owner  $WEB_IP/32   scram-sha-256
host   all       all          0.0.0.0/0    reject
host   all       all          ::/0         reject
EOF
[[ $(psql_su -c "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL") == 0 ]] \
  || die "pg_hba.conf has errors (see pg_hba_file_rules)"

# listen_addresses는 재시작해야 적용된다: 값이 바뀔 때만 재시작, 아니면 reload.
if [[ $(psql_su -c "SHOW listen_addresses") != "$LISTEN_IP" ]]; then
  psql_su -c "ALTER SYSTEM SET listen_addresses = '$LISTEN_IP'"
  systemctl restart postgresql
else
  psql_su -c "SELECT pg_reload_conf()" >/dev/null
fi
[[ $(psql_su -c "SHOW listen_addresses") == "$LISTEN_IP" ]] || die "listen_addresses not applied"

echo "OK  db-setup: db=$DB_NAME listen=$LISTEN_IP allow haven_app/haven_owner from $WEB_IP only"
