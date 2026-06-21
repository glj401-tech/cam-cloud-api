@echo off
chcp 65001 >nul
rem ====================================================================
rem  Fusion360 CAM Cloud AI Process Recommender 鈥?One-Click Launcher
rem  Service: FastAPI on port 8000 + AI 3D Gen MCP Server (v1.5)
rem  Path:    D:\CAM_CLOUD_API\start_service.bat
rem  Usage:   Double-click to start, Ctrl+C to stop
rem ====================================================================

title CAM Cloud AI Service [Port 8000]

echo ================================================================
echo    Fusion360 CAM Cloud AI Process Recommender v1.5.0
echo    Local FastAPI Relay Service + Ollama Backend + AI 3D Gen
echo ================================================================
echo.

rem --- Ollama Local Model Configuration ---
rem *** 纭繚宸插畨瑁?Ollama 骞舵媺鍙栨墍闇€妯″瀷 ***
rem *** 瀹夎: https://ollama.com/download ***
rem *** 鎷夊彇: ollama pull qwen2.5:7b-instruct-q4_K_M (鎴栧叾浠栫増鏈? ***
set OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
set OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M

rem --- v1.5: AI 3D Generation API Keys ---
rem *** Hunyuan3D (鎺ㄨ崘, 鍏嶈垂20娆?澶?: https://3d.hunyuanglobal.com ***
rem *** 鍦ㄦ璁剧疆浣犵殑 API Key (鏇夸唬涓嬫柟 your_key_here) ***
rem 鈽?璇峰厛璁剧疆鐜鍙橀噺 HUNYUAN3D_API_KEY锛屾垨鍦ㄤ笅鏂瑰～鍏ヤ綘鐨?API Key 鈽?rem 鈽?娉ㄥ唽鍦板潃: https://3d.hunyuanglobal.com 鈽?if "%HUNYUAN3D_API_KEY%"=="" (
    set HUNYUAN3D_API_KEY=your_key_here
)
if "%HUNYUAN3D_API_KEY%"=="your_key_here" (
    echo [WARN]  HUNYUAN3D_API_KEY not configured 鈥?AI 3D text/image-to-3D disabled
    echo         Register at: https://3d.hunyuanglobal.com
    echo         Then edit start_service.bat and replace 'your_key_here'
) else if "%HUNYUAN3D_API_KEY%"=="" (
    echo [WARN]  HUNYUAN3D_API_KEY not set 鈥?AI 3D disabled
) else (
    echo [INFO]  Hunyuan3D API Key: configured
)

rem --- Check FreeCAD (for mesh-to-STEP conversion) ---
where freecadcmd >nul 2>&1
if errorlevel 1 (
    echo [WARN]  FreeCAD not found 鈥?STEP conversion disabled, will output OBJ
    echo         Download: https://www.freecad.org/downloads.php
) else (
    echo [INFO]  FreeCAD detected 鈥?STEP conversion available
)

echo.

rem --- Check Ollama connectivity ---
echo [INFO]  Checking Ollama service...
curl -s --connect-timeout 3 --max-time 5 http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [WARN]  Ollama service not reachable at http://127.0.0.1:11434
    echo         Please install and start Ollama first:
    echo         1. Download: https://ollama.com/download
    echo         2. Run: ollama serve
    echo         3. Pull model: ollama pull %OLLAMA_MODEL%
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
python -c "import fastapi, openai" >nul 2>&1
if errorlevel 1 (
    echo [WARN]  Dependencies missing. Auto-installing...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed! Check your network.
        pause
        exit /b 1
    )
    echo [INFO]  Dependencies installed successfully!
    echo.
)

rem --- Check v1.5 new deps ---
python -c "import fastmcp, trimesh, PIL" >nul 2>&1
if errorlevel 1 (
    echo [WARN]  v1.5 new dependencies missing. Installing...
    pip install fastmcp trimesh pymeshlab Pillow requests
    rem 鈽?淇 starlette 鐗堟湰鍐茬獊 (mcp 鍖呬細瀹夎涓嶅吋瀹圭殑 starlette 1.x fork)
    pip install "starlette>=0.37.2,<0.39.0" 2>nul
    if errorlevel 1 (
        echo [WARN]  Some v1.5 deps failed to install. AI 3D Gen may not work.
    ) else (
        echo [INFO]  v1.5 dependencies installed!
    )
    echo.
)

rem --- Start the service ---
echo [INFO]  Starting service on http://127.0.0.1:8000
echo [INFO]  CAM API:     http://127.0.0.1:8000/get_craft
echo [INFO]  AI 3D MCP:   http://127.0.0.1:8000/mcp
echo [INFO]  Swagger docs: http://127.0.0.1:8000/docs
echo [INFO]  Press Ctrl+C to stop
echo ================================================================
echo.

python cam_cloud_api.py

pause