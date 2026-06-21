# CAM 云端智能工艺推荐系统 · 系统设计文档

> 文档版本：1.0 ｜ 对应代码版本：后端 `cam_cloud_api.py` v1.5.0 / 客户端 `fusion360_cam_ai.py` v1.4.0
> 生成日期：2026-06-19
> 定位：面向开发与维护的架构说明书，覆盖模块划分、数据流、接口契约、持久化、部署及已知问题。

---

## 1. 项目概述

### 1.1 是什么

一套面向 Autodesk Fusion360 CAM 工作区的**本地化数控工艺推荐系统**。Fusion360 内置 Python 脚本自动识别 3D 模型的加工特征（平面/孔/型腔/凸台/倒角等），通过本地 FastAPI 中转服务调用 **Ollama 本地大模型（通义千问 Qwen 系列）**，生成结构化的切削参数与多步工艺流程，整个过程数据不出本机、零 API 费用、可离线运行。

### 1.2 核心价值

| 维度 | 说明 |
|------|------|
| 本地推理 | Ollama 本地大模型，无云端调用成本，工艺数据不离开本机 |
| 知识库兜底 | 内置 14 种材料 × 8 种加工特征的车间级基准参数，AI 不可用时可离线查询 |
| 特征自动识别 | 扫描 Fusion360 BRep 几何体，自动分类加工特征，免手动选择 |
| 结构化输出 | 多步工序含刀路策略/刀具/转速/进给/切深，可直接用于 CAM 对话框 |
| 管理后台 | Web 端工艺库 CRUD、批量导入导出、机床注册表管理、推理状态实时轮询 |

### 1.3 技术栈

- **后端**：Python 3.10+、FastAPI 0.115、Uvicorn 0.30、Pydantic v2、OpenAI SDK（兼容模式连 Ollama）
- **AI**：Ollama 本地大模型（默认 `qwen2.5:7b-instruct-q4_K_M`，可切换）
- **客户端**：Autodesk Fusion360 Python API（`adsk` 命名空间）
- **3D 生成（v1.5 可选）**：FastMCP、trimesh、Hunyuan3D / Meshy 云 API
- **持久化**：JSON 文件（无数据库）
- **平台**：Windows 11 为主，端口 8000

---

## 2. 系统架构

### 2.1 三层架构

系统采用清晰的三层分层架构，层间通过 HTTP / 本地调用解耦：

```
┌─────────────────────────────────────────────────────────┐
│  客户端层 · Fusion360 脚本 (fusion360_cam_ai.py v1.4.0)  │
│  BRep 特征识别 · CAM Assist 风格 UI · 工序表格展示        │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP POST (127.0.0.1:8000)
┌────────────────────────▼────────────────────────────────┐
│  后端层 · FastAPI 中转服务 (cam_cloud_api.py :8000)      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │AI 工艺生成│ │内置知识库 │ │个人工艺库 │ │状态/管理/MCP│ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
└──┬───────────────┬──────────────────────┬──────────────┘
   │ AI 推理        │ 读写                  │ 3D 生成
┌──▼──────┐  ┌──────▼──────┐  ┌────────────▼─────────────┐
│ Ollama  │  │ JSON 文件    │  │ 外部 3D API              │
│ :11434  │  │ library/    │  │ Hunyuan3D · Meshy        │
│ qwen2.5 │  │ registry    │  │ (FastMCP /mcp 端点)      │
└─────────┘  └─────────────┘  └──────────────────────────┘
```

### 2.2 设计要点

- **零中间件**：无 Redis、无数据库、无 Docker，仅 Python + FastAPI，降低部署复杂度。
- **中转服务定位**：后端是"中转层"，职责为参数校验 → 拼装含知识库的 Prompt → 调用 Ollama → 解析清洗输出，本身不做推理。
- **可选 3D 模块隔离**：FastMCP 初始化用 try/except 包裹，失败时降级为 StubMCP，核心 CAM 功能不受影响。
- **线程安全**：推理状态、个人工艺库、机床注册表各有独立 `threading.Lock`，支持并发请求下的安全读写。

---

## 3. 核心模块说明

### 3.1 客户端 — `fusion360_cam_ai.py`（1341 行，v1.4.0）

Fusion360 内置 Python 脚本，对标 Mastercam CAM Assist 工作流。

| 模块 | 职责 |
|------|------|
| `detect_model_features()` | 扫描当前设计 BRep 几何体，按曲面类型（平面/圆柱/圆锥/圆环/NURBS）分类，自动识别平面、通孔/盲孔、型腔、凸台、倒角、圆角，并估算尺寸 |
| `CraftCommandCreatedEventHandler` | 构建 CAM Assist 风格步骤式对话框（环境设置 → 预检+特征分析 → 工艺生成） |
| `CraftInputChangedEventHandler` | 处理按钮点击：预检、扫描、生成工艺、知识库查询、刀具分析、保存到工艺库、单步查询 |
| `http_post_json / http_get_json` | HTTP 辅助函数，正确处理 UTF-8 中文编码 |
| 预检 `_run_pre_check` | 对标 CAM Assist Pre-Flight Check，校验实体/毛坯/WCS/刀具库 |

