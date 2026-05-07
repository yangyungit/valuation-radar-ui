@echo off
REM =============================================================================
REM start_dev.bat — Valuation Radar 一键开发环境启动脚本 (Windows)
REM
REM 目录约定（推荐，也会自动回退到其他位置）：
REM   <parent>\
REM   ├── valuation-radar\       ← 后端
REM   ├── valuation-radar-ui\    ← 前端（本脚本所在目录）
REM   └── system\venv\           ← 共享虚拟环境
REM
REM 用法：双击运行，或在 cmd 中执行 start_dev.bat
REM =============================================================================

SETLOCAL ENABLEDELAYEDEXPANSION

SET SCRIPT_DIR=%~dp0
REM 去掉末尾反斜杠
IF "%SCRIPT_DIR:~-1%"=="\" SET SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

REM 获取父目录
FOR %%I IN ("%SCRIPT_DIR%\..") DO SET PARENT_DIR=%%~fI
SET BACKEND_DIR=%PARENT_DIR%\valuation-radar

REM ── 1. 自动探测前后端各自的虚拟环境 ──────────────────────────────────────
SET FRONTEND_VENV_ACTIVATE=
SET BACKEND_VENV_ACTIVATE=

IF EXIST "%PARENT_DIR%\system\venv\Scripts\activate.bat" (
    SET FRONTEND_VENV_ACTIVATE=%PARENT_DIR%\system\venv\Scripts\activate.bat
) ELSE IF EXIST "%SCRIPT_DIR%\venv\Scripts\activate.bat" (
    SET FRONTEND_VENV_ACTIVATE=%SCRIPT_DIR%\venv\Scripts\activate.bat
) ELSE IF EXIST "%SCRIPT_DIR%\.venv\Scripts\activate.bat" (
    SET FRONTEND_VENV_ACTIVATE=%SCRIPT_DIR%\.venv\Scripts\activate.bat
) ELSE IF EXIST "%PARENT_DIR%\venv\Scripts\activate.bat" (
    SET FRONTEND_VENV_ACTIVATE=%PARENT_DIR%\venv\Scripts\activate.bat
)

IF EXIST "%BACKEND_DIR%\venv\Scripts\activate.bat" (
    SET BACKEND_VENV_ACTIVATE=%BACKEND_DIR%\venv\Scripts\activate.bat
) ELSE IF EXIST "%BACKEND_DIR%\.venv\Scripts\activate.bat" (
    SET BACKEND_VENV_ACTIVATE=%BACKEND_DIR%\.venv\Scripts\activate.bat
) ELSE IF EXIST "%PARENT_DIR%\system\venv\Scripts\activate.bat" (
    SET BACKEND_VENV_ACTIVATE=%PARENT_DIR%\system\venv\Scripts\activate.bat
) ELSE IF EXIST "%PARENT_DIR%\venv\Scripts\activate.bat" (
    SET BACKEND_VENV_ACTIVATE=%PARENT_DIR%\venv\Scripts\activate.bat
)

IF "%FRONTEND_VENV_ACTIVATE%"=="" (
    echo.
    echo ERROR: 找不到前端 Python 虚拟环境，已搜索以下路径：
    echo   · %PARENT_DIR%\system\venv
    echo   · %SCRIPT_DIR%\venv
    echo   · %SCRIPT_DIR%\.venv
    echo   · %PARENT_DIR%\venv
    echo.
    echo 请先为前端创建虚拟环境。
    pause
    exit /b 1
)

IF "%BACKEND_VENV_ACTIVATE%"=="" (
    echo.
    echo ERROR: 找不到后端 Python 虚拟环境，已搜索以下路径：
    echo   · %BACKEND_DIR%\venv
    echo   · %BACKEND_DIR%\.venv
    echo   · %PARENT_DIR%\system\venv
    echo   · %PARENT_DIR%\venv
    echo.
    echo 请先为后端创建虚拟环境。
    pause
    exit /b 1
)

echo [OK] 前端虚拟环境: %FRONTEND_VENV_ACTIVATE%
echo [OK] 后端虚拟环境: %BACKEND_VENV_ACTIVATE%
CALL "%FRONTEND_VENV_ACTIVATE%"

REM ── 2. 检查后端目录 ────────────────────────────────────────────────────────
IF NOT EXIST "%BACKEND_DIR%" (
    echo.
    echo ERROR: 找不到后端目录: %BACKEND_DIR%
    echo 请确认 valuation-radar 与 valuation-radar-ui 位于同一父目录下。
    pause
    exit /b 1
)

REM ── 3. 在新窗口中启动后端 ─────────────────────────────────────────────────
echo [>>] 启动后端 API 服务 (http://localhost:8000) ...
START "Valuation Radar - Backend" cmd /k "CALL "%BACKEND_VENV_ACTIVATE%" && cd /d "%BACKEND_DIR%" && python api_server.py"

REM 等待后端初始化
timeout /t 3 /nobreak >nul

REM ── 4. 在当前窗口启动前端 ─────────────────────────────────────────────────
echo [>>] 启动前端 Streamlit (http://localhost:8501) ...
SET RADAR_API_URL=http://localhost:8000
SET USE_LOCAL_API=true
echo [OK] 前端 API 目标已锁定: %RADAR_API_URL%
cd /d "%SCRIPT_DIR%"
streamlit run app.py

ENDLOCAL
