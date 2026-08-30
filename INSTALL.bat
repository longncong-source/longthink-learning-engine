@echo off
title LongThink Learning Engine - One Click Setup
echo ============================================================
echo   LongThink Learning Engine - One Click Installer
echo   First Brain (local) + Second Brain (cloud) - FastAPI+pgvector
echo ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup.ps1"
echo.
echo ============================================================
echo   Log day du: installer\setup.log
echo   Chay lai bat ky luc nao: double-click file nay
echo ============================================================
pause