**工作流**：步骤1 设置加工环境（机床/材料/装夹/冷却/表面目标/AI 策略）→ 步骤2 预检 + 扫描特征 → 步骤3 AI 生成完整工艺方案。

### 3.2 后端 — `cam_cloud_api.py`（2506 行，v1.5.0）

FastAPI 中转服务，端口 8000，是系统的核心枢纽。

#### 3.2.1 配置与全局状态

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` | Ollama OpenAI 兼容地址（可环境变量覆盖） |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct-q4_K_M` | 默认模型（⚠️ 与文档不一致，见问题清单） |
| `TEMPERATURE` | 0.1 | 低温减少幻觉，参数稳定 |
| `MAX_TOKENS` | 200（get_craft）/ 600（auto_craft） | 输出 token 上限 |
| `TOP_P` | 0.1 | 极窄采样，确定性高 |

- **推理状态追踪器** `_inference_status`：线程安全字典，记录 state/message/model/elapsed_ms/tokens 等，供前端 `/inference_status` 轮询展示模型调用进度。
- **OpenAI 兼容客户端**：`api_key="ollama"` 占位，实际指向本地 Ollama。

#### 3.2.2 内置知识库

| 知识库 | 规模 | 用途 |
|--------|------|------|
| `CRAFT_KNOWLEDGE_BASE` | 14 材料 × 8 特征 | 车间级基准切削参数，注入 Prompt 作参考，亦支持离线直查 |
| `TOOL_MATERIAL_KNOWLEDGE` | 12 种刀具材料 | HSS→PCD，含耐热温度/硬度/适用场景/切削速度比 |
| `TOOLPATH_STRATEGIES` | 8 大类 | 平面/型腔/轮廓/钻孔/曲面/自适应/螺纹/倒角，参考开源 CAM（FreeCAD Path、OpenCAMLib、LinuxCNC） |

#### 3.2.3 Prompt 构建

- `build_system_prompt()`：单步查询，注入对应材料+特征的知识库基准值 + 完整知识库 JSON，强制单行输出 `刀具 | S | F | ap`。
- `build_auto_craft_system_prompt()`：多步规划，注入检测特征描述 + 完整知识库 + 刀路策略 + 刀具材料，要求先工艺总览再 `---` 分隔后逐行输出工序。

#### 3.2.4 输出解析

- `parse_process_plan()`：以 `---`/`===`/`***` 分割总览与工序列表，逐行解析。
- `_parse_single_step_line()`：正则去序号前缀，按 `|` 分割，兼容 8 段（含刀路策略）与 7 段（旧格式）。
- `_fallback_process_plan()`：解析失败时按特征类型映射到知识库工序名，生成兜底工序。
- `clean_output()`：去除常见前缀噪声、合并换行、补 `|` 分隔符。

#### 3.2.5 持久化

| 文件 | 内容 | 锁 |
|------|------|----|
| `personal_craft_library.json` | 个人工艺库条目（UUID 键） | `_library_lock` |
| `machine_registry.json` | 机床注册表（8 台种子） | `_machine_registry_lock` |

两者均为"读时全量加载 → 修改 → 全量写回"模式，配合线程锁保证并发安全。

#### 3.2.6 AI 3D 生成 MCP（v1.5 可选）

- 通过 FastMCP 注册工具：`text_to_3d`、`image_to_3d`、`mesh_to_step`、`check_3d_backends`。
- 挂载到 `/mcp` 端点，ASGI 兼容，lifespan 合并进 FastAPI。
- 后端支持 Hunyuan3D（腾讯，免费 20 次/天）与 Meshy（付费），用 trimesh 做网格修复，FreeCAD 可选做 STEP 转换。
- 初始化失败时降级为 `_StubMCP`，不阻断核心服务启动。

### 3.3 管理前端 — `static/index.html`（1017 行）

单文件 Web 管理后台，挂载于 `/admin`，无构建步骤。

- **仪表盘**：统计工艺条目/材料/特征/机床数，轮询推理状态（5s）与健康检查（30s）。
- **工艺库**：表格化展示、过滤搜索、单条增删改、批量删除（含 DELETE 二次确认挑战）。
- **数据导入**：JSON 文本粘贴 / 文件拖拽上传 / 批量导入 / 全量导出 / 清空。
- **机床管理**：注册表增删，chip 样式展示。
- **系统信息**：服务版本/模型/端点参考表/知识库摘要。

