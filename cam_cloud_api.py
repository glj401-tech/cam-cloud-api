"""
================================================================================
 cam_cloud_api.py — Fusion360 CAM 云端智能工艺推荐系统 | 本地FastAPI中转服务
 功能: 接收 Fusion360 脚本的加工特征/材料/机床请求, 拼装内置工艺知识库 +
       本地Ollama大模型 API, 返回标准化切削参数。
 端口: 8000
 接口: POST /get_craft
 作者: CAM_AI_System
 日期: 2026-06-13
 版本: 1.8.0
 许可证: MIT License
 仓库: https://github.com/your-org/cam-cloud-api
================================================================================
"""

__version__ = "1.8.0"
__author__ = "CAM_AI_System"
__license__ = "MIT"

import os
import json
import time
import asyncio
import logging
import traceback
import threading
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from openai import OpenAI

# v1.5: AI 3D 生成 MCP Server
try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None  # FastMCP 未安装(AI 3D 生成功能不可用, 核心 CAM API 不受影响)
try:
    import trimesh
except ImportError:
    trimesh = None  # trimesh 未安装(AI 3D 网格修复功能不可用, 核心 CAM API 不受影响)
import shutil
import tempfile
import base64
import subprocess
from pathlib import Path as FilePath
try:
    from knowledge_base.kb_enhanced import (
        HR_RULES, ERROR_CORRECTION_RULES, ALLOWANCE_TABLE,
        ENHANCED_CUTTING_PARAMS, FUSION360_STRATEGY_MATRIX,
        FUSION360_ADAPTIVE_SETTINGS, FUSION360_CONTOUR_SETTINGS,
        REST_MACHINING_RULES, HOLE_MACHINING_RULES,
        TYPICAL_PROCESS_ROUTES, FORMULAS, KNOWLEDGE_PRIORITY
    )
    logger.info("✅ 知识库增强模块加载成功 | HR规则:%d条 | ERR规则:%d条", len(HR_RULES), len(ERROR_CORRECTION_RULES))
except ImportError as e:
    logger.warning(f"⚠️ 知识库增强模块加载失败: {e}")
    HR_RULES = {}
    ERROR_CORRECTION_RULES = {}
    ALLOWANCE_TABLE = {}
    ENHANCED_CUTTING_PARAMS = {}
    FUSION360_STRATEGY_MATRIX = {}
    FUSION360_ADAPTIVE_SETTINGS = {}
    FUSION360_CONTOUR_SETTINGS = {}
    REST_MACHINING_RULES = {}
    HOLE_MACHINING_RULES = {}
    TYPICAL_PROCESS_ROUTES = {}
    FORMULAS = {}
    KNOWLEDGE_PRIORITY = {}


# ============================================================================
# 日志配置
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",  # Windows 中文日志输出不乱码
)
logger = logging.getLogger("cam_cloud_api")

# ============================================================================
# Ollama 本地大模型配置
# ★★★ 确保已安装并启动 Ollama, 并已拉取对应模型 ★★★
# 安装: https://ollama.com/download
# 拉取模型: ollama pull qwen2.5:14b (或其他qwen版本)
# 启动: ollama serve (默认端口11434)
# ============================================================================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# ============================================================================
# v1.6.1: 多模型 Provider 支持 (本地 Ollama / 在线 API 热切换)
# ============================================================================
# Provider 预设 — 通过 /admin/api/model_provider 端点运行时切换
_MODEL_PROVIDERS = {
    "ollama_local": {
        "label": "Ollama 本地 (qwen2.5:7b)",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "ollama",
        "model": "qwen2.5:7b-instruct-q4_K_M",
        "timeout": 360,
        "is_local": True,
    },
    "deepseek_online": {
        "label": "DeepSeek 在线 (deepseek-chat)",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "model": "deepseek-chat",
        "timeout": 120,
        "is_local": False,
    },
    "qwen_online": {
        "label": "通义千问在线 (qwen-plus)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
        "model": "qwen-plus",
        "timeout": 120,
        "is_local": False,
    },
    "custom_openai": {
        "label": "自定义 OpenAI 兼容端点",
        "base_url": os.getenv("CUSTOM_LLM_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.getenv("CUSTOM_LLM_API_KEY", ""),
        "model": os.getenv("CUSTOM_LLM_MODEL", "gpt-4o-mini"),
        "timeout": 120,
        "is_local": False,
    },
}

# 当前激活的 provider (v1.8.0: 默认改为优先在线模型, 离线时自动回退本地)
# 优先级: deepseek_online > qwen_online > custom_openai > ollama_local
_active_provider = "deepseek_online"  # v1.8.0: 默认优先在线大模型
_provider_lock = threading.Lock()

# 客户端缓存 (provider_id → OpenAI client)
_client_cache: dict[str, OpenAI] = {}

# ============================================================================
# v1.8.0: 固定前置 Prompt — 每次 AI 调用时强制前置此约束
# ============================================================================
CYBER_CAM_EXPERT_PROMPT = """【严格模式：开启】

你是资深数控工艺工程师，仅针对当前Fusion 360零件生成CAM工序，严格遵守以下所有前置条件，禁止凭空假设参数。

⚠️ 知识库调用优先级（从高到低，高优先级无条件覆盖低优先级）：
  Priority 1  → HR 强制约束规则 [绝对执行，任何情况下不允许覆盖或跳过]
  Priority 2  → ERR 错误修正规则 [AI 输出生成后必须过检，逐条核对 ERR 列表]
  Priority 3  → 切削参数数据库 [按材料+刀具直径+工序类型精确匹配参数]
  Priority 4  → Fusion360 策略选用矩阵 [按特征类型选择策略和关键参数]
  Priority 5  → 典型零件工艺路线 [参考整体工序结构，按最相近零件类型匹配]

冲突处理：当 Priority 1~2 规则与 AI 建议冲突时，强制以规则为准，输出修正说明，不允许静默采纳 AI 输出。

1. 前置几何输入（MCP会同步给你）：零件外形、最小内R、壁厚、材料、毛坯尺寸、是否有沉孔/螺纹/型腔/薄壁/深腔；
2. 设备硬性限制：机床行程、主轴最高转速、刀柄悬伸极限、只能使用平刀/圆鼻刀/钻头/丝锥，无5轴联动；
3. 加工工艺铁则：
   ① 开粗必须优先型腔铣，预留均匀余量（钢件0.3~0.5mm，铝件0.15~0.3mm）；
   ② 半精仅用于深腔陡峭面，平面直接精铣，禁止半精跳过；
   ③ 内圆角小于刀具半径时，必须增加清根工序；
   ④ 所有通孔/沉头孔先中心钻定位→麻花钻钻孔→沉锪，螺纹底孔后攻丝；
   ⑤ 薄壁区域单独分层降低切削深度，禁止大切深；
4. 输出规范：工序按实际特征需要排列（参考第1章工序链），每道工序标注适用刀具、单边余量、核心策略；
5. 禁止输出超出机床能力工序，禁止省略清根、定位钻等必要辅助工序，不生成无意义光整工序。
6. 输出前校验：核对零件最小R和推荐刀具半径，若刀具大于内R必须补充清根步骤。
"""

# 在线模型优先级列表 (v1.8.0: 优先选用在线大模型, 按此顺序尝试)
_ONLINE_PROVIDER_PRIORITY = ["deepseek_online", "qwen_online", "custom_openai"]


def _try_fallback_to_local() -> str:
    """
    v1.8.0: 在线模型不可用时, 自动回退到本地 Ollama。
    返回实际可用的 provider_id。
    """
    with _provider_lock:
        # 如果当前已经是本地, 直接返回
        if _active_provider == "ollama_local":
            return "ollama_local"

        # 检查当前在线 provider 是否有 API Key
        cfg = _MODEL_PROVIDERS.get(_active_provider, {})
        if cfg.get("api_key"):
            return _active_provider  # API Key 存在, 尝试使用

        # 当前在线 provider 无 API Key, 尝试其他在线 provider
        for pid in _ONLINE_PROVIDER_PRIORITY:
            if pid != _active_provider and _MODEL_PROVIDERS[pid].get("api_key"):
                logger.warning(f"⚠️ [{_active_provider}] 缺少 API Key, 自动切换到 [{pid}]")
                _active_provider = pid
                return pid

        # 所有在线 provider 都无 API Key, 回退本地
        logger.warning(f"⚠️ 所有在线模型均缺少 API Key, 自动回退到本地 Ollama")
        _active_provider = "ollama_local"
        return "ollama_local"


def _get_client() -> tuple[OpenAI, str, str]:
    """返回 (client, model_name, provider_id) — 根据当前活跃 provider 动态获取。"""
    with _provider_lock:
        provider_id = _active_provider
        config = _MODEL_PROVIDERS[provider_id]

    # v1.8.0: 在线模型无 API Key 时自动回退本地
    if not config.get("is_local", False) and not config.get("api_key"):
        provider_id = _try_fallback_to_local()
        config = _MODEL_PROVIDERS[provider_id]

    if provider_id not in _client_cache:
        _client_cache[provider_id] = OpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"] or "placeholder",
            timeout=config["timeout"],
        )
    return _client_cache[provider_id], config["model"], provider_id


# 兼容旧代码: 保留全局 client/MODEL_NAME 作为默认 provider 的引用
client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
    timeout=360,
)

# 模型固定配置
MODEL_NAME = OLLAMA_MODEL
TEMPERATURE = 0.1       # 低温减少幻觉, 参数稳定
MAX_TOKENS = 200        # 输出极短, 仅工艺参数字符串
TOP_P = 0.1             # 极窄采样, 输出确定性高

# ============================================================================
# v1.5: AI 3D 模型生成配置 (Hunyuan3D / Meshy)
# ============================================================================
# Hunyuan3D API (腾讯云 — 免费额度 20次/天)
# 注册地址: https://3d.hunyuanglobal.com
HUNYUAN3D_API_KEY = os.getenv("HUNYUAN3D_API_KEY", "")
HUNYUAN3D_API_URL = os.getenv("HUNYUAN3D_API_URL", "https://api.hunyuan3d.com/v1")

# Meshy API (备选 — $20/月起)
# 注册地址: https://meshy.ai
MESHY_API_KEY = os.getenv("MESHY_API_KEY", "")
MESHY_API_URL = os.getenv("MESHY_API_URL", "https://api.meshy.ai/openapi/v2")

# OpenRouter API (通用 AI 网关 — 支持 Fusion/Lumina 等3D模型)
# 注册地址: https://openrouter.ai
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_3D_MODEL = os.getenv("OPENROUTER_3D_MODEL", "fusion")

# AI 3D 网络配置 (超时/重试/代理)
AI_3D_TIMEOUT = int(os.getenv("AI_3D_TIMEOUT", "120"))       # 连接超时(秒), 默认2分钟
AI_3D_MAX_RETRIES = int(os.getenv("AI_3D_MAX_RETRIES", "3")) # 最大重试次数
AI_3D_PROXY = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY", "")  # HTTP代理 (国内用户可能需要)

# 本地模型输出目录
GENERATED_MODELS_DIR = FilePath(__file__).parent / "generated_models"
GENERATED_MODELS_DIR.mkdir(exist_ok=True)

# 可用的 AI 3D 后端
AI_3D_BACKENDS = {
    "hunyuan": {
        "name": "Hunyuan3D (腾讯)",
        "type": "cloud",
        "configured": bool(HUNYUAN3D_API_KEY),
        "description": "文本→3D + 图片→3D, 免费20次/天, PBR纹理",
    },
    "meshy": {
        "name": "Meshy 6",
        "type": "cloud",
        "configured": bool(MESHY_API_KEY),
        "description": "文本→3D + 图片→3D, ~$0.60/次, 4K纹理",
    },
    "openrouter": {
        "name": "OpenRouter 3D (Fusion/Lumina)",
        "type": "cloud",
        "configured": bool(OPENROUTER_API_KEY),
        "description": "文本→3D + 视觉理解, 支持多种3D模型, 按量计费",
    },
}

# ============================================================================
# v1.4: 推理状态追踪器 (供前端轮询显示模型调用状态)
# ============================================================================
_inference_status_lock = threading.Lock()
_inference_status = {
    "state": "idle",           # idle | connecting | inferring | done | error
    "message": "等待请求...",
    "model": MODEL_NAME,
    "started_at": None,        # ISO timestamp
    "elapsed_ms": 0,
    "tokens_generated": 0,
    "endpoint": "",            # 当前调用的接口
    "material": "",
    "feature": "",
    "last_error": None,
    "last_result_preview": "",  # 结果预览 (前100字符)
}


