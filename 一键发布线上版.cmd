@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publish-online.ps1"
set "publish_code=%errorlevel%"
echo.
if not "%publish_code%"=="0" (
  echo 发布失败，请把 data\deploy\logs 中最新的日志交给技术人员检查。
) else (
  echo 发布完成。
)
pause
exit /b %publish_code%
