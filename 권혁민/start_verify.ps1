<#
.SYNOPSIS
Prepare, reset, or start the local Haven verification environment on Windows.
.DESCRIPTION
Start (default): keep existing data and start Django in the foreground.
Prepare: create haven_verify if missing, migrate, and seed only an empty DB.
Reset: migrate, flush haven_verify (including sequences), and seed it again.

Only localhost:5432 / haven_verify is a writable database target. Existing
haven_owner / haven_app roles and libpq pgpass credentials are required.
This script does not install PostgreSQL, alter roles, or run HTTP tests.
Passwords are never written to source files, command arguments, or reports.
Keep this file ASCII-compatible for Windows PowerShell 5.1.
.EXAMPLE
.\start_verify.ps1 -Mode Prepare
.EXAMPLE
.\start_verify.ps1
.EXAMPLE
.\start_verify.ps1 -Mode Reset
.EXAMPLE
.\start_verify.ps1 -Mode Start -PostgresBin 'C:\Program Files\PostgreSQL\16\bin'
#>
[CmdletBinding()]
param(
    [ValidateSet('Start', 'Prepare', 'Reset')]
    [string]$Mode = 'Start',
    [string]$PostgresBin = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
# Unicode code points keep the teammate's folder name readable by PS 5.1.
$appFolder = -join ([char[]]@(0xC2E0, 0xC694, 0xCC2C))
$appRoot = Join-Path (Join-Path $repoRoot $appFolder) 'app'
$pythonPath = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$managePath = Join-Path $appRoot 'manage.py'
$databaseName = 'haven_verify'
$databaseHost = 'localhost'
$databasePort = '5432'

function Invoke-LocalSql {
    param(
        [ValidateSet('haven_owner', 'haven_app')][string]$Role,
        [ValidateSet('postgres', 'haven_verify')][string]$Database,
        [string]$Sql
    )
    # Native stderr can otherwise become a terminating error in Windows PS 5.1.
    $ErrorActionPreference = 'Continue'
    $sqlOutput = @($Sql | & $psqlPath -X -w -q -A -t `
        -h $databaseHost -p $databasePort -U $Role -d $Database `
        -v ON_ERROR_STOP=1 -f - 2>&1)
    $sqlExit = $LASTEXITCODE
    if ($sqlExit -ne 0) {
        $sqlMessage = ($sqlOutput | ForEach-Object { $_.ToString() }) -join "`n"
        throw "PostgreSQL failed ($Role / $Database, exit $sqlExit). Check the local service, existing roles, and pgpass credentials. $sqlMessage"
    }
    return (($sqlOutput | ForEach-Object { $_.ToString() }) -join "`n").Trim()
}

function Assert-VerifyConnection {
    param([ValidateSet('haven_owner', 'haven_app')][string]$Role)
    $identity = Invoke-LocalSql -Role $Role -Database $databaseName -Sql @'
SELECT current_database() || '|' || current_user || '|' ||
       COALESCE(host(inet_server_addr()), '') || '|' || inet_server_port()::text;
'@
    # inet::text includes /32 or /128; host(inet) returns only the IP address.
    if ($identity -notmatch ('^haven_verify\|' + $Role + '\|(127\.0\.0\.1|::1)\|5432$')) {
        throw "Connection guard failed: expected the selected role on local haven_verify:5432. Actual database|role|address|port: $identity"
    }
}

function Assert-NoOtherConnections {
    $connectionCount = Invoke-LocalSql -Role haven_owner -Database $databaseName -Sql @'
SELECT count(*) FROM pg_stat_activity
WHERE datname = 'haven_verify' AND pid <> pg_backend_pid();
'@
    if ($connectionCount -ne '0') {
        throw 'haven_verify has other connections. Close its servers/DB clients before Reset; no sessions will be terminated automatically.'
    }
}

function Invoke-VerifyPython {
    param([string[]]$CommandArguments, [string]$Stage, [string]$StandardInput)
    $ErrorActionPreference = 'Continue'
    Push-Location -LiteralPath $appRoot -ErrorAction Stop
    try {
        if ($PSBoundParameters.ContainsKey('StandardInput')) {
            # Pass embedded Python via stdin, not PS 5.1 native quote parsing.
            $StandardInput | & $pythonPath -B @CommandArguments
        } else {
            & $pythonPath -B @CommandArguments
        }
        $pythonExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($pythonExit -ne 0) {
        throw "$Stage failed (exit $pythonExit). No later stage was started."
    }
}

function Invoke-VerifyManage {
    param([string[]]$ManagementArguments, [string]$Stage, [string]$StandardInput)
    $pythonOptions = @{
        CommandArguments = @($managePath) + $ManagementArguments
        Stage = $Stage
    }
    if ($PSBoundParameters.ContainsKey('StandardInput')) {
        $pythonOptions.StandardInput = $StandardInput
    }
    Invoke-VerifyPython @pythonOptions
}

function Set-SeedPassword {
    if ([string]::IsNullOrEmpty($env:HAVEN_SEED_PASSWORD)) {
        $seedSecret = Read-Host 'Shared password for the four local test accounts' -AsSecureString
        try {
            $env:HAVEN_SEED_PASSWORD = [System.Net.NetworkCredential]::new('', $seedSecret).Password
        } finally {
            $seedSecret.Dispose()
        }
    }
    # Validate before Reset can erase data; this code does not connect to the DB.
    $passwordValidation = @'
import os
import django
django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
password = os.environ.get("HAVEN_SEED_PASSWORD", "")
if not password:
    raise SystemExit("A non-empty test account password is required.")
for username in ("member_a", "member_b", "member_c", "operator"):
    try:
        validate_password(password, get_user_model()(username=username))
    except ValidationError as exc:
        raise SystemExit("Test account password rejected: " + " ".join(exc.messages))
'@
    Invoke-VerifyPython -CommandArguments @('-') -StandardInput $passwordValidation -Stage 'Password validation'
}

function Assert-InitialData {
    $baselineCheck = @'
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from accounts.roles import OPERATOR_CODENAMES, PERM_APP, is_member
from posts.models import Post, PostShare

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SELECT current_database(), current_user")
        if cursor.fetchone() != ("haven_verify", "haven_app"):
            raise SystemExit("Baseline check refused an unexpected database or role.")
    users = list(get_user_model().objects.order_by("id"))
    expected = [(1, "member_a"), (2, "member_b"), (3, "member_c"), (4, "operator")]
    errors = []
    if [(u.pk, u.username) for u in users] != expected:
        errors.append("Expected exactly member_a=1, member_b=2, member_c=3, operator=4.")
    if any(not u.is_active or u.is_staff or u.is_superuser for u in users):
        errors.append("Expected all four accounts active, without staff/superuser flags.")
    by_name = {u.username: u for u in users}
    operator = by_name.get("operator")
    if operator is None or not all(operator.has_perm(f"{PERM_APP}.{code}") for code in OPERATOR_CODENAMES):
        errors.append("operator is missing the dedicated account administration permissions.")
    if any(not is_member(by_name.get(name)) for name in ("member_a", "member_b", "member_c")):
        errors.append("A/B/C must be ordinary members.")
    posts = list(Post.objects.order_by("id").values_list("id", "owner_id", "status"))
    if posts != [(1, 1, Post.Status.ACTIVE), (2, 1, Post.Status.ACTIVE)]:
        errors.append("Expected exactly P1=1 and P2=2, ACTIVE and owned by member_a=1.")
    if PostShare.objects.exists():
        errors.append("Expected zero initial share relationships.")
    for message in errors:
        print("BASELINE: " + message)
    if errors:
        raise SystemExit("Existing data was retained. Use Start to keep it, or explicitly choose Reset for a fresh baseline.")
print("OK: A=1 / B=2 / C=3 / operator=4; P1=1 / P2=2; shares=0.")
'@
    # Django shell treats stdin as interactive on Windows and can swallow errors.
    # Python '-' executes the whole input as a script and preserves failure exits.
    Invoke-VerifyPython -CommandArguments @('-') -StandardInput $baselineCheck -Stage 'Initial data verification'
}

$managedEnvironment = @(
    'DB_NAME', 'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD',
    'DJANGO_SETTINGS_MODULE', 'DJANGO_SECRET_KEY', 'DJANGO_DEBUG',
    'DJANGO_ALLOWED_HOSTS', 'DJANGO_CSRF_TRUSTED_ORIGINS',
    'HAVEN_SEED_PASSWORD', 'HAVEN_TEMPLATES_DIR', 'HAVEN_STATIC_DIR',
    'PGPASSWORD', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS', 'PGHOSTADDR',
    'PGCLIENTENCODING', 'PGCONNECT_TIMEOUT',
    'PYTHONDONTWRITEBYTECODE', 'PYTHONIOENCODING', 'PYTHONUTF8'
)
$savedEnvironment = @{}
foreach ($environmentName in $managedEnvironment) {
    $savedEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable($environmentName, 'Process')
}

try {
    foreach ($requiredFile in @($pythonPath, $managePath)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Required file missing: $requiredFile"
        }
    }
    if ($PostgresBin) {
        $psqlPath = Join-Path $PostgresBin 'psql.exe'
    } else {
        $psqlCommand = Get-Command psql.exe -CommandType Application -ErrorAction SilentlyContinue
        if ($null -ne $psqlCommand) {
            $psqlPath = $psqlCommand.Source
        } else {
            $psqlPath = Join-Path $env:ProgramFiles 'PostgreSQL\16\bin\psql.exe'
        }
    }
    if (-not (Test-Path -LiteralPath $psqlPath -PathType Leaf)) {
        throw 'psql.exe was not found. Supply -PostgresBin with your existing PostgreSQL bin directory.'
    }
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    if (@($listeners | Where-Object { $_.Port -eq 8000 }).Count -gt 0) {
        throw 'Port 8000 is already in use. Stop the existing server before running this script.'
    }

    foreach ($environmentName in @('DB_PASSWORD', 'PGPASSWORD', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS', 'PGHOSTADDR', 'HAVEN_TEMPLATES_DIR', 'HAVEN_STATIC_DIR')) {
        [Environment]::SetEnvironmentVariable($environmentName, $null, 'Process')
    }
    $env:DB_NAME = $databaseName
    $env:DB_HOST = $databaseHost
    $env:DB_PORT = $databasePort
    $env:DJANGO_SETTINGS_MODULE = 'config.settings'
    $env:DJANGO_DEBUG = '1'
    $env:DJANGO_ALLOWED_HOSTS = '127.0.0.1,localhost'
    $env:DJANGO_CSRF_TRUSTED_ORIGINS = 'http://127.0.0.1:8000,http://localhost:8000'
    $env:PGCLIENTENCODING = 'UTF8'
    $env:PGCONNECT_TIMEOUT = '5'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    if ([string]::IsNullOrWhiteSpace($env:DJANGO_SECRET_KEY)) {
        # Ephemeral local key: a fresh terminal/key invalidates older sessions.
        $secretBytes = New-Object byte[] 48
        $secretGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $secretGenerator.GetBytes($secretBytes)
            $env:DJANGO_SECRET_KEY = [Convert]::ToBase64String($secretBytes)
        } finally {
            $secretGenerator.Dispose()
            [Array]::Clear($secretBytes, 0, $secretBytes.Length)
        }
    }

    Write-Host "Mode=$Mode  DB=localhost:5432/haven_verify  HTTP=http://127.0.0.1:8000"
    Write-Host 'DB authentication uses existing pgpass credentials; no password files are created.'

    if ($Mode -ne 'Start') {
        $env:DB_USER = 'haven_owner'
        $databaseOwner = Invoke-LocalSql -Role haven_owner -Database postgres -Sql @'
SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'haven_verify';
'@
        if (-not $databaseOwner) {
            Invoke-LocalSql -Role haven_owner -Database postgres -Sql 'CREATE DATABASE haven_verify OWNER haven_owner;' | Out-Null
            Write-Host 'Created haven_verify.'
        } elseif ($databaseOwner -ne 'haven_owner') {
            throw 'haven_verify must already be owned by haven_owner. Ownership was not changed.'
        }
        Assert-VerifyConnection -Role haven_owner
        if ($Mode -eq 'Reset') {
            Assert-NoOtherConnections
            Set-SeedPassword
        }

        Invoke-LocalSql -Role haven_owner -Database $databaseName -Sql @'
GRANT CONNECT ON DATABASE haven_verify TO haven_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM haven_app;
GRANT USAGE ON SCHEMA public TO haven_app;
ALTER DEFAULT PRIVILEGES FOR ROLE haven_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO haven_app;
ALTER DEFAULT PRIVILEGES FOR ROLE haven_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO haven_app;
'@ | Out-Null
        Invoke-VerifyManage -ManagementArguments @('migrate', '--noinput') -Stage 'Migration'
        Invoke-LocalSql -Role haven_owner -Database $databaseName -Sql @'
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO haven_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO haven_app;
'@ | Out-Null

        if ($Mode -eq 'Reset') {
            Assert-VerifyConnection -Role haven_owner
            Assert-NoOtherConnections
            Write-Host 'Reset: clearing only haven_verify application data and resetting sequences.'
            Invoke-VerifyManage -ManagementArguments @('flush', '--noinput') -Stage 'Reset'
        }
        $seedState = Invoke-LocalSql -Role haven_owner -Database $databaseName -Sql @'
SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM auth_user)
                 AND NOT EXISTS (SELECT 1 FROM posts_post)
                 AND NOT EXISTS (SELECT 1 FROM posts_postshare)
            THEN 'empty' ELSE 'existing' END;
'@
        if ($seedState -eq 'empty') {
            if ($Mode -ne 'Reset') { Set-SeedPassword }
            Invoke-VerifyManage -ManagementArguments @('seed_demo') -Stage 'Seeding'
        } elseif ($seedState -eq 'existing') {
            Write-Host 'Existing account/post/share data was retained; seed_demo was skipped.'
        } else {
            throw 'Could not determine whether the verification database is empty.'
        }
        $env:DB_USER = 'haven_app'
        Assert-VerifyConnection -Role haven_app
        Assert-InitialData
    }

    $env:DB_USER = 'haven_app'
    Assert-VerifyConnection -Role haven_app
    Invoke-VerifyManage -ManagementArguments @('migrate', '--check', '--noinput') -Stage 'Migration readiness check (no migrations applied)'
    [Environment]::SetEnvironmentVariable('HAVEN_SEED_PASSWORD', $null, 'Process')
    Write-Host 'Starting Django as haven_app. Keep this terminal open; Ctrl+C stops the server.'
    Write-Host 'A separate CLI terminal must receive its own test account password environment.'
    Invoke-VerifyManage -ManagementArguments @('runserver', '127.0.0.1:8000', '--noreload') -Stage 'Django server'
} finally {
    foreach ($environmentName in $managedEnvironment) {
        [Environment]::SetEnvironmentVariable($environmentName, $savedEnvironment[$environmentName], 'Process')
    }
}