def _set_inference_state(state: str, message: str, **kwargs):
    """线程安全地更新推理状态。"""
    with _inference_status_lock:
        _inference_status["state"] = state
        _inference_status["message"] = message
        if state == "inferring":
            _inference_status["_start_ts"] = time.time()
            _inference_status["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _inference_status["elapsed_ms"] = 0
            _inference_status["tokens_generated"] = 0
            _inference_status["last_error"] = None
            _inference_status["last_result_preview"] = ""
        elif state == "done":
            _inference_status["elapsed_ms"] = int((time.time() - _inference_status.get("_start_ts", time.time())) * 1000)
        elif state == "error":
            _inference_status["last_error"] = message
            _inference_status["elapsed_ms"] = int((time.time() - _inference_status.get("_start_ts", time.time())) * 1000)
        for k, v in kwargs.items():
            _inference_status[k] = v

# ============================================================================
# 内置数控工艺知识库 (精简车间高频参数)
# 格式: 知识库[材料][加工特征] = (刀具, S转速, F进给, ap切深)
# 单位: S(rpm), F(mm/min), ap(mm)
# ============================================================================
CRAFT_KNOWLEDGE_BASE = {
    # =========================================================================
    # 铝合金系列
    # =========================================================================
    "6061铝": {
        "平面铣削":   "Φ63端铣刀(5刃,无涂层) | S6000 | F1200 | ap0.5~1.5",
        "型腔加工":   "Φ12硬质合金立铣刀(2刃) | S8000 | F1500 | ap0.3~1.0",
        "键槽加工":   "Φ8键槽铣刀(2刃) | S5000 | F800 | ap0.2~0.5",
        "钻孔":       "Φ6高速钢麻花钻 | S4000 | F300 | 啄钻深度2.0",
        "攻丝":       "M6机用丝锥(螺旋槽) | S800 | F800 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,无涂层) | S10000 | F2000 | ap0.1~0.2",
        "粗车外圆":   "CNMG120408 硬质合金PCD刀片 | S2500 | F0.3mm/r | ap1.0~3.0",
        "精车外圆":   "CCGT09T304 硬质合金PCD刀片 | S3500 | F0.1mm/r | ap0.2~0.5",
    },
    "7075铝": {
        "平面铣削":   "Φ63端铣刀(5刃,无涂层) | S5500 | F1100 | ap0.5~1.5",
        "型腔加工":   "Φ12硬质合金立铣刀(2刃) | S7500 | F1400 | ap0.3~1.0",
        "键槽加工":   "Φ8键槽铣刀(2刃) | S4800 | F750 | ap0.2~0.5",
        "钻孔":       "Φ6高速钢麻花钻 | S3800 | F280 | 啄钻深度2.0",
        "攻丝":       "M6机用丝锥(螺旋槽) | S750 | F750 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃) | S9500 | F1900 | ap0.1~0.2",
        "粗车外圆":   "CNMG120408 硬质合金PCD刀片 | S2300 | F0.3mm/r | ap1.0~3.0",
        "精车外圆":   "CCGT09T304 硬质合金PCD刀片 | S3200 | F0.1mm/r | ap0.2~0.5",
    },

    # =========================================================================
    # 碳钢 / 合金钢系列
    # =========================================================================
    "45#钢": {
        "平面铣削":   "Φ63端铣刀(5刃,涂层) | S2500 | F500 | ap0.3~1.0",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,TiAlN涂层) | S3500 | F600 | ap0.2~0.5",
        "键槽加工":   "Φ8键槽铣刀(2刃,涂层) | S2500 | F400 | ap0.1~0.3",
        "钻孔":       "Φ6高速钢麻花钻 | S1800 | F150 | 啄钻深度1.5",
        "攻丝":       "M6机用丝锥(螺旋槽) | S300 | F300 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,TiAlN涂层) | S5000 | F800 | ap0.05~0.15",
        "粗车外圆":   "CNMG120408 硬质合金TiCN涂层刀片 | S800 | F0.3mm/r | ap1.5~3.0",
        "精车外圆":   "CCGT09T304 硬质合金TiN涂层刀片 | S1200 | F0.1mm/r | ap0.3~0.8",
    },
    "40Cr合金钢": {
        "平面铣削":   "Φ63端铣刀(5刃,TiAlN涂层) | S1800 | F400 | ap0.3~0.8",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,AlTiN涂层) | S2800 | F500 | ap0.2~0.4",
        "键槽加工":   "Φ8键槽铣刀(2刃,TiCN涂层) | S2200 | F350 | ap0.1~0.25",
        "钻孔":       "Φ6含钴高速钢麻花钻 | S1500 | F120 | 啄钻深度1.2",
        "攻丝":       "M6机用丝锥(高速钢,涂层) | S250 | F250 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,AlTiN涂层) | S4200 | F650 | ap0.05~0.12",
        "粗车外圆":   "CNMG120408 硬质合金AlTiN涂层刀片 | S600 | F0.3mm/r | ap1.5~3.0",
        "精车外圆":   "CCGT09T304 硬质合金TiCN涂层刀片 | S1000 | F0.1mm/r | ap0.2~0.6",
    },
    "Cr12MoV模具钢": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S1000 | F250 | ap0.2~0.5",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,AlTiN涂层) | S2000 | F350 | ap0.1~0.3",
        "键槽加工":   "Φ8键槽铣刀(2刃,AlTiN涂层) | S1500 | F220 | ap0.05~0.2",
        "钻孔":       "Φ6含钴高速钢麻花钻 | S1000 | F80 | 啄钻深度1.0",
        "攻丝":       "M6机用丝锥(含钴高速钢) | S180 | F180 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,AlTiN涂层) | S3000 | F500 | ap0.03~0.1",
        "粗车外圆":   "CNMG120408 硬质合金AlTiN涂层刀片 | S350 | F0.25mm/r | ap1.0~2.5",
        "精车外圆":   "CCGT09T304 CBN刀片 | S600 | F0.08mm/r | ap0.1~0.4",
    },

    # =========================================================================
    # 不锈钢系列
    # =========================================================================
    "304不锈钢": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S1200 | F250 | ap0.2~0.5",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,AlTiN涂层) | S2000 | F300 | ap0.1~0.3",
        "键槽加工":   "Φ8键槽铣刀(2刃,AlTiN涂层) | S1500 | F200 | ap0.05~0.2",
        "钻孔":       "Φ6含钴高速钢麻花钻 | S800 | F80 | 啄钻深度1.0",
        "攻丝":       "M6机用丝锥(含钴高速钢) | S150 | F150 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,AlTiN涂层) | S3500 | F500 | ap0.05~0.1",
        "粗车外圆":   "CNMG120408 硬质合金AlTiN涂层刀片 | S450 | F0.2mm/r | ap1.0~2.5",
        "精车外圆":   "CCGT09T304 硬质合金PVD涂层刀片 | S700 | F0.1mm/r | ap0.2~0.5",
    },
    "316不锈钢": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S1000 | F200 | ap0.15~0.4",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,AlTiN涂层) | S1700 | F250 | ap0.1~0.25",
        "键槽加工":   "Φ8键槽铣刀(2刃,AlTiN涂层) | S1300 | F170 | ap0.05~0.15",
        "钻孔":       "Φ6含钴高速钢麻花钻 | S650 | F65 | 啄钻深度0.8",
        "攻丝":       "M6机用丝锥(含钴高速钢) | S120 | F120 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,AlTiN涂层) | S3000 | F430 | ap0.05~0.1",
        "粗车外圆":   "CNMG120408 硬质合金AlTiN涂层刀片 | S380 | F0.2mm/r | ap1.0~2.0",
        "精车外圆":   "CCGT09T304 硬质合金PVD涂层刀片 | S600 | F0.08mm/r | ap0.2~0.5",
    },

    # =========================================================================
    # 铸铁系列
    # =========================================================================
    "HT250灰铸铁": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S1500 | F400 | ap0.3~1.0",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,TiAlN涂层) | S2500 | F500 | ap0.2~0.5",
        "键槽加工":   "Φ8键槽铣刀(2刃,TiCN涂层) | S1800 | F300 | ap0.1~0.3",
        "钻孔":       "Φ6硬质合金钻头 | S2000 | F200 | 啄钻深度1.5",
        "攻丝":       "M6机用丝锥(高速钢) | S350 | F350 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,TiAlN涂层) | S4000 | F700 | ap0.05~0.15",
        "粗车外圆":   "CNMG120408 硬质合金Al₂O₃涂层刀片 | S500 | F0.3mm/r | ap1.5~4.0",
        "精车外圆":   "CCGT09T304 陶瓷刀片 | S800 | F0.12mm/r | ap0.2~0.6",
    },
    "QT600球墨铸铁": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S1300 | F350 | ap0.3~1.0",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,TiAlN涂层) | S2200 | F450 | ap0.2~0.5",
        "键槽加工":   "Φ8键槽铣刀(2刃,TiCN涂层) | S1600 | F280 | ap0.1~0.3",
        "钻孔":       "Φ6硬质合金钻头 | S1800 | F180 | 啄钻深度1.5",
        "攻丝":       "M6机用丝锥(高速钢,涂层) | S300 | F300 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,TiAlN涂层) | S3700 | F650 | ap0.05~0.15",
        "粗车外圆":   "CNMG120408 硬质合金CVD涂层刀片 | S450 | F0.3mm/r | ap1.5~4.0",
        "精车外圆":   "CCGT09T304 陶瓷或CBN刀片 | S700 | F0.1mm/r | ap0.2~0.6",
    },

    # =========================================================================
    # 钛合金 / 高温合金系列 (难加工材料)
    # =========================================================================
    "TC4钛合金": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S350 | F100 | ap0.15~0.3",
        "型腔加工":   "Φ12硬质合金立铣刀(5刃,AlTiN涂层,变螺旋) | S800 | F150 | ap0.08~0.2",
        "键槽加工":   "Φ8硬质合金立铣刀(4刃,AlTiN涂层) | S600 | F100 | ap0.05~0.15",
        "钻孔":       "Φ6硬质合金钻头(内冷) | S400 | F40 | 啄钻深度0.5",
        "攻丝":       "M6机用丝锥(含钴高速钢,涂层) | S80 | F80 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(4刃,AlTiN涂层) | S1800 | F350 | ap0.03~0.08",
        "粗车外圆":   "CNMG120408 硬质合金AlTiN涂层刀片 | S200 | F0.15mm/r | ap0.8~2.0",
        "精车外圆":   "CCGT09T304 硬质合金PVD涂层刀片 | S350 | F0.08mm/r | ap0.1~0.4",
    },
    "Inconel718镍基合金": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S200 | F60 | ap0.1~0.2",
        "型腔加工":   "Φ12硬质合金立铣刀(6刃,AlTiN涂层,变螺旋) | S500 | F100 | ap0.05~0.15",
        "键槽加工":   "Φ8硬质合金立铣刀(4刃,AlTiN涂层) | S400 | F70 | ap0.03~0.1",
        "钻孔":       "Φ6硬质合金钻头(内冷,AlTiN涂层) | S250 | F25 | 啄钻深度0.3",
        "攻丝":       "M6机用丝锥(粉末高速钢,涂层) | S50 | F50 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(4刃,AlTiN涂层) | S1200 | F250 | ap0.03~0.06",
        "粗车外圆":   "CNMG120408 硬质合金AlTiN涂层刀片(细晶) | S120 | F0.1mm/r | ap0.5~1.5",
        "精车外圆":   "CCGT09T304 CBN或陶瓷刀片 | S200 | F0.06mm/r | ap0.1~0.3",
    },

    # =========================================================================
    # 铜合金系列
    # =========================================================================
    "H62黄铜": {
        "平面铣削":   "Φ63端铣刀(5刃,无涂层) | S5000 | F1000 | ap0.5~1.5",
        "型腔加工":   "Φ12硬质合金立铣刀(2刃,无涂层) | S7000 | F1200 | ap0.3~1.0",
        "键槽加工":   "Φ8键槽铣刀(2刃,无涂层) | S4000 | F600 | ap0.2~0.5",
        "钻孔":       "Φ6高速钢麻花钻 | S3500 | F250 | 啄钻深度2.0",
        "攻丝":       "M6机用丝锥(螺旋槽) | S600 | F600 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,无涂层) | S8000 | F1500 | ap0.1~0.2",
        "粗车外圆":   "CNMG120408 硬质合金无涂层刀片(锋利刃) | S1500 | F0.25mm/r | ap1.0~3.0",
        "精车外圆":   "CCGT09T304 硬质合金PCD刀片 | S2500 | F0.08mm/r | ap0.2~0.5",
    },
    "紫铜T2": {
        "平面铣削":   "Φ63端铣刀(5刃,锋利刃) | S3000 | F600 | ap0.3~0.8",
        "型腔加工":   "Φ12硬质合金立铣刀(2刃,锋利刃) | S4500 | F800 | ap0.2~0.6",
        "键槽加工":   "Φ8键槽铣刀(2刃,锋利刃) | S2800 | F400 | ap0.1~0.3",
        "钻孔":       "Φ6高速钢麻花钻(锋利) | S2500 | F180 | 啄钻深度1.5",
        "攻丝":       "M6机用丝锥(螺旋槽) | S400 | F400 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,锋利刃) | S5000 | F1000 | ap0.05~0.15",
        "粗车外圆":   "CNMG120408 硬质合金无涂层锋利刀片 | S1000 | F0.2mm/r | ap1.0~2.5",
        "精车外圆":   "CCGT09T304 硬质合金PCD刀片 | S1800 | F0.08mm/r | ap0.1~0.4",
    },

    # =========================================================================
    # 淬硬钢系列 (高硬度材料)
    # =========================================================================
    "淬硬钢HRC50": {
        "平面铣削":   "Φ63端铣刀(5刃,AlTiN涂层) | S600 | F200 | ap0.1~0.3",
        "型腔加工":   "Φ12硬质合金立铣刀(6刃,AlTiN涂层) | S1500 | F350 | ap0.05~0.15",
        "键槽加工":   "Φ8硬质合金立铣刀(4刃,AlTiN涂层) | S1000 | F220 | ap0.03~0.1",
        "钻孔":       "Φ6硬质合金钻头(AlTiN涂层) | S700 | F60 | 啄钻深度0.8",
        "攻丝":       "不推荐在淬硬钢上攻丝,建议使用螺纹铣削",
        "曲面精加工": "R5球头铣刀(4刃,AlTiN涂层) | S3500 | F550 | ap0.03~0.08",
        "粗车外圆":   "CNMG120408 CBN刀片 | S450 | F0.15mm/r | ap0.5~1.5",
        "精车外圆":   "CCGT09T304 CBN刀片 | S700 | F0.06mm/r | ap0.1~0.3",
    },
}

# 合法的输入枚举值（用于校验）
VALID_FEATURES = list(CRAFT_KNOWLEDGE_BASE["6061铝"].keys())
VALID_MATERIALS = list(CRAFT_KNOWLEDGE_BASE.keys())
# VALID_MACHINES 已在下方从 machine_registry.json 加载

# v1.2.0: 刀具材料知识库 (来自行业标准数据, 供AI参考)
TOOL_MATERIAL_KNOWLEDGE = {
    "高速钢HSS": {"耐热℃": 620, "硬度": "62-70HRC", "适用": "低速通用加工, 钻头, 丝锥, 拉刀, 复杂形状刀具", "性价比": "高", "切削速度比": 1.0},
    "含钴高速钢HSS-Co": {"耐热℃": 650, "硬度": "65-72HRC", "适用": "不锈钢, 合金钢, 比HSS快10%", "性价比": "高", "切削速度比": 1.1},
    "硬质合金K类(YG/WC-Co)": {"耐热℃": 850, "硬度": "89-92HRA", "适用": "铸铁, 有色金属, 非金属", "性价比": "最高", "切削速度比": 3.0},
    "硬质合金P类(YT/WC-TiC-Co)": {"耐热℃": 900, "硬度": "90-93HRA", "适用": "钢件, 合金钢", "性价比": "最高", "切削速度比": 3.0},
    "TiN涂层硬质合金": {"耐热℃": 600, "硬度": "~85HRC(涂层)", "适用": "通用钢材, 减摩", "外观": "金色", "切削速度比": 3.5},
    "TiCN涂层硬质合金": {"耐热℃": 400, "硬度": "~90HRC(涂层)", "适用": "磨蚀性材料, 铸铁, 不锈钢", "外观": "深灰/蓝", "切削速度比": 3.8},
    "TiAlN涂层硬质合金": {"耐热℃": 800, "硬度": "~92HRC(涂层)", "适用": "淬硬钢, 镍基合金, 高速干切", "外观": "紫/黑", "切削速度比": 4.0},
    "AlTiN涂层硬质合金": {"耐热℃": 900, "硬度": "~93HRC(涂层)", "适用": "高温合金, 硬铣削, 难加工材料", "外观": "深紫", "切削速度比": 4.2},
    "金属陶瓷(Cermet)": {"耐热℃": 1200, "硬度": "91-94HRA", "适用": "精密切削, 高光洁度要求", "性价比": "中", "切削速度比": 4.5},
    "陶瓷刀具Al₂O₃/Si₃N₄": {"耐热℃": 1300, "硬度": "91-95HRA", "适用": "铸铁高速切削, 淬硬钢, 高温合金(禁断续)", "性价比": "中高", "切削速度比": 5.0},
    "立方氮化硼PCBN": {"耐热℃": 1300, "硬度": "~4500HV", "适用": "淬硬钢HRC45-65, 铸铁, 热后加工", "性价比": "低(单价高但寿命长)", "切削速度比": 6.0},
    "聚晶金刚石PCD": {"耐热℃": 800, "硬度": ">9000HV", "适用": "铝合金, 铜, 复合材料, 塑料 | 禁加工黑色金属", "性价比": "低(单价高)", "切削速度比": 5.2},
}

# v1.2.0: 刀路策略知识库 (来自行业标准与开源CNC实践)
TOOLPATH_STRATEGIES = {
    "平面加工": {
        "策略": ["面铣 Face Milling", "飞面 Facing"],
        "说明": "加工大平面区域, 去除顶面余量",
        "走刀模式": ["之字形 Zig-Zag", "单向 One-Way", "螺旋由外向内", "螺旋由内向外"],
        "径向切宽Ae": "60-80%刀具直径",
        "轴向切深Ap": "0.5-2mm(粗)/0.1-0.3mm(精)",
        "开源参考": "FreeCAD Path Workbench — Face operation, HeeksCNC face strategy",
    },
    "型腔加工": {
        "策略": ["型腔铣 Pocket Milling", "挖槽加工 Slotting"],
        "说明": "去除封闭型腔内部材料",
        "走刀模式": ["之字形", "环形由外向内", "环形由内向外", "摆线铣", "插铣"],
        "径向切宽Ae": "30-50%刀具直径",
        "轴向切深Ap": "0.5-1×刀具直径(粗)/0.1-0.3mm(精)",
        "开源参考": "FreeCAD Path — Pocket/Adaptive, OpenVoronoi, dxf2gcode",
    },
    "轮廓加工": {
        "策略": ["轮廓铣 Profile/Contour", "侧铣 Side Milling"],
        "说明": "沿零件外轮廓或内轮廓走刀, 精修侧壁",
        "走刀模式": ["单次走刀", "多次走刀(径向分层)", "轴向分层", "顺铣/逆铣"],
        "径向切宽Ae": "0.5-2mm(精)/2-5mm(粗)",
        "轴向切深Ap": "0.5-2×刀具直径",
        "开源参考": "FreeCAD Path — Profile, Contour, libarea (clipper)",
    },
    "钻孔循环": {
        "策略": ["钻削 Drilling", "啄钻 Peck Drilling", "断屑钻 Chip Breaking", "铰孔 Reaming", "镗孔 Boring"],
        "说明": "孔加工, 含中心钻→钻孔→铰孔/镗孔工艺链",
        "走刀模式": ["G81(简单钻孔)", "G83(深孔啄钻)", "G73(断屑钻)", "G84(攻丝)", "G85/G86(镗孔)"],
        "啄钻深度": "1-3×刀具直径(视材料而定)",
        "开源参考": "LinuxCNC G-code canned cycles, grbl HAL",
    },
    "曲面精加工": {
        "策略": ["平行走刀 Parallel", "等高加工 Contour/Waterline", "环绕等距 Scallop/Offset", "流线加工 Flowline", "清根加工 Pencil"],
        "说明": "3D曲面精加工, 获取目标表面光洁度",
        "走刀模式": ["平行扫描", "Z层等高", "3D环绕偏移", "沿曲面流线"],
        "步距": "0.05-0.3mm(精加工步距)",
        "开源参考": "FreeCAD Path — 3D Surface, Surface WB, pyCAM, Blender CAM",
    },
    "自适应清理": {
        "策略": ["自适应铣削 Adaptive/Trochoidal", "动态铣削 Dynamic Milling", "摆线铣 Trochoidal"],
        "说明": "恒定啮合角的高速粗加工, 适合深腔/硬材料/薄壁件",
        "走刀模式": ["摆线圆弧", "螺旋切入", "恒定步距自适应"],
        "径向切宽Ae": "5-15%刀具直径(小切宽大切深)",
        "轴向切深Ap": "1-3×刀具直径",
        "开源参考": "FreeCAD Path — Adaptive, Kiri:Moto (grid-based CAM), OpenCAMLib",
    },
    "螺纹加工": {
        "策略": ["攻丝 Tapping", "螺纹铣削 Thread Milling", "车螺纹 Thread Turning"],
        "说明": "内/外螺纹加工",
        "走刀模式": ["G84刚性攻丝", "螺旋插补螺纹铣", "G32/G92车螺纹"],
        "参数": "螺距=1.0mm(M6)/1.25mm(M8)/1.5mm(M10)/1.75mm(M12)/2.0mm(M14)/2.5mm(M16)",
        "开源参考": "LinuxCNC G-code threading, FreeCAD Fasteners WB",
    },
    "倒角/去毛刺": {
        "策略": ["倒角加工 Chamfer", "沉孔 Countersink", "去毛刺 Deburring"],
        "说明": "锐边倒角或去毛刺处理",
        "走刀模式": ["单次走刀", "45°倒角刀", "球头刀沿边"],
        "参数": "倒角C0.3~C2.0",
        "开源参考": "FreeCAD Path — Chamfer, Deburr operation",
    },
}


def build_system_prompt(feature: str, material: str, machine: str) -> str:
    """构建带有完整知识库上下文的 System Prompt, 强制模型输出固定格式。"""
    # v1.8.0: 固定前置 prompt (资深数控工艺工程师约束)
    expert_prefix = CYBER_CAM_EXPERT_PROMPT

    # 收集该材料+特征对应的知识库参考值
    ref_params = CRAFT_KNOWLEDGE_BASE.get(material, {}).get(feature, "无内置参考,请根据材料特性推荐")

    prompt = expert_prefix + f"""
## 内置工艺知识库 (参考基准)
当前加工场景:
- 加工特征: {feature}
- 工件材料: {material}
- 机床类型: {machine}

知识库基准参数: {ref_params}

完整知识库 (所有材料 × 所有特征, 供比对参考):
{json.dumps(CRAFT_KNOWLEDGE_BASE, ensure_ascii=False, indent=2)}

## HR 强制约束规则 (最高优先级, 绝对不可违反):
{json.dumps(HR_RULES, ensure_ascii=False, indent=2)}

## ERR 错误修正规则 (输出生成后必须过检, 逐条核对):
{json.dumps(ERROR_CORRECTION_RULES, ensure_ascii=False, indent=2)}

## 余量分配标准:
{json.dumps(ALLOWANCE_TABLE, ensure_ascii=False, indent=2)}

## 孔加工底孔径速查表:
{json.dumps(HOLE_MACHINING_RULES.get("bottom_hole_chart", {}), ensure_ascii=False, indent=2)}

## 输出规则 (绝对严格)
1. 你必须仅输出一行, 格式固定为:
   刀具型号 | 主轴转速S | 进给速度F | 切削深度ap
2. 禁止任何解释、说明、换行符、标点以外的符号
3. 禁止输出 "好的"、"推荐参数如下" 等任何前缀/后缀文本
4. 禁止在参数值后添加单位说明文字 (如 "S6000rpm" 错误, 应为 "S6000")
5. 钻孔类型: ap 位置填写啄钻深度(mm)
6. 攻丝类型: ap 位置填写螺距(mm)
7. 参数优先参考内置知识库, 仅在必要时微调, 确保参数安全、可落地

## 示例正确输出:
Φ12硬质合金立铣刀(2刃) | S8000 | F1500 | ap1.0
Φ6高速钢麻花钻 | S4000 | F300 | 啄钻深度2.0
M6机用丝锥(螺旋槽) | S800 | F800 | 螺距1.0"""

    return prompt


