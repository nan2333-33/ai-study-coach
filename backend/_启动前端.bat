@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title AI学习助手-前端
echo.
echo   前端启动中，地址 http://127.0.0.1:8123
echo   这个窗口不要关，关了网页就打不开了。
echo.
"%~dp0.venv\Scripts\python.exe" -m http.server 8123 --bind 127.0.0.1
echo.
echo   前端已停止。
pause