---

## 4. 数据流

### 4.1 主流程一：自动工艺规划（`/auto_craft`）

最完整的数据流，覆盖特征识别到结构化输出：

1. **Fusion360 特征扫描**：`detect_model_features()` 遍历 `design.allComponents` 的 BRep 面，按曲面类型分类，估算尺寸，返回 `list[dict]`。
2. **POST /auto_craft**：客户端将特征列表 + 材料 + 机床 + 零件名 + 外形尺寸 POST 到后端。
3. **后端校验 + 构建 Prompt**：校验材料合法性 → `build_auto_craft_system_prompt()` 注入知识库/策略/刀具材料。
4. **Ollama 推理**：`client.chat.completions.create()`，temperature=0.1，max_tokens=600。
5. **解析工序**：`parse_process_plan()` 分割总览与工序，逐行解析为 `ProcessStep`；失败走 `_fallback_process_plan`。
6. **返回 + 展示**：返回 `AutoCraftResponse`（含 process_plan_text + steps），Fusion360 弹窗渲染工序表格，可一键存入个人工艺库。

### 4.2 主流程二：单步查询（`/get_craft`）

简化版：客户端选单个特征+材料+机床 → POST → 校验 → `build_system_prompt` → Ollama → `clean_output` → 返回单行参数 `刀具 | S | F | ap`。另有 `/get_craft/stream` 提供 SSE 流式输出。

### 4.3 离线流程（`/knowledge_base/lookup`）

不调用 AI，直接返回 `CRAFT_KNOWLEDGE_BASE[material][feature]` 基准参数，断网可用、零成本。

### 4.4 工艺库管理流

前端 → `/craft_library/*`（GET 查询 / POST 上传 / PUT 更新 / DELETE 删除 / 批量导入导出）→ 线程锁保护下读写 `personal_craft_library.json`。

### 4.5 3D 生成流（v1.5）

MCP 客户端 → `/mcp` → 调用 Hunyuan3D/Meshy API 生成 GLB → trimesh 网格修复 → 可选 FreeCAD 转 STEP / 导出 OBJ → 落盘 `generated_models/`。

---

## 5. 关键接口契约

### 5.1 工艺生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/get_craft` | 单步切削参数，返回 `CraftResponse` |
| POST | `/get_craft/stream` | SSE 流式单步推理 |
| POST | `/auto_craft` | 多步工艺规划，返回 `AutoCraftResponse`（含 steps[]） |

### 5.2 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/knowledge_base` | 全量知识库（材料/特征/机床/参数） |
| GET | `/knowledge_base/lookup?feature=&material=` | 离线查基准参数 |

### 5.3 个人工艺库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/craft_library` | 全部条目 |
| GET | `/craft_library/query?material=&feature=&tag=&keyword=` | 多条件搜索 |
| POST | `/craft_library/upload` | 上传条目（支持 overwrite） |
| PUT | `/craft_library/{entry_id}` | 更新单条 |
| DELETE | `/craft_library/{entry_id}` | 删除单条 |
| POST | `/craft_library/import_batch` | 批量导入 |
| POST | `/craft_library/delete_batch` | 批量删除 |
| GET | `/craft_library/export` | 导出 JSON 下载 |

### 5.4 管理与状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 + 端点清单 |
| GET | `/health` | 健康检查（含 Ollama 连通与模型可用性） |
| GET | `/inference_status` | 推理状态（前端轮询） |
| GET | `/admin/api/overview` | 仪表盘统计 |
| GET/POST/DELETE | `/admin/api/machines` | 机床注册表管理 |
| POST | `/mcp` | AI 3D 生成 MCP 端点（v1.5） |

### 5.5 错误码约定

| HTTP | 含义 | 触发场景 |
|------|------|----------|
| 400 | 参数不合法 | 材料/特征不在枚举；entry_ids 为空 |
| 404 | 资源不存在 | Ollama 模型未拉取；工艺库条目/机床不存在 |
| 409 | 冲突 | 机床已存在 |
| 503 | 服务不可达 | Ollama 未启动 |
| 500 | 内部错误 | AI 推理异常 |

---

## 6. 部署与启动

### 6.1 前置依赖

1. Python 3.10+，`pip install -r requirements.txt`
2. Ollama 已安装并 `ollama pull qwen2.5:7b-instruct-q4_K_M`（或自选模型）
3.（可选）配置 `HUNYUAN3D_API_KEY` / `MESHY_API_KEY` 启用 3D 生成

### 6.2 启动方式

| 方式 | 命令/文件 |
|------|-----------|
| 一键启动 | 双击 `start_service.bat` |
| 命令行 | `python cam_cloud_api.py` |
| 静默自启 | `auto_start.vbs`（开机后台启动） |

### 6.3 验证

