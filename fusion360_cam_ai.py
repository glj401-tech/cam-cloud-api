"""
================================================================================
 Fusion360_CAM_AI_Script.py — Fusion360 内置 Python 脚本
 功能: 弹窗选择加工特征/材料/机床 → 调用本地8000端口API → 弹窗展示AI推荐工艺参数
 使用方法:
   1. 在 Fusion360 中: 工具 → 脚本与附加模块 → 新建Python脚本 → 粘贴本文件全部内容
   2. 保存后点击"运行"
   3. 在弹出对话框中选择参数 → 点击"查询工艺参数"
   4. 结果自动弹窗显示
 前提条件: cam_cloud_api.py 服务已在后台运行 (端口8000)
 作者: CAM_AI_System
 日期: 2026-06-13
 版本: 1.0.0
 许可证: MIT License
 仓库: https://github.com/your-org/cam-cloud-api
================================================================================
"""

__version__ = "1.0.0"
__author__ = "CAM_AI_System"
__license__ = "MIT"

import traceback
import json
import urllib.request
import urllib.error

# Fusion360 专用模块 (在Fusion360内置Python环境中可用)
import adsk.core
import adsk.fusion
import adsk.cam

# ============================================================================
# 全局变量
# ============================================================================
# 本地API服务地址
API_BASE_URL = "http://127.0.0.1:8000"
API_ENDPOINT = f"{API_BASE_URL}/get_craft"

# 保存事件处理器引用 (防止被Python GC回收导致事件失效)
_handlers = []

# 加工特征选项 (与后端知识库同步)
FEATURE_OPTIONS = [
    "平面铣削",
    "型腔加工",
    "键槽加工",
    "钻孔",
    "攻丝",
    "曲面精加工",
]

# 材料选项
MATERIAL_OPTIONS = [
    "6061铝",
    "45#钢",
    "304不锈钢",
    "H62黄铜",
]

# 机床选项
MACHINE_OPTIONS = [
    "三轴立式加工中心",
    "数控铣床",
    "钻攻中心",
    "五轴加工中心",
    "龙门铣床",
]


