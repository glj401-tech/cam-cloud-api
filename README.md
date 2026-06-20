<!--
============================================================================
README.md — Fusion360 CAM 云端AI工艺推荐系统
============================================================================
-->

<div align="center">

# 🔧 Fusion360 CAM × Ollama 本地大模型 智能数控工艺推荐系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.8.0-orange)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D6?logo=windows&logoColor=white)]()
[![AI Model](https://img.shields.io/badge/AI-Ollama%20%7C%20OpenRouter-00C7B7?logo=ollama&logoColor=white)]()
[![3D Backend](https://img.shields.io/badge/3D-Hunyuan3D%20%7C%20Meshy%20%7C%20OpenRouter/Fusion-7B1FA2?logo=threedotjs&logoColor=white)]()

**Fusion360内置脚本 → 自动识别3D模型特征 → 本地FastAPI中转 → 本地Ollama大模型API → 多步工艺流程 + 刀路策略推荐 + 切削参数 → 自动弹窗展示**

</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [System Architecture](#-system-architecture)
- [Features](#-features)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [API Reference](#-api-reference)
- [Built-in Knowledge Base](#-built-in-knowledge-base)
- [Configuration](#-configuration)
- [Fusion360 Integration](#-fusion360-integration)
- [Troubleshooting](#-troubleshooting)
- [Changelog](CHANGELOG.md)
- [License](#-license)

---

## 🎯 Overview

A production-ready CNC process recommendation system that bridges **Autodesk Fusion360 CAM** with a **local Ollama LLM (通义千问 Qwen)**. The system provides **AI-generated cutting parameters** (tool, spindle speed, feed rate, depth of cut) for machining operations directly inside the Fusion360 CAM workspace.

### Key Design Decisions

| Decision | Rationale |
|---|---|
| 🖥️ Local LLM via Ollama | No cloud API costs, data stays local, no network dependency |
| 🔧 Configurable model | Default `qwen2.5:7b-instruct-q4_K_M`; can switch to any Ollama model |
| 📐 Fixed output format | `Tool | S | F | ap` — parsable, copy-paste ready for CAM dialogs |
| 🌡️ `temperature=0.1` | Minimizes hallucination; parameters are deterministic |
| 📚 Embedded knowledge base | 8 features × 14 materials with shop-floor-validated baseline params |
| ⚡ Zero middleware | No Redis, no database, no Docker — Python + FastAPI only |

---

## 🏗 System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Autodesk Fusion360                         │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  fusion360_cam_ai.py (内置Python脚本)                    │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌────────────────────┐ │  │
│  │  │ 下拉框选择   │  │ 查询按钮  │  │ 结果弹窗展示       │ │  │
│  │  │ 特征·材料·机床│  │ →调用API  │  │ 刀具|S|F|ap       │ │  │
│  │  └─────────────┘  └────┬─────┘  └────────────────────┘ │  │
│  └────────────────────────┼────────────────────────────────┘  │
└───────────────────────────┼───────────────────────────────────┘
                            │ HTTP POST /get_craft
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              Windows 11 本机 (D:\CAM_CLOUD_API)               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  FastAPI 中转服务 (cam_cloud_api.py :8000)              │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │  │
│  │  │ 1.参数校验    │→│ 2.拼装Prompt  │→│ 3.调用本地AI  │ │  │
│  │  │ 材料/特征枚举 │  │ 知识库前缀   │  │ Ollama API   │ │  │
│  │  └──────────────┘  └──────────────┘  └──────┬───────┘ │  │
│  └──────────────────────────────────────────────┼─────────┘  │
└─────────────────────────────────────────────────┼─────────────┘
                                                  │ HTTP (本地)
                                                  ▼
┌──────────────────────────────────────────────────────────────┐
│              Ollama 本地大模型服务 (端口11434)                 │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  qwen2.5:7b-instruct-q4_K_M (temperature=0.1)            │  │
│  │  → 生成标准化切削参数 (OpenAI兼容API)                    │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### 🆕 v1.8 — OpenRouter/Fusion 3D 模型在线生成
- 🎨 **OpenRouter Fusion 3D**: 文本→3D + 图片→3D, 基于 OpenRouter API 调用 `fusion` 模型, AI 描述驱动几何生成
- 🔗 **多后端支持**: Hunyuan3D (腾讯, 免费20次/天) | Meshy (付费, 4K纹理) | OpenRouter/Fusion (通用, 按量计费)
- 🖼️ **图片→3D**: 上传图片自动分析形状/尺寸/材质并生成对应3D模型
- ⚡ **运行时热切换**: `/admin/api/ai_3d/{backend}/key` 运行时配置 API Key, 无需重启
- 📦 **自动导入 Fusion360**: 生成的模型自动导入当前设计文档

### 🆕 v1.3 — AI-Powered Auto Process Planning
- 🔍 **Auto Model Feature Detection**: Scans Fusion360 BRep geometry, detects planes/holes/pockets/bosses/chamfers automatically (no manual selection needed)
- 🤖 **AI-Generated Full Process Plan**: Multi-step process plan with toolpath strategies, cutting parameters for every detected feature
- 🗺️ **Toolpath Strategy Knowledge Base**: 8 strategy categories (face milling, pocket, contour, drill cycles, surface finish, adaptive, threading, chamfer) referencing open-source CAM projects (FreeCAD Path, OpenCAMLib, FabexCNC, LinuxCNC)
- 🔧 **Tool Material Knowledge Base**: 12 tool material types with hot hardness, coatings, and application guidance
- 📤 **Personal Craft Library**: Upload/manage your own shop-validated process parameters, persisted to `personal_craft_library.json`

### Core
- 🔗 **End-to-end pipeline**: Fusion360 script → local FastAPI → cloud AI → formatted parameters
- 🎯 **Fixed output format**: `工序号. 工序名称 | 刀路策略 | 特征 | 刀具型号 | S转速 | F进给 | ap切深 | 备注`
- 📚 **Built-in knowledge base**: 8 machining features × 11 materials with validated baseline data
- 🌡️ **Low-temperature inference**: `temperature=0.1` ensures deterministic, stable outputs
- 🔒 **Offline fallback**: Knowledge base lookup works without internet / API calls

### Developer Experience
- 📝 **Fully commented code** — every function, class, and complex block
- 🧹 **Clean variable naming** — `craft_params`, `VALID_MATERIALS`, `CRAFT_KNOWLEDGE_BASE`
- 🛡️ **Input validation** — Pydantic models with enum constraints
- 📊 **Structured logging** — timestamped, level-tagged log output
- 🔍 **Health check endpoint** — API connectivity verification

### Operations
- 🚀 **One-click Windows startup** — `start_service.bat` with auto-dependency check
- 🤖 **Auto-start support** — VBScript for silent boot-time launch
- 📖 **Auto-generated API docs** — Swagger UI at `http://127.0.0.1:8000/docs`

---

## 🚀 Quick Start

### Prerequisites
- **Windows 11** (primary target; works on Win10+)
- **Python 3.10+** ([download](https://www.python.org/downloads/))
- **Ollama** 本地大模型服务 ([下载安装](https://ollama.com/download))
- **Ollama 模型** (已拉取, 如 `ollama pull qwen2.5:7b-instruct-q4_K_M`)
- **Autodesk Fusion360** with CAM workspace

### 1. Install Ollama & Pull Model
```powershell
# 下载安装 Ollama: https://ollama.com/download
# 安装完成后, 拉取所需模型:
ollama pull qwen2.5:7b-instruct-q4_K_M
# 或其他 qwen 版本:
# ollama pull qwen2.5:14b
# ollama pull qwen2.5:32b

# 启动 Ollama 服务 (通常开机自启, 也可手动启动):
ollama serve
```

### 2. Install Python Dependencies
```powershell
mkdir D:\CAM_CLOUD_API
cd D:\CAM_CLOUD_API

# Clone or copy all project files into this directory, then:
pip install -r requirements.txt
```

### 3. Configure Ollama
Edit `start_service.bat` lines 18-19 (可选, 默认即可):
```batch
set OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
set OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
```

### 4. Start the Service
```powershell
# Double-click:
start_service.bat

# Or command line:
python cam_cloud_api.py
```
You should see:
```
模型: qwen2.5:7b-instruct-q4_K_M | 温度: 0.1 | 端口: 8000
Ollama地址: http://127.0.0.1:11434/v1
Uvicorn running on http://0.0.0.0:8000
```

### 5. Verify
```powershell
# Health check
Invoke-RestMethod http://127.0.0.1:8000/health

# Test AI query
$body = '{"feature":"平面铣削","material":"6061铝","machine":"三轴立式加工中心"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/get_craft -Method Post -Body $body -ContentType "application/json"
```

### 6. Run in Fusion360
1. **Tools → Scripts & Add-Ins → Create → Python**
2. Name it `CAM_AI_Craft`
3. Paste `fusion360_cam_ai.py` contents
4. Save → **Run**

---

## 📁 Project Structure

```
D:\CAM_CLOUD_API\
├── cam_cloud_api.py              # FastAPI relay service (core backend) v1.8
├── fusion360_cam_ai.py           # Fusion360 Python script (client) v1.7
├── static/                       # 管理后台 Web UI (index.html)
│   └── index.html
├── personal_craft_library.json   # 个人工艺库 (持久化存储, 自动创建)
├── machine_registry.json         # 机床注册表 (持久化, 运行时可增删)
├── generated_models/             # AI 3D 生成模型输出目录 (v1.5)
├── requirements.txt              # Python dependency manifest
├── start_service.bat             # Windows one-click launcher
├── start_service.ps1             # PowerShell launcher
├── auto_start.vbs                # Silent auto-start script for boot
├── test_api.py                   # Quick API diagnostic script
├── DESIGN.md                     # 系统设计文档 (架构/数据流/接口/已知问题)
├── README.md                     # This file
├── CHANGELOG.md                  # Version history
├── LICENSE                       # MIT License
└── .gitignore                    # Git ignore rules
```

---

## 📡 API Reference

### Base URL
```
http://127.0.0.1:8000
```

### `POST /get_craft`
Generate AI-recommended cutting parameters.

**Request Body:**
```json
{
  "feature": "平面铣削",
  "material": "6061铝",
  "machine": "三轴立式加工中心"
}
```

| Field | Type | Required | Options |
|---|---|---|---|
| `feature` | string | ✅ Yes | `平面铣削`, `型腔加工`, `键槽加工`, `钻孔`, `攻丝`, `曲面精加工` |
| `material` | string | ✅ Yes | `6061铝`, `45#钢`, `304不锈钢`, `H62黄铜` |
| `machine` | string | No (default: `三轴立式加工中心`) | `三轴立式加工中心`, `数控铣床`, `钻攻中心`, `五轴加工中心`, `龙门铣床` |

**Response `200 OK`:**
```json
{
  "craft_params": "Φ63端铣刀(5刃) | S6000 | F1200 | ap1.0",
  "feature": "平面铣削",
  "material": "6061铝",
  "machine": "三轴立式加工中心",
  "status": "ok"
}
```

**Error Responses:**

| Code | Detail | Cause |
|---|---|---|
| `400` | 不支持的材料: 'xxx' | Material not in knowledge base |
| `400` | 不支持的特征: 'xxx' | Feature not in knowledge base |
| `404` | 模型未找到 | Ollama模型未拉取, 运行 `ollama pull` |
| `503` | 无法连接到Ollama | Ollama服务未启动 |
| `500` | AI服务调用失败 | SDK / 推理异常 |

### `GET /knowledge_base`
List full knowledge base (no API call).

### `GET /knowledge_base/lookup?feature=X&material=Y`
Look up baseline parameters offline.

### `POST /auto_craft` 🆕 v1.3
AI-powered full process planning from detected model features.

**Request Body:**
```json
{
  "features": [
    {"feature_type": "平面", "name": "顶面", "dimensions": "约100×80mm", "count": 1, "area_mm2": 8000},
    {"feature_type": "通孔", "name": "Φ10通孔", "dimensions": "Φ10×深约25mm", "count": 4, "diameter": 10, "depth": 25}
  ],
  "material": "6061铝",
  "machine": "三轴立式加工中心",
  "part_name": "底板",
  "overall_dimensions": "100×80×30mm"
}
```

**Response `200 OK`:**
```json
{
  "process_plan_text": "工艺总览...\n---\n1. 平面铣削 | 面铣之字形 | 顶面 | ...",
  "steps": [
    {"step": 1, "operation": "平面铣削", "toolpath_strategy": "面铣之字形", "feature_ref": "顶面", "tool": "Φ63端铣刀(5刃)", "spindle_speed": "6000", "feed_rate": "1200", "depth_of_cut": "1.0", "note": "粗铣顶面"}
  ],
  "features_detected": 2,
  "material": "6061铝",
  "machine": "三轴立式加工中心",
  "status": "ok"
}
```

### `POST /craft_library/upload` 🆕 v1.3
Upload custom process parameters to personal library (persisted as JSON).

### `GET /craft_library/query?material=6061铝&feature=钻孔` 🆕 v1.3
Search personal craft library with optional filters.

### `GET /health`
Service health + API connectivity check.

### Interactive Docs
Visit **http://127.0.0.1:8000/docs** for the auto-generated Swagger UI.

---

## 📚 Built-in Knowledge Base

| Material | Face Milling | Pocket | Keyway | Drilling | Tapping | Surface Finish |
|---|---|---|---|---|---|---|
| **6061 Al** | Φ63端铣刀 S6000 F1200 ap1.5 | Φ12立铣刀 S8000 F1500 ap1.0 | Φ8键槽铣刀 S5000 F800 ap0.5 | Φ6麻花钻 S4000 F300 | M6丝锥 S800 F800 | R5球刀 S10000 F2000 ap0.2 |
| **7075 Al** | Φ63端铣刀 S5500 F1100 ap1.5 | Φ12立铣刀 S7500 F1400 ap1.0 | Φ8键槽铣刀 S4800 F750 ap0.5 | Φ6麻花钻 S3800 F280 | M6丝锥 S750 F750 | R5球刀 S9500 F1900 ap0.2 |
| **45# Steel** | Φ63端铣刀 S2500 F500 ap1.0 | Φ12立铣刀 S3500 F600 ap0.5 | Φ8键槽铣刀 S2500 F400 ap0.3 | Φ6麻花钻 S1800 F150 | M6丝锥 S300 F300 | R5球刀 S5000 F800 ap0.15 |
| **40Cr Alloy** | Φ63端铣刀 S1800 F400 ap0.8 | Φ12立铣刀 S2800 F500 ap0.4 | Φ8键槽铣刀 S2200 F350 ap0.25 | Φ6含钴钻 S1500 F120 | M6丝锥 S250 F250 | R5球刀 S4200 F650 ap0.12 |
| **Cr12MoV Die** | Φ63端铣刀 S1000 F250 ap0.5 | Φ12立铣刀 S2000 F350 ap0.3 | Φ8键槽铣刀 S1500 F220 ap0.2 | Φ6含钴钻 S1000 F80 | M6丝锥 S180 F180 | R5球刀 S3000 F500 ap0.1 |
| **304 SS** | Φ63端铣刀(AlTiN) S1200 F250 ap0.5 | Φ12立铣刀(AlTiN) S2000 F300 ap0.3 | Φ8键槽铣刀(AlTiN) S1500 F200 ap0.2 | Φ6含钴钻 S800 F80 | M6含钴丝锥 S150 F150 | R5球刀(AlTiN) S3500 F500 ap0.1 |
| **316 SS** | Φ63端铣刀(AlTiN) S1000 F200 ap0.4 | Φ12立铣刀(AlTiN) S1700 F250 ap0.25 | Φ8键槽铣刀(AlTiN) S1300 F170 ap0.15 | Φ6含钴钻 S650 F65 | M6含钴丝锥 S120 F120 | R5球刀(AlTiN) S3000 F430 ap0.1 |
| **HT250 Cast Iron** | Φ63端铣刀 S1500 F400 ap1.0 | Φ12立铣刀 S2500 F500 ap0.5 | Φ8键槽铣刀 S1800 F300 ap0.3 | Φ6硬质合金钻 S2000 F200 | M6丝锥 S350 F350 | R5球刀 S4000 F700 ap0.15 |
| **TC4 Titanium** | Φ63端铣刀(AlTiN) S350 F100 ap0.3 | Φ12立铣刀(AlTiN) S800 F150 ap0.2 | Φ8立铣刀(AlTiN) S600 F100 ap0.15 | Φ6硬质合金钻(内冷) S400 F40 | M6丝锥 S80 F80 | R5球刀(AlTiN) S1800 F350 ap0.08 |
| **Inconel 718** | Φ63端铣刀(AlTiN) S200 F60 ap0.2 | Φ12立铣刀(AlTiN) S500 F100 ap0.15 | Φ8立铣刀(AlTiN) S400 F70 ap0.1 | Φ6硬质合金钻(内冷) S250 F25 | M6丝锥 S50 F50 | R5球刀(AlTiN) S1200 F250 ap0.06 |
| **H62 Brass** | Φ63端铣刀 S5000 F1000 ap1.5 | Φ12立铣刀 S7000 F1200 ap1.0 | Φ8键槽铣刀 S4000 F600 ap0.5 | Φ6麻花钻 S3500 F250 | M6丝锥 S600 F600 | R5球刀 S8000 F1500 ap0.2 |

> 💡 These are **shop-floor-validated starting parameters**. Always adjust based on your specific setup, tool holder, coolant, and rigidity conditions.
> 💡 v1.3 adds tool material knowledge (HSS→PCD, 12 types), toolpath strategy knowledge (8 categories from open-source CAM projects), and CAM Assist-style UI.

---

## ⚙️ Configuration

| Parameter | Location | Default | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `cam_cloud_api.py:48` or env var | `http://127.0.0.1:11434/v1` | Ollama OpenAI兼容API地址 |
| `OLLAMA_MODEL` | `cam_cloud_api.py:49` or env var | `qwen2.5:7b-instruct-q4_K_M` | Ollama模型名称 |
| `TEMPERATURE` | `cam_cloud_api.py:53` | `0.1` | LLM sampling temperature |
| `MAX_TOKENS` | `cam_cloud_api.py:54` | `200` (600 for auto_craft) | Max output tokens |
| `TOP_P` | `cam_cloud_api.py:55` | `0.1` | Nucleus sampling parameter |
| `HUNYUAN3D_API_KEY` | env var | (空) | 腾讯 Hunyuan3D API Key — 文本/图片→3D, 免费20次/天 |
| `MESHY_API_KEY` | env var | (空) | Meshy API Key — 付费3D生成, 4K纹理 |
| `OPENROUTER_API_KEY` | env var | (空) | OpenRouter API Key — 通用AI网关, 调用 `fusion` 3D模型 |
| `OPENROUTER_3D_MODEL` | env var | `fusion` | OpenRouter 3D 模型名称 |
| Host/Port | `cam_cloud_api.py` main / env `HOST`/`PORT` | `127.0.0.1:8000` | FastAPI server binding (设 `HOST=0.0.0.0` 开放局域网) |
| `API_BASE_URL` | `fusion360_cam_ai.py:39` | `http://127.0.0.1:8000` | Fusion360 → API endpoint |
| `PERSONAL_LIBRARY_FILE` | auto: `personal_craft_library.json` | same dir as API | Personal craft library persistence |

---

## 🖥 Fusion360 Integration

### Script Location
Fusion360 scripts are stored at:
```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\Scripts\CAM_AI_Craft\
```

### Installation Steps
1. In Fusion360: **Tools → Scripts & Add-Ins**
2. Click **Create → Python**
3. Name: `CAM_AI_Craft`
4. Replace default content with `fusion360_cam_ai.py`
5. Save & Run

### UI Overview
```
┌──────────────────────────────────────────┐
│  ⭐ 云端AI工艺参数推荐系统 ⭐ v1.3       │
├──────────────────────────────────────────┤
│  加工特征: [▼ 平面铣削              ]    │
│  工件材料: [▼ 6061铝                ]    │
│  机床类型: [▼ 三轴立式加工中心      ]    │
├──────────────────────────────────────────┤
│  🆕 v1.3 自动工艺规划                    │
│  [🔍 自动识别模型特征]  ← 扫描3D几何体   │
│  [🤖 AI生成完整工艺流程] ← 多步工序+策略 │
├──────────────────────────────────────────┤
│  📊 检测结果: 平面×1 / 通孔×4 / 倒角×2  │
│  📋 AI工艺:                              │
│  1. 平面铣削 | 面铣之字形 | S6000 F1200  │
│  2. 钻孔 | G83啄钻 | S3500 F250 ...      │
├──────────────────────────────────────────┤
│  [🔍 查询工艺参数]     ← 单步手动 (收费) │
│  [📖 查看知识库基准]    ← 离线 (免费)    │
└──────────────────────────────────────────┘
```

---

## 🔧 Troubleshooting

| Symptom | Probable Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: openai` | Missing dependency | `pip install -r requirements.txt` |
| Ollama connection refused | Ollama not running | Run `ollama serve` first |
| Model not found error | Model not pulled | `ollama pull qwen2.5:7b-instruct-q4_K_M` |
| Connection refused in Fusion360 | Service not running | Double-click `start_service.bat` first |
| Port 8000 occupied | Another process | `netstat -ano \| findstr :8000` → `taskkill /PID N /F` |
| Port 11434 occupied | Ollama already running | Normal — Ollama runs on this port |
| Script error in Fusion360 | Paste truncated | Re-copy full `fusion360_cam_ai.py` |
| AI output malformed | Rare model variance | Use offline KB button; or re-query |
| Firewall blocks Python | Windows Defender | Allow `python.exe` in firewall settings |

### Full diagnostic check:
```powershell
# 1. Python version
python --version

# 2. Ollama status
ollama list

# 3. Dependencies
python -c "import fastapi, uvicorn, openai, pydantic; print('OK')"

# 4. Service health
Invoke-RestMethod http://127.0.0.1:8000/health

# 5. AI connectivity
Invoke-RestMethod http://127.0.0.1:8000/get_craft -Method Post `
  -Body '{"feature":"平面铣削","material":"6061铝","machine":"三轴立式加工中心"}' `
  -ContentType "application/json"
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Ollama** — 本地大模型运行平台
- **Qwen (通义千问)** — 阿里云开源大模型系列
- **Autodesk Fusion360** — Python API for CAM automation
- **FastAPI** — High-performance Python web framework
- **Uvicorn** — Lightning-fast ASGI server

---

<div align="center">

**Built with ❤️ for CNC machinists and CAM programmers**

[![Stars](https://img.shields.io/badge/⭐_Star_this_repo-if_useful-yellow)]()
[![Made with](https://img.shields.io/badge/Made%20with-Python%20%7C%20FastAPI%20%7C%20Ollama-blue)]()

</div>
