# LLM Provider Manager — LongThink (smart, auto-recover)
# Providers: lmstudio (1234/v1) | ollama (11434) | deepseek (api.deepseek.com/v1, chat-only) | auto
param(
    [ValidateSet("status","start","test","doctor","switch")][string]$Action = "status",
    [ValidateSet("lmstudio","ollama","deepseek","auto")][string]$Provider = "auto"
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-LMStudio {
    try { $r = Invoke-RestMethod "http://127.0.0.1:1234/v1/models" -TimeoutSec 3; return $true } catch { return $false }
}
function Test-Ollama {
    try { $r = Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 3; return $true } catch { return $false }
}

if ($Action -eq "status") {
    Write-Host "=== LLM Provider Status ===" -ForegroundColor Cyan
    $lm = Test-LMStudio; $ol = Test-Ollama
    Write-Host "LMStudio (1234): $(if($lm){'ONLINE'}else{'OFFLINE'})" -ForegroundColor $(if($lm){'Green'}else{'Red'})
    if ($lm) {
        try { $m = (Invoke-RestMethod "http://127.0.0.1:1234/v1/models" -TimeoutSec 3).data.id -join ", "; Write-Host "  Models: $m" -ForegroundColor Gray } catch {}
    }
    Write-Host "Ollama (11434): $(if($ol){'ONLINE'}else{'OFFLINE'})" -ForegroundColor $(if($ol){'Green'}else{'Yellow'})
    if ($ol) {
        try {
            $m2 = (Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 3).models.name -join ", "
            Write-Host "  Models: $m2" -ForegroundColor Gray
            if ($m2 -match "deepseek") { Write-Host "  DeepSeek-R1 local available via Ollama (LLM_MODEL=deepseek-r1:8b)" -ForegroundColor Cyan }
        } catch {}
    }
    $dsKey = ""
    try {
        $raw = Get-Content "local\.env" -Raw -ErrorAction Stop
        if ($raw -match '(?m)^DEEPSEEK_API_KEY\s*=\s*(\S+)\s*$') { $dsKey = $Matches[1].Trim() }
    } catch {}
    if (-not $dsKey -and $env:DEEPSEEK_API_KEY) { $dsKey = $env:DEEPSEEK_API_KEY.Trim() }
    if ($dsKey) {
        $masked = if ($dsKey.Length -gt 8) { $dsKey.Substring(0, 5) + "***" + $dsKey.Substring($dsKey.Length - 3) } else { "***" }
        Write-Host "DeepSeek API: KEY SET ($masked) — chat-only, embeddings stay hash/ollama/lmstudio" -ForegroundColor Green
    } else {
        Write-Host "DeepSeek API: NO KEY (set DEEPSEEK_API_KEY in local/.env for cloud chat)" -ForegroundColor DarkGray
    }
    Get-Content "cloud\.env" | Select-String "EMBEDDING_PROVIDER|EMBEDDING_MODEL|EMBEDDING_DIMENSION" | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Get-Content "local\.env" | Select-String "LLM_PROVIDER|LLM_MODEL|LLM_BASE_URL" | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    exit 0
}

if ($Action -eq "test") {
    Write-Host "=== Test LMStudio Chat + Embedding ===" -ForegroundColor Cyan
    $body = @{model="vistral-7b-chat"; messages=@(@{role="user"; content="Chào, nói 1 câu ngắn"}); max_tokens=50; temperature=0.2} | ConvertTo-Json -Depth 4
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:1234/v1/chat/completions" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 20
        Write-Host "Chat OK: $($r.choices[0].message.content)" -ForegroundColor Green
    } catch { Write-Host "Chat FAIL: $_" -ForegroundColor Red }
    $emb = @{model="text-embedding-nomic-embed-text-v1.5"; input=@("hello LongThink")} | ConvertTo-Json
    try {
        $r2 = Invoke-RestMethod "http://127.0.0.1:1234/v1/embeddings" -Method Post -Body $emb -ContentType "application/json" -TimeoutSec 10
        Write-Host "Embedding OK: dim $($r2.data[0].embedding.Count)" -ForegroundColor Green
    } catch { Write-Host "Embedding FAIL: $_" -ForegroundColor Red }
    exit 0
}

if ($Action -eq "doctor") {
    & ".\scripts\brain.ps1" doctor --quick
    exit 0
}

