@echo off
cd /d %~dp0
echo === DIAG RESULT === > diag_result.txt
echo Generated: %date% %time% >> diag_result.txt
echo. >> diag_result.txt
echo [1] Python version >> diag_result.txt
python --version >> diag_result.txt 2>&1
echo. >> diag_result.txt
echo [2] Port 8000 usage >> diag_result.txt
netstat -ano | findstr ":8000" >> diag_result.txt
echo. >> diag_result.txt
echo [3] Port 8001-8009 usage >> diag_result.txt
netstat -ano | findstr ":800[1-9]" >> diag_result.txt
echo. >> diag_result.txt
echo [4] Python processes >> diag_result.txt
tasklist | findstr /i python >> diag_result.txt
echo. >> diag_result.txt
echo [5] Current dir >> diag_result.txt
cd >> diag_result.txt
echo. >> diag_result.txt
echo [6] Smoke test (code health) >> diag_result.txt
python smoke_test.py >> diag_result.txt 2>&1
echo. >> diag_result.txt
echo === DIAG DONE === >> diag_result.txt
type diag_result.txt
echo.
echo Result saved to diag_result.txt - copy its content and send to admin.
pause
