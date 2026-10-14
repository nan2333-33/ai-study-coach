@echo off
chcp 65001 >nul
cd /d "%~dp0."
title AI 学习助手 - 一键启动

echo.
echo   ==========================================
echo      AI 学习助手 - 一键启动
echo   ==========================================
echo.
echo   第一次运行会自动安装依赖，约 5~10 分钟，请耐心等待。
echo   以后再双击就只要几秒。
echo.

REM ---------- 1. 后端（5000）----------
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo   [后端] 已经在跑了，跳过。
) else (
  echo   [后端] 启动中...
  start "AI学习助手-后端" /min cmd /k call "%~dp0启动后端.bat"
)

REM ---------- 2. 前端（8123）----------
netstat -ano | findstr ":8123" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo   [前端] 已经在跑了，跳过。
) else (
  echo   [前端] 启动中...
  start "AI学习助手-前端" /min cmd /k call "%~dp0backend\_启动前端.bat"
)

REM ---------- 3. 等后端真正就绪再开浏览器 ----------
echo.
echo   等待后端就绪（首次装依赖会久一点，最多等 120 秒）...
set WAIT=0
:WAIT
timeout /t 3 >nul
curl -s -o NUL "http://127.0.0.1:5000/api/materials"
if not errorlevel 1 goto READY
set /a WAIT+=3
if %WAIT% LSS 120 goto WAIT

echo.
echo   等了 120 秒后端还没起来。请检查：
echo.
echo     1) 双击「启动.bat」选 1，把两个 Key 填上（只需一次）
echo     2) 看任务栏那个「AI学习助手-后端」窗口里的红色报错
echo.
pause
exit /b 1

:READY
echo   后端就绪。
echo.
start "" "http://127.0.0.1:8123"
echo   ==========================================
echo      已打开浏览器
echo.
echo      地址： http://127.0.0.1:8123
echo.
echo      建议把这个地址存成书签。
echo      以后开机后双击本文件一次，再点书签即可。
echo.
echo      任务栏那两个黑窗口是服务器，用的时候别关；
echo      用完直接关浏览器就行，不用管它们。
echo   ==========================================
echo.
pause
