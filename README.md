<!--
============================================================================
README.md — Fusion360 CAM 云端AI工艺推荐系统
============================================================================
-->

<div align="center">

# 🔧 Fusion360 CAM × 通义千问 智能数控工艺推荐系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-orange)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D6?logo=windows&logoColor=white)]()
[![AI Model](https://img.shields.io/badge/AI-通义千问%20qwen2.5--14b-FF6B6B?logo=alibabacloud&logoColor=white)](https://dashscope.aliyun.com/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)]()

**Fusion360内置脚本 → 本地FastAPI中转 → 阿里云通义千问API → 标准化铣削/钻孔/型腔切削参数 → 自动弹窗展示**

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

A production-ready CNC process recommendation system that bridges **Autodesk Fusion360 CAM** with **Alibaba Cloud Tongyi Qianwen (通义千问) LLM API**. The system provides **AI-generated cutting parameters** (tool, spindle speed, feed rate, depth of cut) for machining operations directly inside the Fusion360 CAM workspace.

### Key Design Decisions

| Decision | Rationale |
|---|---|
| ☁️ Cloud API only | No local GPU required; runs on Intel Ultra5 integrated graphics laptops |
| 🔧 Fixed model `qwen2.5-14b-instruct` | Stable, cost-effective, Chinese-optimized |
| 📐 Fixed output format | `Tool | S | F | ap` — parsable, copy-paste ready for CAM dialogs |
| 🌡️ `temperature=0.1` | Minimizes hallucination; parameters are deterministic |
| 📚 Embedded knowledge base | 6 features × 4 materials with shop-floor-validated baseline params |
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
│  │  │ 1.参数校验    │→│ 2.拼装Prompt  │→│ 3.调用AI API  │ │  │
│  │  │ 材料/特征枚举 │  │ 知识库前缀   │  │ DashScope SDK │ │  │
│  │  └──────────────┘  └──────────────┘  └──────┬───────┘ │  │
│  └──────────────────────────────────────────────┼─────────┘  │
└─────────────────────────────────────────────────┼─────────────┘
                                                  │ HTTPS
                                                  ▼
┌──────────────────────────────────────────────────────────────┐
│              阿里云 DashScope 云端                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  qwen2.5-14b-instruct (temperature=0.1)                │  │
│  │  → 生成标准化切削参数                                   │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### Core
- 🔗 **End-to-end pipeline**: Fusion360 script → local FastAPI → cloud AI → formatted parameters
- 🎯 **Fixed output format**: `刀具型号 | 主轴转速S | 进给速度F | 切削深度ap`
- 📚 **Built-in knowledge base**: 6 machining features × 4 materials with validated baseline data
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
- **Alibaba Cloud DashScope API Key** ([get one](https://dashscope.console.aliyun.com/apiKey))
- **Autodesk Fusion360** with CAM workspace

### 1. Install Dependencies
```powershell
mkdir D:\CAM_CLOUD_API
cd D:\CAM_CLOUD_API

# Clone or copy all project files into this directory, then:
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 2. Configure API Key
Edit `start_service.bat` line 18:
```batch
set DASHSCOPE_API_KEY=sk-YOUR-REAL-API-KEY-HERE
```

### 3. Start the Service
```powershell
# Double-click:
start_service.bat

# Or command line:
python cam_cloud_api.py
```
You should see:
```
模型: qwen2.5-14b-instruct | 温度: 0.1 | 端口: 8000
Uvicorn running on http://0.0.0.0:8000
```

### 4. Verify
```powershell
# Health check
Invoke-RestMethod http://127.0.0.1:8000/health

# Test AI query
$body = '{"feature":"平面铣削","material":"6061铝","machine":"三轴立式加工中心"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/get_craft -Method Post -Body $body -ContentType "application/json"
```

### 5. Run in Fusion360
1. **Tools → Scripts & Add-Ins → Create → Python**
2. Name it `CAM_AI_Craft`
3. Paste `fusion360_cam_ai.py` contents
4. Save → **Run**

---

## 📁 Project Structure

```
D:\CAM_CLOUD_API\
├── cam_cloud_api.py          # FastAPI relay service (core backend)
├── fusion360_cam_ai.py       # Fusion360 Python script (client)
├── requirements.txt          # Python dependency manifest
├── start_service.bat         # Windows one-click launcher
├── auto_start.vbs            # Silent auto-start script for boot
├── README.md                 # This file
├── CHANGELOG.md              # Version history
├── LICENSE                   # MIT License
└── .gitignore                # Git ignore rules
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
| `401` | API Key 认证失败 | Invalid/expired DashScope API key |
| `502` | DashScope API 返回错误 | Cloud API downstream failure |
| `500` | AI服务调用失败 | Network / SDK exception |

### `GET /knowledge_base`
List full knowledge base (no API call).

### `GET /knowledge_base/lookup?feature=X&material=Y`
Look up baseline parameters offline.

### `GET /health`
Service health + API connectivity check.

### Interactive Docs
Visit **http://127.0.0.1:8000/docs** for the auto-generated Swagger UI.

---

## 📚 Built-in Knowledge Base

| Material | Face Milling<br>平面铣削 | Pocket<br>型腔加工 | Keyway<br>键槽加工 | Drilling<br>钻孔 | Tapping<br>攻丝 | Surface Finish<br>曲面精加工 |
|---|---|---|---|---|---|---|
| **6061 Al** | Φ63端铣刀<br>S6000 F1200 ap1.5 | Φ12立铣刀<br>S8000 F1500 ap1.0 | Φ8键槽铣刀<br>S5000 F800 ap0.5 | Φ6麻花钻<br>S4000 F300 | M6丝锥<br>S800 F800 | R5球刀<br>S10000 F2000 ap0.2 |
| **45# Steel** | Φ63端铣刀<br>S2500 F500 ap1.0 | Φ12立铣刀<br>S3500 F600 ap0.5 | Φ8键槽铣刀<br>S2500 F400 ap0.3 | Φ6麻花钻<br>S1800 F150 | M6丝锥<br>S300 F300 | R5球刀<br>S5000 F800 ap0.15 |
| **304 SS** | Φ63端铣刀(涂层)<br>S1200 F250 ap0.5 | Φ12立铣刀(AlTiN)<br>S2000 F300 ap0.3 | Φ8键槽铣刀(涂层)<br>S1500 F200 ap0.2 | Φ6含钴钻<br>S800 F80 | M6含钴丝锥<br>S150 F150 | R5球刀(涂层)<br>S3500 F500 ap0.1 |
| **H62 Brass** | Φ63端铣刀<br>S5000 F1000 ap1.5 | Φ12立铣刀<br>S7000 F1200 ap1.0 | Φ8键槽铣刀<br>S4000 F600 ap0.5 | Φ6麻花钻<br>S3500 F250 | M6丝锥<br>S600 F600 | R5球刀<br>S8000 F1500 ap0.2 |

> 💡 These are **shop-floor-validated starting parameters** for carbide tooling on 3-axis VMCs.
> Always adjust based on your specific setup, tool holder, coolant, and rigidity conditions.

---

## ⚙️ Configuration

| Parameter | Location | Default | Description |
|---|---|---|---|
| `DASHSCOPE_API_KEY` | `cam_cloud_api.py:40` or env var | `sk-xxx...` | Alibaba Cloud DashScope API key |
| `MODEL_NAME` | `cam_cloud_api.py:44` | `qwen2.5-14b-instruct` | AI model ID |
| `TEMPERATURE` | `cam_cloud_api.py:45` | `0.1` | LLM sampling temperature |
| `MAX_TOKENS` | `cam_cloud_api.py:46` | `200` | Max output tokens |
| `TOP_P` | `cam_cloud_api.py:47` | `0.1` | Nucleus sampling parameter |
| Host/Port | `cam_cloud_api.py:265` | `0.0.0.0:8000` | FastAPI server binding |
| `API_BASE_URL` | `fusion360_cam_ai.py:39` | `http://127.0.0.1:8000` | Fusion360 → API endpoint |

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
┌─────────────────────────────────────────┐
│  ⭐ 云端AI工艺参数推荐系统 ⭐            │
├─────────────────────────────────────────┤
│  加工特征: [▼ 平面铣削              ]   │
│  工件材料: [▼ 6061铝                ]   │
│  机床类型: [▼ 三轴立式加工中心      ]   │
├─────────────────────────────────────────┤
│  ✅ Φ63端铣刀(5刃) | S6000 | F1200 |   │
│     ap1.0                   ← AI结果    │
├─────────────────────────────────────────┤
│  [🔍 查询工艺参数]      ← 云端AI (收费) │
│  [📖 查看知识库基准]     ← 离线 (免费)  │
└─────────────────────────────────────────┘
```

---

## 🔧 Troubleshooting

| Symptom | Probable Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: dashscope` | Missing dependency | `pip install -r requirements.txt` |
| `AuthenticationError` | Wrong API key | Check `cam_cloud_api.py:40` |
| Connection refused in Fusion360 | Service not running | Double-click `start_service.bat` first |
| Port 8000 occupied | Another process | `netstat -ano \| findstr :8000` → `taskkill /PID N /F` |
| Script error in Fusion360 | Paste truncated | Re-copy full `fusion360_cam_ai.py` |
| AI output malformed | Rare model variance | Use offline KB button; or re-query |
| Firewall blocks Python | Windows Defender | Allow `python.exe` in firewall settings |

### Full diagnostic check:
```powershell
# 1. Python version
python --version

# 2. Dependencies
python -c "import fastapi, uvicorn, dashscope, pydantic; print('OK')"

# 3. Service health
Invoke-RestMethod http://127.0.0.1:8000/health

# 4. AI connectivity
Invoke-RestMethod http://127.0.0.1:8000/get_craft -Method Post `
  -Body '{"feature":"平面铣削","material":"6061铝","machine":"三轴立式加工中心"}' `
  -ContentType "application/json"
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Alibaba Cloud DashScope** — Tongyi Qianwen LLM API
- **Autodesk Fusion360** — Python API for CAM automation
- **FastAPI** — High-performance Python web framework
- **Uvicorn** — Lightning-fast ASGI server

---

<div align="center">

**Built with ❤️ for CNC machinists and CAM programmers**

[![Stars](https://img.shields.io/badge/⭐_Star_this_repo-if_useful-yellow)]()
[![Made with](https://img.shields.io/badge/Made%20with-Python%20%7C%20FastAPI%20%7C%20%E9%80%9A%E4%B9%89%E5%8D%83%E9%97%AE-blue)]()

</div>
