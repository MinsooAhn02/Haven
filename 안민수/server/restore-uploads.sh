#!/usr/bin/env bash
# web-1에서 root로 실행: BACKUP_BUCKET=haven-backup-<계정ID> bash restore-uploads.sh <시각>
# 기본은 격리 폴더 /srv/haven/restore-check/uploads 에 풀고 파일 수·sha256을 대조한다(운영 첨부는 건드리지 않음).
# 새 계정 이전: TARGET_DIR=/srv/haven/uploads (비어 있어야 함, 아니면 거부).
source "$(dirname "$0")/common.sh"

TS="${1:-}"
[[ $TS =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "usage: restore-uploads.sh <backup time, e.g. 20261113T120000Z>"
need BACKUP_BUCKET
CHECK_DIR=/srv/haven/restore-check/uploads
TARGET="${TARGET_DIR:-$CHECK_DIR}"
SRC="s3://$BACKUP_BUCKET/db-backups/$TS"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

for f in uploads.manifest uploads.list uploads.tar; do
  aws s3 cp --only-show-errors --region "$AWS_REGION" "$SRC/$f" "$W/$f" || die "download $SRC/$f failed (no such uploads backup, or incomplete)"
done
want() { grep "^$1=" "$W/uploads.manifest" | cut -d= -f2; }
[[ $(sha256sum "$W/uploads.tar" | cut -d' ' -f1) == "$(want tar_sha256)" ]] || die "uploads.tar sha256 does not match manifest (corrupted?)"
[[ $(sha256sum "$W/uploads.list" | cut -d' ' -f1) == "$(want list_sha256)" ]] || die "uploads.list sha256 does not match manifest"

if [[ $TARGET == "$CHECK_DIR" ]]; then
  rm -rf "$CHECK_DIR"   # 격리 확인용 폴더는 이 스크립트 전용이라 매번 새로
else
  [[ -d $TARGET ]] || die "target $TARGET does not exist (web-setup.sh first)"
  [[ -z $(ls -A "$TARGET") ]] || die "target $TARGET is not empty; refusing to overwrite"
fi
install -d -m 750 "$TARGET"
tar -C "$TARGET" --no-same-owner -xf "$W/uploads.tar"
id haven >/dev/null 2>&1 && chown -R haven:haven "$TARGET"

n=$(find "$TARGET" -type f | wc -l)
[[ $n == "$(want files)" ]] || die "file count $n != backup $(want files)"
[[ ! -s $W/uploads.list ]] || (cd "$TARGET" && sha256sum --quiet -c "$W/uploads.list") >&2 || die "file contents differ from backup (sha256 mismatch)"
echo "OK  restored uploads $TS into $TARGET: $n files, sha256 match"
