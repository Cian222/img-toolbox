@echo off
rem 图片工具箱快捷启动：优先用打包好的 exe，没有则退回 Python 源码运行。
rem 支持透传参数，例如：启动图片工具箱.bat --selftest 或 --layout nav
cd /d "%~dp0"
if exist "dist\图片工具箱.exe" (
    start "" "dist\图片工具箱.exe" %*
    exit /b
)
echo 未找到打包版 exe，改用 Python 源码运行...
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py %*
) else (
    echo 未找到 Python。请先安装依赖：pip install -r requirements.txt
    echo 或按 README 打包 exe 后再运行。
    pause
)
