@echo off
cd /d %~dp0
echo 正在停止债权申报与审查系统...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run.py*' -or $_.CommandLine -like '*run_verified.py*' -or $_.CommandLine -like '*app.main:app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 1 >nul
echo 已停止。如需重启，双击 start_hidden.bat
pause