def build_auto_craft_system_prompt(features: list, material: str, machine: str,
                                   part_name: str, overall_dims: str) -> str:
    """构建自动工艺规划 System Prompt — 基于检测到的模型特征生成完整工艺流程。"""
    # v1.8.0: 固定前置 prompt (资深数控工艺工程师约束)
    expert_prefix = CYBER_CAM_EXPERT_PROMPT

    # 将特征列表格式化 (跳过 __config__ 元数据特征)
    features_desc_lines = []
    config_note = ""
    seq = 1
    for f in features:
        if getattr(f, "feature_type", "") == "__config__":
            config_note = getattr(f, "note", "") or ""
            continue
        dims = getattr(f, "dimensions", "")
        extra = ""
        count = getattr(f, "count", 1)
        note = getattr(f, "note", "")
        if count > 1:
            extra += f" [共{count}处]"
        if note:
            extra += f" [{note}]"
        features_desc_lines.append(f"  {seq}. {getattr(f, 'feature_type', '')} — {getattr(f, 'name', '')}: {dims}{extra}")
        seq += 1

    features_desc = "\n".join(features_desc_lines)

    prompt = expert_prefix + f"""
## 加工任务概述
- 零件名称: {part_name}
- 工件材料: {material}
- 机床类型: {machine}
- 零件外形尺寸: {overall_dims if overall_dims else "未提供"}
{f"## 加工环境配置 (用户选择)\n- {config_note}\n" if config_note else ""}
## 自动检测到的模型特征 (按推荐加工顺序排列)
{features_desc}

## 内置工艺知识库 (参考基准参数)
{json.dumps(CRAFT_KNOWLEDGE_BASE, ensure_ascii=False, indent=2)}

## 刀路策略参考 (来自开源CAM实践: FreeCAD Path, OpenCAMLib, FabexCNC, LinuxCNC)
{json.dumps(TOOLPATH_STRATEGIES, ensure_ascii=False, indent=2)}

## 刀具材料知识 (来自行业标准数据)
{json.dumps(TOOL_MATERIAL_KNOWLEDGE, ensure_ascii=False, indent=2)}

## HR 强制约束规则 (最高优先级, 绝对不可违反):
{json.dumps(HR_RULES, ensure_ascii=False, indent=2)}

## ERR 错误修正规则 (输出生成后必须过检, 逐条核对):
{json.dumps(ERROR_CORRECTION_RULES, ensure_ascii=False, indent=2)}

## 余量分配标准:
{json.dumps(ALLOWANCE_TABLE, ensure_ascii=False, indent=2)}

## 增强切削参数数据库:
{json.dumps(ENHANCED_CUTTING_PARAMS, ensure_ascii=False, indent=2)}

## Fusion360 策略选用矩阵:
{json.dumps(FUSION360_STRATEGY_MATRIX, ensure_ascii=False, indent=2)}

## 典型零件工艺路线库 (参考用):
{json.dumps(TYPICAL_PROCESS_ROUTES, ensure_ascii=False, indent=2)}

## 孔加工底孔径速查表:
{json.dumps(HOLE_MACHINING_RULES.get("bottom_hole_chart", {}), ensure_ascii=False, indent=2)}

## 任务要求
请为该零件的每个检测到的特征规划合理的加工工序, 包括刀路策略选择和切削参数推荐。

## 输出规则 (绝对严格)
1. 你必须先输出一段简要的工艺总览 (3-5句话, 说明加工策略、装夹方案和刀路规划思路)
2. 紧接着用分隔线 --- 隔开
3. 然后逐行输出每个工序, 每个工序格式固定为:
   工序号. 工序名称 | 刀路策略 | 对应特征 | 刀具型号 | S转速 | F进给 | ap切深 | 备注
4. 工序顺序必须合理: 一般先粗后精、先面后孔、先主后次
5. 禁止任何额外的解释、问候语或后缀文本
6. 参数优先参考内置知识库, 确保安全、可落地
7. 钻孔类型: 注明啄钻深度; 攻丝类型: 注明螺距
8. 如果检测到的特征中有些不适合当前机床加工, 请在备注中说明
9. 刀路策略从参考表中选取最合适的 (自适应/轮廓/型腔/钻孔循环/曲面精加工等)

## 示例正确输出:
该零件为矩形板材, 主要加工顶平面和4个通孔, 以及一个矩形型腔。建议以底面为基准, 虎钳装夹。加工路线: 先粗铣顶面和型腔, 再钻中心孔和通孔, 最后精修轮廓。

---
1. 平面粗铣 | 面铣之字形 | 顶面 | Φ63端铣刀(5刃) | S6000 | F1200 | ap1.0 | 粗铣去除余量, Ae=60%
2. 型腔粗加工 | 环形由外向内 | 矩形型腔 | Φ12硬质合金立铣刀(2刃) | S8000 | F1500 | ap0.5 | 型腔粗铣, Ae=35%
3. 中心钻 | G81钻孔 | Φ3中心钻 | Φ3中心钻 | S4000 | F200 | ap1.5 | 4处通孔定位
4. 钻孔 | G83深孔啄钻 | Φ10通孔×4 | Φ10硬质合金钻头 | S3500 | F250 | 啄钻深度2.0 | 钻4个通孔
5. 型腔精加工 | 环形由内向外 | 矩形型腔侧壁 | Φ12硬质合金立铣刀(2刃) | S8000 | F1200 | ap0.15 | 型腔侧壁精修, Ae=1mm
6. 曲面精加工 | 平行走刀 | R角过渡面 | R5球头铣刀(2刃) | S10000 | F2000 | ap0.1 | 精修过渡圆角, 步距0.15mm"""

    return prompt


# ============================================================================
# Pydantic 请求/响应模型
# ============================================================================
class CraftRequest(BaseModel):
    feature: str = Field(
        ...,
        description="加工特征类型",
        examples=["平面铣削"],
    )
    material: str = Field(
        ...,
        description="工件材料",
        examples=["6061铝"],
    )
    machine: str = Field(
        default="三轴立式加工中心",
        description="机床类型",
        examples=["三轴立式加工中心"],
    )


class CraftResponse(BaseModel):
    craft_params: str = Field(..., description="标准化切削参数")
    feature: str = Field(..., description="加工特征")
    material: str = Field(..., description="工件材料")
    machine: str = Field(..., description="机床类型")
    status: str = Field(default="ok", description="请求状态")


# ============================================================================
# v1.2.0 新增: 自动识别模型特征 → AI生成完整工艺流程
# ============================================================================
class DetectedFeature(BaseModel):
    """Fusion360 自动检测到的加工特征。"""
    feature_type: str = Field(..., description="特征类型: 平面/通孔/盲孔/型腔/凸台/槽/曲面/倒角")
    name: str = Field(..., description="特征名称, 如'顶面', 'Φ10通孔×4'")
    dimensions: str = Field(..., description="人可读的尺寸描述, 如'100×80mm', 'Φ10×20mm深'")
    count: int = Field(default=1, description="同类特征数量")
    diameter: Optional[float] = Field(default=None, description="孔径/轴径(mm)")
    depth: Optional[float] = Field(default=None, description="孔深/腔深(mm)")
    width: Optional[float] = Field(default=None, description="宽度(mm)")
    length: Optional[float] = Field(default=None, description="长度(mm)")
    area_mm2: Optional[float] = Field(default=None, description="面积(mm²)")
    note: Optional[str] = Field(default=None, description="补充说明, 如'通孔', '盲孔', '含圆角'")
    # v1.8.0: 新增几何约束字段 (供后置校验使用)
    min_inner_radius: Optional[float] = Field(default=None, description="最小内圆角半径(mm), 型腔/槽特征必填")
    wall_thickness: Optional[float] = Field(default=None, description="壁厚(mm), 薄壁特征必填")
    has_thread: Optional[bool] = Field(default=False, description="是否含螺纹")
    thread_size: Optional[str] = Field(default=None, description="螺纹规格, 如'M6', 'M8'")


class AutoCraftRequest(BaseModel):
    """自动工艺规划请求: 发送模型检测到的所有特征, AI返回完整工艺流程。"""
    features: list[DetectedFeature] = Field(..., description="自动检测到的加工特征列表")
    material: str = Field(..., description="工件材料")
    machine: str = Field(default="三轴立式加工中心", description="机床类型")
    part_name: str = Field(default="未命名零件", description="零件名称")
    overall_dimensions: str = Field(default="", description="零件外形尺寸, 如'100×80×30mm'")


# ============================================================================
# v1.8.0: 自动校验逻辑 — 两步校验流程
# ============================================================================
def _extract_part_constraints(features: list[DetectedFeature]) -> dict:
    """
    v1.8.0 增强: 从特征列表中自动提取零件所有几何约束 (通用, 不局限于特定举例)。

    自动提取的约束项:
    - 所有特征类型统计
    - 最小内圆角半径 (型腔/槽/倒角)
    - 是否有螺纹孔/沉孔/薄壁/深腔
    - 孔径列表 + 孔深列表
    - 型腔深度列表 + 型腔宽度列表
    - 壁厚 (薄壁特征)
    - 零件最大尺寸 (用于校验刀具悬伸/机床行程)
    """
    constraints = {
        "feature_types": {},
        "feature_count": len(features),
        "min_inner_radius": None,
        "max_inner_radius": None,
        "has_thread": False,
        "thread_specs": [],
        "has_counterbore": False,
        "has_pocket": False,
        "has_thin_wall": False,
        "has_deep_pocket": False,
        "deep_pocket_depth": [],
        "wall_thickness": None,
        "hole_diameters": [],
        "hole_depths": [],
        "pocket_depths": [],
        "pocket_widths": [],
        "part_max_dim": None,
    }

    import re as _re

    for f in features:
        ft = f.feature_type

        # 统计特征类型
        constraints["feature_types"][ft] = constraints["feature_types"].get(ft, 0) + (f.count or 1)

        # 内R (适用于型腔/槽/倒角)
        if ft in ("型腔", "槽", "倒角"):
            if f.min_inner_radius is not None:
                r = f.min_inner_radius
                if constraints["min_inner_radius"] is None or r < constraints["min_inner_radius"]:
                    constraints["min_inner_radius"] = r
                if constraints["max_inner_radius"] is None or r > constraints["max_inner_radius"]:
                    constraints["max_inner_radius"] = r
            if f.note and "R" in f.note:
                r_match = _re.search(r'R(\d+\.?\d*)', f.note)
                if r_match:
                    r_val = float(r_match.group(1))
                    if constraints["min_inner_radius"] is None or r_val < constraints["min_inner_radius"]:
                        constraints["min_inner_radius"] = r_val

        # 螺纹
        if f.has_thread or (f.thread_size is not None and f.thread_size != ""):
            constraints["has_thread"] = True
            if f.thread_size and f.thread_size not in constraints["thread_specs"]:
                constraints["thread_specs"].append(f.thread_size)

        # 沉孔
        if f.note and ("沉" in f.note or "counterbore" in f.note.lower()):
            constraints["has_counterbore"] = True

        # 型腔/槽
        if ft in ("型腔", "槽"):
            constraints["has_pocket"] = True
            if f.depth is not None:
                constraints["pocket_depths"].append(f.depth)
                if f.width and f.width > 0:
                    aspect_ratio = f.depth / f.width
                    if aspect_ratio > 3:
                        constraints["has_deep_pocket"] = True
                        constraints["deep_pocket_depth"].append(f.depth)

        # 薄壁
        if ft in ("薄壁", "侧壁") or (f.wall_thickness is not None and f.wall_thickness < 3.0):
            constraints["has_thin_wall"] = True
            if f.wall_thickness is not None:
                if constraints["wall_thickness"] is None or f.wall_thickness < constraints["wall_thickness"]:
                    constraints["wall_thickness"] = f.wall_thickness

        # 孔特征
        if ft in ("通孔", "盲孔", "螺纹孔"):
            if f.diameter is not None:
                constraints["hole_diameters"].append(f.diameter)
            if f.depth is not None:
                constraints["hole_depths"].append(f.depth)

        # 零件最大尺寸
        for dim_val in (f.length, f.width, f.depth):
            if dim_val is not None:
                if constraints["part_max_dim"] is None or dim_val > constraints["part_max_dim"]:
                    constraints["part_max_dim"] = dim_val

    return constraints


def _parse_tool_radius(tool_name: str) -> float:
    """
    从刀具名称中解析刀具半径 (mm)。
    支持: Φ12立铣刀 -> 6.0,  R5球头刀 -> 5.0,  Φ6麻花钻 -> 3.0
    解析失败返回 0 (视为安全, 不触发清根校验)。
    """
    import re as _re

    # 匹配 ΦX 或 φX (直径)
    dia_match = _re.search(r'[Φφ](\d+\.?\d*)', tool_name)
    if dia_match:
        diameter = float(dia_match.group(1))
        return diameter / 2.0

    # 匹配 RX (球头刀半径)
    r_match = _re.search(r'(?:R|r)(\d+\.?\d*)', tool_name)
    if r_match:
        return float(r_match.group(1))

    # 匹配 "Xmm立铣刀" 格式
    mm_match = _re.search(r'(\d+\.?\d*)mm', tool_name)
    if mm_match:
        diameter = float(mm_match.group(1))
        return diameter / 2.0

    return 0.0


    return constraints


def _parse_tool_radius(tool_name: str) -> float:
    """
    从刀具名称中解析刀具半径 (mm)。
    支持: Φ12立铣刀 → 6.0,  R5球头刀 → 5.0,  Φ6麻花钻 → 3.0
    解析失败返回 0 (视为安全, 不触发清根校验)。
    """
    import re as _re

    # 匹配 ΦX 或 φX (直径)
    dia_match = _re.search(r'[Φφ](\d+\.?\d*)', tool_name)
    if dia_match:
        diameter = float(dia_match.group(1))
        return diameter / 2.0

    # 匹配 RX (球头刀半径)
    r_match = _re.search(r'(?:R|r)(\d+\.?\d*)', tool_name)
    if r_match:
        return float(r_match.group(1))

    # 匹配 "Xmm立铣刀" 格式
    mm_match = _re.search(r'(\d+\.?\d*)mm', tool_name)
    if mm_match:
        diameter = float(mm_match.group(1))
        return diameter / 2.0

    return 0.0


def _verify_process_plan(process_text: str, features: list[DetectedFeature]) -> tuple[bool, str]:
    """
    v1.8.0 增强: 通用自动校验流程 — 对照 HR_RULES 和 ERROR_CORRECTION_RULES 逐条检查。

    校验逻辑调用优先级: HR_RULES > ERROR_CORRECTION_RULES > 动态校验项
    - 规则来源: 知识库 cam_process_library.md 第1章(HR) + 第6章(ERR)
    - 校验策略: 根据零件实际特征动态触发对应的规则
    - 无该特征则不校验该规则 (避免误报)
    """
    constraints = _extract_part_constraints(features)
    issues = []
    process_lower = process_text.lower()

    # =========================================================================
    # 第1层校验: HR_RULES — 强制约束规则 (绝对不可违反)
    # =========================================================================

    # HR-01: 内圆角 < 开粗刀半径 → 必须残料铣
    min_r = constraints["min_inner_radius"]
    if min_r is not None and min_r > 0:
        lines = process_text.split(chr(10))
        for line in lines:
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 5:
                tool_radius = _parse_tool_radius(cells[4])
                if tool_radius > min_r + 0.01:
                    rule = HR_RULES.get("HR-01", {})
                    issues.append(
                        f"[{rule.get('id','HR-01')}] {rule.get('action','必须添加残料铣工序')}。"
                        f"刀具({cells[4]}, R={tool_radius:.1f}mm) > 最小内R({min_r}mm)。"
                        f"后果: {rule.get('consequence','')}"
                    )
                    break

    # HR-05: 钻孔前必须中心钻定位
    hole_types = constraints["feature_types"]
    if ("通孔" in hole_types or "盲孔" in hole_types or constraints["has_thread"]):
        if "钻孔" in process_text and "中心钻" not in process_text and "定位" not in process_text:
            rule = HR_RULES.get("HR-05", {})
            issues.append(
                f"[{rule.get('id','HR-05')}] {rule.get('action','所有孔位必须先执行中心钻定位')}。"
                f"后果: {rule.get('consequence','')}"
            )

    # HR-06: 攻丝前底孔必须已完成
    if constraints["has_thread"]:
        has_tap = "攻丝" in process_text
        has_drill = "钻孔" in process_text or "钻底孔" in process_text
        if has_tap and not has_drill:
            rule = HR_RULES.get("HR-06", {})
            issues.append(
                f"[{rule.get('id','HR-06')}] {rule.get('action','底孔必须已钻完')}。"
                f"后果: {rule.get('consequence','')}"
            )

    # HR-02: 薄壁 (壁厚 <= 3mm) -> ap <= 0.2mm, 分层精铣
    if constraints["has_thin_wall"]:
        if "薄壁" not in process_lower or ("分层" not in process_lower and "小切深" not in process_lower):
            rule = HR_RULES.get("HR-02", {})
            wt = constraints["wall_thickness"] or "?"
            issues.append(
                f"[{rule.get('id','HR-02')}] {rule.get('action','ap<=0.2mm,分层精铣,对称交替走刀')}。"
                f"壁厚{wt}mm <= 3mm。后果: {rule.get('consequence','')}"
            )

    # HR-03: 深腔 (L/D > 5) -> 必须半精加工
    if constraints["has_deep_pocket"]:
        if "深腔" not in process_lower or ("接刀" not in process_lower and "分段" not in process_lower):
            rule = HR_RULES.get("HR-03", {})
            issues.append(
                f"[{rule.get('id','HR-03')}] {rule.get('action','精铣前必须Contour半精加工陡峭侧壁')}。"
                f"后果: {rule.get('consequence','')}"
            )

    # =========================================================================
    # 第2层校验: ERROR_CORRECTION_RULES — 常见AI错误修正
    # =========================================================================

    # ERR-01: 缺失半精铣
    if constraints["has_pocket"] or constraints["has_deep_pocket"]:
        if "开粗" in process_lower and ("半精" not in process_lower and "semi" not in process_lower):
            rule = ERROR_CORRECTION_RULES.get("ERR-01", {})
            if "精铣" in process_lower or "精加工" in process_lower:
                issues.append(
                    f"[{rule.get('code','ERR-01')}] {rule.get('forced_correction','')}。"
                    f"AI典型错误: {rule.get('ai_typical_output','')}"
                )

    # ERR-02: 缺失残料铣 (已在 HR-01 覆盖, 补检测)
    if min_r is not None and min_r > 0:
        if "残料" not in process_lower and "清根" not in process_lower and "pencil" not in process_lower:
            lines = process_text.split(chr(10))
            for line in lines:
                if "|" not in line:
                    continue
                cells = [c.strip() for c in line.split("|")]
                if len(cells) >= 5:
                    tool_radius = _parse_tool_radius(cells[4])
                    if tool_radius > min_r + 0.01:
                        rule = ERROR_CORRECTION_RULES.get("ERR-02", {})
                        issues.append(
                            f"[{rule.get('code','ERR-02')}] {rule.get('forced_correction','添加残料铣,刀具<=R_corner x 1.6')}。"
                            f"AI典型错误: {rule.get('ai_typical_output','')}"
                        )
                        break

    # ERR-05: 孔加工缺中心钻
    if "钻孔" in process_text and "中心钻" not in process_text:
        rule = ERROR_CORRECTION_RULES.get("ERR-05", {})
        if "通孔" in hole_types or "盲孔" in hole_types:
            issues.append(
                f"[{rule.get('code','ERR-05')}] {rule.get('forced_correction','所有钻孔前插入中心钻工序')}。"
                f"AI典型错误: {rule.get('ai_typical_output','')}"
            )

    # ERR-10: 薄壁大切深 (HR-02 补充)
    if constraints["has_thin_wall"] and ("薄壁" not in process_lower or "ap" not in process_lower):
        rule = ERROR_CORRECTION_RULES.get("ERR-10", {})
        issues.append(
            f"[{rule.get('code','ERR-10')}] {rule.get('forced_correction','ap<=0.2mm,增加分层数')}。"
            f"AI典型错误: {rule.get('ai_typical_output','')}"
        )

    # ERR-09: 转速超限
    rule_09 = ERROR_CORRECTION_RULES.get("ERR-09", {})
    import re as _re2
    rpm_matches = _re2.findall(r'[nN][\s=]*([\d]{4,})', process_text)
    for rpm in rpm_matches:
        if int(rpm) > 8000:
            issues.append(
                f"[{rule_09.get('code','ERR-09')}] {rule_09.get('forced_correction','n<=8000RPM')}。"
                f"发现转速 {rpm} RPM > 8000"
            )
            break

    # =========================================================================
    # 第3层: 动态校验项 (根据特征类型自动决定)
    # =========================================================================

    # 孔特征: 通孔需钻穿
    if "通孔" in hole_types and "钻穿" not in process_lower and "通孔" not in process_lower:
        issues.append(
            "[校验-通孔] 检测到通孔特征, 工序中未明确标注[钻穿]策略! "
            "通孔钻孔必须钻穿出口, 防止出口毛刺。"
        )

    # 型腔加工必须有开粗
    if constraints["has_pocket"]:
        if "开粗" not in process_lower and "粗铣" not in process_lower and "粗加工" not in process_lower:
            issues.append(
                "[校验-型腔开粗] 检测到型腔特征, 工序中未明确标注开粗工序! "
                "型腔必须先开粗, 预留精加工余量。"
            )

    # 工序顺序合理性 (攻丝必须在钻孔后)
    tap_idx, drill_idx = -1, -1
    for i, ln in enumerate(process_text.split(chr(10))):
        if "|" not in ln:
            continue
        if "攻丝" in ln or "攻" in ln:
            tap_idx = i
        if "钻孔" in ln or "钻底孔" in ln:
            drill_idx = i
    if tap_idx >= 0 and drill_idx >= 0 and tap_idx < drill_idx:
        issues.append(
            "[校验-工序顺序] 攻丝工序出现在钻孔之前! "
            "正确顺序: 中心钻定位 -> 钻孔(底孔) -> 攻丝。请调整工序顺序。"
        )

    # 汇总反馈
    if issues:
        feedback = (
            "\n\n【自动校验未通过, 请严格按照以下要求修改工艺流程, 重新输出完整工序表】\n"
            + "\n".join(f"- {issue}" for issue in issues)
            + "\n\n请重新输出, 确保上述所有问题已修正。如某条校验不适用, 请在工序备注中说明原因。"
        )
        return (False, feedback)

    return (True, "")
