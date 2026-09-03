# Start All - Auto-detect online/offline mode and start complete system
# Usage: .\scripts\start_all.ps1

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== LongThink Learning Engine - Auto Start ===" -ForegroundColor Cyan

# 0. Ensure Postgres+pgvector (fsb-db :5433) when MEMORY_DB_BACKEND=postgres
try {
    $cloudEnvRaw = ""
    $cloudEnvPath = Join-Path $root "cloud\.env"
    if (Test-Path $cloudEnvPath) { $cloudEnvRaw = Get-Content $cloudEnvPath -Raw }
    if ($cloudEnvRaw -match "MEMORY_DB_BACKEND=postgres") {
        $pgUp = $false
        try {
            & ".\.venv\Scripts\python.exe" -c "import psycopg; psycopg.connect('postgresql://second_brain:second_brain@localhost:5433/second_brain', connect_timeout=3).close()" 2>$null
            if ($LASTEXITCODE -eq 0) { $pgUp = $true }
        } catch {}
        if (-not $pgUp) {
            Write-Host "[PG] Starting fsb-db (pgvector :5433)..." -ForegroundColor Cyan
            try {
                docker compose -f docker-compose.brain.yml up -d fsb-db 2>&1 | Select-Object -Last 2 | Out-Host
                $deadline = (Get-Date).AddMinutes(2)
                while ((Get-Date) -lt $deadline -and -not $pgUp) {
                    Start-Sleep -Seconds 3
                    try {
                        & ".\.venv\Scripts\python.exe" -c "import psycopg; psycopg.connect('postgresql://second_brain:second_brain@localhost:5433/second_brain', connect_timeout=3).close()" 2>$null
                        if ($LASTEXITCODE -eq 0) { $pgUp = $true }
                    } catch {}
                }
            } catch { Write-Host "[PG] docker unavailable: $_" -ForegroundColor Yellow }
        }
        if ($pgUp) { Write-Host "[PG] online :5433 (pgvector)" -ForegroundColor Green }
        else { Write-Host "[PG] NOT reachable - API may fail (MEMORY_DB_BACKEND=postgres)" -ForegroundColor Red }
    }
} catch { Write-Host "[PG] skip: $_" -ForegroundColor Yellow }

# Function to check if Ollama is running
function Test-Ollama {
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}
function Test-LMStudio {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# Function to check if API is running
function Test-API {
    param([int]$Port = 8100)
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 -ErrorAction Stop
        return $response.status -eq "ok"
    } catch {
        return $false
    }
}

# 1. Detect LLM/Embedding availability (priority: LMStudio > Ollama > hash/none)
$lmstudioAvailable = Test-LMStudio
$ollamaAvailable = Test-Ollama
if ($lmstudioAvailable) {
    Write-Host "[LMSTUDIO MODE] LMStudio detected at http://127.0.0.1:1234/v1" -ForegroundColor Green
    try { $models = (Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 3).data.id -join ", "; Write-Host "  Models: $models" -ForegroundColor Gray } catch {}
    $env:EMBEDDING_PROVIDER = "lmstudio"
    $env:LLM_PROVIDER = "lmstudio"
} elseif ($ollamaAvailable) {
    Write-Host "[ONLINE MODE] Ollama detected at http://localhost:11434" -ForegroundColor Green
    $env:EMBEDDING_PROVIDER = "ollama"
    $env:LLM_PROVIDER = "ollama"
} else {
    Write-Host "[OFFLINE MODE] Ollama/LMStudio not available - using hash embeddings fallback" -ForegroundColor Yellow
    $env:EMBEDDING_PROVIDER = "hash"
    $env:LLM_PROVIDER = "none"
}

# 2. Ensure .env files exist with correct settings
$cloudEnv = Join-Path $root "cloud\.env"
$localEnv = Join-Path $root "local\.env"

# Update cloud/.env for embedding provider (preserve LMStudio base/model if needed)
if (Test-Path $cloudEnv) {
    $content = Get-Content $cloudEnv -Raw
    $content = $content -replace 'EMBEDDING_PROVIDER=.*', "EMBEDDING_PROVIDER=$env:EMBEDDING_PROVIDER"
    if ($env:EMBEDDING_PROVIDER -eq "lmstudio") {
        if ($content -notmatch "EMBEDDING_BASE_URL=http://127.0.0.1:1234") {
            $content = $content -replace 'EMBEDDING_BASE_URL=.*', "EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1"
            $content = $content -replace 'EMBEDDING_MODEL=.*', "EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5"
            # LMStudio nomic v1.5 is 768d (not 384)
            $content = $content -replace 'EMBEDDING_DIMENSION=.*', "EMBEDDING_DIMENSION=768"
        }
    }
    Set-Content $cloudEnv -Value $content -Encoding UTF8
    Write-Host "Updated cloud/.env: EMBEDDING_PROVIDER=$env:EMBEDDING_PROVIDER"
}

