# ============================================================================
# LongThink Learning Engine - One Click Setup
#   First Brain (local) + Second Brain (cloud) - deep-learning ready
#   1. Python 3.11+      (winget if missing)
#   2. venv + deps       (offline-safe: hash embeddings fallback)
#   3. .env files        (dev-local-key defaults, gitignored)
#   4. Ollama (optional) - embeddings upgrade, auto model pick
#   5. Start API :8100   (skips if already healthy) - http://127.0.0.1:8100/ui/
#   6. Run demo --yes    (full loop PASS = install verified)
# Everything is best-effort except steps 1-3: the stack works fully offline
# with SQLite + hash embeddings even with zero extra software.
# ============================================================================

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $PSScriptRoot "setup.log"
Start-Transcript -Path $log -Force | Out-Null

function Info($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    [!]  $m" -ForegroundColor Yellow }

$venvPy = Join-Path $root ".venv\Scripts\python.exe"

# ---------------------------------------------------------------- 1. Python
Info "1/6 Kiem tra Python 3.11+"
$pyCandidates = @()
if (Test-Path $venvPy) { $pyCandidates += $venvPy }
$pyCandidates += @("python", "py -3")
foreach ($cand in @("python", "py")) {
    try {
        $v = & $cand --version 2>$null
        if ($v -match "Python 3\.(\d+)") { $pyCandidates += $cand; break }
    } catch {}
}
$pythonCmd = $null
foreach ($c in $pyCandidates) {
    try {
        $parts = $c.Split(' ')
        $v = (& $parts[0] $parts[1..($parts.Length-1)] --version 2>$null) -join ''
        if ($v -match "Python 3\.(11|12|13|14)") { $pythonCmd = $c; Ok "$v ($c)"; break }
    } catch {}
}
if (-not $pythonCmd) {
    Warn "Khong thay Python - dang cai qua winget (can bam Yes neu UAC hoi)"
    winget install --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    # refresh PATH for this session
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python3.12\python.exe")) {
        if (Test-Path $p) { $pythonCmd = "`"$p`""; break }
    }
    if (-not $pythonCmd) { throw "Python chua duoc cai. Chay lai INSTALL.bat sau khi cai Python 3.12." }
    Ok "Da cai Python"
}
$pyExe = $pythonCmd.Split(' ')[0]
$pyArgs = $pythonCmd.Split(' ')[1..($pythonCmd.Split(' ').Length-1)]

# ---------------------------------------------------------------- 2. venv + deps
Info "2/6 Tao venv + cai dependencies (lan dau ~2 phut)"
if (-not (Test-Path $venvPy)) {
    & $pyExe @pyArgs -m venv .venv
}
& $venvPy -m pip install --upgrade pip -q
& $venvPy -m pip install -q -r cloud\requirements.txt -r cloud\requirements-documents.txt
Ok "Dependencies san sang"

# ---------------------------------------------------------------- 4 (early): Ollama detection
Info "3/6 Phat hien Ollama (tuy chon - nang chat luong embedding)"
$ollamaReady = $false
$chatModel = $null
try {
    $ver = (cmd /c "ollama --version 2>NUL") -join ''
    if ($ver) {
        try {
            Invoke-RestMethod -Uri http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null
            $ollamaReady = $true
        } catch {
            Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
            Start-Sleep -Seconds 4
            try { Invoke-RestMethod -Uri http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null; $ollamaReady = $true } catch {}
        }
        if ($ollamaReady) {
            Info "Tai embedding model nomic-embed-text (~274MB, bo qua neu da co)"
            # cmd /c swallows ollama's stderr progress safely (EAP=Stop turns
            # native stderr via 2>&1 into a terminating error otherwise)
            cmd /c "ollama pull nomic-embed-text > NUL 2>&1"
            try {
                $names = (Invoke-RestMethod -Uri http://127.0.0.1:11434/api/tags -TimeoutSec 5).models.name
                $chatModel = $names |
                    Where-Object { $_ -and $_ -notmatch "embed|minilm|bge-|e5-" } |
                    Sort-Object { if ($_ -match "gemma|llama|qwen|mistral") { 0 } else { 1 } } |
                    Select-Object -First 1
            } catch {}
        }
    }
} catch {}
if ($ollamaReady) {
    Ok ("Ollama OK" + $(if ($chatModel) { " - LLM: $chatModel" } else { " - se pull LLM tu do" }))
} else {
    Warn "Khong co Ollama - dung hash embedding offline (van search duoc), LLM=EchoLLM"
}

# ---------------------------------------------------------------- 3. .env files
Info "4/6 Tao file cau hinh .env"
$embProvider = if ($ollamaReady) { "ollama" } else { "hash" }
$embDim      = if ($ollamaReady) { "768" } else { "384" }
$llmModel    = if ($chatModel) { $chatModel } else { "llama3.2" }

if (-not (Test-Path "cloud\.env")) {
@"
ENVIRONMENT=development
MEMORY_DB_BACKEND=sqlite
SQLITE_PATH=data/second_brain.sqlite3
DATABASE_URL=postgresql://second_brain:second_brain@localhost:5433/second_brain
MEMORY_API_KEYS=dev-local-key
EMBEDDING_PROVIDER=$embProvider
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=$embDim
EMBEDDING_BASE_URL=http://localhost:11434
WEIGHT_SEMANTIC=0.60
WEIGHT_KEYWORD=0.20
WEIGHT_IMPORTANCE=0.10
WEIGHT_RECENCY=0.10
RECENCY_HALF_LIFE_DAYS=30
DEDUPE_THRESHOLD=0.92
RATE_LIMIT_PER_MINUTE=240
"@ | Set-Content cloud\.env -Encoding UTF8
    Ok "cloud/.env (embedding=$embProvider)"
} else { Ok "cloud/.env da ton tai - giu nguyen" }

if (-not (Test-Path "local\.env")) {
@"
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=$llmModel
LLM_API_KEY=
SECOND_BRAIN_URL=http://127.0.0.1:8100
SECOND_BRAIN_API_KEY=dev-local-key
MEMORY_TOP_K=8
DATA_POLICY=selective
CACHE_TTL_SECONDS=600
LOCAL_DATA_DIR=local_data
REQUEST_TIMEOUT_SECONDS=30
"@ | Set-Content local\.env -Encoding UTF8
    Ok "local/.env (llm=$llmModel)"
} else { Ok "local/.env da ton tai - giu nguyen" }

New-Item -ItemType Directory -Force -Path data, backups, local_data | Out-Null

# ---------------------------------------------------------------- 5. Start API
Info "5/6 Khoi dong Memory API (:8100)"
$apiUp = $false
try { $apiUp = ((Invoke-RestMethod -Uri http://127.0.0.1:8100/health -TimeoutSec 2).status -eq "ok") } catch {}
if ($apiUp) {
    Ok "API da chay san (Docker hoac instance khac) - dung lai"
} else {
    Start-Process -FilePath $venvPy `
        -ArgumentList "-m","uvicorn","cloud.app.main:app","--host","127.0.0.1","--port","8100" `
        -WorkingDirectory $root -WindowStyle Hidden
    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        try { if (((Invoke-RestMethod -Uri http://127.0.0.1:8100/health -TimeoutSec 2).status -eq "ok")) { $apiUp = $true; break } } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $apiUp) { throw "API khong khoi dong duoc - xem installer\setup.log va uvicorn log" }
    Ok "API chay tai http://127.0.0.1:8100"
}

# ---------------------------------------------------------------- 6. Demo verification
Info "6/6 Chay demo kiem chung (full loop OBSERVE->STORE)"
$env:PYTHONPATH = $root
& $venvPy -m local.brain_cli demo --yes 2>&1 | Tee-Object -Variable demoOut | Select-Object -Last 6
$demoPass = ($demoOut -join "`n") -match "\[PASS\]"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
if ($demoPass) {
    Write-Host "  CAI DAT THANH CONG - DEMO [PASS]" -ForegroundColor Green
} else {
    Write-Host "  Demo chua PASS - xem log: installer\setup.log" -ForegroundColor Yellow
}
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Su dung hang ngay:" -ForegroundColor White
Write-Host "    .\scripts\brain.ps1 status                        # trang thai"
Write-Host "    .\scripts\brain.ps1 memory add --title `"Tieu de`" --content `"kien thuc`"  # luu"
Write-Host "    .\scripts\brain.ps1 memory search `"tu khoa`"      # tim kiem"
Write-Host "    .\scripts\brain.ps1 doctor                        # chan doan"
Write-Host "    .\scripts\serve.ps1                               # khoi dong API"
Write-Host "  Docker (PostgreSQL that, neu may co Docker):"
Write-Host "    docker compose -f docker-compose.brain.yml up -d --build"
Write-Host ""

Stop-Transcript | Out-Null