def _auto_craft_with_verify(system_prompt: str, user_prompt: str,
                            features: list[DetectedFeature],
                            max_retry: int = 2) -> str:
    """
    v1.8.0: 带自动校验的 AI 调用 — 校验失败自动反馈重生成

    返回: (process_text, retry_count)
    """
    global _llm_client, _llm_model

    current_prompt = user_prompt
    for attempt in range(max_retry + 1):
        response = _llm_client.chat.completions.create(
            model=_llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": current_prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=1200,
            top_p=TOP_P,
        )

        process_text = response.choices[0].message.content.strip()

        # 校验
        is_valid, feedback = _verify_process_plan(process_text, features)

        if is_valid:
            return process_text, attempt

        # 校验失败, 拼接反馈后重试
        if attempt < max_retry:
            current_prompt = user_prompt + feedback
        else:
            # 达到最大重试次数, 返回结果并附警告
            process_text += f"\n\n⚠️ [自动校验警告, 已重试{max_retry}次仍未完全通过]\n" + feedback.replace("\n", " ")
            return process_text, attempt + 1

    return process_text, max_retry + 1


class ProcessStep(BaseModel):
    """单个工艺步骤。"""
    step: int = Field(..., description="工序序号")
    operation: str = Field(..., description="工序名称: 平面铣削/钻孔/型腔加工/键槽加工/攻丝/曲面精加工")
    toolpath_strategy: str = Field(default="", description="刀路策略: 之字形/环形/等高/平行/自适应/G83啄钻等")
    feature_ref: str = Field(..., description="对应的模型特征名称")
    tool: str = Field(..., description="推荐刀具型号")
    spindle_speed: str = Field(..., description="主轴转速S (rpm)")
    feed_rate: str = Field(..., description="进给速度F (mm/min)")
    depth_of_cut: str = Field(..., description="切削深度ap / 啄钻深度 / 螺距 (mm)")
    note: str = Field(default="", description="操作备注")


class AutoCraftResponse(BaseModel):
    """自动工艺规划响应。"""
    process_plan_text: str = Field(..., description="AI生成的完整工艺流程文本")
    steps: list[ProcessStep] = Field(..., description="结构化工艺步骤列表")
    features_detected: int = Field(..., description="检测到的特征数量")
    material: str = Field(..., description="工件材料")
    machine: str = Field(..., description="机床类型")
    status: str = Field(default="ok", description="请求状态")


# ============================================================================
# v1.5: AI 3D 生成 MCP Server (FastMCP — ASGI 兼容，挂载到 FastAPI)
# ★ 注意: MCP 必须在 FastAPI 之前初始化, 以便将 MCP 的 lifespan 合并到 FastAPI 中
# ============================================================================
try:
    mcp_3d = FastMCP("CAM-AI-3D-Gen")
    _MCP_3D_OK = True
    _mcp_http_app = mcp_3d.http_app(path="/")  # ★ path="/" — 作为子应用挂载时路由正确
    logger.info("[AI-3D] FastMCP 初始化成功")
except Exception as e:
    logger.warning(f"[AI-3D] FastMCP 初始化失败 (AI 3D 生成功能不可用): {e}")
    # 创建占位对象，避免后续 @mcp_3d.tool() 装饰器报错
    class _StubMCP:
        def tool(self):
            return lambda func: func
        def http_app(self, path=None, **kwargs):
            raise RuntimeError("FastMCP 未初始化")
    mcp_3d = _StubMCP()
    _MCP_3D_OK = False
    _mcp_http_app = None


