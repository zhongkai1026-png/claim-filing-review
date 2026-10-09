@echo off
cd /d %~dp0
echo ============================================
echo   LAN Share Setup - allow others to access
echo ============================================
echo.

rem ---- elevate to admin (needed for firewall rule) ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Step 1: opening firewall for ports 8000-8020 ...
netsh advfirewall firewall delete rule name="ClaimsSystem" >nul 2>&1
netsh advfirewall firewall add rule name="ClaimsSystem" dir=in action=allow protocol=TCP localport=8000-8020
echo   firewall rule added.
echo.

echo Step 2: your LAN IP addresses:
echo.
ipconfig | findstr /R /C:"IPv4"
echo.
echo ============================================
echo   Share this address with colleagues:
echo   http://YOUR_IP:PORT   (port is 8000 by
echo   default, or the number shown in the server
echo   startup window, e.g. 8001 if 8000 is busy)
echo ============================================
echo.
echo Reminder: start the server first (restart.bat
echo or python run_verified.py), then colleagues on
echo the SAME WiFi/LAN can open the address above.
echo.
pause
