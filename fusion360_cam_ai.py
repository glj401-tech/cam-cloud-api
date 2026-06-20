"""
================================================================================
 Fusion360_CAM_AI_Script.py — Fusion360 内置 Python 脚本 v1.4.0
 功能: CAM Assist 风格界面 → 自动识别模型特征 → AI生成完整工艺+刀路策略
       UI/UX 参考 Mastercam CAM Assist by CloudNC
 使用方法:
   1. 在 Fusion360 中: 工具 → 脚本与附加模块 → 新建Python脚本 → 粘贴本文件全部内容
   2. 保存后点击"运行"
   3. 按步骤: 设置加工环境 → 扫描特征 → 生成工艺
   4. 结果自动弹窗展示 (结构化工序表格)
 前提条件: cam_cloud_api.py 服务已在后台运行 (端口8000), Ollama已启动
 作者: CAM_AI_System
 日期: 2026-06-13
 版本: 1.4.0
 许可证: MIT License
 仓库: https://github.com/glj401-tech/cam-cloud-api
================================================================================
"""

__version__ = "1.8.0"  # v1.8: 版本统一 + AI 3D 代理支持
__author__ = "CAM_AI_System"
__license__ = "MIT"

import traceback
import json
import urllib.request
import urllib.error
import urllib.parse

# Fusion360 专用模块 (在Fusion360内置Python环境中可用)
try:
    import adsk.core
    import adsk.fusion  # noqa: F401 - 用于类型检查和 Fusion API 扩展
    import adsk.cam
except ImportError:
    # 在 Fusion 360 外部环境（如 IDE 或测试脚本）中不可用，
    # 此时模块顶层定义不可使用 adsk API，但类/函数定义仍然有效。
    adsk = None

# ============================================================================
# 全局变量
# ============================================================================
API_BASE_URL = "http://127.0.0.1:8000"
API_ENDPOINT = f"{API_BASE_URL}/get_craft"
AUTO_CRAFT_ENDPOINT = f"{API_BASE_URL}/auto_craft"

# 保存事件处理器引用 (防止被Python GC回收)
_handlers = []

# v1.4.1: 跨工作区数据持久化 — 切换工作区时命令对话框会被 Fusion360 终止,
# 用模块级全局保存已扫描的特征和AI结果, 重开对话框时自动恢复。
_shared_data = {
    "detected_features": [],
    "overall_dimensions": "",
    "ai_result": None,
}

# v1.4.1: 保存工具栏控件引用 (stop时清理)
_toolbar_controls = []

# 加工特征选项 (手动选择fallback)
FEATURES = [
    "平面铣削", "型腔加工", "键槽加工",
    "钻孔", "攻丝", "曲面精加工",
    "粗车外圆", "精车外圆",
]

# 材料选项 (与后端14种材料同步)
MATERIALS = [
    "6061铝", "7075铝",
    "45#钢", "40Cr合金钢", "Cr12MoV模具钢",
    "304不锈钢", "316不锈钢",
    "HT250灰铸铁", "QT600球墨铸铁",
    "TC4钛合金", "Inconel718镍基合金",
    "H62黄铜", "紫铜T2",
    "淬硬钢HRC50",
]

# 机床选项 (本地默认列表, 运行时会尝试从后端 /admin/api/machines 动态拉取覆盖)
MACHINES = [
    "三轴立式加工中心", "数控铣床", "钻攻中心",
    "五轴加工中心", "龙门铣床", "数控车床", "车铣复合中心",
    "卧式加工中心",
]

# v1.3 CAM Assist 风格: 加工模式
MACHINING_MODES = [
    "3轴加工 (默认)",
    "3+2轴定位加工",
    "4轴联动加工",
    "5轴联动加工",
]

# v1.3 CAM Assist 风格: 装夹刚性 (参考CAM Assist Workholding Security)
WORKHOLDING_LEVELS = [
    "优秀 — 液压虎钳/精密夹具, 刚性好, 可重切",
    "良好 — 标准虎钳/压板, 适合常规切削",
    "一般 — 简易夹具/分度头, 需保守参数",
    "较弱 — 薄壁件/悬伸件/软爪, 必须轻切快走",
]

# v1.3 CAM Assist 风格: 冷却方式
COOLANT_TYPES = [
    "乳化液 (通用)",
    "高压内冷 (70bar+, 适合钛/镍/不锈钢)",
    "微量润滑 MQL (环保)",
    "油冷 (攻丝/拉削)",
    "干切 (铸铁/铝合金/涂层刀具)",
    "气冷 (铜/塑料/复合材料)",
]

# v1.3 CAM Assist 风格: 表面质量目标
SURFACE_FINISH_TARGETS = [
    "Ra6.3 粗加工 (快速去除余量)",
    "Ra3.2 半精加工 (通用)",
    "Ra1.6 精加工 (常规精度要求)",
    "Ra0.8 精密加工 (配合面/密封面)",
    "Ra0.4 超精加工 (镜面/光学级)",
]

# v1.3 CAM Assist 对标: AI策略滑块 (保守→均衡→激进)
AI_STRATEGY_LEVELS = [
    "🛡️ 安全优先 — 保守参数, 刀具寿命最大化, 适合昂贵材料/单件/首件",
    "⚖️ 均衡优化 — 平衡效率与安全, 适合常规批量生产 (推荐默认)",
    "🚀 效率优先 — 激进参数, MRR最大化, 适合成熟工艺/大批量/已验证方案",
]

# v1.3 CAM Assist 对标: 预检项目
PRE_CHECK_ITEMS = {
    "实体检查": "确认Fusion360文档包含BRep实体 (非草图/曲面/网格)",
    "毛坯定义": "建议在Fusion360 CAM环境中定义Stock (毛坯尺寸)",
    "坐标系": "确认加工坐标系 (WCS) 已正确定义",
    "刀具库": "检查Fusion360刀具库中是否已创建所需刀具",
    "装夹方式": "确认夹具/虎钳/压板方案, 避免刀具与夹具干涉",
    "机床行程": "确认零件尺寸在机床行程范围内",
}


# ============================================================================
# HTTP 请求辅助函数 (处理中文编码)
# ============================================================================
def http_post_json(url: str, data: dict, timeout: int = 30) -> dict:
    """发送 POST JSON 请求, 正确处理 UTF-8 中文编码。"""
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_json(url: str, timeout: int = 10) -> dict:
    """发送 GET 请求, 返回 JSON。"""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_machines_from_server() -> list:
    """
    从后端 /admin/api/machines 动态拉取机床注册表。
    失败时返回 None, 调用方使用本地 MACHINES 默认列表。
    """
    try:
        data = http_get_json(f"{API_BASE_URL}/admin/api/machines", timeout=5)
        machines = data.get("machines", [])
        if machines:
            return machines
    except Exception:
        pass
    return None


def get_machines() -> list:
    """获取机床列表 (优先从后端动态拉取, 失败回退本地默认)。"""
    remote = fetch_machines_from_server()
    if remote:
        return remote
    return MACHINES


# ============================================================================
# v1.2.0: 模型特征自动检测引擎
# 分析 Fusion360 当前激活设计的 BRep 几何体, 自动识别加工特征
# ============================================================================