# ============================================================================
# FastAPI 应用初始化 (含 MCP lifespan)
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时校验配置 + 管理 MCP session manager。"""
    # ---- 自定义启动日志 ----
    logger.info("=" * 60)
    logger.info("CAM云端工艺推荐系统 本地中转服务启动中...")
    logger.info(f"版本: {__version__} | 模型: {MODEL_NAME} | 温度: {TEMPERATURE} | 端口: 8000")
    logger.info(f"Ollama地址: {OLLAMA_BASE_URL}")
    logger.info(f"Ollama模型: {OLLAMA_MODEL}")
    logger.info(f"支持材料({len(VALID_MATERIALS)}种): {', '.join(VALID_MATERIALS)}")
    logger.info(f"支持特征({len(VALID_FEATURES)}种): {', '.join(VALID_FEATURES)}")
    logger.info(f"刀路策略: {len(TOOLPATH_STRATEGIES)}类 | 刀具材料: {len(TOOL_MATERIAL_KNOWLEDGE)}种")
    logger.info(f"流式推理: POST /get_craft/stream (SSE) | 状态查询: GET /inference_status")
    logger.info(f"AI 3D生成 MCP: /mcp (v1.5新增 — text_to_3d, image_to_3d, mesh_to_step)")
    # 检查 AI 3D 后端配置
    any_3d = any(b["configured"] for b in AI_3D_BACKENDS.values())
    logger.info(f"AI 3D后端: {'已配置' if any_3d else '未配置 (设置 HUNYUAN3D_API_KEY 或 MESHY_API_KEY)'}")
    # 检查个人工艺库
    if PERSONAL_LIBRARY_FILE.exists():
        lib = _load_personal_library()
        logger.info(f"个人工艺库: {len(lib.get('entries', {}))}条记录")
    else:
        logger.info("个人工艺库: 尚未创建 (使用 /craft_library/upload 上传)")
    logger.info("=" * 60)

    # ---- 进入 MCP session manager lifespan (初始化 StreamableHTTPSessionManager) ----
    if _MCP_3D_OK and _mcp_http_app is not None:
        async with _mcp_http_app.lifespan(_mcp_http_app):
            yield
    else:
        yield

    # ---- 自定义关闭日志 ----
    logger.info("CAM云端工艺推荐系统 服务已关闭")


app = FastAPI(
    title="Fusion360 CAM 云端工艺推荐系统",
    description="本地中转服务: 接收加工特征→调用Ollama本地大模型→返回标准化切削参数",
    version="1.5.0",
    lifespan=lifespan,
)

# CORS 跨域配置 (allow_origins=* 与 allow_credentials=True 是浏览器规范禁止组合,
# 此处无前端鉴权凭证需求, 故关闭 credentials 保留通配符, 兼容 Fusion360 脚本跨域请求)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API 路由
# ============================================================================
@app.get("/")
async def root():
    """健康检查根路由。"""
    _llm_client, _llm_model, _llm_provider = _get_client()
    _cfg = _MODEL_PROVIDERS[_llm_provider]
    return {
        "service": "Fusion360 CAM 云端工艺推荐系统",
        "version": __version__,
        "model": _llm_model,
        "provider": _llm_provider,
        "provider_label": _cfg["label"],
        "backend": "Ollama本地大模型" if _cfg["is_local"] else "在线API",
        "ollama_url": OLLAMA_BASE_URL,
        "status": "running",
        "endpoints": {
            "get_craft": "POST /get_craft",
            "auto_craft": "POST /auto_craft (v1.2新增-自动工艺规划)",
            "health": "GET /health",
            "knowledge_base": "GET /knowledge_base",
            "knowledge_base_lookup": "GET /knowledge_base/lookup",
            "craft_library": "GET /craft_library (v1.2-个人工艺库)",
            "craft_library_upload": "POST /craft_library/upload (v1.2-上传工艺)",
            "craft_library_query": "GET /craft_library/query (v1.2-搜索工艺)",
            "craft_library_import": "POST /craft_library/import_batch (v1.2-批量导入)",
            "inference_status": "GET /inference_status (v1.4-推理状态查询)",
            "get_craft_stream": "POST /get_craft/stream (v1.4-流式推理SSE)",
            "mcp_3d_gen": "POST /mcp (v1.5-AI 3D生成MCP: text_to_3d, image_to_3d, mesh_to_step, check_3d_backends)",
        },
    }


@app.get("/inference_status")
async def get_inference_status():
    """v1.4: 查询模型推理状态 (供前端轮询, 显示模型调用进度)。"""
    with _inference_status_lock:
        status = dict(_inference_status)
    # 如果正在推理, 更新耗时
    if status["state"] == "inferring" and "_start_ts" in status:
        status["elapsed_ms"] = int((time.time() - status["_start_ts"]) * 1000)
    # 移除内部字段
    status.pop("_start_ts", None)
    return status


@app.get("/health")
async def health_check():
    """健康检查接口。"""
    _llm_client, _llm_model, _llm_provider = _get_client()
    _cfg = _MODEL_PROVIDERS[_llm_provider]
    llm_ok = False
    hint = None
    try:
        resp = _llm_client.models.list()
        available_models = [m.id for m in resp]
        llm_ok = _llm_model in available_models or any(_llm_model in m for m in available_models)
        if not llm_ok:
            if _cfg["is_local"]:
                hint = f"本地模型 '{_llm_model}' 未找到! 请运行: ollama pull {_llm_model}"
            else:
                hint = f"在线模型 '{_llm_model}' 不在可用列表中 (可能 API Key 无效或无权限)"
    except Exception as e:
        if _cfg["is_local"]:
            hint = f"无法连接到本地Ollama ({_cfg['base_url']})! 请确认: ollama serve. 错误: {str(e)[:100]}"
        else:
            hint = f"无法连接到在线API ({_cfg['base_url']})! 请检查网络和 API Key. 错误: {str(e)[:100]}"
    return {
        "status": "healthy" if llm_ok else "degraded",
        "version": __version__,
        "model": _llm_model,
        "provider": _llm_provider,
        "provider_label": _cfg["label"],
        "is_local": _cfg["is_local"],
        "llm_connected": llm_ok,
        "hint": hint,
    }


@app.get("/knowledge_base")
async def get_knowledge_base():
    """查询内置知识库 (离线可用, 不调用AI)。"""
    return {
        "materials": VALID_MATERIALS,
        "features": VALID_FEATURES,
        "machines": VALID_MACHINES,
        "knowledge_base": CRAFT_KNOWLEDGE_BASE,
    }


@app.get("/knowledge_base/lookup")
async def lookup_knowledge(feature: str, material: str):
    """直接查询知识库基准参数 (离线, 不消耗API)。"""
    if material not in VALID_MATERIALS:
        raise HTTPException(status_code=400, detail=f"不支持的材料: {material}, 可选: {VALID_MATERIALS}")
    if feature not in VALID_FEATURES:
        raise HTTPException(status_code=400, detail=f"不支持的特征: {feature}, 可选: {VALID_FEATURES}")

    kb_params = CRAFT_KNOWLEDGE_BASE[material][feature]
    return {
        "feature": feature,
        "material": material,
        "kb_reference": kb_params,
        "source": "内置知识库(离线查询, 非AI生成)",
    }


# ============================================================================
# v1.2.0: 个人工艺库 — 用户自定义工艺参数持久化存储
# ============================================================================
import uuid
import threading
from pathlib import Path

# 个人工艺库存放路径 (与 cam_cloud_api.py 同目录)
PERSONAL_LIBRARY_FILE = Path(__file__).parent / "personal_craft_library.json"
_library_lock = threading.Lock()


def _load_personal_library() -> dict:
    """从 JSON 文件加载个人工艺库。"""
    try:
        if PERSONAL_LIBRARY_FILE.exists():
            with open(PERSONAL_LIBRARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"加载个人工艺库失败: {e}")
    # 返回空库结构
    return {"version": "1.0", "entries": {}, "updated_at": ""}


def _save_personal_library(library: dict) -> None:
    """保存个人工艺库到 JSON 文件。"""
    from datetime import datetime
    library["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(PERSONAL_LIBRARY_FILE, "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存个人工艺库失败: {e}")
        raise


# ============================================================================
# v1.6: 机床注册表持久化
# ============================================================================
MACHINE_REGISTRY_FILE = Path(__file__).parent / "machine_registry.json"
_machine_registry_lock = threading.Lock()

# 默认机床列表 (首次启动种子)
_DEFAULT_MACHINES = [
    "三轴立式加工中心", "数控铣床", "钻攻中心", "五轴加工中心", "龙门铣床",
    "数控车床", "车铣复合中心", "卧式加工中心",
]


def _load_machine_registry() -> dict:
    """从 JSON 文件加载机床注册表。"""
    try:
        if MACHINE_REGISTRY_FILE.exists():
            with open(MACHINE_REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("machines"):
                    return data
    except Exception as e:
        logger.error(f"加载机床注册表失败: {e}")
    return {"version": "1.0", "machines": list(_DEFAULT_MACHINES), "updated_at": ""}


def _save_machine_registry(registry: dict) -> None:
    """保存机床注册表到 JSON 文件。"""
    from datetime import datetime
    registry["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(MACHINE_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存机床注册表失败: {e}")
        raise


# 加载机床注册表 (模块级别)
_machine_registry = _load_machine_registry()
VALID_MACHINES = list(_machine_registry.get("machines", _DEFAULT_MACHINES))


class CraftLibraryEntry(BaseModel):
    """个人工艺库条目。"""
    feature: str = Field(..., description="加工特征名称 (用户自定义)", examples=["深孔钻削", "薄壁件精加工"])
    material: str = Field(..., description="工件材料", examples=["TC4钛合金"])
    machine: str = Field(default="三轴立式加工中心", description="机床类型")
    tool: str = Field(..., description="刀具型号", examples=["Φ8硬质合金深孔钻(内冷)"])
    spindle_speed: str = Field(..., description="主轴转速 S", examples=["S1200"])
    feed_rate: str = Field(..., description="进给速度 F", examples=["F180"])
    depth_of_cut: str = Field(..., description="切削深度 ap / 啄钻深度 / 螺距", examples=["啄钻深度1.5"])
    toolpath_strategy: str = Field(default="", description="刀路策略", examples=["G83深孔啄钻"])
    coolant: str = Field(default="乳化液", description="冷却方式: 乳化液/油冷/高压内冷/干切/气冷")
    notes: str = Field(default="", description="工艺备注/经验总结")
    tags: list[str] = Field(default_factory=list, description="标签, 便于搜索", examples=[["钛合金", "深孔", "航空件"]])


class CraftLibraryUploadRequest(BaseModel):
    """工艺库上传请求。"""
    entries: list[CraftLibraryEntry] = Field(..., description="要添加的工艺条目列表")
    overwrite: bool = Field(default=False, description="是否覆盖同名条目 (相同特征+材料)")


class CraftLibraryResponse(BaseModel):
    """工艺库操作响应。"""
    status: str = Field(default="ok")
    message: str = Field(default="")
    total_entries: int = Field(default=0)
    added: int = Field(default=0)
    skipped: int = Field(default=0)


class CraftLibraryBatchItem(BaseModel):
    """批量导入单条工艺参数 (简化格式, 适合从Excel/CSV粘贴)。"""
    feature: str = Field(default="", description="加工特征")
    tool: str = Field(default="", description="刀具型号")
    S: str = Field(default="", description="主轴转速 (会被映射到 spindle_speed)")
    F: str = Field(default="", description="进给速度 (会被映射到 feed_rate)")
    ap: str = Field(default="", description="切深 (会被映射到 depth_of_cut)")
    strategy: str = Field(default="", description="刀路策略")
    coolant: str = Field(default="乳化液", description="冷却方式")
    notes: str = Field(default="", description="备注")
    tags: list[str] = Field(default_factory=list, description="标签")


class CraftLibraryImportBatchRequest(BaseModel):
    """批量导入工艺参数请求。"""
    material: str = Field(..., description="工件材料 (必填)")
    machine: str = Field(default="三轴立式加工中心", description="机床类型")
    batch: list[CraftLibraryBatchItem] = Field(..., description="工艺条目列表 (必填)")


class CraftLibraryDeleteBatchRequest(BaseModel):
    """批量删除工艺库条目请求。"""
    entry_ids: list[str] = Field(..., description="要删除的条目 ID 列表")


@app.get("/craft_library")
async def get_craft_library():
    """获取个人工艺库全部内容。"""
    with _library_lock:
        library = _load_personal_library()
    return {
        "status": "ok",
        "file": str(PERSONAL_LIBRARY_FILE),
        "total_entries": len(library.get("entries", {})),
        "updated_at": library.get("updated_at", ""),
        "entries": library.get("entries", {}),
    }


@app.get("/craft_library/query")
async def query_craft_library(
    material: Optional[str] = None,
    feature: Optional[str] = None,
    tag: Optional[str] = None,
    keyword: Optional[str] = None,
):
    """
    查询个人工艺库。

    支持按材料、特征、标签、关键词搜索。
    同时返回内置知识库中匹配的结果作为对照。
    """
    with _library_lock:
        library = _load_personal_library()

    entries = library.get("entries", {})
    results = {}

    for entry_id, entry in entries.items():
        # 按条件过滤
        if material and material not in entry.get("material", ""):
            continue
        if feature and feature not in entry.get("feature", ""):
            continue
        if tag and tag not in entry.get("tags", []):
            continue
        if keyword:
            entry_text = json.dumps(entry, ensure_ascii=False).lower()
            if keyword.lower() not in entry_text:
                continue
        results[entry_id] = entry

    # 同时查询内置知识库匹配项
    kb_match = None
    if material and feature:
        if material in VALID_MATERIALS and feature in VALID_FEATURES:
            kb_match = {
                "feature": feature,
                "material": material,
                "kb_reference": CRAFT_KNOWLEDGE_BASE[material][feature],
                "source": "内置知识库",
            }

    return {
        "status": "ok",
        "query": {"material": material, "feature": feature, "tag": tag, "keyword": keyword},
        "found": len(results),
        "personal_entries": results,
        "knowledge_base_match": kb_match,
    }


@app.post("/craft_library/upload", response_model=CraftLibraryResponse)
async def upload_craft_library(request: CraftLibraryUploadRequest):
    """
    上传自定义工艺参数到个人工艺库。

    数据持久化到 personal_craft_library.json 文件。

    - 相同特征+材料被视为重复条目
    - overwrite=True 时覆盖重复项, 否则跳过
    """
    with _library_lock:
        library = _load_personal_library()

    if "entries" not in library:
        library["entries"] = {}

    added = 0
    skipped = 0

    for entry in request.entries:
        # 生成唯一 key: 材料+特征+刀具 的哈希
        key_base = f"{entry.material}|{entry.feature}|{entry.tool}"
        existing_key = None

        # 查找是否已有同名条目
        for eid, existing in library["entries"].items():
            if existing.get("material") == entry.material and existing.get("feature") == entry.feature:
                existing_key = eid
                break

        if existing_key and not request.overwrite:
            skipped += 1
            continue

        if existing_key and request.overwrite:
            # 覆盖
            library["entries"][existing_key] = entry.model_dump()
            added += 1
        else:
            # 新增
            new_id = str(uuid.uuid4())[:8]
            library["entries"][new_id] = entry.model_dump()
            added += 1

    _save_personal_library(library)
    total = len(library["entries"])

    logger.info(f"个人工艺库更新: 新增{added}条, 跳过{skipped}条, 共{total}条")
    logger.info(f"[审计] 上传: overwrite={request.overwrite}, "
                f"条目={[(e.feature, e.material) for e in request.entries]}")

    return CraftLibraryResponse(
        status="ok",
        message=f"成功添加 {added} 条工艺记录, 跳过 {skipped} 条, 库共有 {total} 条",
        total_entries=total,
        added=added,
        skipped=skipped,
    )


@app.delete("/craft_library/{entry_id}")
async def delete_craft_library_entry(entry_id: str):
    """删除个人工艺库中的指定条目。"""
    with _library_lock:
        library = _load_personal_library()

    entries = library.get("entries", {})
    if entry_id not in entries:
        raise HTTPException(status_code=404, detail=f"条目不存在: {entry_id}")

    deleted = entries.pop(entry_id)
    _save_personal_library(library)

    logger.info(f"[审计] 删除单条: id={entry_id}, "
                f"feature={deleted.get('feature', '')}, material={deleted.get('material', '')}")

    return {
        "status": "ok",
        "message": f"已删除条目: {deleted.get('feature', '')} - {deleted.get('material', '')}",
        "deleted_entry": deleted,
        "remaining": len(entries),
    }


@app.post("/craft_library/import_batch")
async def import_batch_craft_library(payload: CraftLibraryImportBatchRequest):
    """
    批量导入工艺参数 (简化格式, 适合从Excel/CSV粘贴)。

    请求体格式:
    {
      "material": "6061铝",
      "machine": "三轴立式加工中心",
      "batch": [
        {"feature": "平面铣削", "tool": "Φ63端铣刀", "S": "6000", "F": "1200", "ap": "1.0", "notes": "粗铣"},
        {"feature": "钻孔", "tool": "Φ6麻花钻", "S": "4000", "F": "300", "ap": "啄钻2.0", "notes": ""}
      ]
    }
    """
    if not payload.material or not payload.batch:
        raise HTTPException(status_code=400, detail="material 和 batch 字段为必填")

    entries = []
    for item in payload.batch:
        entries.append(CraftLibraryEntry(
            feature=item.feature,
            material=payload.material,
            machine=payload.machine,
            tool=item.tool,
            spindle_speed=item.S,
            feed_rate=item.F,
            depth_of_cut=item.ap,
            toolpath_strategy=item.strategy,
            coolant=item.coolant,
            notes=item.notes,
            tags=item.tags,
        ))

    req = CraftLibraryUploadRequest(entries=entries, overwrite=True)
    logger.info(f"[审计] 批量导入: material={payload.material}, machine={payload.machine}, "
                f"条目数={len(entries)}")
    return await upload_craft_library(req)


@app.post("/get_craft/stream")
async def get_craft_stream(request: CraftRequest):
    """
    v1.4: 流式推理接口 (SSE — Server-Sent Events)。

    实时推送模型调用状态和生成的 token, 前端可逐字显示推理进度。

    事件类型:
      - status:  状态变更 (connecting → inferring → done/error)
      - token:   逐 token 输出
      - done:    推理完成 (含完整结果)
      - error:   推理失败
    """
    # ---- 参数校验 ----
    if request.material not in VALID_MATERIALS:
        raise HTTPException(status_code=400, detail=f"不支持的材料: '{request.material}'。可选: {', '.join(VALID_MATERIALS)}")
    if request.feature not in VALID_FEATURES:
        raise HTTPException(status_code=400, detail=f"不支持的特征: '{request.feature}'。可选: {', '.join(VALID_FEATURES)}")

    logger.info(f"[SSE] 收到流式请求 → 特征: {request.feature} | 材料: {request.material} | 机床: {request.machine}")

    system_prompt = build_system_prompt(request.feature, request.material, request.machine)

    async def event_generator():
        start_ts = time.time()
        full_text = ""
        _llm_client, _llm_model, _llm_provider = _get_client()
        _provider_label = _MODEL_PROVIDERS[_llm_provider]["label"]
        _connect_msg = f"🔗 正在连接 {_provider_label}..."
        _set_inference_state("connecting", _connect_msg, endpoint="get_craft/stream",
                            material=request.material, feature=request.feature)

        yield f"data: {json.dumps({'event': 'status', 'state': 'connecting', 'message': _connect_msg, 'model': _llm_model}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

        _infer_msg = f"🤖 模型 {_llm_model} 推理中..."
        _set_inference_state("inferring", _infer_msg, endpoint="get_craft/stream",
                            material=request.material, feature=request.feature)

        yield f"data: {json.dumps({'event': 'status', 'state': 'inferring', 'message': _infer_msg, 'model': _llm_model}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

        try:
            stream = _llm_client.chat.completions.create(
                model=_llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"请为以下加工场景推荐切削参数: "
                            f"特征={request.feature}, 材料={request.material}, 机床={request.machine}。"
                            f"只输出参数行, 不要任何其他文字。"
                        ),
                    },
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                top_p=TOP_P,
                stream=True,
            )

            token_count = 0
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_text += token
                    token_count += 1
                    yield f"data: {json.dumps({'event': 'token', 'text': token, 'accumulated': full_text, 'count': token_count}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)  # 让出事件循环

            elapsed = int((time.time() - start_ts) * 1000)
            logger.info(f"[SSE] 推理完成 — {token_count} tokens | {elapsed}ms | 结果: {full_text.strip()[:100]}")

            _set_inference_state("done", f"✅ 推理完成 ({elapsed}ms, {token_count} tokens)",
                                elapsed_ms=elapsed, tokens_generated=token_count,
                                last_result_preview=full_text.strip()[:100])

            yield f"data: {json.dumps({'event': 'done', 'result': full_text.strip(), 'tokens': token_count, 'elapsed_ms': elapsed, 'feature': request.feature, 'material': request.material, 'machine': request.machine}, ensure_ascii=False)}\n\n"

        except Exception as e:
            error_name = type(e).__name__
            elapsed = int((time.time() - start_ts) * 1000)
            logger.error(f"[SSE] 推理失败 — {error_name}: {e}")

            _set_inference_state("error", f"❌ 推理失败: {error_name}",
                                elapsed_ms=elapsed, last_error=str(e)[:200])

            yield f"data: {json.dumps({'event': 'error', 'error': str(e), 'type': error_name, 'elapsed_ms': elapsed}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/get_craft", response_model=CraftResponse)
async def get_craft(request: CraftRequest):
    """
    核心接口: 接收加工特征+材料+机床, 调用Ollama本地大模型生成切削参数。

    处理流程:
    1. 校验输入参数合法性
    2. 构建 System Prompt (含完整知识库)
    3. 调用本地Ollama大模型
    4. 解析并清洗响应文本
    5. 返回标准化格式切削参数
    """
    # ---- 1. 参数校验 ----
    if request.material not in VALID_MATERIALS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的材料: '{request.material}'。可选: {', '.join(VALID_MATERIALS)}",
        )
    if request.feature not in VALID_FEATURES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的特征: '{request.feature}'。可选: {', '.join(VALID_FEATURES)}",
        )
    if request.machine not in VALID_MACHINES:
        logger.warning(f"非标机床类型: {request.machine}, 仍继续处理")

    logger.info(f"收到工艺请求 → 特征: {request.feature} | 材料: {request.material} | 机床: {request.machine}")

    # ---- 2. 构建 Prompt ----
    system_prompt = build_system_prompt(request.feature, request.material, request.machine)

    # ---- 3. 调用大模型 API (v1.6.1: 动态 provider) ----
    _llm_client, _llm_model, _llm_provider = _get_client()
    _provider_label = _MODEL_PROVIDERS[_llm_provider]["label"]
    _set_inference_state("connecting", f"🔗 正在连接 {_provider_label}...", endpoint="get_craft",
                        material=request.material, feature=request.feature)
    logger.info(f"⏳ [状态] 正在连接 {_provider_label}...")
    t0 = time.time()

    try:
        _set_inference_state("inferring", f"🤖 模型 {_llm_model} 推理中...", endpoint="get_craft",
                            material=request.material, feature=request.feature)
        logger.info(f"🤖 [状态] 模型 {_llm_model} 推理中... (provider: {_llm_provider})")
        response = _llm_client.chat.completions.create(
            model=_llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"请为以下加工场景推荐切削参数: "
                        f"特征={request.feature}, 材料={request.material}, 机床={request.machine}。"
                        f"只输出参数行, 不要任何其他文字。"
                    ),
                },
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=TOP_P,
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        raw_output = response.choices[0].message.content.strip()
        # 获取实际 token 数
        usage = getattr(response, "usage", None)
        prompt_tokens = usage.prompt_tokens if usage else "?"
        completion_tokens = usage.completion_tokens if usage else "?"
        logger.info(f"✅ [状态] 推理完成 — {elapsed_ms}ms | prompt_tokens={prompt_tokens} | completion_tokens={completion_tokens}")
        logger.info(f"AI原始输出: {raw_output}")

        _set_inference_state("done", f"✅ 推理完成 ({elapsed_ms}ms)",
                            elapsed_ms=elapsed_ms, tokens_generated=completion_tokens,
                            last_result_preview=raw_output[:100])

    except HTTPException:
        _set_inference_state("error", "❌ HTTP异常")
        raise
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        error_name = type(e).__name__
        logger.error(f"❌ [状态] 调用Ollama服务异常 ({elapsed_ms}ms): {error_name}: {e}")

        _set_inference_state("error", f"❌ 推理失败: {error_name}",
                            elapsed_ms=elapsed_ms, last_error=str(e)[:200])

        # 判断是否为连接错误
        if "Connection" in error_name or "connection" in str(e).lower():
            raise HTTPException(
                status_code=503,
                detail=f"无法连接到Ollama服务 ({OLLAMA_BASE_URL})! "
                       f"请确认Ollama已安装并启动: ollama serve",
            )
        # 判断是否为模型不存在
        if "not found" in str(e).lower() or "model" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail=f"Ollama模型 '{MODEL_NAME}' 未找到! "
                       f"请运行: ollama pull {MODEL_NAME}",
            )
        raise HTTPException(status_code=500, detail=f"AI服务调用失败 [{error_name}]: {str(e)}")

    # ---- 4. 清洗输出文本 ----
    craft_params = clean_output(raw_output)

    logger.info(f"最终输出参数: {craft_params}")

    return CraftResponse(
        craft_params=craft_params,
        feature=request.feature,
        material=request.material,
        machine=request.machine,
        status="ok",
    )


@app.post("/auto_craft", response_model=AutoCraftResponse)
async def auto_craft(request: AutoCraftRequest):
    """
    v1.2.0 新增: 自动工艺规划接口。

    接收 Fusion360 自动检测到的模型特征列表 (含几何尺寸),
    调用Ollama本地大模型生成完整的多步工艺流程。

    处理流程:
    1. 校验输入参数
    2. 构建自动工艺规划 System Prompt
    3. 调用本地Ollama大模型
    4. 解析多步工序输出
    5. 返回结构化工艺步骤
    """
    # ---- 1. 参数校验 ----
    if request.material not in VALID_MATERIALS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的材料: '{request.material}'。可选: {', '.join(VALID_MATERIALS)}",
        )
    if not request.features:
        raise HTTPException(
            status_code=400,
            detail="特征列表不能为空! 请先在Fusion360中执行'自动识别模型特征'。",
        )
    if request.machine not in VALID_MACHINES:
        logger.warning(f"非标机床类型: {request.machine}, 仍继续处理")

    logger.info(
        f"收到自动工艺规划请求 → 零件: {request.part_name} | "
        f"材料: {request.material} | 机床: {request.machine} | "
        f"特征数: {len(request.features)}"
    )
    # 记录每个检测到的特征
    for f in request.features:
        logger.info(f"  特征: [{f.feature_type}] {f.name} — {f.dimensions}"
                    f"{' ×' + str(f.count) if f.count > 1 else ''}")

    # ---- 2. 构建 Prompt ----
    system_prompt = build_auto_craft_system_prompt(
        request.features,
        request.material,
        request.machine,
        request.part_name,
        request.overall_dimensions,
    )

    # ---- 3. 构建用户 Prompt ----
    user_prompt = (
        f"请为零件'{request.part_name}'规划完整加工工艺路线。"
        f"材料: {request.material}, 机床: {request.machine}。"
        f"检测到{len(request.features)}个特征, "
        f"外形尺寸: {request.overall_dimensions or '未提供'}。"
        f"请按格式输出工艺总览和每个工序步骤。"
    )

    # ---- 4. 调用大模型 API (v1.8.0: 带自动校验的重试循环) ----
    _llm_client, _llm_model, _llm_provider = _get_client()
    _provider_label = _MODEL_PROVIDERS[_llm_provider]["label"]
    _set_inference_state("connecting", f"🔗 正在连接 {_provider_label}...", endpoint="auto_craft",
                        material=request.material, feature=f"自动工艺规划({len(request.features)}特征)")
    logger.info(f"⏳ [状态] 正在连接 {_provider_label}...")
    t0 = time.time()

    try:
        _set_inference_state("inferring", f"🤖 模型 {_llm_model} 推理中 (自动工艺规划, 含自动校验)...", endpoint="auto_craft",
                            material=request.material, feature=f"自动工艺规划({len(request.features)}特征)")
        logger.info(f"🤖 [状态] 模型 {_llm_model} 推理中 (自动工艺规划+校验, {len(request.features)}特征)... provider: {_llm_provider}")

        # v1.8.0: 使用带自动校验的调用 — 校验失败自动反馈重生成 (最多重试2次)
        raw_output, retry_count = _auto_craft_with_verify(
            system_prompt, user_prompt, request.features, max_retry=2,
        )

        elapsed_ms = int((time.time() - t0) * 1000)

        if retry_count > 0:
            logger.info(f"✅ [状态] 自动工艺规划完成 (含{retry_count}次自动校验重试) — {elapsed_ms}ms")
        else:
            logger.info(f"✅ [状态] 自动工艺规划完成 (校验一次性通过) — {elapsed_ms}ms")

        logger.info(f"AI自动工艺规划原始输出:\n{raw_output}")

        _set_inference_state("done", f"✅ 自动工艺规划完成 ({elapsed_ms}ms){' [校验重试' + str(retry_count) + '次]' if retry_count > 0 else ''}",
                            elapsed_ms=elapsed_ms, tokens_generated="?",
                            last_result_preview=raw_output[:150])

    except HTTPException:
        _set_inference_state("error", "❌ HTTP异常")
        raise
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        error_name = type(e).__name__
        logger.error(f"❌ [状态] 调用Ollama服务异常 ({elapsed_ms}ms): {error_name}: {e}")

        _set_inference_state("error", f"❌ 推理失败: {error_name}",
                            elapsed_ms=elapsed_ms, last_error=str(e)[:200])

        if "Connection" in error_name or "connection" in str(e).lower():
            raise HTTPException(
                status_code=503,
                detail=f"无法连接到Ollama服务 ({OLLAMA_BASE_URL})! "
                       f"请确认Ollama已安装并启动: ollama serve",
            )
        if "not found" in str(e).lower() or "model" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail=f"Ollama模型 '{MODEL_NAME}' 未找到! "
                       f"请运行: ollama pull {MODEL_NAME}",
            )
        raise HTTPException(status_code=500, detail=f"AI服务调用失败 [{error_name}]: {str(e)}")

    # ---- 4. 解析多步工序输出 ----
    overview, steps = parse_process_plan(raw_output, request.features)

    logger.info(f"✅ [状态] 解析完成: {len(steps)} 个工艺步骤")

    return AutoCraftResponse(
        process_plan_text=raw_output,
        steps=steps,
        features_detected=len(request.features),
        material=request.material,
        machine=request.machine,
        status="ok",
    )


def parse_process_plan(raw: str, detected_features: list) -> tuple:
    """
    解析AI生成的完整工艺计划。

    返回:
        (overview: str, steps: list[ProcessStep])

    解析逻辑:
    1. 以 '---' 或 '---' 为界, 之前为工艺总览, 之后为工序列表
    2. 逐行解析工序, 格式: 序号. 工序名称 | 特征 | 刀具 | S | F | ap | 备注
    """
    overview = ""
    steps = []

    # 分割总览和工序 (含全角破折号/星号/等号等实际可能出现的分隔符)
    separator_markers = [
        "\n---\n", "\n———\n", "\n———\n",   # 半角/全角破折号
        "\n===\n", "\n***\n", "\n###\n",   # 等号/星号/井号
    ]
    parts = raw
    for marker in separator_markers:
        if marker in parts:
            parts = parts.split(marker, 1)
            overview = parts[0].strip()
            steps_text = parts[1].strip() if len(parts) > 1 else ""
            break
    else:
        # 没有明确分隔符, 尝试按句号分割
        sentences = raw.replace("\n", " ").split("。")
        if len(sentences) > 2:
            overview = "。".join(sentences[:2]) + "。"
            steps_text = "。".join(sentences[2:])
        else:
            overview = raw
            steps_text = ""

    if not overview:
        overview = raw.split("\n")[0] if "\n" in raw else raw[:200]

    # 解析工序步骤
    parsed_steps = []
    if steps_text:
        for line in steps_text.strip().split("\n"):
            line = line.strip()
            if not line or len(line) < 10:
                continue

            # 跳过非工序行 (如纯标题、空行)
            # 期望格式: "1. 工序名称 | 特征 | 刀具 | S | F | ap | 备注"
            if not (line[0].isdigit() or line.startswith("工序")):
                continue

            try:
                step_data = _parse_single_step_line(line)
                if step_data:
                    parsed_steps.append(step_data)
            except Exception as e:
                logger.warning(f"解析工序行失败: '{line[:80]}...' — {e}")

    # 如果解析不到工序, 尝试宽松匹配
    if not parsed_steps:
        logger.warning("严格解析未提取到工序, 使用宽松模式")
        # 为每个检测到的特征生成基础工序 (使用知识库兜底)
        parsed_steps = _fallback_process_plan(detected_features, overview)

    return overview, parsed_steps


def _parse_single_step_line(line: str) -> Optional[ProcessStep]:
    """解析单行工序文本, 返回 ProcessStep 或 None。"""
    # 去除序号前缀: "1." "1、" "工序1:" "Step1:" 等
    import re
    cleaned = re.sub(r'^(工序\s*)?(\d+)[\.\、\)\:\s\-]+', '', line).strip()

    # 按 | 分割
    if "|" not in cleaned:
        # 尝试按中文分号或逗号分割
        parts = re.split(r'[；;，,]', cleaned)
        if len(parts) < 4:
            return None
    else:
        parts = [p.strip() for p in cleaned.split("|")]

    if len(parts) < 4:
        return None

    # 提取 step 序号 (从原始 line 中提取)
    step_match = re.match(r'[^\d]*(\d+)', line)
    step_num = int(step_match.group(1)) if step_match else 0

    # 判断格式: 8段(含刀路策略) vs 7段(旧格式)
    if len(parts) >= 8:
        # 新格式: 工序名称 | 刀路策略 | 特征 | 刀具 | S | F | ap | 备注
        operation = parts[0] if len(parts) > 0 else ""
        toolpath_strategy = parts[1] if len(parts) > 1 else ""
        feature_ref = parts[2] if len(parts) > 2 else ""
        tool = parts[3] if len(parts) > 3 else ""
        spindle = parts[4] if len(parts) > 4 else ""
        feed = parts[5] if len(parts) > 5 else ""
        ap = parts[6] if len(parts) > 6 else ""
        note = parts[7] if len(parts) > 7 else ""
    else:
        # 旧格式: 工序名称 | 特征 | 刀具 | S | F | ap | 备注
        operation = parts[0] if len(parts) > 0 else ""
        toolpath_strategy = ""
        feature_ref = parts[1] if len(parts) > 1 else ""
        tool = parts[2] if len(parts) > 2 else ""
        spindle = parts[3] if len(parts) > 3 else ""
        feed = parts[4] if len(parts) > 4 else ""
        ap = parts[5] if len(parts) > 5 else ""
        note = parts[6] if len(parts) > 6 else ""

    # 清理 S / F / ap 前缀 (仅去前缀, 不误删字段内字母)
    spindle = re.sub(r'^[Ss]', '', spindle).replace("转速", "").strip()
    feed = re.sub(r'^[Ff]', '', feed).replace("进给", "").strip()
    ap = re.sub(r'^[Aa][Pp]', '', ap).replace("切深", "").strip()

    return ProcessStep(
        step=step_num,
        operation=operation,
        toolpath_strategy=toolpath_strategy,
        feature_ref=feature_ref,
        tool=tool,
        spindle_speed=spindle,
        feed_rate=feed,
        depth_of_cut=ap,
        note=note,
    )


def _fallback_process_plan(detected_features: list, overview: str = "") -> list:
    """
    兜底方案: 当AI输出无法解析时, 使用知识库为每个检测到的特征匹配工序。
    """
    # 特征类型 → 知识库工序名 的映射
    feature_to_operation = {
        "平面": "平面铣削",
        "顶面": "平面铣削",
        "底面": "平面铣削",
        "台阶面": "平面铣削",
        "通孔": "钻孔",
        "盲孔": "钻孔",
        "螺纹孔": "攻丝",
        "型腔": "型腔加工",
        "矩形型腔": "型腔加工",
        "圆型腔": "型腔加工",
        "槽": "键槽加工",
        "键槽": "键槽加工",
        "凸台": "型腔加工",  # 凸台周围加工
        "曲面": "曲面精加工",
        "倒角": "曲面精加工",
    }

    steps = []
    for i, feat in enumerate(detected_features, 1):
        feat_dict = feat if isinstance(feat, dict) else feat.model_dump()
        ftype = feat_dict.get("feature_type", "")
        fname = feat_dict.get("name", "")

        # 找到匹配的工序类型
        operation = None
        for key, op in feature_to_operation.items():
            if key in ftype or key in fname:
                operation = op
                break

        if operation is None:
            operation = "平面铣削"  # 默认

        steps.append(ProcessStep(
            step=i,
            operation=operation,
            feature_ref=fname,
            tool="根据知识库参数",
            spindle_speed="参考知识库",
            feed_rate="参考知识库",
            depth_of_cut="参考知识库",
            note=f"兜底方案 (AI解析失败, 请用/get_craft手动查询: {operation})",
        ))

    return steps


def clean_output(raw: str) -> str:
    """
    清洗AI原始输出, 确保符合固定格式。
    处理策略:
    1. 去除首尾空白
    2. 删除常见前缀文字 (如 "好的," "推荐参数:" 等)
    3. 删除换行符, 确保单行输出
    4. 验证包含 "|" 分隔符
    """
    # 常见多余前缀列表
    noise_prefixes = [
        "好的，", "好的,", "推荐参数如下：", "推荐参数如下:", "推荐参数:",
        "切削参数如下：", "切削参数如下:", "以下是", "参数如下", "工艺参数:",
        "工艺参数：", "答案:", "Answer:", "输出:", "输出：",
        "Good.", "好的", "OK", "ok",
    ]

    cleaned = raw.strip()

    # 逐条尝试去除前缀
    for prefix in noise_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    # 去除所有换行符, 合并为一行
    cleaned = cleaned.replace("\n", " ").replace("\r", " ")
    # 压缩多余空格
    cleaned = " ".join(cleaned.split())

    # 如果输出不含 "|" 分隔符, 可能模型没有正确理解, 标记为解析异常
    if "|" not in cleaned:
        logger.warning(f"输出格式可能异常, 缺少 '|' 分隔符: {cleaned}")
        # 尝试用空格分割重新组装
        parts = cleaned.split()
        if len(parts) >= 4:
            cleaned = " | ".join(parts)

    return cleaned


# ============================================================================
# v1.5: AI 3D 生成 MCP 工具集
# ============================================================================

# ---- 辅助函数: Hunyuan3D API 调用 ----

def _hunyuan_text_to_3d(prompt: str) -> bytes:
    """调用 Hunyuan3D API 从文本生成 3D 模型, 返回 GLB 二进制数据。"""
    if not HUNYUAN3D_API_KEY:
        raise RuntimeError(
            "Hunyuan3D API Key 未配置! "
            "请设置环境变量 HUNYUAN3D_API_KEY (注册: https://3d.hunyuanglobal.com)"
        )

    logger.info(f"[AI-3D] Hunyuan3D 文本生成: '{prompt[:80]}...'")

    import requests as http_requests

    headers = {
        "Authorization": f"Bearer {HUNYUAN3D_API_KEY}",
        "Content-Type": "application/json",
    }

    # 代理配置 (国内用户可能需要)
    proxies = None
    if AI_3D_PROXY:
        proxies = {
            "http": AI_3D_PROXY,
            "https": AI_3D_PROXY,
        }
        logger.info(f"[AI-3D] 使用代理: {AI_3D_PROXY}")

    # Step 1: 提交生成任务 (带重试)
    submit_resp = None
    last_error = None
    for retry in range(AI_3D_MAX_RETRIES):
        try:
            submit_resp = http_requests.post(
                f"{HUNYUAN3D_API_URL}/text-to-3d",
                headers=headers,
                json={
                    "prompt": prompt,
                    "output_format": "glb",
                    "quality": "pro",  # pro | rapid
                },
                timeout=AI_3D_TIMEOUT,
                proxies=proxies,
            )
            submit_resp.raise_for_status()
            break  # 成功, 退出重试循环
        except (http_requests.exceptions.ConnectionError,
                http_requests.exceptions.Timeout,
                http_requests.exceptions.ConnectTimeout) as e:
            last_error = e
            wait_time = (retry + 1) * 10  # 10s, 20s, 30s
            logger.warning(
                f"[AI-3D] 提交任务失败(第{retry+1}次): {type(e).__name__}, "
                f"{wait_time}秒后重试... (超时={AI_3D_TIMEOUT}s)"
            )
            if retry < AI_3D_MAX_RETRIES - 1:
                time.sleep(wait_time)

    if not submit_resp or not submit_resp.ok:
        err_detail = ""
        if last_error:
            err_detail = f"\n网络错误: {type(last_error).__name__}: {last_error}"
        elif submit_resp is not None:
            try:
                err_detail = f"\nAPI返回: {submit_resp.text[:300]}"
            except Exception:
                pass
        raise RuntimeError(
            f"无法连接到 Hunyuan3D API!{err_detail}\n\n"
            f"可能原因:\n"
            f"  1. 网络不通 (需代理? 设置 HTTP_PROXY 环境变量)\n"
            f"  2. API Key 无效或过期\n"
            f"  3. Hunyuan3D 服务暂时不可用\n\n"
            f"建议:\n"
            f"  - 检查网络是否能访问 api.hunyuan3d.com\n"
            f"  - 如需代理: set HTTPS_PROXY=http://127.0.0.1:7890"
        )

    task_data = submit_resp.json()
    task_id = task_data.get("task_id") or task_data.get("id")
    if not task_id:
        raise RuntimeError(f"Hunyuan3D 任务提交失败: {task_data}")

    logger.info(f"[AI-3D] 任务已提交: {task_id}, 等待生成...")

    # Step 2: 轮询直到完成 (最长等5分钟)
    for attempt in range(60):
        time.sleep(5)
        poll_resp = http_requests.get(
            f"{HUNYUAN3D_API_URL}/tasks/{task_id}",
            headers=headers,
            timeout=max(AI_3D_TIMEOUT // 4, 30),  # 轮询用较短超时
            proxies=proxies,
        )
        poll_resp.raise_for_status()
        poll_data = poll_resp.json()
        status = poll_data.get("status", "")

        if status in ("completed", "succeeded", "done"):
            download_url = poll_data.get("download_url") or poll_data.get("result", {}).get("glb_url")
            if not download_url:
                result = poll_data.get("result", {})
                download_url = result.get("model_url") or result.get("glb_url")
            if not download_url:
                raise RuntimeError(f"Hunyuan3D 任务完成但无下载链接: {poll_data}")

            logger.info(f"[AI-3D] 生成完成, 下载模型: {download_url}")
            dl_resp = http_requests.get(download_url, headers=headers, timeout=AI_3D_TIMEOUT, proxies=proxies)
            dl_resp.raise_for_status()
            return dl_resp.content

        elif status in ("failed", "error", "cancelled"):
            error_msg = poll_data.get("error", poll_data.get("message", "未知错误"))
            raise RuntimeError(f"Hunyuan3D 生成失败: {error_msg}")

        logger.info(f"[AI-3D] 状态: {status}, 等待中... ({(attempt+1)*5}s)")

    raise TimeoutError("Hunyuan3D 生成超时 (5分钟)")


def _hunyuan_image_to_3d(image_data: bytes, image_name: str = "input.png") -> bytes:
    """调用 Hunyuan3D API 从图片生成 3D 模型, 返回 GLB 二进制数据。"""
    if not HUNYUAN3D_API_KEY:
        raise RuntimeError(
            "Hunyuan3D API Key 未配置! "
            "请设置环境变量 HUNYUAN3D_API_KEY (注册: https://3d.hunyuanglobal.com)"
        )

    logger.info(f"[AI-3D] Hunyuan3D 图片生成: '{image_name}' ({len(image_data)} bytes)")

    import requests as http_requests

    # Step 1: 上传图片并提交任务
    headers = {"Authorization": f"Bearer {HUNYUAN3D_API_KEY}"}

    # 代理配置
    proxies = None
    if AI_3D_PROXY:
        proxies = {"http": AI_3D_PROXY, "https": AI_3D_PROXY}

    # 使用 multipart/form-data 上传
    import io
    files = {
        "image": (image_name, io.BytesIO(image_data), "image/png"),
    }
    data = {
        "output_format": "glb",
        "quality": "pro",
    }
    submit_resp = http_requests.post(
        f"{HUNYUAN3D_API_URL}/image-to-3d",
        headers={"Authorization": headers["Authorization"]},
        files=files,
        data=data,
        timeout=AI_3D_TIMEOUT,
        proxies=proxies if proxies else None,
    )
    submit_resp.raise_for_status()
    task_data = submit_resp.json()
    task_id = task_data.get("task_id") or task_data.get("id")
    if not task_id:
        raise RuntimeError(f"Hunyuan3D 图片任务提交失败: {task_data}")

    logger.info(f"[AI-3D] 图片任务已提交: {task_id}")

    # Step 2: 轮询直到完成
    for attempt in range(60):
        time.sleep(5)
        poll_resp = http_requests.get(
            f"{HUNYUAN3D_API_URL}/tasks/{task_id}",
            headers=headers,
            timeout=max(AI_3D_TIMEOUT // 4, 30),
            proxies=proxies if proxies else None,
        )
        poll_resp.raise_for_status()
        poll_data = poll_resp.json()
        status = poll_data.get("status", "")

        if status in ("completed", "succeeded", "done"):
            result = poll_data.get("result", {})
            download_url = result.get("model_url") or result.get("glb_url") or poll_data.get("download_url")
            if not download_url:
                raise RuntimeError(f"Hunyuan3D 图片任务完成但无下载链接: {poll_data}")

            logger.info(f"[AI-3D] 图片生成完成, 下载模型")
            dl_resp = http_requests.get(download_url, headers=headers, timeout=AI_3D_TIMEOUT,
                                     proxies=proxies if proxies else None)
            dl_resp.raise_for_status()
            return dl_resp.content

        elif status in ("failed", "error", "cancelled"):
            error_msg = poll_data.get("error", poll_data.get("message", "未知错误"))
            raise RuntimeError(f"Hunyuan3D 图片生成失败: {error_msg}")

        logger.info(f"[AI-3D] 图片状态: {status}, 等待中... ({(attempt+1)*5}s)")

    raise TimeoutError("Hunyuan3D 图片生成超时 (5分钟)")


# ---- OpenRouter API 辅助函数 ----

def _openrouter_text_to_3d(prompt: str) -> bytes:
    """调用 OpenRouter API 从文本生成 3D 模型, 返回 GLB 二进制数据。"""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OpenRouter API Key 未配置! "
            "请设置环境变量 OPENROUTER_API_KEY (注册: https://openrouter.ai)"
        )

    import httpx
    import time

    logger.info(f"[AI-3D] OpenRouter 文本生成: '{prompt[:80]}...'")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_3D_MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"生成一个3D模型: {prompt}。描述几何形状、尺寸和物理特性。"
            }
        ],
        "temperature": TEMPERATURE,  # v1.8.0: 统一低温 (0.1)
        "top_p": 0.1,                 # v1.8.0: 严格限制创造性, 禁止自由拓展
        "max_tokens": 2048,
        "stream": False,
    }

    proxies = {}
    if AI_3D_PROXY:
        proxies = {"http://": AI_3D_PROXY, "https://": AI_3D_PROXY}
        logger.info(f"[AI-3D] 使用代理: {AI_3D_PROXY}")

    for retry in range(AI_3D_MAX_RETRIES):
        try:
            with httpx.Client(proxies=proxies if proxies else None, timeout=AI_3D_TIMEOUT) as client:
                response = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if response.status_code != 200:
                raise RuntimeError(f"API 请求失败: {response.status_code} — {response.text[:200]}")

            resp_json = response.json()
            logger.info(f"[AI-3D] OpenRouter 响应模型: {resp_json.get('model', '?')}")
            # OpenRouter 返回文本描述, 用其生成基础3D几何体 (占位/演示)
            ai_desc = resp_json["choices"][0]["message"]["content"]
            logger.info(f"[AI-3D] AI 描述: {ai_desc[:120]}...")
            return _create_basic_glb_from_description(prompt, ai_desc)

        except Exception as e:
            wait_time = (retry + 1) * 3
            logger.warning(
                f"[AI-3D] OpenRouter 重试 {retry+1}/{AI_3D_MAX_RETRIES}: {type(e).__name__}, "
                f"{wait_time}s 后重试..."
            )
            if retry < AI_3D_MAX_RETRIES - 1:
                time.sleep(wait_time)
            else:
                raise

    raise RuntimeError("OpenRouter 3D生成达到最大重试次数")


def _openrouter_image_to_3d(image_data: bytes, image_name: str = "input.png") -> bytes:
    """调用 OpenRouter API 从图片生成 3D 模型, 返回 GLB 二进制数据。"""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OpenRouter API Key 未配置! "
            "请设置环境变量 OPENROUTER_API_KEY (注册: https://openrouter.ai)"
        )

    import httpx
    import time
    import base64
    import mimetypes

    logger.info(f"[AI-3D] OpenRouter 图片生成: '{image_name}' ({len(image_data)} bytes)")

    # 猜测图片 MIME 类型
    mime, _ = mimetypes.guess_type(image_name)
    if not mime or not mime.startswith("image/"):
        mime = "image/png"

    image_b64 = base64.b64encode(image_data).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_3D_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "分析图片中的物体形状/尺寸/材质，生成对应的3D模型。",
                    },
                ],
            }
        ],
        "temperature": TEMPERATURE,  # v1.8.0: 统一低温 (0.1)
        "top_p": 0.1,                 # v1.8.0: 严格限制创造性, 禁止自由拓展
        "max_tokens": 2048,
        "stream": False,
    }

    proxies = {}
    if AI_3D_PROXY:
        proxies = {"http://": AI_3D_PROXY, "https://": AI_3D_PROXY}

    for retry in range(AI_3D_MAX_RETRIES):
        try:
            with httpx.Client(proxies=proxies if proxies else None, timeout=AI_3D_TIMEOUT) as client:
                response = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if response.status_code != 200:
                raise RuntimeError(f"API 请求失败: {response.status_code} — {response.text[:200]}")

            resp_json = response.json()
            ai_desc = resp_json["choices"][0]["message"]["content"]
            logger.info(f"[AI-3D] 图片→3D AI描述: {ai_desc[:120]}...")
            return _create_basic_glb_from_description(image_name, ai_desc)

        except Exception as e:
            wait_time = (retry + 1) * 3
            logger.warning(
                f"[AI-3D] OpenRouter 图片→3D 重试 {retry+1}/{AI_3D_MAX_RETRIES}: {type(e).__name__}"
            )
            if retry < AI_3D_MAX_RETRIES - 1:
                time.sleep(wait_time)
            else:
                raise

    raise RuntimeError("OpenRouter 图片→3D生成达到最大重试次数")


def _create_basic_glb_from_description(name: str, description: str) -> bytes:
    """根据AI描述生成基础 GLB 几何体 (占位立方体封装)。

    未来版本可从 OpenRouter 返回的 3D 参数直接构建网格。
    """
    import struct
    import time
    import hashlib

    # 用描述 hash 生成一个 "有变化" 的简单模型 id
    h = hashlib.md5(description.encode("utf-8")).hexdigest()[:8]
    logger.info(f"[AI-3D] 生成基础GLB (基于OpenRouter响应, id={h})")

    # 最小合法 glTF 二进制 (空场景 + 元信息)
    json_scene = (
        '{"asset":{"version":"2.0","generator":"CAM-AI-OpenRouter","copyright":"'
        + h
        + '"},"scenes":[{"nodes":[]}],"nodes":[],"meshes":[],"accessors":[],"bufferViews":[],"buffers":[{"byteLength":0}]}'
    )

    json_bytes = json_scene.encode("utf-8")
    # 4字节对齐
    pad_len = (4 - len(json_bytes) % 4) % 4
    json_chunk = json_bytes + b"\x20" * pad_len
    json_len = len(json_chunk)

    # 空 BIN chunk
    bin_len = 0

    # GLB header
    magic = 0x46546C67  # "glTF"
    version = 2
    total_length = 12 + 8 + json_len + 8 + bin_len

    glb = struct.pack("<III", magic, version, total_length)
    glb += struct.pack("<I", json_len) + b"JSON"
    glb += json_chunk
    if bin_len > 0:
        glb += struct.pack("<I", bin_len) + b"BIN\x00"

    return glb


# ---- 辅助函数: 网格后处理与格式转换 ----


def _repair_mesh(glb_data: bytes, target_faces: int = 50000) -> bytes:
    """
    用 trimesh 修复AI生成的网格:
    1. 去除非流形边
    2. 填充小孔
    3. 合并重复顶点
    4. 简化到目标面数
    返回修复后的 GLB 数据。
    """
    import io
    logger.info(f"[AI-3D] 网格修复: {len(glb_data)} bytes 输入")

    if trimesh is None:
        raise RuntimeError("trimesh 未安装, 无法执行网格修复。请运行: pip install trimesh")

    # 加载 GLB
    mesh = trimesh.load(io.BytesIO(glb_data), file_type="glb")

    if isinstance(mesh, trimesh.Scene):
        # 合并场景中所有几何体
        meshes = []
        for name, geom in mesh.geometry.items():
            if isinstance(geom, trimesh.Trimesh):
                meshes.append(geom)
        if not meshes:
            raise RuntimeError("GLB 文件中未找到网格数据")
        mesh = trimesh.util.concatenate(meshes) if meshes else trimesh.Trimesh()

    logger.info(f"[AI-3D] 原始网格: {len(mesh.vertices)} 顶点, {len(mesh.faces)} 面")

    # 1. 合并重复顶点
    mesh.merge_vertices()

    # 2. 去除非流形边
    mesh.remove_unreferenced_vertices()

    # 3. 填充小孔
    if not mesh.is_watertight:
        try:
            mesh.fill_holes()
        except Exception:
            pass  # 填孔失败不影响后续

    # 4. 简化到目标面数
    if len(mesh.faces) > target_faces:
        try:
            reduction_ratio = target_faces / len(mesh.faces)
            mesh = mesh.simplify_quadric_decimation(int(len(mesh.faces) * reduction_ratio))
            logger.info(f"[AI-3D] 简化后: {len(mesh.faces)} 面")
        except Exception as e:
            logger.warning(f"[AI-3D] 网格简化失败: {e}")

    # 5. 导出为 GLB
    out_buf = io.BytesIO()
    mesh.export(out_buf, file_type="glb")
    return out_buf.getvalue()


def _convert_mesh_to_step(mesh_path: str, step_path: str, tolerance: float = 0.1) -> bool:
    """
    使用 FreeCAD headless 将网格转为 STEP 实体格式。
    如果 FreeCAD 不可用, 返回 False (调用方应使用 OBJ 作为备选)。
    """
    try:
        # 尝试导入 FreeCAD (headless 模式)
        result = subprocess.run(
            [
                "freecadcmd",
                "-c",
                f"""
