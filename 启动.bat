@echo off
chcp 65001 >nul
cd /d "%~dp0."
title AI 学习助手 - 启动菜单

:MENU
cls
echo.
echo   ==========================================
echo         AI 学习助手 - 启动菜单
echo   ==========================================
echo.
echo        1   填写密钥（只需做一次）
echo        2   检查密钥是否填好
echo        3   启动后端（自动装依赖，弹出新窗口别关）
echo        4   启动前端（弹出新窗口，别关）
echo        5   打开浏览器
echo        9   跑一遍完整自检（上传-对话-出题-周报）
echo        0   退出
echo.
echo   ------------------------------------------
echo     第一次用：1 填密钥，然后 3、4、5
echo     密钥已填好：直接 3、4、5
echo     也可以直接双击「启动后端.bat」只启后端
echo   ------------------------------------------
echo.
set /p CHOICE=请输入数字后按回车:

if "%CHOICE%"=="1" goto FILL
if "%CHOICE%"=="2" goto CHECK
if "%CHOICE%"=="3" goto BACKEND
if "%CHOICE%"=="4" goto FRONTEND
if "%CHOICE%"=="5" goto OPEN
if "%CHOICE%"=="9" goto SELFTEST
if "%CHOICE%"=="0" goto END
goto MENU

:FILL
cls
echo.
echo   配置向导：除了两个 Key 要粘贴，其他项直接按回车跳过。
echo.
cd /d "%~dp0backend\."
"%~dp0backend\.venv\Scripts\python.exe" setup_env.py
cd /d "%~dp0."
echo.
pause
goto MENU

:CHECK
cls
echo.
cd /d "%~dp0backend\."
"%~dp0backend\.venv\Scripts\python.exe" setup_env.py --check
cd /d "%~dp0."
echo.
pause
goto MENU

:BACKEND
cls
echo.
echo   已在新窗口启动后端（http://127.0.0.1:5000），那个窗口不要关。
echo   首次运行会自动创建虚拟环境并安装依赖，需要几分钟。
echo.
start "AI学习助手-后端" cmd /k call "%~dp0启动后端.bat"
timeout /t 3 >nul
goto MENU

:FRONTEND
cls
echo.
echo   已在新窗口启动前端（http://127.0.0.1:8123），那个窗口不要关。
echo.
start "AI学习助手-前端" cmd /k call "%~dp0backend\_启动前端.bat"
timeout /t 3 >nul
goto MENU

:OPEN
start "" "http://127.0.0.1:8123"
goto MENU

:SELFTEST
cls
echo.
echo   正在跑完整自检（会真实调用大模型，产生极少量费用），请稍候...
echo.
cd /d "%~dp0backend\."
"%~dp0backend\.venv\Scripts\python.exe" tests\test_apikey_live.py
echo.
"%~dp0backend\.venv\Scripts\python.exe" tests\test_e2e_live.py
cd /d "%~dp0."
echo.
pause
goto MENU

:END
exit
