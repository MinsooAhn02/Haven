# Haven local dev PostgreSQL setup (Windows). Safe to re-run.
# Run from repo root:  powershell -ExecutionPolicy Bypass -File 안민수\dev-db-setup.ps1
#
# What it does (why: everyone gets the same DB layout as CI/server, see 안민수/공통실행.md):
#  1. Installs PostgreSQL 16 via winget if missing (server + CLI only).
#  2. Stores generated passwords ONLY in %APPDATA%\postgresql\pgpass.conf (libpq reads it; never in Git).
#  3. Restricts the server to localhost (installer default listens on all interfaces).
#  4. Creates haven_owner (migrations, CREATEDB for Django test DB) / haven_app (CRUD only) / haven_dev.
#  5. Verifies: owner can create, app can CRUD, app CREATE TABLE is refused.
# Messages are ASCII on purpose: Windows PowerShell 5.1 misreads non-BOM UTF-8.

$ErrorActionPreference = "Stop"
$bin  = "C:\Program Files\PostgreSQL\16\bin"
$psql = Join-Path $bin "psql.exe"
$pgpass = Join-Path $env:APPDATA "postgresql\pgpass.conf"

function NewPw { -join ((48..57 + 65..90 + 97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }
function HasPw($user) { (Test-Path $pgpass) -and (Select-String -Path $pgpass -Pattern "^localhost:5432:\*:${user}:" -Quiet) }
function AddPw($user, $pw) {
  New-Item -ItemType Directory -Force (Split-Path $pgpass) | Out-Null
  Add-Content -Path $pgpass -Value "localhost:5432:*:${user}:$pw" -Encoding ascii
}
# Native commands don't throw on failure; check exit codes explicitly.
# Local "Continue": with "Stop", PS 5.1 turns any psql stderr (even NOTICE or an expected refusal) into a crash.
$env:PGCLIENTENCODING = "UTF8"
function Sql($user, $db, $sql, [switch]$MayFail) {
  $ErrorActionPreference = "Continue"
  $out = "set client_min_messages = warning;`n$sql" | & $psql -h localhost -p 5432 -U $user -d $db -w -q -At -v ON_ERROR_STOP=1 2>&1
  $code = $LASTEXITCODE
  if (-not $MayFail -and $code -ne 0) { throw "psql failed as ${user} (exit $code): $out" }
  return @{ ok = ($code -eq 0); out = "$out".Trim() }
}

# 1. install
if (-not (Test-Path $psql)) {
  if (HasPw "postgres") { throw "pgpass has a postgres entry but PostgreSQL 16 is not installed. Remove that line from $pgpass and re-run." }
  $pw = NewPw
  AddPw "postgres" $pw
  Write-Host "Installing PostgreSQL 16 (accept the admin prompt)..."
  winget install --id PostgreSQL.PostgreSQL.16 --exact --silent --accept-package-agreements --accept-source-agreements `
    --override "--mode unattended --unattendedmodeui none --superpassword $pw --serverport 5432 --enable-components server,commandlinetools"
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $psql)) { throw "winget install failed (exit $LASTEXITCODE)" }
} elseif (-not (HasPw "postgres")) {
  throw "PostgreSQL 16 is already installed but $pgpass has no postgres password. Add a line 'localhost:5432:*:postgres:<your password>' and re-run."
}
Sql postgres postgres "select 1;" | Out-Null
Write-Host "OK  postgres login"

# 2. localhost only
if ((Sql postgres postgres "show listen_addresses;").out -ne "localhost") {
  Sql postgres postgres "alter system set listen_addresses = 'localhost';" | Out-Null
  Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", "Restart-Service postgresql-x64-16"
  Start-Sleep 3
  if ((Sql postgres postgres "show listen_addresses;").out -ne "localhost") { throw "listen_addresses is still not localhost" }
}
Write-Host "OK  listening on localhost only"

# 3. roles + db (names from 안민수/공통실행.md)
foreach ($r in @(@{n = "haven_owner"; opt = "LOGIN CREATEDB"}, @{n = "haven_app"; opt = "LOGIN"})) {
  $exists = (Sql postgres postgres "select 1 from pg_roles where rolname = '$($r.n)';").out -eq "1"
  if ($exists -and -not (HasPw $r.n)) { throw "role $($r.n) exists but has no pgpass entry. Add its password to $pgpass or drop the role, then re-run." }
  if (-not $exists) {
    $pw = NewPw
    Sql postgres postgres "create role $($r.n) $($r.opt) password '$pw';" | Out-Null
    AddPw $r.n $pw
  }
}
if ((Sql postgres postgres "select 1 from pg_database where datname = 'haven_dev';").out -ne "1") {
  Sql postgres postgres "create database haven_dev owner haven_owner;" | Out-Null
}
Sql postgres haven_dev @"
revoke create on schema public from public;
grant usage on schema public to haven_app;
alter default privileges for role haven_owner in schema public grant select, insert, update, delete on tables to haven_app;
alter default privileges for role haven_owner in schema public grant usage, select on sequences to haven_app;
"@ | Out-Null
Write-Host "OK  haven_owner / haven_app / haven_dev"

# 4. verify the permission split (the point of having two roles)
Sql haven_owner haven_dev "drop table if exists _setup_check; create table _setup_check (id serial primary key, v text);" | Out-Null
try {
  $crud = Sql haven_app haven_dev "insert into _setup_check (v) values ('x'); update _setup_check set v = 'y'; select v from _setup_check; delete from _setup_check;"
  if ($crud.out -ne "y") { throw "haven_app CRUD returned '$($crud.out)'" }
  $ddl = Sql haven_app haven_dev "create table _should_fail (id int);" -MayFail
  if ($ddl.ok) { Sql postgres haven_dev "drop table _should_fail;" | Out-Null; throw "haven_app was able to CREATE TABLE (must be refused)" }
} finally {
  Sql haven_owner haven_dev "drop table if exists _setup_check;" | Out-Null
}
Write-Host "OK  haven_app CRUD works, CREATE TABLE refused"
Write-Host ""
Write-Host "Done. Passwords are in $pgpass (do not commit or share)."
Write-Host "Django: DB_NAME=haven_dev DB_USER=haven_owner DB_HOST=localhost DB_PORT=5432; set DB_PASSWORD from that file if the app requires it."
