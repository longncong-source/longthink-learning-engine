# Start the Second Brain API on :8100 (SQLite mode). No-op if already running.
param([int]$Port = 8100)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
try {
    if (((Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2).status) -eq "ok") {
        Write-Host "API already running at http://127.0.0.1:$Port"; exit 0
    }
} catch {}
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","cloud.app.main:app","--host","127.0.0.1","--port",$Port `
    -WorkingDirectory $root -WindowStyle Hidden
$deadline = (Get-Date).AddMinutes(2)
while ((Get-Date) -lt $deadline) {
    try { if (((Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2).status) -eq "ok") {
        Write-Host "API started at http://127.0.0.1:$Port"; exit 0 } } catch {}
    Start-Sleep -Seconds 2
}
Write-Host "API failed to start - check logs"; exit 1
