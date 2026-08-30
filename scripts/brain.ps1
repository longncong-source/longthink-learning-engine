# brain CLI wrapper for PowerShell (repo root)
# Usage: .\scripts\brain.ps1 doctor   /   .\scripts\brain.ps1 memory search "..."

$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $root ".venv\Scripts\python.exe") -m local.brain_cli @args
exit $LASTEXITCODE