if ($Action -eq "switch") {
    if ($Provider -eq "auto") {
        & "$PSScriptRoot\start_all.ps1"
        exit 0
    }
    $cloudEnv = "cloud\.env"; $localEnv = "local\.env"
    if ($Provider -eq "lmstudio") {
        (Get-Content $cloudEnv -Raw) -replace 'EMBEDDING_PROVIDER=.*','EMBEDDING_PROVIDER=lmstudio' -replace 'EMBEDDING_MODEL=.*','EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5' -replace 'EMBEDDING_DIMENSION=.*','EMBEDDING_DIMENSION=768' -replace 'EMBEDDING_BASE_URL=.*','EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1' | Set-Content $cloudEnv -Encoding utf8
        (Get-Content $localEnv -Raw) -replace 'LLM_PROVIDER=.*','LLM_PROVIDER=lmstudio' -replace 'LLM_MODEL=.*','LLM_MODEL=vistral-7b-chat' -replace 'LLM_BASE_URL=.*','LLM_BASE_URL=http://127.0.0.1:1234/v1' | Set-Content $localEnv -Encoding utf8
        Write-Host "Switched to LMStudio" -ForegroundColor Green
    } elseif ($Provider -eq "ollama") {
        (Get-Content $cloudEnv -Raw) -replace 'EMBEDDING_PROVIDER=.*','EMBEDDING_PROVIDER=ollama' -replace 'EMBEDDING_MODEL=.*','EMBEDDING_MODEL=nomic-embed-text' -replace 'EMBEDDING_DIMENSION=.*','EMBEDDING_DIMENSION=768' -replace 'EMBEDDING_BASE_URL=.*','EMBEDDING_BASE_URL=http://localhost:11434' | Set-Content $cloudEnv -Encoding utf8
        (Get-Content $localEnv -Raw) -replace 'LLM_PROVIDER=.*','LLM_PROVIDER=ollama' -replace 'LLM_MODEL=.*','LLM_MODEL=gemma4:12b' -replace 'LLM_BASE_URL=.*','LLM_BASE_URL=http://127.0.0.1:11434' | Set-Content $localEnv -Encoding utf8
        Write-Host "Switched to Ollama (tip: LLM_MODEL=deepseek-r1:8b for local DeepSeek-R1 after 'ollama pull deepseek-r1:8b')" -ForegroundColor Green
    } elseif ($Provider -eq "deepseek") {
        # DeepSeek cloud is chat-only -> embeddings fall back to hash (offline, dim 384)
        (Get-Content $cloudEnv -Raw) -replace 'EMBEDDING_PROVIDER=.*','EMBEDDING_PROVIDER=hash' -replace 'EMBEDDING_DIMENSION=.*','EMBEDDING_DIMENSION=384' | Set-Content $cloudEnv -Encoding utf8
        $local = Get-Content $localEnv -Raw
        $local = $local -replace 'LLM_PROVIDER=.*','LLM_PROVIDER=deepseek'
        if ($local -notmatch '(?m)^LLM_MODEL\s*=\s*deepseek') { $local = $local -replace '(?m)^LLM_MODEL\s*=.*','LLM_MODEL=deepseek-chat' }
        if ($local -match '(?m)^LLM_BASE_URL\s*=') { $local = $local -replace '(?m)^LLM_BASE_URL\s*=.*','LLM_BASE_URL=https://api.deepseek.com/v1' }
        else { $local = $local.TrimEnd() + "`nLLM_BASE_URL=https://api.deepseek.com/v1`n" }
        $local | Set-Content $localEnv -Encoding utf8
        if ((Get-Content $localEnv -Raw) -notmatch '(?m)^DEEPSEEK_API_KEY\s*=\S') {
            Write-Host "Switched to DeepSeek, BUT DEEPSEEK_API_KEY is empty in local/.env - add your key or chat falls back to EchoLLM" -ForegroundColor Yellow
        } else {
            Write-Host "Switched to DeepSeek (deepseek-chat via api.deepseek.com, embeddings=hash)" -ForegroundColor Green
        }
    }
    Write-Host "Restart API..." -ForegroundColor Cyan
    Get-Process python | Where-Object { $_.Path -like "*\.venv*" } | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
    & "$PSScriptRoot\serve.ps1"
    Start-Sleep -Seconds 5
    & "$PSScriptRoot\brain.ps1" doctor --quick
    exit 0
}

Write-Host "Usage: .\scripts\lmstudio.ps1 [status|test|doctor|switch] [-Provider lmstudio|ollama|deepseek|auto]" -ForegroundColor Yellow