# Update local/.env for LLM provider
if (Test-Path $localEnv) {
    $content = Get-Content $localEnv -Raw
    $content = $content -replace 'LLM_PROVIDER=.*', "LLM_PROVIDER=$env:LLM_PROVIDER"
    if ($env:LLM_PROVIDER -eq "lmstudio") {
        $content = $content -replace 'LLM_MODEL=.*', "LLM_MODEL=vistral-7b-chat"
        $content = $content -replace 'LLM_BASE_URL=.*', "LLM_BASE_URL=http://127.0.0.1:1234/v1"
    }
    Set-Content $localEnv -Value $content -Encoding UTF8
    Write-Host "Updated local/.env: LLM_PROVIDER=$env:LLM_PROVIDER"
}

# 3. Start API if not running
# Forced OpenCode creds — must match D:\OPENCODE_WEB_HIDDEN.bat (:4096)
$env:OPENCODE_SERVER_USERNAME = "opencode"
$env:OPENCODE_SERVER_PASSWORD = "9de63327-5314-44f7-8525-63a1d4225e82"
if (Test-API) {
    Write-Host "[API] Already running at http://127.0.0.1:8100" -ForegroundColor Green
} else {
    Write-Host "[API] Starting Second Brain API on :8100..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m","uvicorn","cloud.app.main:app","--host","127.0.0.1","--port","8100" `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru
    
    $deadline = (Get-Date).AddMinutes(2)
    $started = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-API) {
            $started = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    
    if ($started) {
        Write-Host "[API] Started successfully at http://127.0.0.1:8100" -ForegroundColor Green
    } else {
        Write-Host "[API] Failed to start - check logs" -ForegroundColor Red
        exit 1
    }
}

# 4. Start ODC Studio :3001 (if not already)
try {
    $odcUp = $false
    try { $r = Invoke-RestMethod "http://127.0.0.1:3001/health" -TimeoutSec 2; if($r.status -eq "ok"){ $odcUp=$true } } catch {}
    if(-not $odcUp){
        Write-Host "[ODC] Starting ODC Studio :3001..." -ForegroundColor Cyan
        Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","odc_studio.main:app","--host","127.0.0.1","--port","3001" -WorkingDirectory $root -WindowStyle Hidden
        Start-Sleep -Seconds 3
        try { $r = Invoke-RestMethod "http://127.0.0.1:3001/health" -TimeoutSec 2; if($r.status -eq "ok"){ Write-Host "[ODC] online http://127.0.0.1:3001/ → http://127.0.0.1:8100/odc/" -ForegroundColor Green } } catch { Write-Host "[ODC] start pending — run .\scripts\odc.ps1" -ForegroundColor Yellow }
    } else {
        Write-Host "[ODC] Already online http://127.0.0.1:3001/" -ForegroundColor Green
    }
} catch { Write-Host "[ODC] skip: $_" -ForegroundColor Yellow }

# 5. Run doctor check
Write-Host "`n[DOCTOR] Running system diagnostics..." -ForegroundColor Cyan
& ".\scripts\brain.ps1" doctor --quick

Write-Host "`n=== System Ready ===" -ForegroundColor Cyan
Write-Host "API: http://127.0.0.1:8100"
Write-Host "UI:  http://127.0.0.1:8100/ui/"
Write-Host "Mode: $($env:LLM_PROVIDER.ToUpper()) / $($env:EMBEDDING_PROVIDER.ToUpper())"
Write-Host ""
Write-Host "Quick commands:"
Write-Host "  .\scripts\brain.ps1 demo --yes     # Run MVP demo"
Write-Host "  .\scripts\brain.ps1 memory search 'query'  # Search memories"
Write-Host "  .\scripts\brain.ps1 obsidian scan  # Scan Obsidian vault"
Write-Host "  curl -H 'X-API-Key: dev-local-key' http://127.0.0.1:8100/v1/mid-brain/process -d '{\"question\":\"...\"}'"

