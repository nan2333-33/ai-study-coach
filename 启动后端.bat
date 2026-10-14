@echo off
chcp 65001 >nul
cd /d "%~dp0."
title AI学习助手-后端启动器

set "BACKEND=%~dp0backend"
set "VENV=%BACKEND%\.venv"
set "PY=%VENV%\Scripts\python.exe"
set "SYSPY="

echo.
echo   ==========================================
echo     后端启动器：自动装依赖 + 启动服务
echo   ==========================================
echo.

REM ---------- 1. 找系统 Python ----------
REM 注意：括号块内不能用 %errorlevel%（会在块解析时提前展开），统一用 "if not errorlevel 1"
where python >nul 2>&1
if not errorlevel 1 set "SYSPY=python"
if not defined SYSPY (
    where py >nul 2>&1
    if not errorlevel 1 set "SYSPY=py"
)
if not defined SYSPY goto NOPYTHON

REM ---------- 2. 没有虚拟环境就创建 ----------
if exist "%PY%" goto DEPS
echo   [1/3] 首次运行，正在创建虚拟环境 backend\.venv ...
"%SYSPY%" -m venv "%VENV%"
if not exist "%PY%" (
    echo.
    echo   创建虚拟环境失败。
    goto FAIL
)
echo         虚拟环境已创建。
echo.

REM ---------- 3. 依赖没装齐就安装 ----------
:DEPS
"%PY%" -c "import flask, chromadb, sqlalchemy, pypdf, docx, pptx, dotenv" >nul 2>&1
if not errorlevel 1 goto RUN

echo   [2/3] 正在安装 Python 依赖（首次约 5~10 分钟，chromadb 体积较大）...
"%PY%" -m pip install -r "%BACKEND%\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120 --retries 5
if not errorlevel 1 goto VERIFY
echo         清华镜像失败，改用官方源重试一次...
"%PY%" -m pip install -r "%BACKEND%\requirements.txt" --timeout 120 --retries 5

:VERIFY
"%PY%" -c "import flask, chromadb, sqlalchemy, pypdf, docx, pptx, dotenv" >nul 2>&1
if errorlevel 1 goto FAILDEPS
echo         依赖已就绪。
echo.

REM ---------- 4. 在虚拟环境里启动后端 ----------
:RUN
echo   [3/3] 启动后端  http://127.0.0.1:5000
echo         这个窗口不要关，关了后端就停了。
echo.
cd /d "%BACKEND%\."
call "%VENV%\Scripts\activate.bat"
python app.py
echo.
echo   后端已停止。
pause
exit /b 0

:NOPYTHON
echo   没有检测到 Python。请先安装 Python 3.10 或更高版本：
echo.
echo       https://www.python.org/downloads/
echo.
echo   安装时务必勾选 "Add Python to PATH"，装完重新双击本文件。
echo.
pause
exit /b 1

:FAILDEPS
echo.
echo   依赖安装失败，多半是网络问题。
echo   可以手动执行下面三条命令再试：
echo.
echo       cd backend
echo       .venv\Scripts\activate
echo       pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:FAIL
echo.
pause
exit /b 1
