@echo off
cd /d "%~dp0frontend"
echo 正在启动前端热更新预览；请保持此窗口打开
echo 访问地址：http://localhost:8280/
npm run dev:ui
