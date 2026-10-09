@echo off
cd /d %~dp0
echo 正在后台启动系统（关闭本窗口不影响运行）...
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw run.py
) else (
    start "" python run.py
)
timeout /t 2 >nul
echo.
echo 已发送后台启动命令。
echo 浏览器将自动打开；如未打开，请手动访问：
echo   http://127.0.0.1:8000   (8000 被占用时自动用 8001/8002...)
echo.
echo 提示：查看运行状态或停止服务，请使用同目录下的 stop.bat
timeout /t 4 >nul
