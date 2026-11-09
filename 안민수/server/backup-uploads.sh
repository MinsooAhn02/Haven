#!/usr/bin/env bash
# web-1에서 root로 실행: BACKUP_BUCKET=haven-backup-<계정ID> bash backup-uploads.sh <DB 백업 시각>
# 첨부 파일을 DB 백업과 같은 폴더(db-backups/<시각>/)에 올려 한 묶음으로 만든다(명세: DB+첨부 일관 백업).
# 순서: web-1 `systemctl stop haven`(쓰기 멈춤) → db-1 backup.sh → 이 스크립트(같은 시각) → `systemctl start haven`.
source "$(dirname "$0")/common.sh"

TS="${1:-}"
[[ $TS =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "usage: backup-uploads.sh <DB backup time printed by backup.sh>"
need BACKUP_BUCKET
UP="${UPLOAD_DIR:-/srv/haven/uploads}"
[[ -d $UP ]] || die "$UP not found (web-setup.sh first)"
# 쓰기가 멈춰 있어야 DB와 파일이 같은 시점이다.
if systemctl is-active --quiet haven; then die "haven service is running; stop it first so DB and files match (systemctl stop haven)"; fi
DEST="s3://$BACKUP_BUCKET/db-backups/$TS"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

# 파일 목록: "sha256  ./경로" 한 줄씩. 복원 후 sha256sum -c 로 그대로 대조한다.
(cd "$UP" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum --) > "$W/uploads.list"
tar -C "$UP" -cf "$W/uploads.tar" .
cat > "$W/uploads.manifest" <<EOF
created=$TS
files=$(wc -l < "$W/uploads.list")
tar_sha256=$(sha256sum "$W/uploads.tar" | cut -d' ' -f1)
list_sha256=$(sha256sum "$W/uploads.list" | cut -d' ' -f1)
EOF

for f in uploads.tar uploads.list uploads.manifest; do   # manifest를 마지막에: 있으면 완전한 첨부 백업
  aws s3 cp --only-show-errors --region "$AWS_REGION" "$W/$f" "$DEST/$f" || die "upload $f to $DEST failed (uploads backup incomplete)"
done
echo "OK  uploads backup $TS -> $DEST ($(wc -l < "$W/uploads.list") files)"
