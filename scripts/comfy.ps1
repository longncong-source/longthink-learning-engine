# ComfyUI launcher for LongThink (uses same venv if torch available, else system python)
param([int]$Port=8188)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $PSScriptRoot
$comfy="$root\comfyui\main.py"
if(-not (Test-Path $comfy)){ Write-Host "ComfyUI not found at $comfy" -ForegroundColor Red; exit 1 }
Write-Host "Starting ComfyUI :$Port ..." -ForegroundColor Cyan
& "$root\.venv\Scripts\python.exe" "$comfy" --cpu --listen 127.0.0.1 --port $Port
