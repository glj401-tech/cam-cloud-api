@echo off
rem ====================================================================
rem  Fusion360 CAM Cloud AI Process Recommender — One-Click Launcher
rem  Service: FastAPI on port 8000
rem  Path:    D:\CAM_CLOUD_API\start_service.bat
rem  Usage:   Double-click to start, Ctrl+C to stop
rem ====================================================================

title CAM Cloud AI Service [Port 8000]

echo ================================================================
echo    Fusion360 CAM Cloud AI Process Recommender v1.0.0
echo    Local FastAPI Relay Service
echo ================================================================
echo.

rem --- Alibaba Cloud DashScope API Key ---
rem *** Replace sk-xxx below with your REAL API Key ***
rem *** Get one at: https://dashscope.console.aliyun.com/apiKey ***
set DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

rem --- Check if API Key is configured ---
if "%DASHSCOPE_API_KEY%"=="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" (
    echo [WARN]  API Key is NOT configured!
    echo         Edit line 14 of this file and paste your real key.
    echo         Get key: https://dashscope.console.aliyun.com/apiKey
    echo.
)

rem --- Go to project directory ---
cd /d D:\CAM_CLOUD_API

rem --- Check Python availability ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Install Python 3.10+ first.
    echo         Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [INFO]  Python detected:
python --version
echo.

rem --- Auto-install dependencies if missing ---
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [WARN]  Dependencies missing. Auto-installing...
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [ERROR] Dependency install failed! Check your network.
        pause
        exit /b 1
    )
    echo [INFO]  Dependencies installed successfully!
    echo.
)

rem --- Start the service ---
echo [INFO]  Starting service on http://127.0.0.1:8000
echo [INFO]  API endpoint: http://127.0.0.1:8000/get_craft
echo [INFO]  Swagger docs: http://127.0.0.1:8000/docs
echo [INFO]  Press Ctrl+C to stop
echo ================================================================
echo.

python cam_cloud_api.py

pause