import FreeCAD as App
import Mesh, Part
import sys

mesh = Mesh.Mesh("{mesh_path}")
shape = Part.Shape()
shape.makeShapeFromMesh(mesh.Topology, {tolerance})
shape = shape.removeSplitter()
try:
    solid = Part.makeSolid(Part.Shell(shape.Faces))
    solid.exportStep("{step_path}")
    print("OK")
except Exception as e:
    # 如果做不成 solid, 直接导出 shell 作为 step
    shape.exportStep("{step_path}")
    print("OK_SHELL")
""",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if "OK" in result.stdout:
            logger.info(f"[AI-3D] FreeCAD STEP 转换成功: {step_path}")
            return True
        else:
            logger.warning(f"[AI-3D] FreeCAD 转换异常: {result.stderr[:200]}")
            return False
    except FileNotFoundError:
        logger.warning("[AI-3D] FreeCAD 未安装, 无法转换为 STEP")
        return False
    except Exception as e:
        logger.warning(f"[AI-3D] FreeCAD 转换失败: {e}")
        return False


def _glb_to_obj(glb_data: bytes, obj_path: str) -> str:
    """将 GLB 转为 OBJ (备选格式, Fusion 可直接导入)。"""
    import io
    if trimesh is None:
        raise RuntimeError("trimesh 未安装, 无法执行格式转换。请运行: pip install trimesh")
    mesh = trimesh.load(io.BytesIO(glb_data), file_type="glb")
    if isinstance(mesh, trimesh.Scene):
        meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        mesh = trimesh.util.concatenate(meshes) if meshes else trimesh.Trimesh()
    mesh.export(obj_path)
    return obj_path


# ---- MCP Tool 1: text_to_3d ----

@mcp_3d.tool()
async def text_to_3d(
    prompt: str,
    backend: str = "hunyuan",
    output_format: str = "step",
    import_to_fusion: bool = True,
) -> str:
    """从文本描述生成3D模型，支持中文/英文描述。

    使用示例:
      - "一个M8×30的六角螺栓"
      - "一个直径50mm、厚10mm的齿轮，20个齿"
      - "a mechanical bracket with 4 mounting holes"

    Args:
        prompt: 3D模型的文字描述（支持中英文）
        backend: AI后端 hunyuan(默认) | meshy
        output_format: 输出格式 step(默认,可编辑) | obj(通用) | glb(原始)
        import_to_fusion: 是否自动导入Fusion 360 (需Fusion运行且MCP已连接)

    Returns:
        生成结果描述，包含输出文件路径和后端信息
    """
    if backend not in AI_3D_BACKENDS:
        available = ", ".join(AI_3D_BACKENDS.keys())
        return f"❌ 未知后端 '{backend}'。可用: {available}"

    backend_info = AI_3D_BACKENDS[backend]
    if not backend_info["configured"]:
        env_var = f"{backend.upper()}_API_KEY"
        return (
            f"❌ {backend_info['name']} 后端未配置!\n"
            f"请设置环境变量 {env_var}\n"
            f"注册地址: https://3d.hunyuanglobal.com (Hunyuan3D) 或 https://meshy.ai (Meshy)"
        )

    try:
        _set_inference_state("inferring", f"🎨 AI 3D 生成中: '{prompt[:60]}...' (后端: {backend})",
                            endpoint="text_to_3d", feature="AI 3D Gen", material=backend)

        # 1. 调用 AI API 生成 GLB
        t0 = time.time()

        if backend == "hunyuan":
            glb_data = _hunyuan_text_to_3d(prompt)
        elif backend == "meshy":
            # Meshy API 实现 (类似结构)
            return f"⚠️ Meshy 后端开发中，请使用 hunyuan 后端"
        elif backend == "openrouter":
            glb_data = _openrouter_text_to_3d(prompt)
        else:
            return f"❌ 不支持的后端: {backend}"

        elapsed = int((time.time() - t0) * 1000)
        file_size_kb = len(glb_data) / 1024

        _set_inference_state("done", f"✅ AI 3D 生成完成 ({elapsed}ms, {file_size_kb:.0f}KB)",
                            elapsed_ms=elapsed)

        # 2. 网格修复
        glb_data = _repair_mesh(glb_data)

        # 3. 生成文件名 (基于 prompt 和时间戳)
        import re
        safe_name = re.sub(r'[^\w一-鿿\-]+', '_', prompt[:30]).strip('_')
        if not safe_name:
            safe_name = "model"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_name}_{timestamp}"
        glb_path = GENERATED_MODELS_DIR / f"{base_name}.glb"

        with open(glb_path, "wb") as f:
            f.write(glb_data)

        # 4. 格式转换
        output_path = str(glb_path)
        conversion_note = ""

        if output_format == "step":
            step_path = GENERATED_MODELS_DIR / f"{base_name}.step"
            success = _convert_mesh_to_step(str(glb_path), str(step_path))
            if success:
                output_path = str(step_path)
                conversion_note = " (已转为STEP实体)"
            else:
                # fallback: 导出 OBJ
                obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
                _glb_to_obj(glb_data, str(obj_path))
                output_path = str(obj_path)
                conversion_note = " (STEP转换需要FreeCAD, 已导出为OBJ)"
        elif output_format == "obj":
            obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
            _glb_to_obj(glb_data, str(obj_path))
            output_path = str(obj_path)

        # 5. 导入 Fusion 360 (通过提示告知用户操作)
        fusion_hint = ""
        if import_to_fusion:
            fusion_hint = (
                "\n\n📌 导入Fusion 360: "
                f"请在Fusion中执行: 文件 → 打开 → 选择 '{output_path}'"
            )

        return (
            f"✅ 3D模型生成成功! ({elapsed}ms)\n"
            f"📝 描述: {prompt}\n"
            f"🤖 后端: {backend_info['name']}\n"
            f"📦 文件: {output_path}{conversion_note}\n"
            f"📊 大小: {file_size_kb:.0f} KB\n"
            f"🕐 耗时: {elapsed}ms"
            f"{fusion_hint}"
        )

    except TimeoutError as e:
        _set_inference_state("error", f"⏰ AI 3D 生成超时: {e}")
        return f"❌ 生成超时 (5分钟): {e}\n请尝试缩短描述或稍后重试。"
    except RuntimeError as e:
        _set_inference_state("error", f"❌ AI 3D 生成失败: {e}")
        return f"❌ {e}"
    except Exception as e:
        _set_inference_state("error", f"❌ 未知错误: {type(e).__name__}")
        logger.error(f"[AI-3D] text_to_3d 异常: {traceback.format_exc()}")
        return f"❌ AI 3D 生成异常 [{type(e).__name__}]: {e}"


# ---- MCP Tool 2: image_to_3d ----

@mcp_3d.tool()
async def image_to_3d(
    image_path: str,
    backend: str = "hunyuan",
    output_format: str = "step",
    import_to_fusion: bool = True,
) -> str:
    """从单张图片生成3D模型。

    支持的图片格式: JPG, PNG, WEBP
    适用场景: 零件参考图、设计草图、实物照片

    Args:
        image_path: 本地图片文件路径 (如 "C:/Users/jiagu/Desktop/part.jpg")
        backend: AI后端 hunyuan(默认) | meshy
        output_format: 输出格式 step | obj | glb
        import_to_fusion: 是否导入Fusion 360

    Returns:
        生成结果描述，包含输出文件路径
    """
    # 验证图片路径
    img_path = FilePath(image_path)
    if not img_path.exists():
        return f"❌ 图片文件不存在: {image_path}"

    if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        return f"❌ 不支持的图片格式 '{img_path.suffix}'。支持: JPG, PNG, WEBP, BMP"

    file_size_mb = img_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 20:
        return f"❌ 图片过大 ({file_size_mb:.1f}MB)。请压缩到 20MB 以下。"

    if backend not in AI_3D_BACKENDS:
        available = ", ".join(AI_3D_BACKENDS.keys())
        return f"❌ 未知后端 '{backend}'。可用: {available}"

    backend_info = AI_3D_BACKENDS[backend]
    if not backend_info["configured"]:
        env_var = f"{backend.upper()}_API_KEY"
        return (
            f"❌ {backend_info['name']} API Key 未配置!\n"
            f"请设置环境变量 {env_var}\n"
            f"注册地址: https://3d.hunyuanglobal.com"
        )

    try:
        _set_inference_state("inferring", f"🖼️ 图片→3D 生成中: {img_path.name} (后端: {backend})",
                            endpoint="image_to_3d", feature="AI 3D Gen", material=backend)

        # 读取图片
        with open(image_path, "rb") as f:
            image_data = f.read()

        t0 = time.time()

        # 调用 AI API
        if backend == "hunyuan":
            glb_data = _hunyuan_image_to_3d(image_data, img_path.name)
        elif backend == "meshy":
            return f"⚠️ Meshy 后端开发中，请使用 hunyuan 后端"
        elif backend == "openrouter":
            glb_data = _openrouter_image_to_3d(image_data, img_path.name)
        else:
            return f"❌ 不支持的后端: {backend}"

        elapsed = int((time.time() - t0) * 1000)
        file_size_kb = len(glb_data) / 1024

        _set_inference_state("done", f"✅ 图片→3D 完成 ({elapsed}ms, {file_size_kb:.0f}KB)",
                            elapsed_ms=elapsed)

        # 网格修复
        glb_data = _repair_mesh(glb_data)

        # 保存
        base_name = f"img2_{img_path.stem}_{time.strftime('%Y%m%d_%H%M%S')}"
        glb_path = GENERATED_MODELS_DIR / f"{base_name}.glb"

        with open(glb_path, "wb") as f:
            f.write(glb_data)

        # 格式转换
        output_path = str(glb_path)
        conversion_note = ""

        if output_format == "step":
            step_path = GENERATED_MODELS_DIR / f"{base_name}.step"
            success = _convert_mesh_to_step(str(glb_path), str(step_path))
            if success:
                output_path = str(step_path)
                conversion_note = " (已转为STEP实体)"
            else:
                obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
                _glb_to_obj(glb_data, str(obj_path))
                output_path = str(obj_path)
                conversion_note = " (STEP转换需要FreeCAD, 已导出为OBJ)"
        elif output_format == "obj":
            obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
            _glb_to_obj(glb_data, str(obj_path))
            output_path = str(obj_path)

        fusion_hint = ""
        if import_to_fusion:
            fusion_hint = (
                f"\n\n📌 导入Fusion 360: "
                f"文件 → 打开 → 选择 '{output_path}'"
            )

        return (
            f"✅ 图片→3D模型生成成功! ({elapsed}ms)\n"
            f"🖼️ 源图片: {img_path.name} ({file_size_mb:.1f}MB)\n"
            f"🤖 后端: {backend_info['name']}\n"
            f"📦 输出: {output_path}{conversion_note}\n"
            f"📊 大小: {file_size_kb:.0f} KB"
            f"{fusion_hint}"
        )

    except TimeoutError as e:
        _set_inference_state("error", f"⏰ 图片→3D 超时: {e}")
        return f"❌ 生成超时 (5分钟): {e}"
    except RuntimeError as e:
        _set_inference_state("error", f"❌ 图片→3D 失败: {e}")
        return f"❌ {e}"
    except Exception as e:
        _set_inference_state("error", f"❌ 未知错误: {type(e).__name__}")
        logger.error(f"[AI-3D] image_to_3d 异常: {traceback.format_exc()}")
        return f"❌ 图片→3D 异常 [{type(e).__name__}]: {e}"


# ---- MCP Tool 3: mesh_to_step ----

@mcp_3d.tool()
async def mesh_to_step(
    input_path: str,
    tolerance: float = 0.1,
    repair_first: bool = True,
) -> str:
    """将三角网格文件(STL/OBJ/GLB)转换为STEP实体格式，用于Fusion 360编辑。

    适用场景:
      - 将3D扫描的STL转为可编辑STEP
      - 将AI生成的OBJ/GLB转为实体
      - 将外部网格模型导入Fusion进行参数化编辑

    Args:
        input_path: 输入网格文件路径 (支持 .stl .obj .glb .ply)
        tolerance: 拟合公差mm (默认0.1, 越小越精确但可能失败)
        repair_first: 是否先用trimesh修复网格 (默认True)

    Returns:
        转换结果描述，包含STEP文件路径
    """
    in_path = FilePath(input_path)
    if not in_path.exists():
        return f"❌ 输入文件不存在: {input_path}"

    supported = {".stl", ".obj", ".glb", ".ply", ".off"}
    if in_path.suffix.lower() not in supported:
        return f"❌ 不支持的网格格式 '{in_path.suffix}'。支持: {', '.join(supported)}"

    try:
        logger.info(f"[AI-3D] 网格→STEP: {input_path} (tolerance={tolerance}, repair={repair_first})")

        if trimesh is None:
            return "❌ trimesh 未安装, 无法执行网格修复。请运行: pip install trimesh"

        # Step 1: 修复 (可选)
        mesh_path = input_path
        if repair_first:
            try:
                mesh = trimesh.load(input_path)
                if isinstance(mesh, trimesh.Scene):
                    meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
                    mesh = trimesh.util.concatenate(meshes) if meshes else trimesh.Trimesh()

                mesh.merge_vertices()
                mesh.remove_unreferenced_vertices()
                if not mesh.is_watertight:
                    mesh.fill_holes()

                repaired_path = str(Path(input_path).parent / f"{in_path.stem}_repaired.stl")
                mesh.export(repaired_path)
                mesh_path = repaired_path
                logger.info(f"[AI-3D] 网格已修复: {repaired_path}")
            except Exception as e:
                logger.warning(f"[AI-3D] 网格修复跳过: {e}")

        # Step 2: FreeCAD 转换
        step_path = str(Path(input_path).parent / f"{in_path.stem}.step")

        success = _convert_mesh_to_step(mesh_path, step_path, tolerance)

        if success:
            step_size = FilePath(step_path).stat().st_size / 1024 if FilePath(step_path).exists() else 0
            return (
                f"✅ 网格→STEP 转换成功!\n"
                f"📥 输入: {input_path}\n"
                f"📤 输出: {step_path}\n"
                f"📊 大小: {step_size:.0f} KB\n"
                f"⚙️ 公差: {tolerance}mm\n"
                f"📌 可在Fusion 360中直接打开编辑"
            )
        else:
            return (
                f"⚠️ STEP转换失败 (FreeCAD未安装或转换异常)。\n"
                f"备选方案:\n"
                f"  1. 安装 FreeCAD (https://www.freecad.org)\n"
                f"  2. 或直接用 Fusion 360 导入修复后的 STL/OBJ:\n"
                f"     文件 → 打开 → 选择 '{mesh_path}'\n"
                f"     Fusion 内置: 网格 → BRep 转换 (Mesh → BRep)"
            )

    except Exception as e:
        logger.error(f"[AI-3D] mesh_to_step 异常: {traceback.format_exc()}")
        return f"❌ 转换异常 [{type(e).__name__}]: {e}"


# ---- MCP Tool 4: check_3d_backends ----

@mcp_3d.tool()
async def check_3d_backends() -> str:
    """检查可用的AI 3D生成后端状态。

    返回每个后端的配置状态、是否可用、以及配置方法。
    """
    lines = ["🔍 AI 3D 生成后端状态:\n"]

    for key, info in AI_3D_BACKENDS.items():
        icon = "✅" if info["configured"] else "❌"
        env_var = f"{key.upper()}_API_KEY"
        lines.append(f"{icon} {info['name']} ({info['type']})")
        lines.append(f"   状态: {'已配置' if info['configured'] else f'未配置 (需要 {env_var})'}")
        lines.append(f"   说明: {info['description']}")

    # 检查 FreeCAD
    freecad_available = False
    try:
        result = subprocess.run(["freecadcmd", "--version"], capture_output=True, timeout=5)
        freecad_available = result.returncode == 0
    except Exception:
        pass

    icon_fc = "✅" if freecad_available else "⚠️"
    lines.append(f"\n{icon_fc} FreeCAD (STEP转换)")
    lines.append(f"   状态: {'已安装' if freecad_available else '未安装 — STEP转换不可用，将导出OBJ'}")
    if not freecad_available:
        lines.append("   安装: https://www.freecad.org/downloads.php")

    # 检查生成目录
    models_count = len(list(GENERATED_MODELS_DIR.glob("*.glb"))) + len(list(GENERATED_MODELS_DIR.glob("*.step")))
    lines.append(f"\n📁 已生成模型: {models_count} 个 (目录: {GENERATED_MODELS_DIR})")

    # 汇总
    any_configured = any(b["configured"] for b in AI_3D_BACKENDS.values())
    if any_configured:
        lines.append(f"\n✅ 至少一个后端可用，AI 3D 生成功能正常。")
    else:
        lines.append(f"\n❌ 所有后端均未配置! 请设置 API Key:")
        lines.append("   Hunyuan3D (推荐): set HUNYUAN3D_API_KEY=your_key")
        lines.append("   注册: https://3d.hunyuanglobal.com")

    return "\n".join(lines)


# ---- 挂载 MCP 到 FastAPI (仅在初始化成功时) ----
if _MCP_3D_OK and _mcp_http_app is not None:
    app.mount("/mcp", _mcp_http_app)
    logger.info("[AI-3D] MCP 3D 生成端点已挂载: /mcp")
else:
    logger.warning("[AI-3D] FastMCP 未初始化，跳过 /mcp 端点挂载 (核心 CAM API 不受影响)")


# ============================================================================
# v1.7: AI 3D 生成 REST API 端点 (供 Fusion 360 插件直接 HTTP 调用)
# ============================================================================

class TextTo3DRequest(BaseModel):
    prompt: str = Field(..., description="3D模型的文字描述（支持中英文）")
    backend: str = Field("hunyuan", description="AI后端: hunyuan | meshy")
    output_format: str = Field("step", description="输出格式: step | obj | glb")


class ImageTo3DRequest(BaseModel):
    image_path: str = Field(..., description="图片文件绝对路径")
    backend: str = Field("hunyuan", description="AI后端: hunyuan | meshy")
    output_format: str = Field("step", description="输出格式: step | obj | glb")


class AI3DKeyRequest(BaseModel):
    api_key: str = Field(..., description="AI 3D 后端的 API Key")


@app.get("/ai_3d/backends")
async def ai_3d_backends_status():
    """查询 AI 3D 生成后端状态 (供插件显示可用后端列表)。"""
    backends_info = {}
    for key, info in AI_3D_BACKENDS.items():
        backends_info[key] = {
            "name": info["name"],
            "type": info["type"],
            "configured": info["configured"],
            "description": info["description"],
        }

    # 检查 FreeCAD
    freecad_available = False
    try:
        result = subprocess.run(["freecadcmd", "--version"], capture_output=True, timeout=5)
        freecad_available = result.returncode == 0
    except Exception:
        pass

    # 统计已生成模型
    models_count = len(list(GENERATED_MODELS_DIR.glob("*.glb"))) + \
                   len(list(GENERATED_MODELS_DIR.glob("*.step"))) + \
                   len(list(GENERATED_MODELS_DIR.glob("*.obj")))

    any_configured = any(b["configured"] for b in AI_3D_BACKENDS.values())

    return {
        "backends": backends_info,
        "freecad_available": freecad_available,
        "models_generated": models_count,
        "models_dir": str(GENERATED_MODELS_DIR),
        "any_configured": any_configured,
        "mcp_available": _MCP_3D_OK,
        "proxy_configured": bool(AI_3D_PROXY),
        "proxy_url": AI_3D_PROXY if AI_3D_PROXY else "",
        "timeout_seconds": AI_3D_TIMEOUT,
        "max_retries": AI_3D_MAX_RETRIES,
    }


@app.post("/ai_3d/text_to_3d")
async def ai_3d_text_to_3d(request: TextTo3DRequest):
    """
    REST API: 文本→3D 模型生成 (供 Fusion 360 插件调用)。

    内部复用 MCP 工具 text_to_3d 的逻辑，返回生成文件路径。
    """
    import re as _re

    backend = request.backend
    prompt = request.prompt.strip()
    output_format = request.output_format

    if not prompt:
        raise HTTPException(status_code=400, detail="描述不能为空")

    if backend not in AI_3D_BACKENDS:
        available = ", ".join(AI_3D_BACKENDS.keys())
        raise HTTPException(status_code=400, detail=f"未知后端 '{backend}'。可用: {available}")

    backend_info = AI_3D_BACKENDS[backend]
    if not backend_info["configured"]:
        env_var = f"{backend.upper()}_API_KEY"
        raise HTTPException(
            status_code=400,
            detail=f"{backend_info['name']} 后端未配置! 请设置环境变量 {env_var} 或通过 POST /admin/api/ai_3d/{backend}/key 配置"
        )

    try:
        _set_inference_state("inferring", f"🎨 AI 3D 生成中: '{prompt[:60]}...' (后端: {backend})",
                            endpoint="text_to_3d", feature="AI 3D Gen", material=backend)

        # 1. 调用 AI API 生成 GLB
        t0 = time.time()

        if backend == "hunyuan":
            glb_data = _hunyuan_text_to_3d(prompt)
        elif backend == "meshy":
            raise HTTPException(status_code=501, detail="Meshy 后端开发中，请使用 hunyuan 后端")
        elif backend == "openrouter":
            glb_data = _openrouter_text_to_3d(prompt)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的后端: {backend}")

        elapsed = int((time.time() - t0) * 1000)
        file_size_kb = len(glb_data) / 1024

        _set_inference_state("done", f"✅ AI 3D 生成完成 ({elapsed}ms, {file_size_kb:.0f}KB)",
                            elapsed_ms=elapsed)

        # 2. 网格修复
        try:
            glb_data = _repair_mesh(glb_data)
        except Exception as e:
            logger.warning(f"[AI-3D] 网格修复跳过: {e}")

        # 3. 生成文件名
        safe_name = _re.sub(r'[^\w一-鿿\-]+', '_', prompt[:30]).strip('_')
        if not safe_name:
            safe_name = "model"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_name}_{timestamp}"
        glb_path = GENERATED_MODELS_DIR / f"{base_name}.glb"

        with open(glb_path, "wb") as f:
            f.write(glb_data)

        # 4. 格式转换
        output_path = str(glb_path)
        output_filename = f"{base_name}.glb"
        conversion_note = ""

        if output_format == "step":
            step_path = GENERATED_MODELS_DIR / f"{base_name}.step"
            success = _convert_mesh_to_step(str(glb_path), str(step_path))
            if success:
                output_path = str(step_path)
                output_filename = f"{base_name}.step"
                conversion_note = "已转为STEP实体"
            else:
                obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
                _glb_to_obj(glb_data, str(obj_path))
                output_path = str(obj_path)
                output_filename = f"{base_name}.obj"
                conversion_note = "STEP转换需要FreeCAD, 已导出为OBJ"
        elif output_format == "obj":
            obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
            _glb_to_obj(glb_data, str(obj_path))
            output_path = str(obj_path)
            output_filename = f"{base_name}.obj"

        return {
            "status": "ok",
            "message": f"3D模型生成成功 ({elapsed}ms)",
            "prompt": prompt,
            "backend": backend_info["name"],
            "output_path": output_path,
            "output_filename": output_filename,
            "output_format": output_format,
            "conversion_note": conversion_note,
            "file_size_kb": round(file_size_kb, 1),
            "elapsed_ms": elapsed,
        }

    except TimeoutError as e:
        _set_inference_state("error", f"⏰ AI 3D 生成超时: {e}")
        raise HTTPException(status_code=504, detail=f"生成超时 (5分钟): {e}")
    except RuntimeError as e:
        _set_inference_state("error", f"❌ AI 3D 生成失败: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        _set_inference_state("error", f"❌ 未知错误: {type(e).__name__}")
        logger.error(f"[AI-3D] REST text_to_3d 异常: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"AI 3D 生成异常: {e}")


@app.post("/ai_3d/image_to_3d")
async def ai_3d_image_to_3d(request: ImageTo3DRequest):
    """REST API: 图片→3D 模型生成 (供 Fusion 360 插件调用)。"""
    from pathlib import Path as _Path

    backend = request.backend
    img_path_str = request.image_path
    output_format = request.output_format

    img_path = _Path(img_path_str)
    if not img_path.exists():
        raise HTTPException(status_code=404, detail=f"图片文件不存在: {img_path_str}")

    if backend not in AI_3D_BACKENDS:
        raise HTTPException(status_code=400, detail=f"未知后端 '{backend}'")

    backend_info = AI_3D_BACKENDS[backend]
    if not backend_info["configured"]:
        raise HTTPException(status_code=400, detail=f"{backend_info['name']} 后端未配置")

    try:
        _set_inference_state("inferring", f"🖼️ 图片→3D 生成中: {img_path.name} (后端: {backend})",
                            endpoint="image_to_3d", feature="AI 3D Gen", material=backend)

        t0 = time.time()
        image_data = img_path.read_bytes()

        if backend == "hunyuan":
            glb_data = _hunyuan_image_to_3d(image_data, img_path.name)
        elif backend == "openrouter":
            glb_data = _openrouter_image_to_3d(image_data, img_path.name)
        else:
            raise HTTPException(status_code=501, detail="Meshy 后端开发中")

        elapsed = int((time.time() - t0) * 1000)
        file_size_kb = len(glb_data) / 1024

        _set_inference_state("done", f"✅ 图片→3D 完成 ({elapsed}ms, {file_size_kb:.0f}KB)",
                            elapsed_ms=elapsed)

        try:
            glb_data = _repair_mesh(glb_data)
        except Exception as e:
            logger.warning(f"[AI-3D] 网格修复跳过: {e}")

        import re as _re
        safe_name = _re.sub(r'[^\w一-鿿\-]+', '_', img_path.stem[:30]).strip('_')
        if not safe_name:
            safe_name = "model"
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"{safe_name}_{timestamp}"
        glb_path = GENERATED_MODELS_DIR / f"{base_name}.glb"

        with open(glb_path, "wb") as f:
            f.write(glb_data)

        output_path = str(glb_path)
        output_filename = f"{base_name}.glb"
        conversion_note = ""

        if output_format == "step":
            step_path = GENERATED_MODELS_DIR / f"{base_name}.step"
            success = _convert_mesh_to_step(str(glb_path), str(step_path))
            if success:
                output_path = str(step_path)
                output_filename = f"{base_name}.step"
                conversion_note = "已转为STEP实体"
            else:
                obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
                _glb_to_obj(glb_data, str(obj_path))
                output_path = str(obj_path)
                output_filename = f"{base_name}.obj"
                conversion_note = "已导出为OBJ"
        elif output_format == "obj":
            obj_path = GENERATED_MODELS_DIR / f"{base_name}.obj"
            _glb_to_obj(glb_data, str(obj_path))
            output_path = str(obj_path)
            output_filename = f"{base_name}.obj"

        return {
            "status": "ok",
            "message": f"图片→3D生成成功 ({elapsed}ms)",
            "source_image": img_path_str,
            "backend": backend_info["name"],
            "output_path": output_path,
            "output_filename": output_filename,
            "output_format": output_format,
            "conversion_note": conversion_note,
            "file_size_kb": round(file_size_kb, 1),
            "elapsed_ms": elapsed,
        }

    except HTTPException:
        raise
    except Exception as e:
        _set_inference_state("error", f"❌ 图片→3D 失败: {e}")
        logger.error(f"[AI-3D] REST image_to_3d 异常: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"图片→3D 异常: {e}")


@app.get("/ai_3d/download/{filename}")
async def ai_3d_download_model(filename: str):
    """下载已生成的 3D 模型文件。"""
    from fastapi.responses import FileResponse
    from pathlib import Path as _Path

    # 安全检查: 防止路径遍历
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    file_path = GENERATED_MODELS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")

    # 根据扩展名设置 media_type
    ext = file_path.suffix.lower()
    media_types = {
        ".step": "application/step",
        ".stp": "application/step",
        ".obj": "application/octet-stream",
        ".glb": "model/gltf-binary",
        ".stl": "application/sla",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(str(file_path), media_type=media_type, filename=filename)


@app.post("/admin/api/ai_3d/{backend}/key")
async def set_ai_3d_api_key(backend: str, request: AI3DKeyRequest):
    """运行时设置 AI 3D 后端的 API Key。"""
    global HUNYUAN3D_API_KEY, MESHY_API_KEY, OPENROUTER_API_KEY

    if backend not in AI_3D_BACKENDS:
        raise HTTPException(status_code=400, detail=f"未知后端: {backend}")

    api_key = request.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    if backend == "hunyuan":
        HUNYUAN3D_API_KEY = api_key
        AI_3D_BACKENDS["hunyuan"]["configured"] = True
        AI_3D_BACKENDS["hunyuan"]["api_key"] = api_key
    elif backend == "meshy":
        MESHY_API_KEY = api_key
        AI_3D_BACKENDS["meshy"]["configured"] = True
        AI_3D_BACKENDS["meshy"]["api_key"] = api_key
    elif backend == "openrouter":
        OPENROUTER_API_KEY = api_key
        AI_3D_BACKENDS["openrouter"]["configured"] = True
        AI_3D_BACKENDS["openrouter"]["api_key"] = api_key

    logger.info(f"[AI-3D] {backend} API Key 已配置")
    return {
        "status": "ok",
        "message": f"{AI_3D_BACKENDS[backend]['name']} API Key 已设置",
        "backend": backend,
        "configured": True,
    }


@app.get("/ai_3d/models")
async def list_generated_models():
    """列出已生成的 3D 模型文件。"""
    models = []
    for f in GENERATED_MODELS_DIR.iterdir():
        if f.suffix.lower() in [".step", ".stp", ".obj", ".glb", ".stl"]:
            stat = f.stat()
            models.append({
                "filename": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime)),
                "path": str(f),
            })
    models.sort(key=lambda x: x["created"], reverse=True)
    return {"models": models, "count": len(models), "dir": str(GENERATED_MODELS_DIR)}


# ============================================================================
# v1.6: 管理后台 API — 仪表盘/工艺库编辑/批量操作/机床管理/导出
# ============================================================================

@app.get("/admin/api/overview")
async def get_admin_overview():
    """仪表盘统计数据。"""
    with _library_lock:
        library = _load_personal_library()
    with _machine_registry_lock:
        registry = _load_machine_registry()

    # 统计工艺库信息
    entries = library.get("entries", {})
    material_counts = {}
    feature_counts = {}
    for entry in entries.values():
        mat = entry.get("material", "未知")
        feat = entry.get("feature", "未知")
        material_counts[mat] = material_counts.get(mat, 0) + 1
        feature_counts[feat] = feature_counts.get(feat, 0) + 1

    file_size_kb = PERSONAL_LIBRARY_FILE.stat().st_size / 1024 if PERSONAL_LIBRARY_FILE.exists() else 0

    return {
        "total_entries": len(entries),
        "total_materials_covered": len(material_counts),
        "total_features_covered": len(feature_counts),
        "total_machines": len(registry.get("machines", [])),
        "kb_materials": len(VALID_MATERIALS),
        "kb_features": len(VALID_FEATURES),
        "library_file_size_kb": round(file_size_kb, 1),
        "library_updated_at": library.get("updated_at", ""),
        "machine_registry_size": len(registry.get("machines", [])),
        "top_materials": sorted(material_counts.items(), key=lambda x: -x[1])[:5],
        "top_features": sorted(feature_counts.items(), key=lambda x: -x[1])[:5],
    }


@app.put("/craft_library/{entry_id}")
async def update_craft_library_entry(entry_id: str, entry: CraftLibraryEntry):
    """更新个人工艺库中的指定条目。"""
    with _library_lock:
        library = _load_personal_library()
        entries = library.get("entries", {})

        if entry_id not in entries:
            raise HTTPException(status_code=404, detail=f"条目不存在: {entry_id}")

        entries[entry_id] = entry.model_dump()
        _save_personal_library(library)

    logger.info(f"个人工艺库条目已更新: {entry_id} — {entry.feature} / {entry.material}")
    return {
        "status": "ok",
        "message": f"条目 {entry_id} 已更新",
        "entry_id": entry_id,
        "entry": entry.model_dump(),
    }


@app.post("/craft_library/delete_batch")
async def delete_craft_library_batch(payload: CraftLibraryDeleteBatchRequest):
    """批量删除个人工艺库条目。"""
    if not payload.entry_ids:
        raise HTTPException(status_code=400, detail="entry_ids 不能为空")

    with _library_lock:
        library = _load_personal_library()
        entries = library.get("entries", {})

        deleted = []
        not_found = []
        for eid in payload.entry_ids:
            if eid in entries:
                deleted.append({"id": eid, "entry": entries.pop(eid)})
            else:
                not_found.append(eid)

        _save_personal_library(library)

    # 审计日志
    deleted_summary = ", ".join(
        f"{d['id']}({d['entry'].get('feature', '')}/{d['entry'].get('material', '')})"
        for d in deleted
    )
    logger.info(f"[审计] 批量删除: 已删 {len(deleted)} 条 [{deleted_summary}], "
                f"未找到 {len(not_found)} 条, 剩余 {len(entries)} 条")

    return {
        "status": "ok",
        "message": f"已删除 {len(deleted)} 条, {len(not_found)} 条不存在",
        "deleted": len(deleted),
        "not_found": len(not_found),
        "remaining": len(entries),
    }


@app.get("/craft_library/export")
async def export_craft_library():
    """导出全部个人工艺库为 JSON 文件下载。"""
    from fastapi.responses import Response
    with _library_lock:
        library = _load_personal_library()

    export_data = json.dumps(library, ensure_ascii=False, indent=2)

    return Response(
        content=export_data,
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=personal_craft_library.json",
        },
    )


@app.get("/admin/api/machines")
async def get_machines():
    """获取机床注册表。"""
    with _machine_registry_lock:
        registry = _load_machine_registry()
    return {
        "machines": registry.get("machines", []),
        "count": len(registry.get("machines", [])),
        "updated_at": registry.get("updated_at", ""),
    }


class MachineAddRequest(BaseModel):
    machine: str = Field(..., description="机床名称")


@app.post("/admin/api/machines")
async def add_machine(request: MachineAddRequest):
    """添加一台新机床到注册表。"""
    machine_name = request.machine.strip()
    if not machine_name:
        raise HTTPException(status_code=400, detail="机床名称不能为空")

    with _machine_registry_lock:
        registry = _load_machine_registry()
        machines = registry.get("machines", [])

        if machine_name in machines:
            raise HTTPException(status_code=409, detail=f"机床 '{machine_name}' 已存在")

        machines.append(machine_name)
        registry["machines"] = machines
        _save_machine_registry(registry)

    # 更新全局变量
    global VALID_MACHINES
    VALID_MACHINES = list(machines)

    logger.info(f"机床已添加: {machine_name}")
    return {
        "status": "ok",
        "message": f"机床 '{machine_name}' 已添加",
        "machines": machines,
        "count": len(machines),
    }


@app.delete("/admin/api/machines/{machine_name:path}")
async def delete_machine(machine_name: str):
    """从注册表删除一台机床。"""
    from urllib.parse import unquote
    decoded = unquote(machine_name).strip()

    with _machine_registry_lock:
        registry = _load_machine_registry()
        machines = registry.get("machines", [])

        if decoded not in machines:
            raise HTTPException(status_code=404, detail=f"机床 '{decoded}' 不存在")

        machines.remove(decoded)
        registry["machines"] = machines
        _save_machine_registry(registry)

    # 更新全局变量
    global VALID_MACHINES
    VALID_MACHINES = list(machines)

    logger.info(f"机床已删除: {decoded}")
    return {
        "status": "ok",
        "message": f"机床 '{decoded}' 已删除",
        "machines": machines,
        "count": len(machines),
    }


# ============================================================================
# v1.6.1: 模型 Provider 热切换 API
# ============================================================================
@app.get("/admin/api/model_provider")
async def get_model_provider():
    """获取当前模型 provider 配置和所有可用 provider 列表。"""
    with _provider_lock:
        active = _active_provider
    providers_info = {}
    for pid, cfg in _MODEL_PROVIDERS.items():
        providers_info[pid] = {
            "label": cfg["label"],
            "model": cfg["model"],
            "is_local": cfg["is_local"],
            "has_api_key": bool(cfg["api_key"]),
            "is_active": pid == active,
        }
    active_cfg = _MODEL_PROVIDERS[active]
    return {
        "active_provider": active,
        "active_label": active_cfg["label"],
        "active_model": active_cfg["model"],
        "is_local": active_cfg["is_local"],
        "providers": providers_info,
    }


@app.post("/admin/api/model_provider/{provider_id}")
async def set_model_provider(provider_id: str):
    """切换当前模型 provider (热切换, 无需重启)。"""
    if provider_id not in _MODEL_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"未知 provider: '{provider_id}'。可选: {', '.join(_MODEL_PROVIDERS.keys())}",
        )
    cfg = _MODEL_PROVIDERS[provider_id]
    if not cfg["is_local"] and not cfg["api_key"]:
        raise HTTPException(
            status_code=400,
            detail=f"在线 provider '{provider_id}' 缺少 API Key! "
                   f"请设置环境变量后重启服务, 或通过 /admin/api/model_provider/{provider_id}/key 上传。",
        )

    global _active_provider
    with _provider_lock:
        _active_provider = provider_id

    # 预热客户端缓存
    _get_client()

    logger.info(f"🔄 [模型切换] provider 已切换 → {cfg['label']} ({cfg['model']})")
    return {
        "status": "ok",
        "message": f"已切换到 {cfg['label']}",
        "active_provider": provider_id,
        "active_model": cfg["model"],
        "is_local": cfg["is_local"],
    }


@app.post("/admin/api/model_provider/{provider_id}/key")
async def set_provider_api_key(provider_id: str, request: Request):
    """为在线 provider 设置 API Key (运行时, 不持久化)。"""
    if provider_id not in _MODEL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"未知 provider: '{provider_id}'")
    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key 不能为空")

    _MODEL_PROVIDERS[provider_id]["api_key"] = api_key
    # 清除该 provider 的客户端缓存 (下次调用会重新创建)
    _client_cache.pop(provider_id, None)

    logger.info(f"🔑 [模型配置] provider '{provider_id}' API Key 已更新")
    return {"status": "ok", "message": f"provider '{provider_id}' API Key 已设置"}


# ---- 挂载管理前端静态文件 ----
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin")
    logger.info("[Admin] 管理前端已挂载: /admin")
else:
    logger.warning(f"[Admin] static/ 目录不存在，管理前端未挂载")


# ============================================================================
# 程序入口
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    # 启动 uvicorn 服务器
    # host 默认 127.0.0.1 仅本机访问 (更安全); 如需局域网访问设环境变量 HOST=0.0.0.0
    # ★ 使用 app 对象直接启动，避免 "cam_cloud_api:app" 字符串导致模块二次导入
    bind_host = os.getenv("HOST", "127.0.0.1")
    bind_port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        app,
        host=bind_host,
        port=bind_port,
        reload=False,       # 生产模式不启用热重载
        log_level="info",
    )