# ============================================================================
# 命令创建事件处理器 (构建对话框UI)
# ============================================================================
class CraftCommandCreatedEventHandler(adsk.core.CommandCreatedEventHandler):
    """当用户运行脚本命令时触发, 负责构建对话框界面。"""

    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            cmd = args.command
            cmd.isOKButtonVisible = False   # 使用自定义按钮
            cmd.isCancelButtonVisible = True

            inputs = cmd.commandInputs

            # ---- 标题文本 ----
            title_input = inputs.addTextBoxCommandInput(
                "titleText", "Fusion360 CAM 智能工艺推荐",
                "<div align='center' style='font-size:14px;font-weight:bold;padding:8px;'>"
                "⭐ 云端AI工艺参数推荐系统 ⭐<br>"
                "<span style='font-size:10px;color:#888;'>Powered by 通义千问 qwen2.5-14b</span>"
                "</div>",
                5,
                True,
            )
            title_input.isFullWidth = True

            # ---- 加工特征下拉框 ----
            feature_dropdown = inputs.addDropDownCommandInput(
                "featureSelect",
                "加工特征类型",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            feature_dropdown.tooltip = "选择需要加工的几何特征类型"
            for i, opt in enumerate(FEATURE_OPTIONS):
                feature_dropdown.listItems.add(opt, i == 0)  # 默认选中第一项

            # ---- 材料下拉框 ----
            material_dropdown = inputs.addDropDownCommandInput(
                "materialSelect",
                "工件材料",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            material_dropdown.tooltip = "选择工件原材料牌号"
            for i, opt in enumerate(MATERIAL_OPTIONS):
                material_dropdown.listItems.add(opt, i == 0)

            # ---- 机床下拉框 ----
            machine_dropdown = inputs.addDropDownCommandInput(
                "machineSelect",
                "机床类型",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            machine_dropdown.tooltip = "选择使用的数控机床类型"
            for i, opt in enumerate(MACHINE_OPTIONS):
                machine_dropdown.listItems.add(opt, i == 0)

            # ---- 分隔线 ----
            inputs.addTextBoxCommandInput("sep1", "", "<hr style='margin:8px 0;'>", 1, True).isFullWidth = True

            # ---- 状态提示区域 ----
            self.status_input = inputs.addTextBoxCommandInput(
                "statusText",
                "状态",
                "<div style='color:#666;font-size:10px;text-align:center;'>"
                "就绪 — 请选择参数后点击下方按钮查询"
                "</div>",
                3,
                True,
            )
            self.status_input.isFullWidth = True

            # ---- 结果展示区域 ----
            self.result_input = inputs.addTextBoxCommandInput(
                "resultText",
                "推荐工艺参数",
                "<div style='background:#f5f5f5;border:1px solid #ddd;padding:12px;"
                "border-radius:4px;min-height:40px;text-align:center;color:#999;'>"
                "等待查询结果..."
                "</div>",
                6,
                True,
            )
            self.result_input.isFullWidth = True

            # ---- 分隔线 ----
            inputs.addTextBoxCommandInput("sep2", "", "<hr style='margin:8px 0;'>", 1, True).isFullWidth = True

            # ---- 查询按钮 ----
            query_btn = inputs.addBoolValueInput(
                "queryBtn",
                "🔍 查询工艺参数",
                False,
                "",
                True,
            )
            query_btn.tooltip = "点击调用云端AI获取推荐切削参数"
            query_btn.isFullWidth = True

            # ---- 知识库参考按钮 ----
            kb_btn = inputs.addBoolValueInput(
                "kbBtn",
                "📖 查看知识库基准参数 (离线)",
                False,
                "",
                True,
            )
            kb_btn.isFullWidth = True

            # ---- 注册事件处理器 ----
            on_execute = CraftCommandExecuteEventHandler(
                self.status_input, self.result_input
            )
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

            on_input_changed = CraftInputChangedEventHandler(
                self.status_input, self.result_input
            )
            cmd.inputChanged.add(on_input_changed)
            _handlers.append(on_input_changed)

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    f"构建对话框失败:\n{traceback.format_exc()}"
                )


# ============================================================================
# 输入变化事件处理器 (处理按钮点击)
# ============================================================================
class CraftInputChangedEventHandler(adsk.core.InputChangedEventHandler):
    """监听对话框中的用户交互 (按钮点击 / 下拉框变化)。"""

    def __init__(self, status_input, result_input):
        super().__init__()
        self.status_input = status_input
        self.result_input = result_input

    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            changed_input = args.input
            cmd = args.firingEvent.sender
            inputs = cmd.commandInputs

            # ---- 查询按钮被点击 ----
            if changed_input.id == "queryBtn" and changed_input.value:
                # 重置按钮状态 (否则下次点击不触发)
                changed_input.value = False

                # 获取用户选择
                feature = inputs.itemById("featureSelect").selectedItem.name
                material = inputs.itemById("materialSelect").selectedItem.name
                machine = inputs.itemById("machineSelect").selectedItem.name

                # 更新状态为加载中
                self._update_status("⏳ 正在查询云端AI, 请稍候...", "#2196F3")

                # 调用API
                craft_params = self._call_api(feature, material, machine)

                if craft_params:
                    # 显示结果
                    self._show_result(feature, material, machine, craft_params)
                    self._update_status("✅ 查询成功 — 工艺参数来自通义千问AI", "#4CAF50")
                else:
                    self._update_status("❌ 查询失败, 请检查API服务是否启动", "#F44336")

            # ---- 知识库按钮被点击 ----
            if changed_input.id == "kbBtn" and changed_input.value:
                changed_input.value = False

                feature = inputs.itemById("featureSelect").selectedItem.name
                material = inputs.itemById("materialSelect").selectedItem.name

                kb_params = self._call_kb_api(feature, material)
                if kb_params:
                    self.result_input.formattedText = (
                        f"<div style='background:#FFF8E1;border:1px solid #FFB300;padding:12px;"
                        f"border-radius:4px;text-align:center;'>"
                        f"<b>📖 知识库基准参数 (离线查询,非AI生成)</b><br><br>"
                        f"<span style='font-size:16px;font-weight:bold;color:#333;'>"
                        f"{kb_params}</span><br><br>"
                        f"<span style='font-size:10px;color:#999;'>"
                        f"材料: {material} | 特征: {feature}</span></div>"
                    )
                    self._update_status("📖 已显示知识库基准参数 (离线)", "#FF9800")
            else:
                self._update_status("❌ 知识库查询失败", "#F44336")

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    f"处理操作失败:\n{traceback.format_exc()}"
                )

    def _call_api(self, feature: str, material: str, machine: str) -> str:
        """调用本地 FastAPI 服务的 /get_craft 接口。"""
        try:
            request_data = json.dumps({
                "feature": feature,
                "material": material,
                "machine": machine,
            }).encode("utf-8")

            req = urllib.request.Request(
                API_ENDPOINT,
                data=request_data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                resp_body = json.loads(response.read().decode("utf-8"))
                return resp_body.get("craft_params", "")

        except urllib.error.URLError as e:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    f"无法连接到本地AI服务!\n\n"
                    f"请确认 cam_cloud_api.py 已启动:\n"
                    f"  地址: {API_BASE_URL}\n"
                    f"  端口: 8000\n\n"
                    f"错误详情: {str(e)}",
                    "连接失败",
                )
            return ""
        except Exception as e:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    f"API调用异常:\n{str(e)}",
                    "调用失败",
                )
            return ""

    def _call_kb_api(self, feature: str, material: str) -> str:
        """调用知识库查询接口 (离线, 不消耗API)。"""
        try:
            url = f"{API_BASE_URL}/knowledge_base/lookup?feature={urllib.parse.quote(feature)}&material={urllib.parse.quote(material)}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as response:
                resp_body = json.loads(response.read().decode("utf-8"))
                return resp_body.get("kb_reference", "")
        except Exception as e:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    f"知识库查询失败:\n{str(e)}",
                    "查询失败",
                )
            return ""

    def _update_status(self, message: str, color: str):
        """更新状态文本。"""
        if self.status_input:
            self.status_input.formattedText = (
                f"<div style='color:{color};font-size:10px;text-align:center;'>"
                f"{message}</div>"
            )

    def _show_result(self, feature: str, material: str, machine: str, params: str):
        """在结果区域展示AI推荐的工艺参数。"""
        if self.result_input:
            self.result_input.formattedText = (
                f"<div style='background:#E8F5E9;border:2px solid #4CAF50;padding:16px;"
                f"border-radius:6px;text-align:center;'>"
                f"<b style='color:#2E7D32;'>✅ AI推荐切削参数</b><br><br>"
                f"<span style='font-size:18px;font-weight:bold;color:#000;'>"
                f"{params}</span><br><br>"
                f"<span style='font-size:10px;color:#666;'>"
                f"特征: {feature} | 材料: {material} | 机床: {machine}<br>"
                f"Powered by 通义千问 qwen2.5-14b | Temperature=0.1"
                f"</span></div>"
            )


