#!/usr/bin/env bash
# db-1에서 root로 실행: BACKUP_BUCKET=haven-backup-<계정ID> bash restore.sh <UTC시각, 예: 20261113T120000Z>
# 기본은 격리 DB haven_restore_check 에 복원하고 행 수를 비교한다(운영 DB는 건드리지 않음).
# 새 계정 이전: db-setup.sh로 빈 haven을 만든 뒤 TARGET_DB=haven. 대상에 테이블이 하나라도 있으면 거부한다.
source "$(dirname "$0")/common.sh"

TS="${1:-}"
[[ $TS =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "usage: restore.sh <backup time, e.g. 20261113T120000Z>"
need BACKUP_BUCKET
CHECK_DB=haven_restore_check
TARGET="${TARGET_DB:-$CHECK_DB}"
[[ $TARGET =~ ^[a-z_][a-z0-9_]*$ ]] || die "bad TARGET_DB: $TARGET"
SRC="s3://$BACKUP_BUCKET/db-backups/$TS"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT; chown postgres "$W"
psql_su() { runuser -u postgres -- psql -X -q -At -v ON_ERROR_STOP=1 "$@"; }

for f in manifest counts haven.dump; do
  aws s3 cp --only-show-errors --region "$AWS_REGION" "$SRC/$f" "$W/$f" || die "download $SRC/$f failed (no such backup, or incomplete)"
done
chown postgres "$W"/*
want=$(grep '^sha256=' "$W/manifest" | cut -d= -f2)
[[ -n $want && $(sha256sum "$W/haven.dump" | cut -d' ' -f1) == "$want" ]] || die "dump sha256 does not match manifest (corrupted?)"

if [[ $TARGET == "$CHECK_DB" ]]; then
  # 격리 확인용 DB는 이 스크립트 전용이라 매번 새로 만든다.
  psql_su -d postgres -c "DROP DATABASE IF EXISTS $CHECK_DB" -c "CREATE DATABASE $CHECK_DB OWNER haven_owner"
else
  [[ $(psql_su -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = '$TARGET'") == 1 ]] \
    || die "target database $TARGET does not exist (run db-setup.sh first)"
  n=$(psql_su -d "$TARGET" -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
  [[ $n == 0 ]] || die "target database $TARGET already has $n tables; refusing to overwrite"
fi

# 객체 소유자는 haven_owner로(원래 소유자·GRANT는 버리고 대상 DB의 기본 권한을 따른다).
runuser -u postgres -- pg_restore --exit-on-error --no-owner --no-acl --role=haven_owner -d "$TARGET" "$W/haven.dump" \
  || die "pg_restore into $TARGET failed"

counts "$TARGET" > "$W/after"
diff "$W/counts" "$W/after" > "$W/diff" || { cat "$W/diff" >&2; die "row counts differ after restore into $TARGET"; }
echo "OK  restored $TS into $TARGET: $(wc -l < "$W/after") tables, row counts match backup"