- 健康检查：`GET http://127.0.0.1:8000/health`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- 管理后台：`http://127.0.0.1:8000/admin`

### 6.4 Fusion360 集成

工具 → 脚本与附加模块 → 新建 Python 脚本 → 粘贴 `fusion360_cam_ai.py` → 运行。脚本路径建议：
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\Scripts\CAM_AI_Craft\`

---

## 7. 已知问题清单（已全部修复）

> 以下问题由代码审查发现，**已于 2026-06-19 全部修复**。按影响等级分类。

### P1 · 功能正确性

| # | 位置 | 问题 | 修复方式 | 状态 |
|---|------|------|------|------|
| 1 | `cam_cloud_api.py:1436` | `parse_process_plan` 的 `separator_markers` 前两项重复 | 去重并补全全角破折号 `———`、`###` 等实际分隔符 | ✅ 已修复 |
| 2 | `cam_cloud_api.py:68` vs 文档 | 代码默认模型 `qwen2.5:7b-instruct-q4_K_M`，文档写 `14b` | 确认代码用 7b，统一 README/CHANGELOG 文档为 7b | ✅ 已修复 |
| 3 | CHANGELOG | 停在 1.4.0，缺 v1.5/v1.6 记录 | 补充 1.5.0（MCP 3D）、1.6.0（注册表持久化/管理后台/安全修复）变更记录 | ✅ 已修复 |

### P2 · 健壮性与耦合

| # | 位置 | 问题 | 修复方式 | 状态 |
|---|------|------|------|------|
| 4 | `cam_cloud_api.py:42` | `import trimesh` 顶层硬导入 | 改为 try/except，3 处调用点加 `if trimesh is None` 降级提示 | ✅ 已修复 |
| 5 | `:1036,2358` | `import_batch`/`delete_batch` 用裸 dict | 新增 `CraftLibraryImportBatchRequest`/`CraftLibraryDeleteBatchRequest` Pydantic 模型 | ✅ 已修复 |
| 6 | `:1531` | `spindle.replace("S","")` 误删字段内 S | 改用 `re.sub(r'^[Ss]','',...)` 仅去前缀 | ✅ 已修复 |

### P3 · 安全

| # | 位置 | 问题 | 修复方式 | 状态 |
|---|------|------|------|------|
| 7 | `:2501,671` | `0.0.0.0` 绑定 + CORS `*`+credentials | 默认改 `127.0.0.1`（HOST 环境变量可配）；CORS 关闭 credentials | ✅ 已修复 |
| 8 | 全局 | 写操作无审计日志 | 删除/批量删除/上传/批量导入补 `[审计]` 前缀日志，含 entry_id/feature/material | ✅ 已修复 |

### P4 · 文档与规范

| # | 位置 | 问题 | 修复方式 | 状态 |
|---|------|------|------|------|
| 9 | README 项目结构 | 缺 `static/`、`machine_registry.json`、`DESIGN.md` 等 | 同步更新项目结构树，版本徽章升 1.6.0 | ✅ 已修复 |
| 10 | `requirements.txt` | 标注 v1.5 | 更新为 v1.6 | ✅ 已修复 |
| 11 | Fusion360 `MACHINES` | 缺 `卧式加工中心` 且未动态拉取 | 补齐 8 种机床 + 新增 `get_machines()` 运行时从 `/admin/api/machines` 动态拉取，失败回退本地 | ✅ 已修复 |

---

## 8. 模块依赖关系

```
fusion360_cam_ai.py
  └─ HTTP → cam_cloud_api.py (FastAPI)
              ├─ OpenAI SDK → Ollama :11434
              ├─ CRAFT_KNOWLEDGE_BASE / TOOL_MATERIAL_KNOWLEDGE / TOOLPATH_STRATEGIES (内存)
              ├─ personal_craft_library.json (读写)
              ├─ machine_registry.json (读写)
              ├─ FastMCP /mcp → Hunyuan3D/Meshy API + trimesh + FreeCAD(可选)
              └─ static/index.html (挂载 /admin)
```

---

## 9. 扩展指引

- **新增材料/特征**：扩展 `CRAFT_KNOWLEDGE_BASE` 字典，`VALID_FEATURES`/`VALID_MATERIALS` 自动派生。
- **新增机床**：通过管理后台 `/admin` 或 API 添加，持久化到 `machine_registry.json`。
- **切换 AI 模型**：设环境变量 `OLLAMA_MODEL`，重启服务；`/health` 会校验模型可用性。
- **新增 3D 后端**：在 `AI_3D_BACKENDS` 注册，实现对应 `_xxx_to_3d` 辅助函数，用 `@mcp_3d.tool()` 暴露。

---

*本文档由架构分析自动生成，如代码变更请同步更新。问题清单待项目负责人确认后逐项处理。*
