# ODC Studio launcher — :3001 visual orchestration
param([switch]$Stop, [switch]$Status)

$root = Split-Path -Parent $PSScriptRoot
$port = 3001

function Test-ODC {
    try { $r = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2; return $r.status -eq "ok" } catch { return $false }
}

if ($Status) {
    if (Test-ODC) { Write-Host "[ODC] online http://127.0.0.1:$port/ + proxy http://127.0.0.1:8100/odc/" -ForegroundColor Green; Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 3 | ConvertTo-Json | Write-Host }
    else { Write-Host "[ODC] offline — run .\scripts\odc.ps1" -ForegroundColor Yellow }
    exit 0
}
if ($Stop) {
    Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*\.venv*" } | ForEach-Object {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        if ($cmd -like "*odc_studio*") { Stop-Process -Id $_.Id -Force; Write-Host "Stopped ODC pid $($_.Id)" -ForegroundColor Yellow }
    }
    exit 0
}

if (Test-ODC) { Write-Host "[ODC] already online http://127.0.0.1:$port/" -ForegroundColor Green; exit 0 }

Write-Host "[ODC] starting :$port ..." -ForegroundColor Cyan
Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","odc_studio.main:app","--host","127.0.0.1","--port","$port" -WorkingDirectory $root -WindowStyle Hidden -PassThru | Out-Null
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    if (Test-ODC) { Write-Host "[ODC] online http://127.0.0.1:$port/ → proxy http://127.0.0.1:8100/odc/" -ForegroundColor Green; exit 0 }
    Start-Sleep -Seconds 1
}
Write-Host "[ODC] failed to start" -ForegroundColor Red
exit 1