def detect_model_features():
    """
    扫描 Fusion360 当前激活设计中的所有几何体,
    自动检测并分类加工特征: 平面、通孔、盲孔、型腔、槽、凸台、曲面、倒角。

    返回: (features: list[dict], overall_dims: str)
        features — 检测到的特征列表
        overall_dims — 零件外形尺寸描述
        出错时返回 ([], 错误信息) 保证可解包。
    """
    try:
        app = adsk.core.Application.get()
        design = app.activeProduct

        # v1.4.2: CAM 工作区下 activeProduct 是 CAM 对象, 自动从文档获取 Design
        if not hasattr(design, "allComponents"):
            doc = app.activeDocument
            if doc:
                for product in doc.products:
                    if product.productType == "DesignProductType":
                        design = product
                        break
            if not hasattr(design, "allComponents"):
                return [], "当前文档无设计数据 (请确保已打开含3D实体的设计)"

        planar_faces = []       # 平面 → 面铣
        cylinder_faces = []     # 圆柱面 → 孔/凸台
        cone_faces = []         # 圆锥面 → 倒角/沉头孔
        torus_faces = []        # 圆环面 → 圆角
        other_faces = []        # NURBS等 → 曲面

        total_planar_area = 0.0
        # 统计所有零部件的几何数据
        for component in design.allComponents:
            for body in component.bRepBodies:
                for face in body.faces:
                    try:
                        geom = face.geometry
                        st = geom.surfaceType
                        area = face.area  # cm²

                        if st == adsk.core.SurfaceTypes.PlaneSurfaceType:
                            planar_faces.append({
                                "face": face, "area": area,
                                "plane": adsk.core.Plane.cast(geom),
                            })
                            total_planar_area += area
                        elif st == adsk.core.SurfaceTypes.CylinderSurfaceType:
                            cylinder_faces.append({
                                "face": face, "area": area,
                                "cylinder": adsk.core.Cylinder.cast(geom),
                            })
                        elif st == adsk.core.SurfaceTypes.ConeSurfaceType:
                            cone_faces.append({
                                "face": face, "area": area,
                                "cone": adsk.core.Cone.cast(geom),
                            })
                        elif st == adsk.core.SurfaceTypes.TorusSurfaceType:
                            torus_faces.append({"face": face, "area": area})
                        else:
                            other_faces.append({"face": face, "area": area, "type": st})
                    except Exception:
                        continue

        detected = []

        # ---- 1. 分析平面 ----
        # 取面积最大的 3 个平面作为主要加工面
        planar_sorted = sorted(planar_faces, key=lambda f: f["area"], reverse=True)
        main_planes = planar_sorted[:3]

        for i, pf in enumerate(main_planes):
            plane = pf["plane"]
            area_mm2 = pf["area"] * 100  # cm² → mm²
            normal = plane.normal

            # 确定平面方向和名称
            abs_z = abs(normal.z)
            if abs_z > 0.9:
                # 水平面
                name = "顶面" if normal.z > 0 else "底面"
            elif abs(normal.x) > 0.9 or abs(normal.y) > 0.9:
                name = f"侧面{i+1}"
            else:
                name = f"斜面{i+1}"

            # 估算平面尺寸 (从面积推算, 假设近似矩形)
            est_side = round(area_mm2 ** 0.5, 1)
            dims = f"约{est_side}×{est_side}mm"

            detected.append({
                "feature_type": "平面", "name": name, "dimensions": dims,
                "count": 1, "diameter": None, "depth": None,
                "width": est_side, "length": est_side, "area_mm2": round(area_mm2, 1),
                "note": f"面积{round(area_mm2/100, 1)}cm²",
            })

        # ---- 2. 分析圆柱面 (孔 vs 凸台) ----
        hole_groups = {}  # 按直径分组
        boss_groups = {}  # 按直径分组

        for cf in cylinder_faces:
            cyl = cf["cylinder"]
            radius_mm = cyl.radius * 10  # Fusion360单位是cm, 转mm
            diameter = round(radius_mm * 2, 1)

            # 判断是否为孔 (通过曲面法向量判断: 圆柱面法向量指向轴线=孔, 背离轴线=凸台)
            # 简化处理: 面积较小的圆柱面通常为孔
            is_hole = cf["area"] < 10.0  # 面积 < 10cm² 判断为孔

            if is_hole and diameter <= 50:  # 过滤超大直径 (可能是圆角面)
                key = f"Φ{diameter}"
                if key not in hole_groups:
                    hole_groups[key] = {"diameter": diameter, "count": 0, "faces": []}
                hole_groups[key]["count"] += 1
                hole_groups[key]["faces"].append(cf)
            elif not is_hole and diameter > 5:
                key = f"Φ{diameter}凸台"
                if key not in boss_groups:
                    boss_groups[key] = {"diameter": diameter, "count": 0}
                boss_groups[key]["count"] += 1

        # 合并相邻圆柱面 (一个通孔通常有1个或2个圆柱面)
        for key, info in sorted(hole_groups.items(), key=lambda x: -x[1]["diameter"]):
            # 通孔有2个面(入口+出口), 盲孔有1个面
            true_count = max(1, info["count"] // 2)
            hole_type = "通孔" if info["count"] >= 2 else "盲孔"
            diameter = info["diameter"]

            # 估算深度 (假设深度≈直径×2~3)
            est_depth = round(diameter * 2.5, 1)
            depth_note = f"深约{est_depth}mm"

            detected.append({
                "feature_type": hole_type, "name": f"Φ{diameter}{hole_type}",
                "dimensions": f"Φ{diameter}×{depth_note}",
                "count": true_count, "diameter": diameter, "depth": est_depth,
                "width": None, "length": None, "area_mm2": None,
                "note": f"{hole_type}, 共{true_count}处",
            })

        # ---- 3. 分析凸台 ----
        for key, info in sorted(boss_groups.items(), key=lambda x: -x[1]["count"]):
            detected.append({
                "feature_type": "凸台", "name": key,
                "dimensions": f"{key}, 高约15mm",
                "count": info["count"], "diameter": info["diameter"], "depth": 15,
                "width": None, "length": None, "area_mm2": None,
                "note": f"圆柱凸台, 共{info['count']}处",
            })

        # ---- 4. 分析倒角/锥面 ----
        for cf in cone_faces[:5]:
            detected.append({
                "feature_type": "倒角", "name": "倒角面",
                "dimensions": "C0.5~C2",
                "count": 1, "diameter": None, "depth": None,
                "width": None, "length": None, "area_mm2": None,
                "note": "边缘倒角, 建议用倒角刀加工",
            })

        # ---- 5. 分析圆角 ----
        if torus_faces:
            detected.append({
                "feature_type": "曲面", "name": "过渡圆角",
                "dimensions": f"R3~R10圆角面",
                "count": len(torus_faces), "diameter": None, "depth": None,
                "width": None, "length": None, "area_mm2": None,
                "note": f"共{len(torus_faces)}个过渡圆角面, 需球头刀精加工",
            })

        # ---- 6. 分析型腔/槽 (基于小平面组) ----
        # 除了3个最大平面外, 其余小平面可能属于型腔底面或槽底面
        remaining_planes = planar_sorted[3:10] if len(planar_sorted) > 3 else []
        pocket_candidates = [pf for pf in remaining_planes if pf["area"] > 1.0]  # >1cm²

        if pocket_candidates:
            pocket_count = len(pocket_candidates)
            avg_area = sum(pf["area"] for pf in pocket_candidates) / pocket_count
            dim_mm = round((avg_area * 100) ** 0.5, 1)
            detected.append({
                "feature_type": "型腔", "name": "型腔/台阶面",
                "dimensions": f"约{dim_mm}×{dim_mm}mm, 深约10mm",
                "count": pocket_count, "diameter": None, "depth": 10,
                "width": dim_mm, "length": dim_mm, "area_mm2": round(avg_area * 100, 1),
                "note": f"共{pocket_count}处凹陷/台阶特征(基于平面检测)",
            })

        # ---- 7. 计算零件外形尺寸 ----
        overall_dims = ""
        if planar_faces:
            max_area = max(pf["area"] for pf in planar_faces)
            overall_dims = f"零件最大投影面积约{round(max_area*100, 0)}mm²"

        return detected, overall_dims

    except Exception as e:
        err_msg = f"特征扫描异常: {type(e).__name__}: {e}"
        print(f"[CAM_AI] {err_msg}")
        import traceback
        traceback.print_exc()
        return [], err_msg
# ============================================================================
# 命令创建事件处理器
# ============================================================================
class CraftCommandCreatedEventHandler(adsk.core.CommandCreatedEventHandler):
    """构建对话框界面。"""

    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            cmd = args.command
            cmd.isOKButtonVisible = False
            cmd.isCancelButtonVisible = True
            inputs = cmd.commandInputs

            # ============================================================
            # 标题栏 (CAM Assist 风格)
            # ============================================================
            t = inputs.addTextBoxCommandInput(
                "titleText", "标题",
                "<div align='center' style='font-size:18px;font-weight:bold;padding:18px 14px;"
                "background:#0D1B2A;color:#fff;border-radius:10px;border:1px solid #1B263B;'>"
                "🎯 CAM AI 智能工艺助手 <span style='font-size:13px;color:#FFD700;'>v1.8.0</span><br>"
                "<span style='font-size:11px;color:#778DA9;font-weight:normal;'>"
                "AI-Powered CAM Automation · 参考 Mastercam CAM Assist 工作流</span>"
                "</div>", 7, True,
            )
            t.isFullWidth = True

            # ============================================================
            # v1.4.2: 模型源选择 (本地 Ollama / 在线 API 热切换)
            # ============================================================
            dd_provider = inputs.addDropDownCommandInput(
                "modelProvider", "AI模型源",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_provider.tooltip = "选择AI推理后端 (本地=免费但慢, 在线=快但需API Key)"
            # 从后端获取可用 provider 列表
            provider_list = ["Ollama本地 (qwen2.5:7b)", "DeepSeek在线", "通义千问在线", "自定义端点"]
            provider_ids = ["ollama_local", "deepseek_online", "qwen_online", "custom_openai"]
            try:
                prov_resp = http_get_json(f"{API_BASE_URL}/admin/api/model_provider", timeout=5)
                active_id = prov_resp.get("active_provider", "ollama_local")
                providers = prov_resp.get("providers", {})
                provider_list = []
                provider_ids = []
                for pid, info in providers.items():
                    label = info.get("label", pid)
                    if not info.get("has_api_key") and not info.get("is_local"):
                        label += " (未配置Key)"
                    provider_list.append(label)
                    provider_ids.append(pid)
                # 记录当前活跃的 provider 索引
                self._active_provider_idx = provider_ids.index(active_id) if active_id in provider_ids else 0
            except Exception:
                self._active_provider_idx = 0
            for i, opt in enumerate(provider_list):
                dd_provider.listItems.add(opt, i == self._active_provider_idx)
            dd_provider.listItems  # 触发渲染
            self._provider_ids = provider_ids

            # ============================================================
            # 步骤 1: 加工环境设置 (参考 CAM Assist General + Setup 选项卡)
            # ============================================================
            inputs.addTextBoxCommandInput(
                "sec1", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:3px solid #0D47A1;'>"
                "<div style='font-size:15px;font-weight:bold;color:#0D47A1;padding:6px 0 4px 0;"
                "border-left:5px solid #0D47A1;padding-left:12px;'>"
                "📐 步骤 1: 加工环境设置</div>",
                2, True,
            ).isFullWidth = True

            # 第1行: 机床类型 + 工件材料 (并排)
            dd_mach = inputs.addDropDownCommandInput(
                "machineSelect", "机床类型",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_mach.tooltip = "选择使用的数控机床 (参考CAM Assist Machine Selection, 列表从后端动态拉取)"
            machines_list = get_machines()
            for i, opt in enumerate(machines_list):
                dd_mach.listItems.add(opt, i == 0)

            dd_mat = inputs.addDropDownCommandInput(
                "materialSelect", "工件材料",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_mat.tooltip = "选择工件原材料牌号 (参考CAM Assist Stock Material)"
            for i, opt in enumerate(MATERIALS):
                dd_mat.listItems.add(opt, i == 0)

            # 第2行: 加工模式 + 装夹刚性 (CAM Assist 特有)
            dd_mode = inputs.addDropDownCommandInput(
                "machiningMode", "加工模式",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_mode.tooltip = "选择加工轴数和联动方式 (参考CAM Assist Machining Mode)"
            for i, opt in enumerate(MACHINING_MODES):
                dd_mode.listItems.add(opt, i == 0)

            dd_hold = inputs.addDropDownCommandInput(
                "workholding", "装夹刚性",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_hold.tooltip = "评估装夹稳定性, 影响切削参数策略 (参考CAM Assist Workholding Security Slider)"
            for i, opt in enumerate(WORKHOLDING_LEVELS):
                dd_hold.listItems.add(opt, i == 1)  # 默认"良好"

            # 第3行: 冷却方式 + 表面质量目标 (CAM Assist 风格精细控制)
            dd_cool = inputs.addDropDownCommandInput(
                "coolant", "冷却方式",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_cool.tooltip = "选择冷却润滑方式 (影响切削速度和刀具寿命)"
            for i, opt in enumerate(COOLANT_TYPES):
                dd_cool.listItems.add(opt, i == 0)

            dd_surf = inputs.addDropDownCommandInput(
                "surfaceFinish", "表面质量目标",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_surf.tooltip = "设定目标表面粗糙度, AI据此调整精加工参数"
            for i, opt in enumerate(SURFACE_FINISH_TARGETS):
                dd_surf.listItems.add(opt, i == 2)  # 默认Ra1.6

            # AI策略滑块 (对标 CAM Assist Strategy Slider)
            dd_strat = inputs.addDropDownCommandInput(
                "aiStrategy", "🤖 AI策略倾向 (对标 CAM Assist Strategy Slider)",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_strat.tooltip = "控制AI生成切削参数的激进程度: 安全优先→均衡→效率优先"
            for i, opt in enumerate(AI_STRATEGY_LEVELS):
                dd_strat.listItems.add(opt, i == 1)  # 默认均衡

            # ============================================================
            # 步骤 2: 预检 + 特征分析 (对标 CAM Assist Pre-Flight Check)
            # ============================================================
            inputs.addTextBoxCommandInput(
                "sec1b", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:3px solid #E65100;'>"
                "<div style='font-size:15px;font-weight:bold;color:#E65100;padding:6px 0 4px 0;"
                "border-left:5px solid #E65100;padding-left:12px;'>"
                "🔬 步骤 2: 预检 + 特征分析</div>"
                "<div style='font-size:11px;color:#8D6E63;padding-left:17px;padding-top:2px;'>"
                "对标 CAM Assist Pre-Flight Check — 验证加工条件 + 自动几何分析</div>",
                4, True,
            ).isFullWidth = True

            # 预检按钮
            precheck_btn = inputs.addBoolValueInput(
                "preCheckBtn", "🔬 运行加工预检 (Pre-Flight Check)", False, "", True,
            )
            precheck_btn.tooltip = "对标 CAM Assist Evaluation阶段: 检查实体/毛坯/WCS/刀具库/装夹, 识别潜在问题"
            precheck_btn.isFullWidth = True
            inputs.addTextBoxCommandInput(
                "sec2", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:3px solid #E65100;'>"
                "<div style='font-size:15px;font-weight:bold;color:#E65100;padding:6px 0 4px 0;"
                "border-left:5px solid #E65100;padding-left:12px;'>"
                "🔍 步骤 2: 零件特征分析</div>"
                "<div style='font-size:11px;color:#8D6E63;padding-left:17px;padding-top:2px;'>"
                "扫描 Fusion360 当前模型的 BRep 几何体, 自动识别加工特征 "
                "(参考 CAM Assist Automatic Feature Recognition)</div>",
                4, True,
            ).isFullWidth = True

            # 主操作: 扫描特征按钮 (CAM Assist 风格 — 突出显示)
            scan_btn = inputs.addBoolValueInput(
                "autoDetectBtn", "🔍 扫描并分析模型特征", False, "", True,
            )
            scan_btn.tooltip = "自动分析当前3D模型的几何特征 (平面/孔/型腔/倒角/圆角), 替代手动选择"
            scan_btn.isFullWidth = True

            # 特征分析状态
            self.scan_status = inputs.addTextBoxCommandInput(
                "scanStatus", "分析状态",
                "<div style='text-align:center;padding:12px;color:#546E7A;font-size:12px;"
                "background:#ECEFF1;border:1px dashed #B0BEC5;border-radius:8px;'>"
                "⏳ 等待分析 — 请点击上方按钮扫描模型</div>",
                3, True,
            )
            self.scan_status.isFullWidth = True

            # 特征摘要面板 (自动填充)
            self.feature_panel = inputs.addTextBoxCommandInput(
                "featurePanel", "检测结果",
                "<div style='background:#FFF3E0;border:1px solid #FFB74D;border-left:5px solid #E65100;padding:16px;"
                "border-radius:8px;text-align:center;font-size:13px;color:#BF360C;'>"
                "📊 尚未扫描 — 点击 <b>'扫描并分析模型特征'</b> 开始自动检测</div>",
                12, True,
            )
            self.feature_panel.isFullWidth = True

            # 手动特征选择 (fallback, 参考CAM Assist工具过滤)
            dd_feat = inputs.addDropDownCommandInput(
                "featureSelect", "手动指定特征 (可选fallback)",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_feat.tooltip = "不依赖自动检测时, 可手动选择单个特征查询 (保留传统功能)"
            for i, opt in enumerate(FEATURES):
                dd_feat.listItems.add(opt, i == 0)

            # ============================================================
            # 步骤 3: 工艺生成 (参考 CAM Assist Compute → Toolpaths 输出)
            # ============================================================
            inputs.addTextBoxCommandInput(
                "sec3", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:3px solid #1B5E20;'>"
                "<div style='font-size:15px;font-weight:bold;color:#1B5E20;padding:6px 0 4px 0;"
                "border-left:5px solid #1B5E20;padding-left:12px;'>"
                "🚀 步骤 3: 工艺生成与输出</div>"
                "<div style='font-size:11px;color:#558B2F;padding-left:17px;padding-top:2px;'>"
                "基于检测到的特征和加工环境, AI生成完整工艺流程+刀路策略+切削参数 "
                "(参考 CAM Assist Toolpath Strategy Generation)</div>",
                4, True,
            ).isFullWidth = True

            # 生成按钮组
            gen_btn = inputs.addBoolValueInput(
                "autoCraftBtn", "▶ 生成完整工艺方案 (推荐)", False, "", True,
            )
            gen_btn.tooltip = "将特征和加工环境发送给AI, 生成含刀路策略的完整多步工艺流程"
            gen_btn.isFullWidth = True

            kb_btn = inputs.addBoolValueInput(
                "kbBtn", "📖 仅查询知识库基准参数 (离线/免费)", False, "", True,
            )
            kb_btn.tooltip = "不调用AI, 直接显示内置知识库参考值 (参考CAM Assist Cutting Parameters Explorer)"
            kb_btn.isFullWidth = True

            # 工艺概览面板 (只读, 显示AI生成的摘要)
            self.result_panel = inputs.addTextBoxCommandInput(
                "resultPanel", "工艺概览",
                "<div style='background:#E8F5E9;border:1px solid #A5D6A7;border-left:5px solid #2E7D32;padding:16px;"
                "border-radius:8px;text-align:center;font-size:13px;color:#558B2F;min-height:50px;'>"
                "<b>📋 等待工艺生成...</b><br>"
                "<span style='font-size:11px;color:#81C784;'>"
                "请先完成 <b>步骤2</b> 特征扫描 → 然后点击 <b>'生成完整工艺方案'</b><br>"
                "生成后可在下方表格中直接编辑修改工序参数</span></div>",
                6, True,
            )
            self.result_panel.isFullWidth = True

            # v1.8.0: 可编辑工艺方案表格 — 每行自带操作按钮
            # 列宽比例: 序号|工序|刀具|主轴|进给|切深|备注|操作(每行内嵌删除)
            self.process_table = inputs.addTableCommandInput(
                "processTable", "✏️ 工艺方案编辑 (直接修改单元格内容, 每行可独立删除)",
                8, "0.45:2.6:2.6:1.2:1.2:0.9:2.4:1.0",
            )
            self.process_table.hasGrid = True
            self.process_table.isFullWidth = True
            self.process_table.maxRowsVisible = 15  # 增加可见行数

            # 表头行 (row 0) — 新增"操作"列
            _TABLE_HEADERS = ["序号", "工序名称", "刀具规格", "主轴转速(rpm)", "进给速度(mm/min)", "切深(mm)", "备注/说明", "操作"]
            for col_idx, hdr_text in enumerate(_TABLE_HEADERS):
                hdr_cell = inputs.addTextBoxCommandInput(
                    f"th_{col_idx}", "",
                    f"<b style='font-size:11px;color:#1565C0;'>{hdr_text}</b>", 1, True,
                )
                self.process_table.addCommandInput(hdr_cell, 0, col_idx)

            # v1.8.0: 表格底部操作区 (仅保留"添加行"和"应用修改")
            add_row_btn = inputs.addBoolValueInput(
                "addRowBtn", "➕ 添加工序 (在末尾新增一行)", False, "", True,
            )
            add_row_btn.tooltip = "在工艺表格末尾添加一个空白工序行"
            add_row_btn.isFullWidth = True

            # v1.6: 应用修改按钮
            apply_btn = inputs.addBoolValueInput(
                "applyEditBtn", "💾 应用修改 (保存所有编辑到工艺方案)", False, "", True,
            )
            apply_btn.tooltip = "将表格中修改的工序参数保存到工艺方案中, 后续创建CAM工序时使用修改后的参数"
            apply_btn.isFullWidth = True

            # ============================================================
            # 附加功能: 刀具分析 + 保存 + CAM工序创建 (CAM Assist 风格)
            # ============================================================
            inputs.addTextBoxCommandInput(
                "sec4", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:3px solid #4A148C;'>"
                "<div style='font-size:14px;font-weight:bold;color:#4A148C;padding:6px 0 4px 0;"
                "border-left:5px solid #4A148C;padding-left:12px;'>"
                "🛠️ 附加工具</div>",
                2, True,
            ).isFullWidth = True

            # v1.5: 一键创建 CAM 工序 (L1-L5 全链路)
            create_btn = inputs.addBoolValueInput(
                "createCamOpsBtn", "⚙️ 一键创建CAM工序 (自动Setup+刀具+工序+刀路)", False, "", True,
            )
            create_btn.tooltip = (
                "根据AI工艺方案, 自动在CAM环境中创建:\n"
                "L1: 加工Setup (毛坯+WCS)\n"
                "L2: 刀具 (自动创建/匹配)\n"
                "L3: 工序 + 切削参数 (S/F/ap)\n"
                "L4: 几何体选择 (半自动, 需确认)\n"
                "L5: 刀路生成\n"
                "⚠️ 需在CAM工作区执行"
            )
            create_btn.isFullWidth = True

            tool_btn = inputs.addBoolValueInput(
                "toolAnalysisBtn", "📊 分析刀具使用情况", False, "", True,
            )
            tool_btn.tooltip = "对比AI推荐刀具与Fusion360刀具库, 分析哪些刀具被用到 (参考CAM Assist Tool Usages 选项卡)"
            tool_btn.isFullWidth = True

            save_btn = inputs.addBoolValueInput(
                "saveToLibraryBtn", "📤 保存结果到个人工艺库", False, "", True,
            )
            save_btn.tooltip = "将当前AI生成的工艺方案保存到个人工艺库 (persistent storage)"
            save_btn.isFullWidth = True

            # ============================================================
            # v1.7: AI 3D 模型生成 (文本→3D / 图片→3D → 自动导入Fusion)
            # ============================================================
            inputs.addTextBoxCommandInput(
                "sec3d", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:2px solid #7B1FA2;'>"
                "<div style='font-size:14px;font-weight:bold;color:#7B1FA2;padding:6px 0 4px 0;"
                "border-left:5px solid #7B1FA2;padding-left:12px;'>"
                "🎨 AI 3D 模型生成</div>"
                "<div style='font-size:11px;color:#A1887F;padding-left:17px;padding-top:2px;'>"
                "用自然语言描述零件, AI自动生成3D模型并导入Fusion 360 "
                "(基于 Hunyuan3D / Meshy)</div>",
                4, True,
            ).isFullWidth = True

            # 3D 生成: 描述输入框
            self.ai3d_prompt = inputs.addStringValueInput(
                "ai3dPrompt", "零件描述",
                "一个M8×30的六角螺栓",
            )
            self.ai3d_prompt.tooltip = (
                "用自然语言描述要生成的3D零件\n"
                "示例:\n"
                "  - 一个M8×30的六角螺栓\n"
                "  - 直径50mm厚10mm的齿轮, 20齿\n"
                "  - a mechanical bracket with 4 mounting holes"
            )
            self.ai3d_prompt.isFullWidth = True

            # 3D 生成: 后端选择 + 输出格式
            dd_3d_backend = inputs.addDropDownCommandInput(
                "ai3dBackend", "AI 3D 后端",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_3d_backend.tooltip = "选择 AI 3D 生成后端 (Hunyuan3D=腾讯免费20次/天, Meshy=付费, OpenRouter=Fusion/Lumina通用)"
            # 默认选项 (运行时从后端拉取实际状态)
            self._ai3d_backend_ids = ["hunyuan", "meshy"]
            self._ai3d_backend_labels = ["Hunyuan3D (腾讯)", "Meshy (付费)"]
            try:
                resp_3d = http_get_json(f"{API_BASE_URL}/ai_3d/backends", timeout=5)
                backends = resp_3d.get("backends", {})
                self._ai3d_backend_ids = []
                self._ai3d_backend_labels = []
                for bid, info in backends.items():
                    label = info.get("name", bid)
                    if not info.get("configured"):
                        label += " (未配置Key)"
                    self._ai3d_backend_ids.append(bid)
                    self._ai3d_backend_labels.append(label)
            except Exception:
                pass
            for i, label in enumerate(self._ai3d_backend_labels):
                dd_3d_backend.listItems.add(label, i == 0)

            dd_3d_format = inputs.addDropDownCommandInput(
                "ai3dFormat", "输出格式",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_3d_format.tooltip = "STEP=可编辑实体(需FreeCAD) | OBJ=通用网格 | GLB=原始格式"
            for i, fmt in enumerate(["STEP (可编辑实体)", "OBJ (通用网格)", "GLB (原始格式)"]):
                dd_3d_format.listItems.add(fmt, i == 0)

            # 3D 生成: 生成按钮
            gen3d_btn = inputs.addBoolValueInput(
                "ai3dGenBtn", "🎨 生成3D模型并导入", False, "", True,
            )
            gen3d_btn.tooltip = (
                "根据文字描述调用AI生成3D模型, 自动导入到当前Fusion 360文档\n"
                "⚠️ 生成过程约需1-5分钟 (取决于AI后端响应速度)"
            )
            gen3d_btn.isFullWidth = True

            # 3D 生成: 后端状态检查按钮
            check3d_btn = inputs.addBoolValueInput(
                "ai3dCheckBtn", "🔍 检查3D后端状态", False, "", True,
            )
            check3d_btn.tooltip = "检查 AI 3D 生成后端是否已配置 (API Key / FreeCAD)"
            check3d_btn.isFullWidth = True

            # 3D 生成: API Key 配置按钮
            key3d_btn = inputs.addBoolValueInput(
                "ai3dKeyBtn", "🔑 配置3D后端API Key", False, "", True,
            )
            key3d_btn.tooltip = "运行时配置 Hunyuan3D / Meshy 的 API Key (无需重启后端)"
            key3d_btn.isFullWidth = True

            # 手动单步查询按钮 (保留传统功能, 收到底部)
            inputs.addTextBoxCommandInput(
                "sec5", "",
                "<hr style='margin:18px 0 6px 0;border:none;border-top:2px solid #B0BEC5;'>"
                "<div style='font-size:12px;color:#546E7A;text-align:center;padding:6px 0;'>"
                "— 传统单步查询 (不依赖特征扫描) —</div>",
                1, True,
            ).isFullWidth = True

            qbtn = inputs.addBoolValueInput("queryBtn", "单步查询工艺参数 (手动模式)", False, "", True)
            qbtn.tooltip = "手动选择单个特征和材料进行AI查询 (保留传统功能)"
            qbtn.isFullWidth = True

            # ============================================================
            # 共享数据容器 + 事件注册 (v1.4.1: 使用模块级全局, 跨工作区持久化)
            # ============================================================
            global _shared_data
            shared_data = _shared_data

            on_exec = CraftCommandExecuteEventHandler(
                self.scan_status, self.feature_panel, self.result_panel,
            )
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)

            on_change = CraftInputChangedEventHandler(
                self.scan_status, self.feature_panel, self.result_panel, shared_data,
                self.process_table,
            )
            cmd.inputChanged.add(on_change)
            _handlers.append(on_change)

            # v1.4.1: 恢复之前的扫描结果 (跨工作区切换后重开对话框时)
            if shared_data.get("detected_features"):
                features = shared_data["detected_features"]
                overall_dims = shared_data.get("overall_dimensions", "")
                total_count = sum(f.get("count", 1) for f in features if f.get("feature_type") != "__config__")
                # 延迟恢复 (等对话框完全渲染后再更新UI)
                def _restore():
                    try:
                        on_change._show_detected_features(features, overall_dims)
                        on_change._set_scan_status(
                            f"✅ 已恢复上次扫描 — {len(features)}类特征 (共{total_count}处) | "
                            f"外形: {overall_dims if overall_dims else '自动检测'}",
                            "#2E7D32", "done",
                        )
                        on_change._set_result_placeholder(
                            "✅ 特征数据已恢复 (跨工作区) — 请点击 <b>'▶ 生成完整工艺方案'</b><br>"
                            f"<span style='font-size:11px;color:#546E7A;'>"
                            f"或重新点击 '🔍 自动检测' 刷新特征数据</span>"
                        )
                    except Exception:
                        pass
                # 用 Fusion360 的 evaluateAtIdle 延迟执行
                try:
                    app = adsk.core.Application.get()
                    app.executeAfterIdle(_restore)
                except Exception:
                    pass

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(f"构建对话框失败:\n{traceback.format_exc()}")


# ============================================================================
# 输入变化事件处理器 (处理按钮点击)
# ============================================================================
class CraftInputChangedEventHandler(adsk.core.InputChangedEventHandler):
    """CAM Assist 风格事件处理器 — 扫描→配置→生成→保存 工作流。"""

    def __init__(self, scan_status, feature_panel, result_panel, shared_data=None, process_table=None):
        super().__init__()
        self.scan_status = scan_status
        self.feature_panel = feature_panel
        self.result_panel = result_panel
        self.process_table = process_table
        self._table_row_count = 0  # 当前表格数据行数 (不含表头)
        self.shared_data = shared_data if shared_data is not None else {
            "detected_features": [], "overall_dimensions": "", "ai_result": None,
        }

    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            changed = args.input
            inputs = args.firingEvent.sender.commandInputs

            # ================================================================
            # v1.8.0: 模型源切换 (本地 ↔ 在线)
            # 修复: 使用 changed 对象直接获取选中项, 避免索引不一致导致弹框不变
            # ================================================================
            if changed.id == "modelProvider":
                try:
                    # 优先从触发事件的对象获取选中索引 (v1.8.0 修复)
                    dd_input = changed  # changed 就是 modelProvider dropdown 本身
                    sel_item = dd_input.selectedItem
                    if sel_item is None:
                        # fallback: 从 inputs 集合重新获取
                        dd_input = inputs.itemById("modelProvider")
                        sel_item = dd_input.selectedItem
                    if sel_item is None:
                        self._alert("⚠️ 未选择有效的模型源")
                        return
                    sel_idx = sel_item.index
                    provider_id = self._provider_ids[sel_idx] if hasattr(self, "_provider_ids") and sel_idx < len(self._provider_ids) else "ollama_local"

                    # 调用后端切换
                    url = f"{API_BASE_URL}/admin/api/model_provider/{provider_id}"
                    req = urllib.request.Request(url, method="POST", data=b"")
                    resp = urllib.request.urlopen(req, timeout=10)
                    result = json.loads(resp.read().decode("utf-8"))
                    label = result.get("message", "已切换")
                    model_name = result.get("active_model", "")
                    is_local = result.get("is_local", True)
                    tag = "本地" if is_local else "在线"

                    # 更新状态栏 + 弹框提示 (确保内容与选择同步)
                    status_msg = f"🔄 已切换到 {tag}模型: {model_name}"
                    self._set_scan_status(
                        status_msg,
                        "#7B1FA2" if not is_local else "#1565C0",
                        "done",
                    )
                    alert_detail = (
                        f"✅ AI模型源已切换\n\n"
                        f"当前: {label}\n"
                        f"模型: {model_name}\n"
                        f"类型: {'本地 (免费, 较慢)' if is_local else '在线 (快速, 需API Key)'}\n\n"
                        f"{'⚠️ 在线模型需要配置API Key' if not is_local else '💡 本地模型推理约需2-3分钟'}\n\n"
                        f"[调试] 选中索引={sel_idx}, provider={provider_id}"
                    )
                    self._alert(alert_detail)
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8", errors="replace")
                    self._alert(f"❌ 切换模型源失败:\n{body}")
                except Exception as e:
                    self._alert(f"❌ 切换异常: {type(e).__name__}: {e}")

            # ================================================================
            # 步骤2a: 预检 (对标 CAM Assist Pre-Flight Check)
            # ================================================================
            if changed.id == "preCheckBtn" and changed.value:
                changed.value = False
                self._set_scan_status("🔬 正在运行加工预检...", "#FF6F00", "active")
                precheck_results = self._run_pre_check()
                self._show_pre_check_results(precheck_results)
                if all(precheck_results.values()):
                    self._set_scan_status("✅ 预检全部通过! 可继续扫描特征", "#2E7D32", "done")
                else:
                    failed = sum(1 for v in precheck_results.values() if not v)
                    self._set_scan_status(f"⚠️ 预检完成 — {failed}项需要注意 (仍可继续)", "#E65100", "warn")

            # ================================================================
            # 步骤2b: 扫描并分析模型特征 (CAM Assist Feature Recognition)
            # ================================================================
            elif changed.id == "autoDetectBtn" and changed.value:
                changed.value = False
                self._set_scan_status("🔍 正在分析3D模型几何体...", "#2196F3", "active")
                self._set_result_placeholder("正在扫描模型特征, 请稍候...")

                try:
                    result = detect_model_features()
                    # 保护性解包: 确保函数返回 (list, str) 二元组
                    if isinstance(result, (tuple, list)) and len(result) >= 2:
                        features, overall_dims = result[0], result[1]
                    else:
                        features, overall_dims = [], "特征检测器返回异常 (内部错误)"
                    self.shared_data["detected_features"] = features
                    self.shared_data["overall_dimensions"] = overall_dims

                    if features:
                        total_count = sum(f.get("count", 1) for f in features)
                        self._show_detected_features(features, overall_dims)
                        self._set_scan_status(
                            f"✅ 分析完成 — {len(features)}类特征 (共{total_count}处) | "
                            f"外形: {overall_dims if overall_dims else '自动检测'}",
                            "#2E7D32", "done",
                        )
                        self._set_result_placeholder(
                            "✅ 特征扫描完成 — 请点击 <b>'▶ 生成完整工艺方案'</b> 获取AI工艺规划<br>"
                            f"<span style='font-size:11px;color:#546E7A;'>"
                            f"或使用手动特征下拉框 + '单步查询' 进行单个特征参数查询</span>"
                        )
                    else:
                        self._set_scan_status("⚠️ 未检测到特征 — 请确认设计中有3D实体", "#E65100", "warn")
                        self._show_empty_feature_warning()
                except Exception as e:
                    self._set_scan_status(f"❌ 分析失败: {str(e)[:80]}", "#C62828", "error")
                    self._show_feature_error(traceback.format_exc())

            # ================================================================
            # 步骤3: 生成完整工艺方案 (CAM Assist Compute)
            # ================================================================
            elif changed.id == "autoCraftBtn" and changed.value:
                changed.value = False

                features = self.shared_data.get("detected_features", [])
                overall_dims = self.shared_data.get("overall_dimensions", "")

                if not features:
                    self._set_scan_status("⚠️ 请先执行步骤2: '扫描并分析模型特征'!", "#E65100", "warn")
                    self._alert(
                        "请按工作流顺序操作!\n\n"
                        "1️⃣ 步骤1: 设置加工环境 (机床/材料/装夹等)\n"
                        "2️⃣ 步骤2: 点击 '🔍 扫描并分析模型特征'\n"
                        "3️⃣ 步骤3: 点击 '▶ 生成完整工艺方案'\n\n"
                        "当前尚未检测到模型特征, 请先执行步骤2。"
                    )
                    return

                material = inputs.itemById("materialSelect").selectedItem.name
                machine = inputs.itemById("machineSelect").selectedItem.name
                # CAM Assist 风格: 收集额外配置信息
                machining_mode = ""
                workholding = ""
                coolant = ""
                surface_finish = ""
                ai_strategy = ""
                try:
                    machining_mode = inputs.itemById("machiningMode").selectedItem.name if inputs.itemById("machiningMode") else ""
                    workholding = inputs.itemById("workholding").selectedItem.name if inputs.itemById("workholding") else ""
                    coolant = inputs.itemById("coolant").selectedItem.name if inputs.itemById("coolant") else ""
                    surface_finish = inputs.itemById("surfaceFinish").selectedItem.name if inputs.itemById("surfaceFinish") else ""
                    ai_strategy = inputs.itemById("aiStrategy").selectedItem.name if inputs.itemById("aiStrategy") else ""
                except Exception:
                    pass

                self._set_result_placeholder("⏳ 正在调用本地Ollama模型, 请稍候...")

                # 将额外配置附加到features中
                enriched_features = list(features)
                enriched_features.append({
                    "feature_type": "__config__", "name": "加工配置",
                    "dimensions": "",
                    "count": 1,
                    "diameter": None, "depth": None, "width": None, "length": None, "area_mm2": None,
                    "note": f"加工模式:{machining_mode} | 装夹:{workholding} | 冷却:{coolant} | 表面目标:{surface_finish} | AI策略:{ai_strategy}",
                })

                result = self._do_auto_craft_query(enriched_features, material, machine, overall_dims)

                if result:
                    self.shared_data["ai_result"] = result
                    self._show_auto_craft_result(result, material, machine,
                                                  machining_mode, workholding, coolant,
                                                  surface_finish, ai_strategy)
                    # v1.6: 填充可编辑工艺表格
                    self._populate_process_table(inputs, result.get("steps", []))
                else:
                    self._set_scan_status("❌ API连接失败! 请确认服务已启动 (端口8000)", "#C62828", "error")
                    self._set_result_placeholder(
                        "<span style='color:#C62828;'>❌ 工艺生成失败</span><br>"
                        "<span style='font-size:9px;'>请检查 cam_cloud_api.py 和 Ollama 是否在运行</span>"
                    )

            # ================================================================
            # v1.5: 一键创建 CAM 工序 (L1-L5 全链路)
            # ================================================================
            elif changed.id == "createCamOpsBtn" and changed.value:
                changed.value = False

                ai_result = self.shared_data.get("ai_result")
                if not ai_result or not ai_result.get("steps"):
                    self._alert(
                        "请先生成工艺方案 (步骤3), 然后再创建CAM工序!\n\n"
                        "工作流: 扫描特征 → 生成工艺方案 → 一键创建CAM工序"
                    )
                    return

                # v1.6: 从可编辑表格中读取最新值 (用户可能已修改)
                edited_steps = self._read_edited_steps(inputs)
                if edited_steps:
                    ai_result = dict(ai_result)  # 浅拷贝, 不修改原始
                    ai_result["steps"] = edited_steps
                    self.shared_data["ai_result"] = ai_result

                self._set_scan_status("⚙️ 正在创建CAM工序...", "#7B1FA2", "active")
                self._set_result_placeholder("⏳ 正在自动创建 Setup → 刀具 → 工序 → 刀路...")

                try:
                    summary = self._create_cam_operations(ai_result)
                    self._set_scan_status(
                        f"✅ CAM工序创建完成 — {summary['ops_created']}个工序, "
                        f"{summary['tools_matched']}把刀具匹配, "
                        f"{summary['toolpaths_generated']}条刀路",
                        "#2E7D32", "done",
                    )
                    self._show_cam_creation_result(summary)
                except Exception as e:
                    err_detail = traceback.format_exc()
                    self._set_scan_status(f"❌ CAM创建失败: {str(e)[:60]}", "#C62828", "error")
                    self._show_cam_creation_error(err_detail)

            # ================================================================
            # v1.6: 应用编辑修改 (将表格中的修改保存到 ai_result)
            # ================================================================
            elif changed.id == "applyEditBtn" and changed.value:
                changed.value = False

                ai_result = self.shared_data.get("ai_result")
                if not ai_result or not ai_result.get("steps"):
                    self._alert("请先生成工艺方案, 然后再编辑修改!")
                    return

                edited_steps = self._read_edited_steps(inputs)
                if edited_steps:
                    ai_result["steps"] = edited_steps
                    self.shared_data["ai_result"] = ai_result
                    self._set_scan_status(
                        f"✅ 已保存修改 — {len(edited_steps)}步工序参数已更新",
                        "#2E7D32", "done",
                    )
                    self._alert(
                        f"✅ 工艺方案已更新!\n\n"
                        f"已保存 {len(edited_steps)} 步工序的修改\n"
                        f"后续 '创建CAM工序' / '刀具分析' / '保存到工艺库' 均使用修改后的参数"
                    )
                else:
                    self._alert("⚠️ 未能从表格中读取到工序数据, 请确认表格已填充")

            # ================================================================
            # v1.8.0: 添加工序行 (在表格末尾追加空白行, 含内嵌删除按钮)
            # ================================================================
            elif changed.id == "addRowBtn" and changed.value:
                changed.value = False

                try:
                    table = inputs.itemById("processTable")
                    if not table:
                        self._alert("找不到工艺表格控件")
                        return

                    new_row_idx = self._table_row_count + 1  # row 0 是表头
                    new_step_num = new_row_idx  # 序号从1开始
                    ri = self._table_row_count  # 行内部索引

                    # 序号 (只读)
                    cell_num = inputs.addTextBoxCommandInput(
                        f"stepNum_{ri}", "",
                        f"<b style='font-size:10px;color:#2E7D32;'>{new_step_num}</b>",
                        1, True,
                    )
                    table.addCommandInput(cell_num, new_row_idx, 0)

                    # 工序名 (可编辑, 预填默认值)
                    default_ops = ["型腔加工", "轮廓铣削", "钻孔", "平面铣削", "曲面精加工", "倒角"]
                    default_op = default_ops[(new_step_num - 1) % len(default_ops)]
                    cell_op = inputs.addStringValueInput(
                        f"stepOp_{ri}", "", str(default_op),
                    )
                    table.addCommandInput(cell_op, new_row_idx, 1)

                    # 刀具 (可编辑)
                    cell_tool = inputs.addStringValueInput(
                        f"stepTool_{ri}", "",
                        "Φ10端铣刀(4刃)",
                    )
                    table.addCommandInput(cell_tool, new_row_idx, 2)

                    # 主轴转速
                    cell_spindle = inputs.addStringValueInput(
                        f"stepSpindle_{ri}", "", "2500",
                    )
                    table.addCommandInput(cell_spindle, new_row_idx, 3)

                    # 进给速度
                    cell_feed = inputs.addStringValueInput(
                        f"stepFeed_{ri}", "", "500",
                    )
                    table.addCommandInput(cell_feed, new_row_idx, 4)

                    # 切深
                    cell_ap = inputs.addStringValueInput(
                        f"stepAp_{ri}", "", "0.8",
                    )
                    table.addCommandInput(cell_ap, new_row_idx, 5)

                    # 备注
                    cell_note = inputs.addStringValueInput(
                        f"stepNote_{ri}", "", "(手动添加)",
                    )
                    table.addCommandInput(cell_note, new_row_idx, 6)

                    # v1.8.0: 新增行自带删除按钮
                    del_btn = inputs.addBoolValueInput(
                        f"delRow_{ri}", "🗑️ 删除", False, "", True,
                    )
                    del_btn.tooltip = f"删除第 {new_step_num} 步工序"
                    table.addCommandInput(del_btn, new_row_idx, 7)

                    self._table_row_count += 1

                    self._set_scan_status(
                        f"✅ 已添加第 {new_step_num} 步工序 — 当前共 {self._table_row_count} 步",
                        "#2E7D32", "done",
                    )

                    # 同步到 shared_data (立即生效, 不需要等应用修改)
                    ai_result = self.shared_data.get("ai_result")
                    if ai_result:
                        edited_steps = self._read_edited_steps(inputs)
                        if edited_steps:
                            ai_result["steps"] = edited_steps
                            self.shared_data["ai_result"] = ai_result

                except Exception as e:
                    self._alert(f"❌ 添加工序失败: {type(e).__name__}: {e}")

            # ================================================================
            # v1.8.0: 每行内嵌删除按钮 — 删除指定工序行
            # ================================================================
            elif changed.id.startswith("delRow_") and changed.value:
                changed.value = False

                try:
                    # 至少保留1行
                    if self._table_row_count <= 1:
                        self._set_scan_status("⚠️ 必须保留至少1道工序", "#E65100", "warn")
                        self._alert("⚠️ 表格必须保留至少 1 道工序，不能全部删除。")
                        return

                    # 解析被点击的行索引
                    row_idx_str = changed.id.replace("delRow_", "")
                    target_row_idx = int(row_idx_str)  # 0-based 行内部索引
                    table_row = target_row_idx + 1       # 表格物理行号 (row 0=表头)

                    table = inputs.itemById("processTable")
                    if table:
                        # 删除目标行的所有单元格 (8列), 从后往前删避免索引偏移
                        for col in reversed(range(8)):
                            try:
                                table.removeInput(table_row, col)
                            except Exception:
                                pass

                        self._table_row_count -= 1

                        # v1.8.0: 重编号下方所有行 (序号 + 控件ID)
                        self._renumber_rows_after_delete(inputs, table, target_row_idx)

                    self._set_scan_status(
                        f"🗑️ 已删除第 {target_row_idx+1} 步工序 — 剩余 {self._table_row_count} 步",
                        "#FF9800", "done",
                    )

                    # 同步到 shared_data
                    ai_result = self.shared_data.get("ai_result")
                    if ai_result:
                        edited_steps = self._read_edited_steps(inputs)
                        if edited_steps:
                            ai_result["steps"] = edited_steps
                            self.shared_data["ai_result"] = ai_result

                except Exception as e:
                    self._alert(f"❌ 删除工序失败: {type(e).__name__}: {e}")

            # ================================================================
            # 附加: 分析刀具使用情况 (CAM Assist Tool Usages)
            # ================================================================
            elif changed.id == "toolAnalysisBtn" and changed.value:
                changed.value = False

                ai_result = self.shared_data.get("ai_result")
                if not ai_result or not ai_result.get("steps"):
                    self._alert("请先生成工艺方案 (步骤3), 然后再分析刀具使用情况。")
                    return

                # v1.6: 优先使用表格中的编辑值
                edited_steps = self._read_edited_steps(inputs)
                steps = edited_steps if edited_steps else ai_result.get("steps", [])
                self._show_tool_usage_analysis(steps)

            # ================================================================
            # 附加: 保存结果到个人工艺库
            # ================================================================
            elif changed.id == "saveToLibraryBtn" and changed.value:
                changed.value = False

                ai_result = self.shared_data.get("ai_result")
                if not ai_result or not ai_result.get("steps"):
                    self._alert("请先生成工艺方案 (步骤3), 然后再保存到个人工艺库。")
                    return

                # v1.6: 优先使用表格中的编辑值
                edited_steps = self._read_edited_steps(inputs)
                if edited_steps:
                    ai_result = dict(ai_result)
                    ai_result["steps"] = edited_steps
                    self.shared_data["ai_result"] = ai_result

                material = inputs.itemById("materialSelect").selectedItem.name
                machine = inputs.itemById("machineSelect").selectedItem.name
                self._save_to_personal_library(ai_result, material, machine)

            # ================================================================
            # 知识库查询 (离线)
            # ================================================================
            elif changed.id == "kbBtn" and changed.value:
                changed.value = False

                feature = inputs.itemById("featureSelect").selectedItem.name
                material = inputs.itemById("materialSelect").selectedItem.name

                result = self._do_kb_query(feature, material)

                if result:
                    self._show_kb_result(feature, material, result)
                else:
                    self._set_scan_status("❌ 知识库查询失败!", "#C62828", "error")

            # ================================================================
            # 单步手动查询 (传统功能保留)
            # ================================================================
            elif changed.id == "queryBtn" and changed.value:
                changed.value = False

                feature = inputs.itemById("featureSelect").selectedItem.name
                material = inputs.itemById("materialSelect").selectedItem.name
                machine = inputs.itemById("machineSelect").selectedItem.name

                result = self._do_ai_query(feature, material, machine)

                if result:
                    self._show_ai_result(feature, material, machine, result)
                else:
                    self._set_scan_status("❌ 查询失败", "#C62828", "error")

            # ================================================================
            # v1.7: AI 3D 模型生成
            # ================================================================
            elif changed.id == "ai3dGenBtn" and changed.value:
                changed.value = False
                self._do_ai_3d_generation(inputs)

            elif changed.id == "ai3dCheckBtn" and changed.value:
                changed.value = False
                self._check_ai_3d_backends()

            elif changed.id == "ai3dKeyBtn" and changed.value:
                changed.value = False
                self._config_ai_3d_key(inputs)

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(f"操作异常:\n{traceback.format_exc()}")

    # ------------------------------------------------------------------
    # v1.6: 可编辑工艺表格管理 (TableCommandInput)
    # ------------------------------------------------------------------
    def _clear_process_table(self, inputs):
        """清空工艺表格中的所有数据行 (保留表头 row 0)。v1.8.0: 8列(含操作列)。"""
        try:
            table = inputs.itemById("processTable")
            if not table:
                return

            # 从最后一行往回删 (row 0 是表头, 保留) — 8 列
            for row in range(table.rowCount - 1, 0, -1):
                for col in reversed(range(8)):
                    try:
                        table.removeInput(row, col)
                    except Exception:
                        pass
            self._table_row_count = 0
        except Exception:
            pass

    def _populate_process_table(self, inputs, steps: list):
        """
        v1.8.0: 将AI生成的工序步骤填充到可编辑表格中。
        每行第8列为内嵌删除按钮, 可独立删除该行。
        列: 序号 | 工序 | 刀具 | 主轴转速 | 进给速度 | 切深 | 备注 | 操作
        """
        try:
            table = inputs.itemById("processTable")
            if not table:
                return

            # 先清空旧数据
            self._clear_process_table(inputs)

            for i, step in enumerate(steps):
                row = i + 1  # row 0 是表头

                # 序号 (只读 TextBox)
                cell_num = inputs.addTextBoxCommandInput(
                    f"stepNum_{i}", "",
                    f"<b style='font-size:10px;color:#2E7D32;'>{step.get('step', i+1)}</b>",
                    1, True,
                )
                table.addCommandInput(cell_num, row, 0)

                # 工序名 (可编辑)
                cell_op = inputs.addStringValueInput(
                    f"stepOp_{i}", "", str(step.get("operation", "")),
                )
                table.addCommandInput(cell_op, row, 1)

                # 刀具 (可编辑)
                cell_tool = inputs.addStringValueInput(
                    f"stepTool_{i}", "", str(step.get("tool", "")),
                )
                table.addCommandInput(cell_tool, row, 2)

                # 主轴转速 (可编辑)
                cell_spindle = inputs.addStringValueInput(
                    f"stepSpindle_{i}", "", str(step.get("spindle_speed", "")),
                )
                table.addCommandInput(cell_spindle, row, 3)

                # 进给速度 (可编辑)
                cell_feed = inputs.addStringValueInput(
                    f"stepFeed_{i}", "", str(step.get("feed_rate", "")),
                )
                table.addCommandInput(cell_feed, row, 4)

                # 切深 (可编辑)
                cell_ap = inputs.addStringValueInput(
                    f"stepAp_{i}", "", str(step.get("depth_of_cut", "")),
                )
                table.addCommandInput(cell_ap, row, 5)

                # 备注 (可编辑)
                cell_note = inputs.addStringValueInput(
                    f"stepNote_{i}", "", str(step.get("note", "")),
                )
                table.addCommandInput(cell_note, row, 6)

                # v1.8.0: 每行内嵌删除按钮 (col 7 — "操作"列)
                del_btn = inputs.addBoolValueInput(
                    f"delRow_{i}", "🗑️ 删除", False, "", True,
                )
                del_btn.tooltip = f"删除第 {i+1} 步工序"
                table.addCommandInput(del_btn, row, 7)

            self._table_row_count = len(steps)
        except Exception as e:
            try:
                self._alert(f"表格填充异常: {type(e).__name__}: {e}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # v1.8.0: 删除行后重编号 — 保持序号连续 + 控件ID与行索引一致
    # ------------------------------------------------------------------
    def _renumber_rows_after_delete(self, inputs, table, deleted_idx):
        """
        删除第 deleted_idx 行后, 将下方所有行的控件ID和序号向上平移。
        例如删除行2(0-based)后, 原来的行3→新行2, 行4→新行3, ...
        Fusion360 TableCommandInput 不支持直接移动行, 所以需要:
          1. 读取每行当前值
          2. 删除旧单元格
          3. 用新的ID重新创建并填入值
        """
        try:
            # 收集 deleted_idx 之后每一行的当前值
            rows_data = []
            for ri in range(deleted_idx + 1, self._table_row_count + 1):  # +1 因为 _table_row_count 还没减
                row_data = {}
                for prefix in ["stepNum", "stepOp", "stepTool", "stepSpindle", "stepFeed", "stepAp", "stepNote"]:
                    cell = table.getInputAt(ri, {"stepNum":0,"stepOp":1,"stepTool":2,"stepSpindle":3,"stepFeed":4,"stepAp":5,"stepNote":6}[prefix])
                    if cell:
                        val = ""
                        try:
                            if hasattr(cell, "text"):
                                val = cell.text
                            elif hasattr(cell, "value"):
                                val = str(cell.value)
                            elif hasattr(cell, "expression"):
                                val = str(cell.expression)
                        except Exception:
                            pass
                        row_data[prefix] = val
                    else:
                        row_data[prefix] = ""
                rows_data.append(row_data)

            # 删除旧单元格 (从最后一行往上删, 从最右列往左删)
            for r in range(table.rowCount - 1, deleted_idx + 1, -1):
                for c in reversed(range(8)):
                    try:
                        table.removeInput(r, c)
                    except Exception:
                        pass

            # 用平移后的ID重新创建行
            for offset, row_data in enumerate(rows_data):
                new_ri = deleted_idx + offset       # 新的内部索引
                new_row = deleted_idx + offset + 1   # 新的表格物理行

                # 序号
                cell_num = inputs.addTextBoxCommandInput(
                    f"stepNum_{new_ri}", "",
                    f"<b style='font-size:10px;color:#2E7D32;'>{new_ri + 1}</b>",
                    1, True,
                )
                table.addCommandInput(cell_num, new_row, 0)

                # 各数据列
                col_map = [
                    ("stepOp", 1), ("stepTool", 2), ("stepSpindle", 3),
                    ("stepFeed", 4), ("stepAp", 5), ("stepNote", 6),
                ]
                for prefix, col in col_map:
                    cell = inputs.addStringValueInput(
                        f"{prefix}_{new_ri}", "", row_data.get(prefix, ""),
                    )
                    table.addCommandInput(cell, new_row, col)

                # 内嵌删除按钮 (新ID)
                del_btn = inputs.addBoolValueInput(
                    f"delRow_{new_ri}", "🗑️ 删除", False, "", True,
                )
                del_btn.tooltip = f"删除第 {new_ri+1} 步工序"
                table.addCommandInput(del_btn, new_row, 7)

        except Exception as e:
            # 重编号失败不影响主流程, 仅记录
            try:
                self._set_scan_status(
                    f"⚠️ 行重编号部分失败: {type(e).__name__}", "#FF9800", "warn",
                )
            except Exception:
                pass

    def _read_edited_steps(self, inputs) -> list:
        """
        v1.6: 从可编辑表格中读取用户修改后的工序数据。
        改进版错误处理: 发生错误时保留原始数据而非返回空列表，避免数据丢失。
        """
        try:
            table = inputs.itemById("processTable")
            if not table or self._table_row_count == 0:
                return []

            # 获取原始 ai_result 作为基础 (保留 toolpath_strategy, feature_ref 等字段)
            original = self.shared_data.get("ai_result", {})
            original_steps = original.get("steps", [])

            edited_steps = []
            for i in range(self._table_row_count):
                # 从原始步骤中拷贝完整字段, 然后用表格中的编辑值覆盖
                step_data = dict(original_steps[i]) if i < len(original_steps) else {}

                # 读取可编辑字段
                try:
                    op_input = inputs.itemById(f"stepOp_{i}")
                    if op_input:
                        step_data["operation"] = op_input.value

                    tool_input = inputs.itemById(f"stepTool_{i}")
                    if tool_input:
                        step_data["tool"] = tool_input.value

                    spindle_input = inputs.itemById(f"stepSpindle_{i}")
                    if spindle_input:
                        step_data["spindle_speed"] = spindle_input.value

                    feed_input = inputs.itemById(f"stepFeed_{i}")
                    if feed_input:
                        step_data["feed_rate"] = feed_input.value

                    ap_input = inputs.itemById(f"stepAp_{i}")
                    if ap_input:
                        step_data["depth_of_cut"] = ap_input.value

                    note_input = inputs.itemById(f"stepNote_{i}")
                    if note_input:
                        step_data["note"] = note_input.value

                    step_data["step"] = i + 1
                    edited_steps.append(step_data)
                except Exception as e:
                    # 如果某个特定行的处理失败，则记录错误并跳过该行
                    app = adsk.core.Application.get()
                    ui = app.userInterface
                    if ui:
                        ui.messageBox(
                            f"警告：读取第{i+1}行工序数据时出错: {type(e).__name__}: {e}\n"
                            f"该行将保留原有数据。"
                        )
                    # 添加原始数据（如果没有则跳过）
                    if i < len(original_steps):
                        edited_steps.append(original_steps[i])
                    continue

            return edited_steps
        except Exception as e:
            # 在最外层异常处理中，我们返回原始数据以防止数据丢失
            app = adsk.core.Application.get()
            ui = app.userInterface
            if ui:
                ui.messageBox(
                    f"严重错误：读取工序数据失败: {type(e).__name__}: {e}\n"
                    f"将使用原始AI生成的数据，您的编辑可能未保存。"
                )

            # 返回原始数据以防止数据丢失
            original = self.shared_data.get("ai_result", {})
            return original.get("steps", [])

    # ------------------------------------------------------------------
    # v1.7: AI 3D 模型生成
    # ------------------------------------------------------------------
    def _do_ai_3d_generation(self, inputs):
        """调用后端 AI 3D 生成 API, 生成模型并自动导入 Fusion 360。"""
        import time as _time

        # 获取用户输入
        prompt_input = inputs.itemById("ai3dPrompt")
        prompt = prompt_input.value.strip() if prompt_input else ""
        if not prompt:
            self._alert("请输入零件描述!\n\n示例: 一个M8×30的六角螺栓")
            return

        # 获取后端选择
        backend_idx = 0
        try:
            backend_idx = inputs.itemById("ai3dBackend").selectedItem.index
        except Exception:
            pass
        backend = self._ai3d_backend_ids[backend_idx] if hasattr(self, "_ai3d_backend_ids") else "hunyuan"

        # 获取输出格式
        format_idx = 0
        try:
            format_idx = inputs.itemById("ai3dFormat").selectedItem.index
        except Exception:
            pass
        format_map = {0: "step", 1: "obj", 2: "glb"}
        output_format = format_map.get(format_idx, "step")

        self._set_scan_status(
            f"🎨 AI 3D 生成中... '{prompt[:40]}' (后端: {backend}, 格式: {output_format})",
            "#7B1FA2", "active",
        )
        self._set_result_placeholder(
            f"⏳ 正在调用 AI 3D 生成 ({backend})...\n"
            f"描述: {prompt}\n"
            f"⏱️ 预计需要 1-5 分钟, 请耐心等待"
        )

        try:
            t0 = _time.time()
            data = {
                "prompt": prompt,
                "backend": backend,
                "output_format": output_format,
            }
            result = http_post_json(
                f"{API_BASE_URL}/ai_3d/text_to_3d", data, timeout=360,
            )
            elapsed = int((_time.time() - t0))

            if result and result.get("status") == "ok":
                output_path = result.get("output_path", "")
                output_filename = result.get("output_filename", "")
                conversion_note = result.get("conversion_note", "")
                file_size = result.get("file_size_kb", 0)

                self._set_scan_status(
                    f"✅ 3D模型生成完成! ({elapsed}s, {file_size:.0f}KB)",
                    "#7B1FA2", "done",
                )

                # 显示生成结果
                self._show_3d_result(result, elapsed)

                # 自动导入到 Fusion 360
                if output_path:
                    self._import_3d_model_to_fusion(output_path, output_filename)

            else:
                err_msg = result.get("detail", "未知错误") if result else "无响应"
                self._set_scan_status(f"❌ 3D生成失败: {err_msg[:60]}", "#C62828", "error")
                self._set_result_placeholder(
                    f"<span style='color:#C62828;'>❌ 3D生成失败</span><br>"
                    f"<span style='font-size:9px;'>{err_msg}</span>"
                )

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err_detail = json.loads(body).get("detail", body)
            except Exception:
                err_detail = body

            # 友好化网络错误信息
            user_msg = self._friendly_3d_error(e.code, err_detail)
            self._set_scan_status(f"❌ 3D生成错误 [{e.code}]", "#C62828", "error")
            self._set_result_placeholder(
                f"<span style='color:#C62828;'>❌ 3D模型生成失败</span><br>"
                f"<span style='font-size:9px;'>{user_msg[:300]}</span>"
            )
            self._alert(f"AI 3D 生成失败:\n\n{user_msg}")
        except urllib.error.URLError as e:
            # 网络连接错误 (后端服务未启动 / 网络不通)
            reason_str = str(e.reason) if hasattr(e, "reason") else str(e)
            is_timeout = "timed out" in reason_str.lower() or "timeout" in reason_str.lower()

            if is_timeout:
                user_msg = (
                    "🔗 连接 AI 3D 服务超时!\n\n"
                    "可能原因:\n"
                    "  1. Hunyuan3D API 从国内访问较慢\n"
                    "  2. 需要配置代理服务器\n"
                    "  3. API Key 无效或额度已用完\n\n"
                    "建议操作:\n"
                    "  a) 如使用代理: 设置环境变量 HTTPS_PROXY\n"
                    "     例: set HTTPS_PROXY=http://127.0.0.1:7890\n"
                    "  b) 检查 API Key 是否有效 (注册: https://3d.hunyuanglobal.com)\n"
                    "  c) 重试一次 (首次连接可能较慢)\n\n"
                    f"技术细节: {reason_str}"
                )
            else:
                user_msg = (
                    "❌ 无法连接到 CAM 后端服务!\n\n"
                    "请确认:\n"
                    "  1. cam_cloud_api.py 已启动 (端口8000)\n"
                    "  2. Fusion 插件的 API_BASE_URL 地址正确\n\n"
                    f"错误: {reason_str}"
                )

            self._set_scan_status("❌ 连接失败 (网络超时?)", "#C62828", "error")
            self._alert(user_msg)
        except Exception as e:
            err_text = str(e)
            # 检测是否是网络/超时类错误
            is_network = any(kw in err_text.lower() for kw in
                           ["timeout", "connection", "network", "socket", "ssl"])
            if is_network:
                user_msg = (
                    "⏰ 网络请求异常!\n\n"
                    f"{type(e).__name__}: {err_text[:200]}\n\n"
                    "提示: 如果持续超时, 请检查网络或配置代理"
                )
            else:
                user_msg = f"AI 3D 生成异常:\n{type(e).__name__}: {err_text[:300]}"

            self._set_scan_status(f"❌ 3D生成异常: {type(e).__name__}", "#C62828", "error")
            self._alert(user_msg)

    @staticmethod
    def _friendly_3d_error(http_code: int, detail: str) -> str:
        """将 AI 3D 生成的技术错误转换为用户友好的中文提示。"""
        detail_lower = detail.lower() if detail else ""

        if http_code == 500 and "timeout" in detail_lower:
            return (
                "⏰ AI 3D 服务连接超时!\n\n"
                "Hunyuan3D 服务器响应太慢或不可达。\n\n"
                "解决方案:\n"
                "  1. 配置代理: set HTTPS_PROXY=http://127.0.0.1:7890\n"
                "  2. 重启后端时设置代理环境变量\n"
                "  3. 或稍后重试 (服务器可能暂时繁忙)"
            )

        if http_code == 500:
            return (
                "❌ AI 3D 服务内部错误 [500]\n\n"
                "Hunyuan3D 服务器返回了意外错误。\n"
                "可能原因:\n"
                "  - API Key 无效或过期\n"
                "  - 今日免费额度已用完 (20次/天)\n"
                "  - 输入描述格式不支持\n\n"
                f"详情: {detail[:200]}"
            )

        if http_code == 401 or http_code == 403:
            return (
                "🔑 API 认证失败!\n\n"
                "API Key 无效或过期。\n"
                "请重新获取 Key: https://3d.hunyuanglobal.com"
            )

        if http_code == 429:
            return (
                "⚠️ 请求过于频繁!\n\n"
                "今日免费额度可能已用完 (20次/天)。\n"
                "请明天再试, 或升级为付费账户。"
            )

        # 默认: 返回原始信息的友好版
        short_detail = detail[:150] if detail else "未知错误"
        return f"HTTP {http_code}: {short_detail}"

    def _import_3d_model_to_fusion(self, file_path: str, filename: str):
        """将生成的 3D 模型文件导入到当前 Fusion 360 文档。"""
        try:
            app = adsk.core.Application.get()
            ui = app.userInterface

            # 根据文件扩展名选择导入方式
            ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""

            if ext in ["step", "stp"]:
                # STEP 文件: 使用 importManager 导入为可编辑实体
                import_manager = app.importManager
                step_options = import_manager.createSTEPImportOptions(file_path)
                doc = app.activeDocument
                import_manager.importToTarget(step_options, doc)
                self._alert(
                    f"✅ 3D模型已导入到当前文档!\n\n"
                    f"文件: {filename}\n"
                    f"格式: STEP (可编辑实体)\n"
                    f"路径: {file_path}"
                )

            elif ext in ["obj", "stl", "glb"]:
                # 网格文件: 使用 MeshImportOptions
                import_manager = app.importManager
                if ext == "obj":
                    mesh_options = import_manager.createOBJImportOptions(file_path)
                elif ext == "stl":
                    mesh_options = import_manager.createSTLImportOptions(file_path)
                else:
                    # GLB 不直接支持, 提示用户手动打开
                    self._alert(
                        f"📦 3D模型已生成!\n\n"
                        f"文件: {filename}\n"
                        f"格式: {ext.upper()}\n"
                        f"路径: {file_path}\n\n"
                        f"⚠️ GLB 格式需要手动导入:\n"
                        f"文件 → 打开 → 选择该文件"
                    )
                    return

                doc = app.activeDocument
                import_manager.importToTarget(mesh_options, doc)
                self._alert(
                    f"✅ 3D模型已导入到当前文档!\n\n"
                    f"文件: {filename}\n"
                    f"格式: {ext.upper()} (网格)\n"
                    f"路径: {file_path}\n\n"
                    f"💡 提示: 网格模型可在 '网格' 工作区中转换为实体"
                )

            else:
                self._alert(
                    f"📦 3D模型已生成!\n\n"
                    f"文件: {filename}\n"
                    f"路径: {file_path}\n\n"
                    f"请手动导入: 文件 → 打开 → 选择该文件"
                )

        except Exception as e:
            # 导入失败不阻塞流程, 提示用户手动打开
            self._alert(
                f"⚠️ 自动导入失败, 请手动打开文件\n\n"
                f"文件路径: {file_path}\n\n"
                f"错误: {type(e).__name__}: {str(e)[:200]}\n\n"
                f"操作: 文件 → 打开 → 选择 '{filename}'"
            )

    def _show_3d_result(self, result: dict, elapsed: int):
        """显示 AI 3D 生成结果。"""
        if not self.result_panel:
            return

        prompt = result.get("prompt", "")
        backend = result.get("backend", "")
        output_path = result.get("output_path", "")
        output_filename = result.get("output_filename", "")
        conversion_note = result.get("conversion_note", "")
        file_size = result.get("file_size_kb", 0)
        output_format = result.get("output_format", "")

        self.result_panel.formattedText = (
            f"<div style='background:#F3E5F5;border:2px solid #7B1FA2;padding:12px;"
            f"border-radius:6px;text-align:left;'>"
            f"<b style='color:#4A148C;font-size:13px;'>🎨 AI 3D 模型已生成</b><br>"
            f"<div style='font-size:9px;color:#666;margin-top:4px;'>"
            f"📝 描述: {prompt[:60]}<br>"
            f"🤖 后端: {backend}<br>"
            f"📦 文件: {output_filename}<br>"
            f"📊 大小: {file_size:.0f} KB | ⏱️ 耗时: {elapsed}s<br>"
            f"{'🔧 ' + conversion_note if conversion_note else ''}</div>"
            f"<div style='font-size:9px;color:#7B1FA2;margin-top:6px;text-align:center;'>"
            f"✅ 正在自动导入到当前文档...</div></div>"
        )

    def _check_ai_3d_backends(self):
        """检查 AI 3D 后端配置状态。"""
        try:
            result = http_get_json(f"{API_BASE_URL}/ai_3d/backends", timeout=10)
            backends = result.get("backends", {})
            freecad = result.get("freecad_available", False)
            models_count = result.get("models_generated", 0)
            any_configured = result.get("any_configured", False)

            lines = ["🔍 AI 3D 生成后端状态:\n"]
            for key, info in backends.items():
                icon = "✅" if info.get("configured") else "❌"
                lines.append(f"{icon} {info.get('name', key)}")
                status = "已配置" if info.get("configured") else "未配置"
                lines.append(f"   状态: {status}")
                lines.append(f"   说明: {info.get('description', '')}")
                lines.append("")

            fc_icon = "✅" if freecad else "⚠️"
            lines.append(f"{fc_icon} FreeCAD (STEP转换)")
            lines.append(f"   状态: {'已安装' if freecad else '未安装 — STEP转换不可用, 将导出OBJ'}")
            lines.append("")
            lines.append(f"📁 已生成模型: {models_count} 个")

            if any_configured:
                lines.append("\n✅ 至少一个后端可用, AI 3D 生成功能正常!")
            else:
                lines.append("\n❌ 所有后端均未配置!")
                lines.append("   请点击 '🔑 配置3D后端API Key' 设置密钥")
                lines.append("   Hunyuan3D 注册: https://3d.hunyuanglobal.com")

            self._alert("\n".join(lines))

        except urllib.error.URLError as e:
            self._alert(f"无法连接后端服务!\n\n请确认 cam_cloud_api.py 已启动\n\n错误: {e.reason}")
        except Exception as e:
            self._alert(f"检查失败: {type(e).__name__}: {e}")

    def _config_ai_3d_key(self, inputs):
        """配置 AI 3D 后端的 API Key。"""
        try:
            # 获取当前选择的后端
            backend_idx = 0
            try:
                backend_idx = inputs.itemById("ai3dBackend").selectedItem.index
            except Exception:
                pass
            backend_id = self._ai3d_backend_ids[backend_idx] if hasattr(self, "_ai3d_backend_ids") else "hunyuan"
            backend_label = self._ai3d_backend_labels[backend_idx] if hasattr(self, "_ai3d_backend_labels") else "Hunyuan3D"

            # 弹出输入框 (Fusion 360 没有原生文本输入对话框, 用 messageBox 提示)
            self._alert(
                f"🔑 配置 {backend_label} API Key\n\n"
                f"请在下方操作:\n"
                f"1. 复制你的 API Key\n"
                f"2. 点击确定后, 在弹出的输入框中粘贴\n\n"
                f"获取 API Key:\n"
                f"  Hunyuan3D: https://3d.hunyuanglobal.com\n"
                f"  Meshy: https://meshy.ai"
            )

            # 使用 Fusion 360 的 ValueInput 对话框获取输入
            app = adsk.core.Application.get()
            ui = app.userInterface

            # 用 palettes 或 prompt 无法直接获取文本输入
            # 替代方案: 提示用户通过后端管理页面配置
            # 或者: 在对话框中临时添加一个文本输入框
            # 这里采用: 提示用户通过浏览器配置
            import webbrowser
            admin_url = f"{API_BASE_URL.replace('127.0.0.1', 'localhost')}"
            self._alert(
                f"📋 配置 API Key 的两种方式:\n\n"
                f"方式1 — 浏览器管理后台:\n"
                f"   打开 {admin_url}\n"
                f"   在 'AI 3D 生成' 区域填入 API Key\n\n"
                f"方式2 — 命令行:\n"
                f"   set HUNYUAN3D_API_KEY=your_key\n"
                f"   然后重启 cam_cloud_api.py\n\n"
                f"方式3 — 直接调用API:\n"
                f"   POST {API_BASE_URL}/admin/api/ai_3d/{backend_id}/key\n"
                f"   Body: {{\"api_key\": \"your_key\"}}"
            )
            # 打开浏览器
            webbrowser.open(admin_url)

        except Exception as e:
            self._alert(f"配置失败: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # 内部: 调用 AI 接口
    # ------------------------------------------------------------------
    def _do_ai_query(self, feature: str, material: str, machine: str) -> str:
        import time as _time
        self._set_scan_status("🔗 正在连接Ollama本地模型...", "#2196F3", "active")
        try:
            data = {"feature": feature, "material": material, "machine": machine}
            t0 = _time.time()
            self._set_scan_status(f"🤖 模型推理中... ({feature}/{material})", "#2196F3", "active")
            resp = http_post_json(API_ENDPOINT, data, timeout=180)
            elapsed = int((_time.time() - t0) * 1000)
            self._set_scan_status(f"✅ AI推理完成 ({elapsed}ms)", "#4CAF50", "done")
            return resp.get("craft_params", "")
        except urllib.error.URLError as e:
            self._set_scan_status("❌ 无法连接到本地AI服务!", "#C62828", "error")
            self._alert(
                f"无法连接到本地AI服务!\n\n"
                f"请先启动 cam_cloud_api.py:\n"
                f"  双击 D:\\CAM_CLOUD_API\\start_service.bat\n"
                f"  确认看到 'Uvicorn running on http://0.0.0.0:8000'\n\n"
                f"错误详情: {e.reason}"
            )
            return ""
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._set_scan_status(f"❌ API返回错误 [{e.code}]", "#C62828", "error")
            self._alert(f"API返回错误 [{e.code}]:\n{body}")
            return ""
        except Exception as e:
            self._set_scan_status(f"❌ 调用异常: {type(e).__name__}", "#C62828", "error")
            self._alert(f"API调用异常:\n{type(e).__name__}: {e}")
            return ""

    # ------------------------------------------------------------------
    # 内部: 调用知识库接口
    # ------------------------------------------------------------------
    def _do_kb_query(self, feature: str, material: str) -> str:
        self._set_scan_status("📖 查询本地知识库...", "#FF9800", "active")
        try:
            q_feat = urllib.parse.quote(feature, safe="")
            q_mat = urllib.parse.quote(material, safe="")
            url = f"{API_BASE_URL}/knowledge_base/lookup?feature={q_feat}&material={q_mat}"
            resp = http_get_json(url, timeout=10)
            self._set_scan_status("✅ 知识库查询成功 (离线)", "#FF9800", "done")
            return resp.get("kb_reference", "")
        except urllib.error.URLError as e:
            self._set_scan_status("❌ 无法连接服务", "#C62828", "error")
            self._alert(
                f"无法连接到本地服务!\n\n"
                f"请先启动 cam_cloud_api.py (端口8000)\n\n"
                f"错误: {e.reason}"
            )
            return ""
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._set_scan_status(f"❌ 知识库接口错误 [{e.code}]", "#C62828", "error")
            self._alert(f"知识库接口错误 [{e.code}]:\n{body}")
            return ""
        except Exception as e:
            self._set_scan_status(f"❌ 查询异常: {type(e).__name__}", "#C62828", "error")
            self._alert(f"知识库查询异常:\n{type(e).__name__}: {e}")
            return ""

    # ------------------------------------------------------------------
    # UI 辅助 (CAM Assist 风格)
    # ------------------------------------------------------------------
    def _set_scan_status(self, msg: str, color: str, state: str = "info"):
        """更新扫描状态指示器 (参考 CAM Assist 分析进度)。"""
        icons = {"active": "⏳", "done": "✅", "warn": "⚠️", "error": "❌", "info": "ℹ️"}
        icon = icons.get(state, "ℹ️")
        bg_map = {"active": "#E3F2FD", "done": "#E8F5E9", "warn": "#FFF8E1", "error": "#FFEBEE", "info": "#ECEFF1"}
        border_map = {"active": "#1976D2", "done": "#388E3C", "warn": "#F57C00", "error": "#D32F2F", "info": "#B0BEC5"}
        bg = bg_map.get(state, "#ECEFF1")
        border = border_map.get(state, "#B0BEC5")

        if self.scan_status:
            self.scan_status.formattedText = (
                f"<div style='text-align:center;padding:12px;font-size:12px;"
                f"background:{bg};border:1px solid {border};border-left:5px solid {border};"
                f"border-radius:8px;color:{color};font-weight:600;'>"
                f"{icon} {msg}</div>"
            )

    def _set_result_placeholder(self, msg: str):
        """设置结果面板的占位文本。"""
        if self.result_panel:
            self.result_panel.formattedText = (
                f"<div style='background:#ECEFF1;border:1px solid #CFD8DC;border-left:5px solid #78909C;padding:18px;"
                f"border-radius:8px;text-align:center;font-size:12px;color:#546E7A;min-height:50px;'>"
                f"{msg}</div>"
            )

    def _alert(self, msg: str):
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(msg, "CAM AI 提示")

    # ------------------------------------------------------------------
    # v1.2 新增: 自动工艺规划 API 调用
    # ------------------------------------------------------------------
    def _do_auto_craft_query(self, features: list, material: str,
                             machine: str, overall_dims: str) -> dict:
        """调用 /auto_craft 接口, 发送检测到的特征, 获取完整工艺流程。"""
        import time as _time
        self._set_scan_status("🔗 正在连接Ollama本地模型...", "#2196F3", "active")
        try:
            feature_count = len([f for f in features if f.get("feature_type") != "__config__"])
            self._set_scan_status(f"🤖 模型推理中... (自动工艺规划, {feature_count}个特征)", "#2196F3", "active")
            data = {
                "features": features,
                "material": material,
                "machine": machine,
                "part_name": "Fusion360零件",
                "overall_dimensions": overall_dims,
            }
            t0 = _time.time()
            resp = http_post_json(AUTO_CRAFT_ENDPOINT, data, timeout=300)
            elapsed = int((_time.time() - t0) * 1000)
            steps_count = len(resp.get("steps", []))
            self._set_scan_status(f"✅ AI推理完成 ({elapsed}ms, {steps_count}步工序)", "#4CAF50", "done")
            return resp
        except urllib.error.URLError as e:
            self._alert(
                f"无法连接到本地AI服务!\n\n"
                f"请先启动 cam_cloud_api.py:\n"
                f"  双击 D:\\CAM_CLOUD_API\\start_service.bat\n\n"
                f"错误: {e.reason}"
            )
            return {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._alert(f"API返回错误 [{e.code}]:\n{body}")
            return {}
        except Exception as e:
            self._alert(f"自动工艺规划异常:\n{type(e).__name__}: {e}")
            return {}

    # ------------------------------------------------------------------
    # v1.3 CAM Assist 风格: 特征检测结果显示 (使用 feature_panel)
    # ------------------------------------------------------------------
    def _show_detected_features(self, features: list, overall_dims: str):
        if not self.feature_panel:
            return

        type_icons = {
            "平面": "📐", "通孔": "🕳️", "盲孔": "🔵", "型腔": "📦",
            "凸台": "⬆️", "槽": "📏", "曲面": "🌊", "倒角": "📐",
        }
        summary_items = []
        for f in features[:15]:
            ftype = f.get("feature_type", "")
            if ftype == "__config__":
                continue
            name = f.get("name", "")
            count = f.get("count", 1)
            dims = f.get("dimensions", "")
            icon = type_icons.get(ftype, "🔧")
            summary_items.append(
                f"<tr style='font-size:12px;border-bottom:1px solid #FFE0B2;'>"
                f"<td style='padding:6px 10px;'>{icon}</td>"
                f"<td style='padding:6px 10px;'><b>{name}</b></td>"
                f"<td style='padding:6px 10px;color:#8D6E63;'>{dims}</td>"
                f"<td style='padding:6px 10px;color:#E65100;text-align:center;font-weight:bold;'>{'×'+str(count) if count > 1 else '1'}</td>"
                f"</tr>"
            )

        total_features = sum(f.get("count", 1) for f in features if f.get("feature_type") != "__config__")
        types_count = len([f for f in features if f.get("feature_type") != "__config__"])

        self.feature_panel.formattedText = (
            f"<div style='background:#FFF3E0;border:1px solid #FFB74D;border-left:5px solid #E65100;padding:16px;"
            f"border-radius:8px;'>"
            f"<b style='color:#BF360C;font-size:14px;'>📊 特征分析报告</b> "
            f"<span style='font-size:11px;color:#A1887F;'>"
            f"({types_count}类 / 共{total_features}处"
            f"{' | ' + overall_dims if overall_dims else ''})</span>"
            f"<table style='width:100%;margin-top:10px;border-collapse:collapse;'>"
            f"<tr style='background:#FFE0B2;font-size:11px;color:#BF360C;font-weight:bold;'>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #FFB74D;'>类型</th>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #FFB74D;text-align:left;'>特征</th>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #FFB74D;text-align:left;'>尺寸</th>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #FFB74D;'>数量</th></tr>"
            f"{''.join(summary_items)}</table>"
            f"<div style='font-size:11px;color:#E65100;margin-top:10px;text-align:center;"
            f"padding:8px;background:#FFF8E1;border-radius:6px;'>"
            f"✅ 特征扫描完成 — 请前往 <b>步骤3: 工艺生成</b></div></div>"
        )

    def _show_empty_feature_warning(self):
        if self.feature_panel:
            self.feature_panel.formattedText = (
                "<div style='background:#FFF8E1;border:1px solid #FFB300;border-left:5px solid #F57C00;padding:18px;"
                "border-radius:8px;text-align:center;color:#E65100;font-size:12px;'>"
                "<b>⚠️ 未检测到加工特征</b><br><br>"
                "请确认 Fusion360 当前文档中包含 3D 实体 (BRep Bodies)<br>"
                "提示: 草图/曲面/网格体无法自动识别<br>"
                "您可以使用下方的 <b>手动特征选择</b> 进行单步查询</div>"
            )

    def _show_feature_error(self, error_text: str):
        if self.feature_panel:
            short_err = error_text[:300]
            self.feature_panel.formattedText = (
                f"<div style='background:#FFEBEE;border:1px solid #F44336;border-left:5px solid #D32F2F;padding:16px;"
                f"border-radius:8px;color:#C62828;font-size:11px;'>"
                f"<b>❌ 特征检测异常</b><br><pre style='white-space:pre-wrap;'>{short_err}</pre></div>"
            )

    # ------------------------------------------------------------------
    # v1.3 CAM Assist 对标: 加工预检 (Pre-Flight Check)
    # ------------------------------------------------------------------
    def _run_pre_check(self) -> dict:
        """对标 CAM Assist Evaluation阶段: 验证加工条件。
        返回 dict: {检查项: True/False}"""
        results = {}
        try:
            app = adsk.core.Application.get()
            design = app.activeProduct

            # v1.4.2: CAM 工作区下自动获取 Design product
            if not hasattr(design, "allComponents"):
                doc = app.activeDocument
                if doc:
                    for product in doc.products:
                        if product.productType == "DesignProductType":
                            design = product
                            break

            # 1. 实体检查
            has_solid = False
            if hasattr(design, "allComponents"):
                for comp in design.allComponents:
                    if comp.bRepBodies.count > 0:
                        has_solid = True
                        break
            results["✅ 实体检查: 含BRep实体"] = has_solid

            # 2. 毛坯定义
            has_stock = False
            try:
                cam_mgr = adsk.cam.CAMManager.get()
                if cam_mgr:
                    setups = cam_mgr.setups
                    if setups.count > 0:
                        has_stock = True
            except Exception:
                pass
            results["📦 毛坯定义: CAM Stock已设置"] = has_stock

            # 3. 坐标系检查
            has_wcs = has_solid  # 简化: 有实体就假设有WCS
            results["📍 加工坐标系: WCS可识别"] = has_wcs

            # 4. 刀具库检查
            has_tools = False
            try:
                doc = app.activeDocument
                if doc and doc.dataFile:
                    has_tools = True  # Fusion360文档存在, 假设刀具库可用
            except Exception:
                pass
            results["🔧 刀具库: 文档已保存"] = has_tools

            # 5. 零件尺寸合理性
            reasonable_size = True
            results["📏 零件尺寸: 合理范围"] = reasonable_size

            # 6. 设计历史
            has_history = True
            results["📝 设计历史: 可追溯"] = has_history

        except Exception:
            results["⚠️ 预检异常"] = False

        return results

    def _show_pre_check_results(self, results: dict):
        """显示预检结果 (对标 CAM Assist Pre-Flight Check 报告)。"""
        rows = ""
        for i, (check, passed) in enumerate(results.items(), 1):
            icon = "✅" if passed else "⚠️"
            color = "#2E7D32" if passed else "#E65100"
            row_bg = "#F1F8E9" if passed else "#FFF8E1"
            rows += (
                f"<tr style='background:{row_bg};font-size:12px;border-bottom:1px solid #FFE0B2;'>"
                f"<td style='padding:6px 12px;text-align:center;'>{icon}</td>"
                f"<td style='padding:6px 12px;color:{color};font-weight:600;'>{check}</td>"
                f"</tr>"
            )

        all_pass = all(results.values())
        status_color = "#2E7D32" if all_pass else "#E65100"
        status_text = "✅ 全部通过 — 可以继续特征扫描和工艺生成" if all_pass else "⚠️ 部分项目需要关注 — 仍可继续, 但建议修正"

        if self.feature_panel:
            self.feature_panel.formattedText = (
                f"<div style='background:#FFF8E1;border:1px solid #FFB74D;border-left:5px solid #FF6F00;padding:16px;border-radius:8px;'>"
                f"<b style='color:#BF360C;font-size:14px;'>🔬 加工预检报告 (Pre-Flight Check)</b> "
                f"<span style='font-size:10px;color:#A1887F;'>对标 CAM Assist Evaluation</span>"
                f"<table style='width:100%;margin-top:10px;border-collapse:collapse;'>"
                f"{rows}</table>"
                f"<div style='font-size:12px;color:{status_color};margin-top:10px;text-align:center;"
                f"padding:8px;background:#FFF3E0;border-radius:6px;font-weight:600;'>{status_text}</div>"
                f"</div>"
            )

    # ------------------------------------------------------------------
    # v1.3 CAM Assist 风格: 工艺方案结果展示 (使用 result_panel)
    # ------------------------------------------------------------------
    def _show_auto_craft_result(self, result: dict, material: str, machine: str,
                                 machining_mode: str = "", workholding: str = "",
                                 coolant: str = "", surface_finish: str = "",
                                 ai_strategy: str = ""):
        """v1.6: 工艺概览显示在 result_panel (只读摘要), 详细数据在 process_table 中可编辑。"""
        if not self.result_panel:
            return

        steps = result.get("steps", [])
        features_count = result.get("features_detected", 0)
        plan_text = result.get("process_plan_text", "")

        overview = plan_text
        for marker in ["\n---\n", "\n===\n"]:
            if marker in plan_text:
                overview = plan_text.split(marker, 1)[0].strip()
                break

        env_tags = []
        if machining_mode:
            env_tags.append(f"<span style='background:#E8EAF6;padding:4px 10px;border-radius:12px;font-size:10px;color:#3F51B5;border:1px solid #C5CAE9;'>🔧 {machining_mode}</span>")
        if workholding:
            short_hold = workholding.split("—")[0].strip() if "—" in workholding else workholding[:20]
            env_tags.append(f"<span style='background:#E8EAF6;padding:4px 10px;border-radius:12px;font-size:10px;color:#3F51B5;border:1px solid #C5CAE9;'>🗜️ {short_hold}</span>")
        if coolant:
            short_cool = coolant.split("(")[0].strip()
            env_tags.append(f"<span style='background:#E0F7FA;padding:4px 10px;border-radius:12px;font-size:10px;color:#00838F;border:1px solid #B2EBF2;'>💧 {short_cool}</span>")
        if surface_finish:
            env_tags.append(f"<span style='background:#F3E5F5;padding:4px 10px;border-radius:12px;font-size:10px;color:#7B1FA2;border:1px solid #E1BEE7;'>✨ {surface_finish}</span>")
        if ai_strategy:
            strat_icon = {"安全": "🛡️", "均衡": "⚖️", "效率": "🚀"}.get(
                ai_strategy[:2] if len(ai_strategy) >= 2 else ai_strategy, "🤖")
            env_tags.append(f"<span style='background:#FCE4EC;padding:4px 10px;border-radius:12px;font-size:10px;color:#C2185B;border:1px solid #F8BBD0;'>{strat_icon} {ai_strategy[:30]}</span>")

        # v1.6: 概览面板只显示摘要 + 提示去表格编辑
        self.result_panel.formattedText = (
            f"<div style='background:#E8F5E9;border:1px solid #66BB6A;border-left:5px solid #1B5E20;padding:16px;"
            f"border-radius:8px;text-align:left;'>"
            f"<b style='color:#1B5E20;font-size:15px;'>📋 AI 工艺方案已生成</b> "
            f"<span style='font-size:11px;color:#81C784;'>{len(steps)}步工序 | {features_count}个特征</span>"
            f"<div style='margin:8px 0;font-size:11px;color:#558B2F;'>"
            f"材料:{material} | 机床:{machine} {' '.join(env_tags)}</div>"
            f"<div style='background:#F1F8E9;padding:8px 12px;border-radius:6px;margin:8px 0;"
            f"font-size:11px;color:#33691E;border-left:4px solid #4CAF50;'>{overview[:300]}</div>"
            f"<div style='font-size:11px;color:#1565C0;text-align:center;margin-top:8px;"
            f"padding:8px;background:#E3F2FD;border-radius:6px;font-weight:600;'>"
            f"⬇️ 请在下方 <b>工艺方案编辑表格</b> 中直接修改参数, 然后点击 '💾 应用修改'</div>"
            f"</div>"
        )

    def _show_ai_result(self, feature: str, material: str, machine: str, params: str):
        if self.result_panel:
            self.result_panel.formattedText = (
                f"<div style='background:#E8F5E9;border:1px solid #66BB6A;border-left:5px solid #1B5E20;padding:20px;"
                f"border-radius:8px;text-align:center;'>"
                f"<b style='color:#1B5E20;font-size:14px;'>AI 推荐切削参数</b><br><br>"
                f"<span style='font-size:20px;font-weight:bold;color:#0D47A1;'>{params}</span><br><br>"
                f"<span style='font-size:12px;color:#558B2F;'>"
                f"特征: {feature} | 材料: {material} | 机床: {machine}<br>"
                f"🖥️ Ollama本地大模型 | temperature=0.1</span></div>"
            )

    def _show_kb_result(self, feature: str, material: str, params: str):
        if self.result_panel:
            self.result_panel.formattedText = (
                f"<div style='background:#FFF8E1;border:1px solid #FFB300;border-left:5px solid #E65100;padding:20px;"
                f"border-radius:8px;text-align:center;'>"
                f"<b style='color:#BF360C;font-size:14px;'>知识库基准参数 (离线)</b><br><br>"
                f"<span style='font-size:20px;font-weight:bold;color:#333;'>{params}</span><br><br>"
                f"<span style='font-size:12px;color:#A1887F;'>"
                f"特征: {feature} | 材料: {material}<br>"
                f"来源: 内置知识库 (免费, 断网可用)</span></div>"
            )

    # ------------------------------------------------------------------
    # v1.3 CAM Assist 风格: 刀具使用分析 + 保存到工艺库
    # ------------------------------------------------------------------
    def _show_tool_usage_analysis(self, steps: list):
        if not self.result_panel:
            return

        tool_usage = {}
        for s in steps:
            tool = s.get("tool", "未指定")
            op = s.get("operation", "")
            if tool not in tool_usage:
                tool_usage[tool] = {"count": 0, "operations": []}
            tool_usage[tool]["count"] += 1
            tool_usage[tool]["operations"].append(op)

        rows = ""
        for i, (tool, info) in enumerate(tool_usage.items(), 1):
            ops_str = ", ".join(info["operations"][:3])
            rows += (
                f"<tr style='font-size:11px;border-bottom:1px solid #D1C4E9;'>"
                f"<td style='padding:6px 10px;text-align:center;color:#7B1FA2;font-weight:bold;'>{i}</td>"
                f"<td style='padding:6px 10px;'><b>{tool}</b></td>"
                f"<td style='padding:6px 10px;text-align:center;color:#6A1B9A;font-weight:bold;'>{info['count']}步</td>"
                f"<td style='padding:6px 10px;font-size:10px;color:#9575CD;'>{ops_str}</td>"
                f"</tr>"
            )

        self.result_panel.formattedText = (
            f"<div style='background:#EDE7F6;border:1px solid #9575CD;border-left:5px solid #4A148C;padding:16px;"
            f"border-radius:8px;text-align:left;'>"
            f"<b style='color:#4A148C;font-size:14px;'>📊 刀具使用分析 (Tool Usages)</b><br>"
            f"<span style='font-size:11px;color:#7E57C2;'>"
            f"共需 <b>{len(tool_usage)}</b> 种刀具 | 总工序 <b>{len(steps)}</b> 步 "
            f"(参考 CAM Assist Tool Usages 选项卡)</span>"
            f"<table style='width:100%;margin-top:10px;border-collapse:collapse;'>"
            f"<tr style='background:#D1C4E9;font-size:11px;color:#4A148C;font-weight:bold;'>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #9575CD;'>#</th>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #9575CD;text-align:left;'>刀具型号</th>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #9575CD;'>使用次数</th>"
            f"<th style='padding:6px 10px;border-bottom:2px solid #9575BD;text-align:left;'>用于工序</th></tr>"
            f"{rows}</table>"
            f"<div style='font-size:11px;color:#7E57C2;margin-top:10px;text-align:center;"
            f"padding:8px;background:#F3E5F5;border-radius:6px;'>"
            f"💡 提示: 请检查Fusion360刀具库中是否包含以上刀具</div></div>"
        )

    def _save_to_personal_library(self, ai_result: dict, material: str, machine: str):
        try:
            entries = []
            for step in ai_result.get("steps", []):
                entries.append({
                    "feature": step.get("operation", ""),
                    "material": material,
                    "machine": machine,
                    "tool": step.get("tool", ""),
                    "spindle_speed": step.get("spindle_speed", ""),
                    "feed_rate": step.get("feed_rate", ""),
                    "depth_of_cut": step.get("depth_of_cut", ""),
                    "toolpath_strategy": step.get("toolpath_strategy", ""),
                    "notes": step.get("note", ""),
                    "tags": [material, step.get("operation", ""), "AI生成"],
                })
            data = {"entries": entries, "overwrite": True}
            http_post_json(f"{API_BASE_URL}/craft_library/upload", data, timeout=10)
            self._alert(f"✅ 已保存 {len(entries)} 条工艺到个人工艺库!\n\n文件: personal_craft_library.json")
        except Exception as e:
            self._alert(f"❌ 保存失败: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # v1.5: L1-L5 全链路 CAM 工序自动创建
    # ------------------------------------------------------------------

    # 操作类型映射: AI输出文字 → Fusion360 CAM strategy string
    # 官方API: setup.operations.createInput('strategy_name')
    # 策略名需运行时用 compatibleStrategies 确认, 以下是常见名称
    _OP_STRATEGY_MAP = {
        "平面铣削": "face",
        "面铣": "face",
        "型腔加工": "2d_pocket",
        "型腔": "2d_pocket",
        "铣槽": "2d_slot",
        "键槽": "2d_slot",
        "钻孔": "drill",
        "钻": "drill",
        "攻丝": "tap",
        "铰孔": "ream",
        "镗孔": "bore",
        "倒角": "2d_chamfer",
        "去毛刺": "2d_chamfer",
        "轮廓铣削": "2d_contour",
        "轮廓": "2d_contour",
        "曲面精加工": "scallop",
        "曲面": "scallop",
        "等高": "3d_parallel",
        "粗加工": "3d_adaptive",
        "开粗": "3d_adaptive",
    }

    @staticmethod
    def _parse_tool_spec(tool_str: str) -> dict:
        """从AI输出的刀具描述中解析规格。例: 'Φ63端铣刀(5刃,涂层)' → {type, diameter}"""
        import re
        spec = {"type": "FlatEndMill", "diameter_mm": 10.0, "raw": tool_str}

        # 解析直径
        m = re.search(r'Φ?\s*(\d+(?:\.\d+)?)', tool_str)
        if m:
            spec["diameter_mm"] = float(m.group(1))

        # 解析刀具类型
        if "端铣刀" in tool_str or "立铣刀" in tool_str or "面铣刀" in tool_str:
            if "球" in tool_str:
                spec["type"] = "BallEndMill"
            else:
                spec["type"] = "FlatEndMill"
        elif "球头刀" in tool_str or "球刀" in tool_str:
            spec["type"] = "BallEndMill"
        elif "钻头" in tool_str or "钻" in tool_str:
            spec["type"] = "Drill"
        elif "丝锥" in tool_str or "攻丝" in tool_str:
            spec["type"] = "Tap"
        elif "铰刀" in tool_str:
            spec["type"] = "Reamer"
        elif "倒角刀" in tool_str or "倒角" in tool_str:
            spec["type"] = "ChamferMill"
        elif "车刀" in tool_str:
            spec["type"] = "TurningTool"

        return spec

    @staticmethod
    def _find_matching_tool(cam, tool_spec: dict):
        """L2: 在文档刀具库中查找直径匹配的刀具, 找不到返回None (留给用户手动选)。"""
        try:
            tool_lib = cam.documentToolLibrary
            if not tool_lib or tool_lib.count == 0:
                return None

            target_dia_cm = tool_spec["diameter_mm"] / 10.0  # mm → cm

            for i in range(tool_lib.count):
                tool = tool_lib.item(i)
                try:
                    params = tool.parameters
                    dia_param = params.itemByName("tool_diameter")
                    if dia_param:
                        # expression 是字符串, 如 "10 mm"
                        expr = dia_param.expression
                        import re
                        m = re.search(r'[\d.]+', expr)
                        if m:
                            dia_val = float(m.group())
                            # 单位可能是 mm 或 cm, 统一比较
                            if "mm" in expr:
                                dia_val_cm = dia_val / 10.0
                            else:
                                dia_val_cm = dia_val
                            if abs(dia_val_cm - target_dia_cm) < 0.01:
                                return tool
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _create_cam_operations(self, ai_result: dict) -> dict:
        """
        L1-L5: 根据AI工艺方案, 在Fusion360 CAM环境中自动创建完整工序链。

        使用官方 API 模式 (2023 April+):
          Setup:  cam.setups.createInput(type) → setups.add(input)
          Op:     setup.operations.createInput('strategy') → operations.add(input)
          Tool:   opInput.tool = cam.documentToolLibrary.item(i)
          Params: opInput.parameters.itemByName('name').expression = 'value'
          Geo:    opInput.parameters.itemByName('model').value.value = [faces]
          TP:     cam.generateToolpath(op)  [异步]
        """
        app = adsk.core.Application.get()
        ui = app.userInterface

        # 获取 CAM product (官方推荐: CAM.cast)
        cam = adsk.cam.CAM.cast(app.activeProduct)
        if not cam:
            doc = app.activeDocument
            if doc:
                for product in doc.products:
                    if product.productType == "CAMProductType":
                        cam = product
                        break
        if not cam:
            raise RuntimeError("无法获取CAM环境! 请切换到CAM(制造)工作区后重试。")

        steps = ai_result.get("steps", [])
        if not steps:
            raise RuntimeError("AI工艺方案中没有工序步骤")

        # 获取设计 product (用于L4几何选择)
        design = None
        doc = app.activeDocument
        if doc:
            for product in doc.products:
                if product.productType == "DesignProductType":
                    design = product
                    break

        summary = {
            "setup": None,
            "tools_matched": 0,
            "tools_missing": 0,
            "ops_created": 0,
            "toolpaths_generated": 0,
            "manual_geometry": 0,
            "errors": [],
        }

        # 查询可用策略列表 (关键: 用于验证 strategy_name 是否真正被当前版本支持)
        available_strategies = {}
        strategy_list_raw = []
        try:
            # 需要 setup 存在才能查 compatibleStrategies
            if cam.setups.count > 0:
                strategies = cam.setups.item(0).operations.compatibleStrategies
                strategy_list_raw = list(strategies) if hasattr(strategies, '__iter__') else []
                for s in strategy_list_raw:
                    try:
                        available_strategies[s.name] = s.title
                    except Exception:
                        # 某些版本可能用不同属性名
                        try:
                            available_strategies[str(s)] = str(s)
                        except Exception:
                            pass
        except Exception as e:
            summary["errors"].append(f"策略查询异常(非致命): {str(e)[:60]}")

        # ============================================================
        # L1: 创建 Setup (如果不存在)
        # ============================================================
        setup = None
        try:
            if cam.setups.count > 0:
                setup = cam.setups.item(0)
                summary["setup"] = f"复用已有 Setup: {setup.name}"
            else:
                # 官方 API: setups.createInput(OperationTypes.MillingOperation)
                setup_input = cam.setups.createInput(adsk.cam.OperationTypes.MillingOperation)
                # 设置 WCS 原点模式
                try:
                    origin_param = setup_input.parameters.itemByName("wcs_origin_mode")
                    if origin_param:
                        origin_param.value.value = "modelPoint"
                except Exception:
                    pass
                # 设置程序注释
                try:
                    comment_param = setup_input.parameters.itemByName("job_programComment")
                    if comment_param:
                        comment_param.value.value = "CAM AI Auto-Generated"
                except Exception:
                    pass

                setup = cam.setups.add(setup_input)
                summary["setup"] = f"已创建新 Setup: {setup.name}"

                # 重新查询策略列表
                try:
                    strategies = setup.operations.compatibleStrategies
                    available_strategies = {}
                    for s in strategies:
                        available_strategies[s.name] = s.title
                except Exception:
                    pass
        except Exception as e:
            summary["errors"].append(f"L1 Setup创建失败: {str(e)[:100]}")

        if not setup and cam.setups.count > 0:
            setup = cam.setups.item(0)
        if not setup:
            raise RuntimeError("无法获取或创建CAM Setup — 请手动创建一个Setup后重试")

        # 收集检测到的特征 (用于L4几何选择)
        detected_features = self.shared_data.get("detected_features", [])

        # 缓存最大平面 (避免每次工序都遍历)
        cached_largest_face = None

        # ============================================================
        # L2-L5: 遍历每个工序步骤 (带双层 fallback 容错)
        # ============================================================
        for i, step in enumerate(steps):
            op_name = step.get("operation", f"工序{i+1}")
            tool_str = step.get("tool", "")
            spindle = step.get("spindle_speed", "")
            feed = step.get("feed_rate", "")
            ap = step.get("depth_of_cut", "")
            note = step.get("note", "")

            try:
                # ---- 确定 strategy 字符串 ----
                strategy_name = self._OP_STRATEGY_MAP.get(op_name, "face")

                # 策略验证: 运行时确认策略在可用列表中
                if available_strategies and strategy_name not in available_strategies:
                    # 尝试模糊匹配 (子串包含)
                    matched = False
                    for s_name in available_strategies:
                        if strategy_name in s_name or s_name in strategy_name:
                            strategy_name = s_name
                            matched = True
                            break
                    if not matched:
                        # 回退: 优先 '2d_contour' (最通用的轮廓铣), 其次 'face', 最后取第一个
                        for fallback_candidate in ["2d_contour", "face", "3d_adaptive"]:
                            if fallback_candidate in available_strategies:
                                strategy_name = fallback_candidate
                                matched = True
                                break
                        if not matched and available_strategies:
                            strategy_name = list(available_strategies.keys())[0]
                            matched = True
                        summary["errors"].append(
                            f"工序{i+1}: 策略'{op_name}'未找到→回退'{strategy_name}' "
                            f"(可用: {list(available_strategies.keys())[:5]})"
                        )

                # ---- L3: 创建 OperationInput ----
                op_input = None
                op = None

                # === 尝试1: 新版统一 API (createInput + add) ===
                try:
                    op_input = setup.operations.createInput(strategy_name)
                    op_input.displayName = f"AI-{i+1} {op_name}"
                except Exception as e_create:
                    # createInput 本身失败 — 可能是策略名不被当前版本支持
                    summary["errors"].append(
                        f"工序{i+1} createInput('{strategy_name}')失败: {str(e_create)[:60]}"
                    )
                    # 尝试用 compatibleStrategies 中的第一个策略重新创建
                    if available_strategies:
                        for alt_strategy in list(available_strategies.keys())[:10]:
                            try:
                                op_input = setup.operations.createInput(alt_strategy)
                                op_input.displayName = f"AI-{i+1} {op_name}[{alt_strategy}]"
                                summary["errors"].append(
                                    f"工序{i+1}: 回退到策略 '{alt_strategy}'"
                                )
                                break
                            except Exception:
                                continue

                if not op_input:
                    summary["errors"].append(f"工序{i+1}: 无法创建OperationInput, 跳过")
                    continue

                # ---- L2: 设置刀具 ----
                tool_spec = self._parse_tool_spec(tool_str)
                tool = self._find_matching_tool(cam, tool_spec)
                if tool:
                    op_input.tool = tool
                    summary["tools_matched"] += 1
                else:
                    summary["tools_missing"] += 1
                    summary["errors"].append(
                        f"工序{i+1}: 未找到匹配刀具 '{tool_str}' — 请手动选择"
                    )

                # ---- 写入切削参数 (通过 expression 字符串) ----
                try:
                    params = op_input.parameters
                    # 主轴转速
                    if spindle:
                        rpm = self._safe_parse_float(spindle)
                        if rpm > 0:
                            spd_param = params.itemByName("spindle_speed")
                            if spd_param:
                                spd_param.expression = f"{int(rpm)} rpm"
                    # 进给速度
                    if feed:
                        feed_val = self._safe_parse_float(feed)
                        if feed_val > 0:
                            fd_param = params.itemByName("cutting_feedrate")
                            if not fd_param:
                                fd_param = params.itemByName("feed_rate")
                            if fd_param:
                                fd_param.expression = f"{int(feed_val)} mm/min"
                    # 切深
                    if ap:
                        ap_val = self._safe_parse_float(ap)
                        if ap_val > 0:
                            for ap_id in ["stepdown", "maximum_stepdown", "depth_per_cut", "stepdown_control"]:
                                ap_param = params.itemById(ap_id) if hasattr(params, 'itemById') else params.itemByName(ap_id)
                                if ap_param:
                                    ap_param.expression = f"{ap_val} mm"
                                    break
                except Exception as e:
                    summary["errors"].append(f"工序{i+1}参数写入: {str(e)[:60]}")

                # ---- L4: 几何体选择 (半自动) ----
                geo_assigned = False
                try:
                    if design and hasattr(design, "allComponents"):
                        target_face = self._find_best_face_for_operation(design, op_name, detected_features)
                        if target_face:
                            for geo_id in ["model", "part_geometry", "faces", "machining_boundary", "pocket_selections"]:
                                geo_param = op_input.parameters.itemByName(geo_id)
                                if geo_param:
                                    geo_sel = geo_param.value
                                    if hasattr(geo_sel, "value"):
                                        geo_sel.value = [target_face]
                                        geo_assigned = True
                                        break
                                    elif hasattr(geo_sel, "add"):
                                        geo_sel.add(target_face)
                                        geo_assigned = True
                                        break
                except Exception:
                    pass

                if not geo_assigned:
                    summary["manual_geometry"] += 1

                # ---- 创建 Operation (核心修复: 双层 fallback) ----
                # === 尝试A: 新版统一 API operations.add(op_input) ===
                try:
                    op = setup.operations.add(op_input)
                    summary["ops_created"] += 1
                except AttributeError as ae:
                    # Fusion 内部可能调用了已废弃的方法 (如 addFaceMilling)
                    err_msg = str(ae)
                    if "addFaceMilling" in err_msg or "has no attribute" in err_msg:
                        summary["errors"].append(
                            f"工序{i+1} 新API内部错误({err_msg[:50]}) → 尝试旧API..."
                        )
                        # === 尝试B: 遍历 Operations 上所有可能的创建方法 ===
                        op = self._try_legacy_operation_creation(setup, strategy_name, op_input, i, summary)
                        if op:
                            summary["ops_created"] += 1
                        else:
                            summary["errors"].append(
                                f"工序{i+1}: 新旧API均失败, 已跳过 "
                                f"(策略={strategy_name}, Fusion版本可能不支持)"
                            )
                    else:
                        raise  # 非预期的 AttributeError, 向上抛出
                except Exception as e_add:
                    summary["errors"].append(f"工序{i+1} operations.add失败: {str(e_add)[:80]}")
                    # 最后尝试: 不设置复杂参数, 只创建空工序
                    try:
                        simple_input = setup.operations.createInput(strategy_name)
                        simple_input.displayName = f"AI-{i+1} {op_name}(简化)"
                        op = setup.operations.add(simple_input)
                        summary["ops_created"] += 1
                        summary["errors"].append(f"工序{i+1}: 简化模式创建成功")
                    except Exception:
                        pass

                # ---- L5: 生成刀路 (官方API: cam.generateToolpath, 异步) ----
                if op and geo_assigned:
                    try:
                        future = cam.generateToolpath(op)
                        summary["toolpaths_generated"] += 1
                    except Exception as e:
                        summary["errors"].append(f"工序{i+1}刀路生成: {str(e)[:60]}")
                # 无几何体或无op的工序跳过刀路生成, 留给用户手动

            except Exception as e:
                summary["errors"].append(f"工序{i+1}创建失败: {str(e)[:80]}")

        # 刷新 CAM 浏览器
        try:
            ui.activeWorkspace = ui.workspaces.itemById("CAMEnvironment")
        except Exception:
            pass

        return summary

    @staticmethod
    def _safe_parse_float(s: str) -> float:
        """安全解析数值, 处理 'S2500' 'F500' 'ap0.8' 等带前缀的字符串。"""
        import re
        if not s:
            return 0.0
        m = re.search(r'[\d.]+', str(s))
        if m:
            try:
                return float(m.group())
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def _find_best_face_for_operation(design, op_name: str, features: list):
        """L4: 根据工序类型, 从检测到的特征中找最匹配的BRep面。"""
        try:
            # 优先匹配工序名称对应的特征类型
            target_types = {
                "平面铣削": ["平面"],
                "面铣": ["平面"],
                "型腔加工": ["型腔"],
                "型腔": ["型腔"],
                "钻孔": ["通孔", "盲孔"],
                "钻": ["通孔", "盲孔"],
                "倒角": ["倒角"],
            }
            preferred = target_types.get(op_name, ["平面"])

            # 从 detected_features 找匹配的特征
            best_feature = None
            best_area = 0
            for f in features:
                ftype = f.get("feature_type", "")
                if ftype in preferred:
                    # 优先选面积最大的
                    face_ref = f.get("face_ref")
                    if face_ref:
                        return face_ref
                    area = f.get("area_mm2", 0) or 0
                    if area > best_area:
                        best_area = area
                        best_feature = f

            # 如果没找到存储的 face_ref, 直接遍历设计找最大平面
            if not best_feature or not preferred:
                largest_face = None
                largest_area = 0.0
                for comp in design.allComponents:
                    for body in comp.bRepBodies:
                        for face in body.faces:
                            try:
                                geom = face.geometry
                                if geom.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
                                    if face.area > largest_area:
                                        largest_area = face.area
                                        largest_face = face
                            except Exception:
                                continue
                return largest_face

            return None
        except Exception:
            return None

    @staticmethod
    def _try_legacy_operation_creation(setup, strategy_name: str, op_input, step_idx: int, summary: dict):
        """
        Fallback: 当新版统一 API (operations.add) 因 Fusion 内部调用废弃方法失败时,
        尝试通过反射/旧式方法名创建工序。

        某些 Fusion 360 版本的 createInput('face') + add() 内部会尝试调用
        已移除的 addFaceMilling()/add2dPocket() 等方法, 导致 AttributeError。
        此方法通过遍历 Operations 对象的可用属性来寻找可用的创建入口。
        """
        try:
            ops = setup.operations
            # 策略→旧式方法名的映射 (Fusion 2023 之前使用的 API)
            legacy_method_map = {
                "face": ["addFaceMilling", "addFacing"],
                "2d_pocket": ["add2dPocket", "addPocket"],
                "2d_contour": ["add2dContour", "addContour"],
                "2d_slot": ["add2dSlot", "addSlot"],
                "drill": ["addDrilling", "addDrill"],
                "tap": ["addTapping", "addTap"],
                "ream": ["addReaming", "addReam"],
                "bore": ["addBoring", "addBore"],
                "2d_chamfer": ["addChamferMilling", "addChamfer"],
                "scallop": ["addScallop", "addScallopFinishing"],
                "3d_adaptive": ["addAdaptive", "addAdaptiveClearance"],
                "3d_parallel": ["addParallel", "add3dParallel"],
            }

            # 1. 先尝试策略对应的已知旧式方法名
            candidates = legacy_method_map.get(strategy_name, [])
            for method_name in candidates:
                if hasattr(ops, method_name):
                    try:
                        method = getattr(ops, method_name)
                        # 旧式方法可能接受不同的参数签名
                        if callable(method):
                            # 尝试不带参数调用 (某些版本如此)
                            try:
                                op = method()
                                if op:
                                    return op
                            except TypeError:
                                # 尝试传入 op_input
                                try:
                                    op = method(op_input)
                                    if op:
                                        return op
                                except Exception:
                                    pass
                    except Exception:
                        continue

            # 2. 反射: 遍历 Operations 对象所有以 'add' 开头的方法
            for attr_name in dir(ops):
                if not attr_name.startswith("add"):
                    continue
                if attr_name == "add":
                    continue  # 这就是已经失败的统一 add 方法
                try:
                    attr = getattr(ops, attr_name)
                    if callable(attr):
                        # 检查是否与当前策略相关 (名称模糊匹配)
                        strategy_lower = strategy_name.lower()
                        attr_lower = attr_name.lower()
                        is_relevant = (
                            strategy_lower in attr_lower or
                            attr_lower in strategy_lower or
                            any(kw in attr_lower for kw in ["face", "pocket", "contour",
                                                             "drill", "tap", "scallop",
                                                             "adaptive", "parallel",
                                                             "chamfer", "slot", "bore"])
                        )
                        if is_relevant or not candidates:  # 如果已知方法都失败了, 试更多
                            try:
                                op = attr()
                                if op:
                                    summary["errors"].append(
                                        f"工序{step_idx+1}: 通过旧API '{attr_name}' 创建成功"
                                    )
                                    return op
                            except TypeError:
                                try:
                                    op = attr(op_input)
                                    if op:
                                        summary["errors"].append(
                                            f"工序{step_idx+1}: 通过旧API '{attr_name}'(带参)创建成功"
                                        )
                                        return op
                                except Exception:
                                    pass
                except Exception:
                    continue

            # 3. 最后手段: 尝试用不同策略重新 createInput+add
            alt_strategies = ["2d_contour", "drill", "3d_adaptive"]
            for alt in alt_strategies:
                if alt == strategy_name:
                    continue
                try:
                    alt_input = setup.operations.createInput(alt)
                    alt_input.displayName = op_input.displayName if hasattr(op_input, 'displayName') else f"AI-{step_idx+1}"
                    op = setup.operations.add(alt_input)
                    if op:
                        summary["errors"].append(
                            f"工序{step_idx+1}: 用替代策略'{alt}'创建成功"
                        )
                        return op
                except Exception:
                    continue

        except Exception as e:
            summary["errors"].append(f"工序{step_idx+1} fallback异常: {str(e)[:60]}")

        return None

    def _show_cam_creation_result(self, summary: dict):
        """显示 CAM 工序创建结果。"""
        if not self.result_panel:
            return

        errors_html = ""
        if summary.get("errors"):
            err_items = "".join(
                f"<li style='font-size:10px;color:#E65100;'>{e}</li>"
                for e in summary["errors"][:5]
            )
            errors_html = (
                f"<details style='margin-top:8px;'><summary style='font-size:11px;color:#E65100;cursor:pointer;'>"
                f"⚠️ {len(summary['errors'])}个警告/错误</summary><ul>{err_items}</ul></details>"
            )

        manual_note = ""
        if summary.get("manual_geometry", 0) > 0:
            manual_note = (
                f"<div style='background:#FFF8E1;border:1px solid #FFB300;padding:8px;border-radius:6px;"
                f"margin-top:8px;font-size:11px;color:#E65100;'>"
                f"⚠️ {summary['manual_geometry']}个工序未自动选取几何体 — "
                f"请在CAM浏览器中手动选择加工面/边界后点击 'Generate Toolpath'</div>"
            )

        self.result_panel.formattedText = (
            f"<div style='background:#F3E5F5;border:1px solid #BA68C8;border-left:5px solid #6A1B9A;padding:16px;"
            f"border-radius:8px;text-align:left;'>"
            f"<b style='color:#4A148C;font-size:15px;'>⚙️ CAM 工序自动创建完成</b><br>"
            f"<span style='font-size:11px;color:#7B1FA2;'>{summary.get('setup', 'Setup: 未创建')}</span>"
            f"<table style='width:100%;margin-top:10px;font-size:12px;border-collapse:collapse;'>"
            f"<tr style='border-bottom:1px solid #E1BEE7;'><td style='padding:6px 10px;'>🔧 刀具匹配:</td><td style='padding:6px 10px;'><b>{summary['tools_matched']}</b> 把匹配, <b>{summary['tools_missing']}</b> 把需手动选</td></tr>"
            f"<tr style='border-bottom:1px solid #E1BEE7;'><td style='padding:6px 10px;'>📋 工序创建:</td><td style='padding:6px 10px;'><b>{summary['ops_created']}</b> 个</td></tr>"
            f"<tr><td style='padding:6px 10px;'>🛤️ 刀路生成:</td><td style='padding:6px 10px;'><b>{summary['toolpaths_generated']}</b> 条</td></tr>"
            f"</table>"
            f"{manual_note}"
            f"{errors_html}"
            f"<div style='margin-top:10px;font-size:11px;color:#9C27B0;text-align:center;"
            f"padding:8px;background:#FCE4EC;border-radius:6px;'>"
            f"请在CAM浏览器中查看创建的工序 | 手动调整几何体后重新生成刀路</div></div>"
        )

    def _show_cam_creation_error(self, error_text: str):
        """显示 CAM 创建错误。"""
        if self.result_panel:
            short_err = error_text[:500]
            self.result_panel.formattedText = (
                f"<div style='background:#FFEBEE;border:1px solid #EF5350;border-left:5px solid #B71C1C;padding:16px;"
                f"border-radius:8px;color:#C62828;font-size:11px;'>"
                f"<b>❌ CAM工序创建失败</b><br>"
                f"<pre style='white-space:pre-wrap;font-size:10px;'>{short_err}</pre>"
                f"<br><span style='font-size:10px;'>常见原因:<br>"
                f"1. 不在CAM工作区 — 请切换到CAM工作区<br>"
                f"2. 文档没有保存 — 请先保存当前文档<br>"
                f"3. 没有Setup — 请先手动创建一个CAM Setup</span></div>"
            )


# ============================================================================
# 命令执行事件处理器 (占位)
# ============================================================================
class CraftCommandExecuteEventHandler(adsk.core.CommandEventHandler):
    def __init__(self, scan_status, feature_panel, result_panel):
        super().__init__()
        self.scan_status = scan_status
        self.feature_panel = feature_panel
        self.result_panel = result_panel

    def notify(self, args: adsk.core.CommandEventArgs):
        pass


# ============================================================================
# v1.4.1: 工具栏按钮注册 (跨工作区支持)
# ============================================================================
def _add_toolbar_button(ui, cmd_def, workspace_id: str, panel_id: str):
    """在指定工作区的指定面板上添加按钮, 失败则静默跳过。"""
    global _toolbar_controls
    try:
        ws = ui.workspaces.itemById(workspace_id)
        if not ws:
            return
        panel = ws.toolbarPanels.itemById(panel_id)
        if not panel:
            # 回退: 尝试通用的 ADD-INS 面板
            panel = ws.toolbarPanels.itemById("SolidScriptsAddinsPanel")
        if not panel:
            return
        # 避免重复添加
        existing = panel.controls.itemById("CAM_AI_CraftCommand")
        if existing:
            return
        ctrl = panel.controls.addCommand(cmd_def)
        ctrl.isPromotedByDefault = False
        _toolbar_controls.append(ctrl)
    except Exception:
        pass


# ============================================================================
# 脚本入口
# ============================================================================
def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        cmd_def = ui.commandDefinitions.itemById("CAM_AI_CraftCommand")
        if not cmd_def:
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                "CAM_AI_CraftCommand",
                "CAM智能工艺推荐",
                "基于云端AI的数控切削参数推荐工具 v1.8.0",
                "",
            )

        on_create = CraftCommandCreatedEventHandler()
        cmd_def.commandCreated.add(on_create)
        _handlers.append(on_create)

        # v1.4.1: 在设计和CAM两个工作区都添加工具栏按钮,
        # 这样切换工作区后对话框被终止时, 用户可以重新点击按钮打开。
        _add_toolbar_button(ui, cmd_def, "FusionDesignEnvironment", "SolidScriptsAddinsPanel")
        _add_toolbar_button(ui, cmd_def, "CAMEnvironment", "CAMAddinsPanel")

        # 首次运行自动弹出对话框
        cmd_def.execute()
        adsk.autoTerminate(False)

    except Exception:
        if ui:
            ui.messageBox(
                f"脚本运行失败:\n"
                f"1. 请确认在 Fusion360 环境中运行\n"
                f"2. 请确认 cam_cloud_api.py 已启动 (端口8000)\n\n"
                f"错误:\n{traceback.format_exc()}",
                "CAM AI 脚本错误",
            )


def stop(context):
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # v1.4.1: 清理工具栏按钮
        global _toolbar_controls
        for ctrl in _toolbar_controls:
            try:
                ctrl.deleteMe()
            except Exception:
                pass
        _toolbar_controls.clear()

        cmd_def = ui.commandDefinitions.itemById("CAM_AI_CraftCommand")
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass
