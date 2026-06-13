@echo off
chcp 65001 >nul
rem ============================================================================
rem  Fusion360 CAM 云端工艺推荐系统 — Windows 一键启动脚本
rem  用途: 启动本地 FastAPI 中转服务 (端口8000)
rem  路径: D:\CAM_CLOUD_API\start_service.bat
rem  使用方法: 双击运行, 或放入 Windows 启动文件夹实现开机自启
rem ============================================================================

title CAM云端工艺推荐系统 - API服务 [端口8000]

echo ============================================================
echo   Fusion360 CAM 云端工艺推荐系统
echo   本地FastAPI中转服务 v1.0.0
echo ============================================================
echo.

rem --- 设置阿里云 DashScope API Key ---
rem ★★★ 请将下面的 sk-xxx 替换为你的真实 API Key ★★★
rem 获取地址: https://dashscope.console.aliyun.com/apiKey
set DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

rem --- 检查 API Key 是否已配置 ---
if "%DASHSCOPE_API_KEY%"=="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" (
    echo [警告] API Key 未配置! 请编辑 start_service.bat 第18行, 填入真实Key
    echo         获取地址: https://dashscope.console.aliyun.com/apiKey
    echo.
)

rem --- 切换到项目目录 ---
cd /d D:\CAM_CLOUD_API

rem --- 检查 Python 是否可用 ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python! 请先安装 Python 3.10+
    echo         下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [信息] Python 版本:
python --version
echo.

rem --- 检查依赖是否安装 ---
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [警告] 依赖未安装, 正在自动安装...
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [错误] 依赖安装失败! 请检查网络连接后重试
        pause
        exit /b 1
    )
    echo [信息] 依赖安装完成!
    echo.
)

rem --- 启动服务 ---
echo [信息] 正在启动服务: http://127.0.0.1:8000
echo [信息] 接口地址: http://127.0.0.1:8000/get_craft
echo [信息] API文档:  http://127.0.0.1:8000/docs
echo [信息] 按 Ctrl+C 停止服务
echo ============================================================
echo.

python cam_cloud_api.py

pause
