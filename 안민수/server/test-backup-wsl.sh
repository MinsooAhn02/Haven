#!/usr/bin/env bash
# backup.sh / restore.sh 시험. test-wsl.sh가 통과한 같은 WSL Ubuntu-24.04에서 root로: bash test-backup-wsl.sh
# S3는 가짜 aws가 /opt/haven-test/s3 폴더로 흉내 낸다. 일부러 실패하는 경우를 포함한다.
set -uo pipefail
D=$(cd "$(dirname "$0")" && pwd)
T=/opt/haven-test
[[ -d $T/ssm ]] || { echo "run test-wsl.sh first"; exit 1; }
rm -rf "$T/s3" "$T/FAIL"; mkdir -p "$T/s3"
cat > "$T/bin/aws" <<'EOF'
#!/usr/bin/env bash
# 가짜 aws: ssm get-parameter --name, s3 cp <src> <dst> (s3://버킷/키 ↔ /opt/haven-test/s3/버킷/키). FAIL 파일이 있으면 거부.
[[ -f /opt/haven-test/FAIL ]] && { echo "AccessDenied (fake)" >&2; exit 1; }
map() { [[ $1 == s3://* ]] && echo "/opt/haven-test/s3/${1#s3://}" || echo "$1"; }
if [[ $1 == ssm ]]; then
  while [[ $# -gt 0 ]]; do [[ $1 == --name ]] && name=$2; shift; done
  cat "/opt/haven-test/ssm/${name#/haven/}"; exit
fi
args=(); for a in "$@"; do [[ $a == --* || $a == s3 || $a == cp || $a == ap-northeast-2 ]] || args+=("$a"); done
src=$(map "${args[0]}"); dst=$(map "${args[1]}")
[[ -f $src ]] || { echo "fatal error: (404) Not Found: ${args[0]}" >&2; exit 1; }
mkdir -p "$(dirname "$dst")" && cp "$src" "$dst"
EOF
chmod +x "$T/bin/aws"; export PATH="$T/bin:$PATH"
export BACKUP_BUCKET=haven-backup-123456789012
B=$T/s3/$BACKUP_BUCKET/db-backups

pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }
expect_ok()   { local d=$1; shift; if "$@" >"$T/out" 2>&1; then ok "$d"; else bad "$d"; tail -8 "$T/out"; fi; }
expect_fail() { local d=$1; shift; if "$@" >"$T/out" 2>&1; then bad "$d (should have failed)"; else ok "$d -> $(grep -m1 -E 'FAIL:|ERROR' "$T/out" || tail -1 "$T/out")"; fi; }
check()       { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }
sql() { runuser -u postgres -- psql -X -q -At -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }

# 실제 앱 데이터처럼 보이게 사용자 3명을 넣는다.
sql haven "INSERT INTO auth_user (password, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined)
  SELECT '!', false, 'bk_user_' || g, '', '', '', false, true, now() FROM generate_series(1,3) g ON CONFLICT DO NOTHING" >/dev/null
USERS=$(sql haven "SELECT count(*) FROM auth_user")

echo "== backup"
expect_fail "backup without BACKUP_BUCKET" env -u BACKUP_BUCKET bash "$D/backup.sh"
touch "$T/FAIL"
expect_fail "backup when S3 upload is denied" bash "$D/backup.sh"
rm "$T/FAIL"
check "  ...and no manifest was left in S3" bash -c "! find '$T/s3' -name manifest | grep -q ."
expect_ok "backup" bash "$D/backup.sh"
TS=$(grep -o '[0-9]\{8\}T[0-9]\{6\}Z' "$T/out" | head -1)
check "backup has dump, counts, manifest ($TS)" test -s "$B/$TS/haven.dump" -a -s "$B/$TS/counts" -a -s "$B/$TS/manifest"
check "counts include auth_user = $USERS" grep -qx "auth_user $USERS" "$B/$TS/counts"

echo "== restore"
expect_fail "restore with bad time format" bash "$D/restore.sh" yesterday
expect_fail "restore of a backup that does not exist" bash "$D/restore.sh" 20000101T000000Z
expect_ok "restore into isolated check DB" bash "$D/restore.sh" "$TS"
check "  ...restored auth_user = $USERS" [ "$(sql haven_restore_check "SELECT count(*) FROM auth_user")" = "$USERS" ]
check "  ...restored tables owned by haven_owner" [ "$(sql haven_restore_check "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner<>'haven_owner'")" = 0 ]
expect_ok "restore again (check DB recreated)" bash "$D/restore.sh" "$TS"
expect_fail "restore into live haven (has tables) is refused" env TARGET_DB=haven bash "$D/restore.sh" "$TS"
check "  ...live haven untouched (auth_user = $USERS)" [ "$(sql haven "SELECT count(*) FROM auth_user")" = "$USERS" ]
expect_fail "restore into missing DB is refused" env TARGET_DB=haven_nope bash "$D/restore.sh" "$TS"
sql postgres "DROP DATABASE IF EXISTS haven_newacct" >/dev/null; sql postgres "CREATE DATABASE haven_newacct OWNER haven_owner" >/dev/null
expect_ok "restore into empty DB (new account case)" env TARGET_DB=haven_newacct bash "$D/restore.sh" "$TS"
cp "$B/$TS/haven.dump" "$T/dump.bak"; printf 'x' >> "$B/$TS/haven.dump"
expect_fail "restore of corrupted dump is refused" bash "$D/restore.sh" "$TS"
cp "$T/dump.bak" "$B/$TS/haven.dump"
cp "$B/$TS/counts" "$T/counts.bak"; sed -i "s/^auth_user .*/auth_user 999/" "$B/$TS/counts"
expect_fail "restore whose row counts differ is reported" bash "$D/restore.sh" "$TS"
cp "$T/counts.bak" "$B/$TS/counts"
echo "== uploads backup/restore"
U=/srv/haven/uploads; mkdir -p "$U/p1"; echo a > "$U/p1/a.txt"; echo "b b" > "$U/p1/file with space.pdf"; head -c 300000 /dev/urandom > "$U/big.bin"; chown -R haven:haven "$U"
expect_fail "uploads backup while app is running (writes not paused)" bash "$D/backup-uploads.sh" "$TS"
expect_fail "uploads backup with bad time" bash "$D/backup-uploads.sh" now
systemctl stop haven
expect_ok "DB backup for bundle" bash "$D/backup.sh"
UTS=$(grep -o '[0-9]\{8\}T[0-9]\{6\}Z' "$T/out" | head -1)
expect_ok "uploads backup into same folder ($UTS)" bash "$D/backup-uploads.sh" "$UTS"
systemctl start haven
check "bundle folder has DB + uploads files" bash -c "cd '$B/$UTS' && test -s haven.dump -a -s manifest -a -s uploads.tar -a -s uploads.list -a -s uploads.manifest"
expect_ok "restore uploads into isolated dir" bash "$D/restore-uploads.sh" "$UTS"
check "  ...3 files, same content" bash -c "[ \$(find /srv/haven/restore-check/uploads -type f | wc -l) = 3 ] && cmp -s '$U/big.bin' /srv/haven/restore-check/uploads/big.bin"
expect_ok "restore uploads again (check dir recreated)" bash "$D/restore-uploads.sh" "$UTS"
expect_fail "restore uploads into live dir (not empty) is refused" env TARGET_DIR=$U bash "$D/restore-uploads.sh" "$UTS"
mkdir -p /srv/haven/newacct-uploads
expect_ok "restore uploads into empty dir (new account case)" env TARGET_DIR=/srv/haven/newacct-uploads bash "$D/restore-uploads.sh" "$UTS"
rm -rf /srv/haven/newacct-uploads
cp "$B/$UTS/uploads.tar" "$T/tar.bak"; printf x >> "$B/$UTS/uploads.tar"
expect_fail "restore of corrupted uploads.tar is refused" bash "$D/restore-uploads.sh" "$UTS"
cp "$T/tar.bak" "$B/$UTS/uploads.tar"
expect_fail "restore uploads of missing backup" bash "$D/restore-uploads.sh" 20000101T000000Z
check "app still healthy" [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/healthz)" = 200 ]
sql postgres "DROP DATABASE haven_newacct" >/dev/null

echo "== result: $pass passed, $fail failed"
[[ $fail == 0 ]]
