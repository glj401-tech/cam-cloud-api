# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.8.0] — 2026-06-20

### Changed — 版本统一
- **版本号统一为 v1.8.0**：`cam_cloud_api.py`、`fusion360_cam_ai.py`、README badge 全部对齐
- 修复 README 显示版本 (1.8.0) 与代码实际版本不一致的问题

### Added — AI 3D 生成网络适配
- `AI_3D_PROXY` 环境变量支持（HTTP/HTTPS 代理，解决内网无法访问 api.hunyuan3d.com 的问题）
- Hunyuan3D API 调用增加超时控制（`AI_3D_TIMEOUT`，默认 120s）
- Hunyuan3D API 调用增加重试机制（`AI_3D_MAX_RETRIES`，默认 3 次，指数退避）
- AI 3D 生成后端状态检测接口 `/ai_3d/backends` 增加网络连通性提示

### Fixed
- 修复 Hunyuan3D API 连接超时无友好提示的问题（新增中文错误提示）
- 修复版本号分散在多处、各文件版本不一致的问题

---

## [1.7.0] — 2026-06-19

### Changed — UI 视觉升级

#### 管理后台 (`static/index.html`)
- **设计系统重构**: 从单一蓝色(#1a73e8)升级为精密工业蓝体系(#2563eb/#0891b2 双色), 扩展多层阴影(6级)、多级圆角(4级)
- **深色顶栏**: header 从白底改为深色渐变(#0f172a→#1e293b) + 毛玻璃质感状态badge + 渐变logo图标
- **导航优化**: nav-tabs 居中对齐 + active 状态底部蓝→青渐变高亮条
- **统计卡升级**: `::before` 渐变色条 + 渐变色图标圆角背景 + 800字重30px大数字
- **交互组件精致化**: 按钮(渐变+彩色阴影)、表格(圆角容器+精致表头)、模态(毛玻璃遮罩+弹出动画)、Toast(毛玻璃模糊)
- **响应式适配**: 更新 768px 断点匹配新尺寸系统

#### Fusion 360 插件面板 (`fusion360_cam_ai.py`)
- **标题栏**: 深色背景 #0D1B2A + 金色版本号标识
- **分区标题**: border-left:4px 色条 + border-top:2px 分隔线 + 副标题左缩进 (步骤1深蓝/步骤2深橙/步骤3深绿/附加工具深紫)
- **状态卡片**: 统一 border-left:4px 色条 + border-radius:6px + 深色系状态色体系
- **特征分析报告**: 表头加粗+底部2px色线、行间分隔线、底部提示框带背景色
- **预检报告**: 行高加大、字体加粗600、底部状态框带背景
- **工艺方案概览**: 环境标签改为 pill 样式(border-radius:10px+border)、各标签按类型配色
- **刀具分析**: 统一紫色系(#4A148C/#7E57C2)、表头加粗+底部色线
- **CAM创建结果**: 表格行间分隔线、提示框带粉色背景
- **工具栏按钮**: tooltip 版本号同步更新至 v1.7.0

### Fixed
- 清除 Fusion 360 Python 字节码缓存(`__pycache__/*.pyc`)导致插件重载后仍加载旧代码的问题

---

## [1.6.0] — 2026-06-15

### Added
- **机床注册表持久化** (`machine_registry.json`)
  - 机床列表从代码硬编码迁移到 JSON 文件持久化, 支持运行时增删
  - 新增 `GET/POST/DELETE /admin/api/machines` 管理接口
  - 线程安全: 独立 `_machine_registry_lock` 保护并发读写
- **管理后台 Web UI** (`static/index.html`)
  - 仪表盘: 工艺条目/材料/特征/机床统计 + AI 推理状态实时轮询 (5s)
  - 工艺库: 表格化展示、多条件过滤、单条增删改、批量删除 (含 DELETE 二次确认)
  - 数据导入: JSON 文本粘贴 / 文件拖拽上传 / 批量导入 / 全量导出 / 清空
  - 机床管理: 注册表增删, chip 样式展示
  - 系统信息: 服务版本/模型/端点参考表/知识库摘要
  - 挂载于 `/admin`, 健康检查轮询 (30s)
- **管理 API**: `GET /admin/api/overview` 仪表盘统计聚合
- **工艺库扩展接口**: `PUT /craft_library/{entry_id}` 更新单条, `GET /craft_library/export` 导出 JSON

### Changed
- `VALID_MACHINES` 从硬编码列表改为启动时从 `machine_registry.json` 动态加载
- 新增/删除机床时同步更新全局 `VALID_MACHINES` 变量

### Fixed
- 修复 `parse_process_plan` 分隔符列表重复项, 补全全角破折号等实际分隔符
- 修复 `_parse_single_step_line` 中 S/F/ap 前缀清理误删字段内字母 (改用正则仅去前缀)
- 修复 `trimesh` 顶层硬导入导致未安装时整个服务无法启动 (改为 try/except 延迟导入, 与 fastmcp 一致)
- 修复 CORS `allow_origins=["*"]` + `allow_credentials=True` 浏览器禁止组合 (关闭 credentials)
- 修复默认绑定地址 `0.0.0.0` 安全风险 (默认改为 `127.0.0.1`, 通过 HOST 环境变量可配)
- `import_batch` / `delete_batch` 从裸 dict 改为 Pydantic 模型校验
- 关键写操作 (删除/清空/批量/上传) 补充审计日志

---

## [1.5.0] — 2026-06-14

### Added
- **AI 3D 模型生成 MCP Server** (FastMCP)
  - `POST /mcp` 端点, ASGI 兼容, lifespan 合并进 FastAPI
  - 工具: `text_to_3d` (文本→3D), `image_to_3d` (图片→3D), `mesh_to_step` (网格→STEP), `check_3d_backends`
  - 后端支持 Hunyuan3D (腾讯云, 免费20次/天) 与 Meshy (付费)
  - trimesh 网格修复 (去除非流形边/填充孔/合并顶点/简化)
  - 可选 FreeCAD STEP 转换, 备选 OBJ 导出
  - 生成模型落盘 `generated_models/` 目录
- **3D 后端配置**: `HUNYUAN3D_API_KEY` / `MESHY_API_KEY` 环境变量
- **降级机制**: FastMCP 初始化失败时降级为 `_StubMCP`, 不阻断核心 CAM 服务启动

### Changed
- 依赖新增: `fastmcp>=3.0.0`, `trimesh>=4.0.0`, `pymeshlab>=2024.0`, `Pillow>=10.0.0`
- `requirements.txt` 标注 v1.5

---

## [1.4.0] — 2026-06-13

### Changed
- **后端AI引擎迁移**: 从阿里云 DashScope 云API 切换为本地 Ollama 大模型
  - 移除 `dashscope` SDK 依赖, 改用 `openai` SDK (OpenAI兼容模式连接Ollama)
  - 配置项变更: `DASHSCOPE_API_KEY` → `OLLAMA_BASE_URL` + `OLLAMA_MODEL`
  - 默认模型: `qwen2.5:7b-instruct-q4_K_M` (Ollama格式, 可配置其他版本)
  - API调用从 `dashscope.Generation.call()` 迁移至 `openai.Client.chat.completions.create()`
- **健康检查升级**: `/health` 端点自动检测 Ollama 连接和模型可用性
- **错误处理优化**: 区分连接错误(503)和模型不存在(404)
- **Fusion360脚本 UI**: 模型显示从 "通义千问 qwen2.5-14b" 更新为 "Ollama本地模型 qwen2.5:7b"
- **启动脚本**: `start_service.bat` 增加 Ollama 服务检测
- **版本号**: API v1.4.0, Fusion360脚本 v1.4.0

### Removed
- `dashscope` 包依赖及其所有相关错误处理代码
- 阿里云 API Key 配置和认证逻辑

### Benefits
- 🆓 **零API费用**: 本地推理, 无云服务调用成本
- 🔒 **数据本地化**: 工艺参数查询不离开本机
- 🌐 **离线可用**: 不依赖互联网连接
- 🔧 **模型灵活**: 可切换任何 Ollama 支持的模型

---

## [1.3.0] — 2026-06-13

### Added
- **CAM Assist 风格界面重构** (对标 Mastercam CAM Assist by CloudNC)
  - **步骤式工作流**: 步骤1加工环境设置 → 步骤2预检+特征分析 → 步骤3工艺生成与输出
  - **AI策略滑块**: 安全优先/均衡优化/效率优先 (对标 CAM Assist Strategy Slider)
  - **加工预检 (Pre-Flight Check)**: 对标 CAM Assist Evaluation阶段, 自动检查实体/毛坯/WCS/刀具库
  - **加工环境精细控制**: 加工模式(3轴/4轴/5轴)、装夹刚性(弱→优)、冷却方式(6种)、表面质量目标(Ra0.4~Ra6.3)
  - **刀具使用分析**: 对标 CAM Assist Tool Usages 选项卡, 统计AI推荐刀具及使用工序
  - **保存到个人工艺库**: 一键保存AI工艺方案到 personal_craft_library.json
- **新增材料**: 从14种扩展到与后端完全同步的14种
- **新增特征**: 粗车外圆、精车外圆
- **新增机床**: 数控车床、车铣复合中心
- **Fusion360脚本版本升级至 v1.3.0**

### Changed
- **UI 完全重构**: 从简单按钮布局升级为 CAM Assist 风格的步骤式专业界面
- **面板分离**: 特征分析面板(featurePanel) + 工艺结果面板(resultPanel) + 扫描状态指示器(scanStatus)
- **后端版本同步升级至 1.3.0**

---

## [1.2.0] — 2026-06-13

### Added
- **自动模型特征识别** (`detect_model_features` in Fusion360 script)
  - BRep几何体扫描: 自动检测平面、通孔、盲孔、型腔、凸台、倒角、曲面/圆角
  - 尺寸估算: 自动测量孔径、平面面积、特征数量
  - 新的 `🔍 自动识别模型特征` 按钮 + 结果表格展示
- **AI自动完整工艺规划** (`POST /auto_craft` endpoint)
  - 接收检测到的特征列表, AI生成完整多步工艺流程
  - 含刀路策略推荐 (参考开源CAM项目: FreeCAD Path, OpenCAMLib, FabexCNC, LinuxCNC)
  - 结构化工序步骤返回 (工序号/策略/刀具/S/F/ap/备注)
  - 新的 `🤖 AI生成完整工艺流程` 按钮
- **刀路策略知识库** (`TOOLPATH_STRATEGIES`)
  - 8大策略类别: 平面加工、型腔加工、轮廓加工、钻孔循环、曲面精加工、自适应清理、螺纹加工、倒角去毛刺
  - 每种策略含走刀模式、推荐参数、开源参考来源
- **刀具材料知识库** (`TOOL_MATERIAL_KNOWLEDGE`)
  - 12种刀具材料: HSS/含钴HSS/硬质合金K类/硬质合金P类/TiN/TiCN/TiAlN/AlTiN涂层/金属陶瓷/陶瓷/PCBN/PCD
  - 每种材料含耐热温度、硬度、适用场景、切削速度比
- **个人工艺库** (`personal_craft_library.json`)
  - `POST /craft_library/upload` — 上传自定义工艺参数
  - `GET /craft_library` — 获取全部个人工艺库
  - `GET /craft_library/query` — 按材料/特征/标签/关键词搜索
  - `DELETE /craft_library/{id}` — 删除条目
  - `POST /craft_library/import_batch` — 批量导入 (适合Excel/CSV粘贴)
  - 自动持久化, 与内置知识库互补

### Changed
- **知识库大幅扩展**: 从4种材料扩展到11种材料
  - 新增: 7075铝、40Cr合金钢、Cr12MoV模具钢、316不锈钢、HT250灰铸铁、QT600球墨铸铁、TC4钛合金、Inconel718镍基合金、紫铜T2、淬硬钢HRC50
  - 新增特征类型: 粗车外圆、精车外圆 (支持数控车床)
  - 新增机床类型: 数控车床、车铣复合中心、卧式加工中心
- `/auto_craft` 输出格式增加刀路策略字段
- API版本升级至 1.2.0
- `MAX_TOKENS` for `/auto_craft` 增加至600以支持多步工序输出

### Fixed
- 修复 root endpoint 中重复的 JSON 闭合括号
- 修复 Fusion360 脚本中文编码问题 (保留 v1.1.0 修复)

---

## [1.1.0] — 2026-06-13

### Fixed
- 修复 else 缩进导致的"知识库查询失败"覆盖 bug
- 修复中文编码问题 (Content-Type charset + ensure_ascii=False)

---

## [1.0.0] — 2026-06-13

### Added
- Initial release: Fusion360 CAM + Tongyi Qianwen cloud AI process recommendation system
- FastAPI relay service (`cam_cloud_api.py`) on port 8000
  - POST `/get_craft` endpoint for AI-powered cutting parameter generation
  - GET `/health` health check with API connectivity verification
  - GET `/knowledge_base` and `/knowledge_base/lookup` offline knowledge base queries
- Built-in CNC process knowledge base covering:
  - 6 machining features: face milling, pocket, keyway, drilling, tapping, surface finishing
  - 4 materials: 6061 aluminum, 45# steel, 304 stainless steel, H62 brass
  - All with safe, shop-floor-validated cutting parameters
- Fusion360 Python script (`fusion360_cam_ai.py`) with interactive dialog UI
  - Feature / material / machine dropdown selection
  - One-click AI parameter query
  - Offline knowledge base reference button (no API cost)
  - Color-coded result display
- Windows one-click startup script (`start_service.bat`)
- Windows auto-start VBScript (`auto_start.vbs`)
- Complete deployment documentation (CN)
- Fixed model: `qwen2.5-14b-instruct` via Alibaba Cloud DashScope SDK
- Fixed output format: `Tool | SpindleSpeed S | FeedRate F | DepthOfCut ap`
- Low temperature (0.1) for stable, low-hallucination output

### Technical Stack
- **Backend:** Python 3.10+, FastAPI 0.115, Uvicorn 0.30, DashScope SDK 1.20
- **AI Model:** Alibaba Cloud Tongyi Qianwen (`qwen2.5-14b-instruct`)
- **Client:** Autodesk Fusion360 Python API (`adsk` namespace)
- **Platform:** Windows 11 (primary target)
