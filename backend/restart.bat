@echo off
cd /d %~dp0
echo ============================================
echo   One-click restart (stop old, start new)
echo ============================================
echo   Step 1: stopping old service...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' -or $_.CommandLine -like '*run_verified.py*' -or $_.CommandLine -like '*app.main:app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 3 >nul
echo   Step 2: old service stopped. Starting new version...
start "ClaimsSystem" cmd /k python run_verified.py
timeout /t 2 >nul
echo   Done. Check the new window for startup log.
echo   If it says OLD VERSION still running, close this and run stop.bat again.
echo.