# ============================================================================
# 命令执行事件处理器
# ============================================================================
class CraftCommandExecuteEventHandler(adsk.core.CommandEventHandler):
    """命令执行时的回调 (此处用于处理附加逻辑)。"""

    def __init__(self, status_input, result_input):
        super().__init__()
        self.status_input = status_input
        self.result_input = result_input

    def notify(self, args: adsk.core.CommandEventArgs):
        # 主要逻辑在 InputChanged 中处理, 这里仅做兜底
        pass


# ============================================================================
# 脚本入口函数 (Fusion360 脚本规范)
# ============================================================================
def run(context):
    """
    Fusion360 Python脚本标准入口。
    系统自动调用此函数, context 包含当前 Fusion360 应用上下文。
    """
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # 获取命令定义 (如果不存在则创建)
        cmd_def = ui.commandDefinitions.itemById("CAM_AI_CraftCommand")
        if not cmd_def:
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                "CAM_AI_CraftCommand",
                "CAM智能工艺推荐",
                "基于云端AI的数控切削参数推荐工具",
                "",  # 资源文件夹 (不使用图标)
            )

        # 绑定命令创建事件
        on_create = CraftCommandCreatedEventHandler()
        cmd_def.commandCreated.add(on_create)
        _handlers.append(on_create)

        # 执行命令 (弹出对话框)
        cmd_def.execute()

        # 防止事件处理器被GC回收
        adsk.autoTerminate(False)

    except Exception:
        if ui:
            ui.messageBox(
                f"脚本运行失败, 请检查:\n"
                f"1. 确保在 Fusion360 环境中运行此脚本\n"
                f"2. 确保 cam_cloud_api.py 已启动 (端口8000)\n\n"
                f"错误详情:\n{traceback.format_exc()}",
                "CAM AI 脚本错误",
            )


def stop(context):
    """Fusion360 脚本停止时的清理回调。"""
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        cmd_def = ui.commandDefinitions.itemById("CAM_AI_CraftCommand")
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass
