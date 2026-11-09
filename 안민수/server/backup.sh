#!/usr/bin/env bash
# db-1에서 root로 실행: BACKUP_BUCKET=haven-backup-<계정ID> bash backup.sh
# DB를 덤프하고 표별 행 수·sha256을 담은 manifest와 함께 S3 db-backups/<UTC시각>/ 에 올린다.
# manifest를 마지막에 올린다: manifest가 있는 백업만 완전한 백업이다.
source "$(dirname "$0")/common.sh"

need BACKUP_BUCKET
DB_NAME="${DB_NAME:-haven}"
[[ $DB_NAME =~ ^[a-z_][a-z0-9_]*$ ]] || die "bad DB_NAME: $DB_NAME"
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST="s3://$BACKUP_BUCKET/db-backups/$TS"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT; chown postgres "$W"

counts "$DB_NAME" > "$W/before"
[[ -s $W/before ]] || die "no tables in $DB_NAME (deploy/migrate first?)"
runuser -u postgres -- pg_dump -Fc -d "$DB_NAME" -f "$W/haven.dump"
counts "$DB_NAME" > "$W/counts"
# ponytail: 덤프 전후 행 수 비교로 쓰기 감지. 행 수가 같은 수정은 못 잡는다. 사용량 많아지면 pg_export_snapshot으로 같은 스냅샷에서 셀 것.
cmp -s "$W/before" "$W/counts" || die "data changed during backup; run again"

cat > "$W/manifest" <<EOF
created=$TS
db=$DB_NAME
pg_dump=$(pg_dump --version)
sha256=$(sha256sum "$W/haven.dump" | cut -d' ' -f1)
bytes=$(stat -c %s "$W/haven.dump")
tables=$(wc -l < "$W/counts")
EOF

for f in haven.dump counts manifest; do
  aws s3 cp --only-show-errors --region "$AWS_REGION" "$W/$f" "$DEST/$f" || die "upload $f to $DEST failed (backup incomplete)"
done
echo "OK  backup $TS -> $DEST ($(grep ^bytes= "$W/manifest" | cut -d= -f2) bytes, $(wc -l < "$W/counts") tables)"
