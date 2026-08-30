# ============================================================================
# First Brain + Second Brain - one-time setup for Windows (PowerShell)
# Keeps the legacy document-RAG stack untouched.
# ============================================================================

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "..")

Write-Host "== 1/5 Python venv =="
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "== 2/5 Install dependencies (brain stack) =="
.\.venv\Scripts\python.exe -m pip install `
    -r cloud\requirements.txt `
    -r local\requirements.txt `
    -r requirements-dev.txt

Write-Host "== 3/5 Environment files =="
if (-not (Test-Path "cloud\.env")) { Copy-Item "cloud\.env.example" "cloud\.env"; Write-Host "  created cloud\.env (edit MEMORY_API_KEYS!)" }
if (-not (Test-Path "local\.env")) { Copy-Item "local\.env.example" "local\.env"; Write-Host "  created local\.env" }

Write-Host "== 4/5 Docker PostgreSQL/pgvector stack (optional, skipped if Docker missing) =="
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    docker compose -f docker-compose.brain.yml up -d --build
    Write-Host "  brain stack up: api=http://127.0.0.1:8100 db=localhost:5433"
} else {
    Write-Host "  Docker not found - SQLite fallback will be used (loop still fully works)."
    Write-Host "  Install Docker Desktop later, then re-run this step."
}

Write-Host "== 5/5 Smoke test =="
.\.venv\Scripts\python.exe -m pytest cloud\tests local\tests -q
.\.venv\Scripts\python.exe -m local.brain_cli doctor --quick

Write-Host ""
Write-Host "Next steps:"
Write-Host "  .\.venv\Scripts\python.exe -m uvicorn cloud.app.main:app --port 8100"
Write-Host "  .\.venv\Scripts\python.exe -m local.brain_cli demo --yes"
