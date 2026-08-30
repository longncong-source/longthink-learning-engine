# ============================================================================
# Second Brain backup (spec section 45) - works with both backends.
#   PostgreSQL : docker exec pg_dump (custom format) -> backups\*.dump
#   SQLite     : file copy                            -> backups\*.sqlite3
# Usage:  .\scripts\backup.ps1 [-KeepDays 30] [-OutputDir backups]
# ============================================================================

param(
    [string]$OutputDir = "",
    [int]$KeepDays = 30
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $root "backups" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

# --- read cloud/.env (simple KEY=VALUE parsing, comments ignored) ---
$settings = @{}
$envFile = Join-Path $root "cloud\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and $_ -notmatch '^\s*#') {
            $settings[$matches[1].ToUpper()] = $matches[2]
        }
    }
}
$backend = if ($settings.ContainsKey("MEMORY_DB_BACKEND")) { $settings["MEMORY_DB_BACKEND"] } else { "sqlite" }

if ($backend -eq "postgres") {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "MEMORY_DB_BACKEND=postgres needs Docker (container fsb-db) for pg_dump."
        exit 1
    }
    $dbUser = if ($settings.ContainsKey("POSTGRES_USER")) { $settings["POSTGRES_USER"] } else { "second_brain" }
    $dbName = if ($settings.ContainsKey("POSTGRES_DB")) { $settings["POSTGRES_DB"] } else { "second_brain" }
    Write-Host "Backing up PostgreSQL ($dbName) via container fsb-db..."
    docker exec fsb-db pg_dump -U $dbUser -d $dbName -F c -f /tmp/fsb-backup.dump
    if ($LASTEXITCODE -ne 0) { exit 1 }
    $target = Join-Path $OutputDir "second_brain-$stamp.dump"
    docker cp "fsb-db:/tmp/fsb-backup.dump" $target
    docker exec fsb-db rm /tmp/fsb-backup.dump | Out-Null
} else {
    $db = Join-Path $root "data\second_brain.sqlite3"
    if (-not (Test-Path $db)) {
        Write-Error "SQLite database not found at $db"
        exit 1
    }
    $target = Join-Path $OutputDir "second_brain-$stamp.sqlite3"
    # Use the sqlite3 online-backup API so WAL contents are included.
    # A raw file copy of just *.sqlite3 would miss recent writes living in -wal.
    $py = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $py) {
        $env:FSB_SRC = $db
        $env:FSB_DST = $target
        & $py -c "import os, sqlite3; s = sqlite3.connect(os.environ['FSB_SRC']); d = sqlite3.connect(os.environ['FSB_DST']); s.backup(d); d.close(); s.close()"
        Remove-Item Env:FSB_SRC, Env:FSB_DST -ErrorAction SilentlyContinue
        if ($LASTEXITCODE -ne 0) { Write-Error "sqlite backup failed"; exit 1 }
    } else {
        # fallback without venv: copy database plus WAL sidecars
        Copy-Item $db $target -Force
        foreach ($sidecar in @("$db-wal", "$db-shm")) {
            if (Test-Path $sidecar) {
                Copy-Item $sidecar "$target$(if ($sidecar -like '*-wal') { '-wal' } else { '-shm' })" -Force
            }
        }
    }
}

Write-Host "Backup written: $target"

# --- retention ---
$cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem $OutputDir -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Remove-Item $_.FullName -Force; Write-Host "pruned old backup: $($_.Name)" }

Write-Host "Done."
