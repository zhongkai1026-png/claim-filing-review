@echo off
cd /d %~dp0
echo ============================================
echo  Bankruptcy Claim Review System - Launcher
echo  Auto-picks a free port (8000, 8001, ...)
echo  Browser will open automatically
echo  Close this window to stop the server
echo ============================================
python run.py
pause
