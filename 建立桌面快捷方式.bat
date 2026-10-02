@echo off
rem 在桌面创建"图片工具箱"快捷方式（需要先打包 exe）。
cd /d "%~dp0"
if not exist "dist\图片工具箱.exe" (
    echo 未找到 dist\图片工具箱.exe，请先按 README 打包，再运行本脚本。
    pause
    exit /b
)
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\图片工具箱.lnk'); $lnk.TargetPath = '%~dp0dist\图片工具箱.exe'; $lnk.WorkingDirectory = '%~dp0dist'; $lnk.IconLocation = '%~dp0assets\icon.ico,0'; $lnk.Save()"
echo 已在桌面创建快捷方式。
pause
