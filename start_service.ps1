# ===========================================================================
#  Fusion360 CAM Cloud AI Process Recommender — PowerShell Launcher
#  Usage: Right-click → "Run with PowerShell", or run from terminal:
#         powershell -ExecutionPolicy Bypass -File D:\CAM_CLOUD_API\start_service.ps1
# ===========================================================================
$ErrorActionPreference = "Stop"

# --- Alibaba Cloud DashScope API Key ---
# *** Replace sk-xxx below with your REAL API Key ***
# *** Get one at: https://dashscope.console.aliyun.com/apiKey ***
$env:DASHSCOPE_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

if ($env:DASHSCOPE_API_KEY -eq "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") {
    Write-Warning "API Key is NOT configured!"
    Write-Warning "Edit line 8 of this file and paste your real key."
    Write-Warning "Get key: https://dashscope.console.aliyun.com/apiKey"
    Write-Host ""
}

# Go to project directory
Set-Location D:\CAM_CLOUD_API

# Check Python
try {
    $pyVersion = python --version 2>&1
    Write-Host "[INFO] $pyVersion" -ForegroundColor Green
} catch {
    Write-Error "Python not found! Install Python 3.10+ from https://www.python.org/downloads/"
    Read-Host "Press Enter to exit"
    exit 1
}

# Check / install dependencies
try {
    python -c "import fastapi, uvicorn, dashscope, pydantic" 2>&1
} catch {
    Write-Warning "Dependencies missing. Auto-installing..."
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Dependency install failed! Check your network."
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[INFO] Dependencies installed successfully!" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Starting service on http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  API endpoint: http://127.0.0.1:8000/get_craft" -ForegroundColor Cyan
Write-Host "  Swagger docs: http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

python cam_cloud_api.py

Read-Host "Press Enter to exit"
