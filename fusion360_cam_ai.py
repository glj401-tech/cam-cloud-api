"""
================================================================================
 Fusion360_CAM_AI_Script.py — Fusion360 内置 Python 脚本 v1.1.0
 功能: 弹窗选择加工特征/材料/机床 → 调用本地8000端口API → 弹窗展示AI推荐工艺参数
 使用方法:
   1. 在 Fusion360 中: 工具 → 脚本与附加模块 → 新建Python脚本 → 粘贴本文件全部内容
   2. 保存后点击"运行"
   3. 在弹出对话框中选择参数 → 点击"查询工艺参数"
   4. 结果自动弹窗显示
 前提条件: cam_cloud_api.py 服务已在后台运行 (端口8000)
 修复: v1.1.0 — 修复 else 缩进导致的"知识库查询失败"覆盖bug, 修复中文编码问题
 作者: CAM_AI_System
 日期: 2026-06-13
 版本: 1.1.0
 许可证: MIT License
 仓库: https://github.com/glj401-tech/cam-cloud-api
================================================================================
"""

__version__ = "1.1.0"
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
API_BASE_URL = "http://127.0.0.1:8000"
API_ENDPOINT = f"{API_BASE_URL}/get_craft"

# 保存事件处理器引用 (防止被Python GC回收)
_handlers = []

# 加工特征选项
FEATURES = [
    "平面铣削", "型腔加工", "键槽加工",
    "钻孔", "攻丝", "曲面精加工",
]

# 材料选项
MATERIALS = ["6061铝", "45#钢", "304不锈钢", "H62黄铜"]

# 机床选项
MACHINES = ["三轴立式加工中心", "数控铣床", "钻攻中心", "五轴加工中心", "龙门铣床"]


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

            # 标题
            t = inputs.addTextBoxCommandInput(
                "titleText", "Fusion360 CAM 智能工艺推荐",
                "<div align='center' style='font-size:14px;font-weight:bold;padding:8px;'>"
                "⭐ 云端AI工艺参数推荐系统 ⭐<br>"
                "<span style='font-size:10px;color:#888;'>Powered by qwen2.5-14b | v1.1.0</span>"
                "</div>", 5, True,
            )
            t.isFullWidth = True

            # 加工特征下拉框
            dd_feat = inputs.addDropDownCommandInput(
                "featureSelect", "加工特征类型",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_feat.tooltip = "选择需要加工的几何特征类型"
            for i, opt in enumerate(FEATURES):
                dd_feat.listItems.add(opt, i == 0)

            # 材料下拉框
            dd_mat = inputs.addDropDownCommandInput(
                "materialSelect", "工件材料",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_mat.tooltip = "选择工件原材料牌号"
            for i, opt in enumerate(MATERIALS):
                dd_mat.listItems.add(opt, i == 0)

            # 机床下拉框
            dd_mach = inputs.addDropDownCommandInput(
                "machineSelect", "机床类型",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            dd_mach.tooltip = "选择使用的数控机床类型"
            for i, opt in enumerate(MACHINES):
                dd_mach.listItems.add(opt, i == 0)

            # 分隔线
            inputs.addTextBoxCommandInput("sep1", "", "<hr style='margin:8px 0;'>", 1, True).isFullWidth = True

            # 状态区域
            self.status_input = inputs.addTextBoxCommandInput(
                "statusText", "状态",
                "<div style='color:#666;font-size:10px;text-align:center;'>"
                "就绪 - 请选择参数后点击下方按钮</div>",
                3, True,
            )
            self.status_input.isFullWidth = True

            # 结果展示区域
            self.result_input = inputs.addTextBoxCommandInput(
                "resultText", "推荐工艺参数",
                "<div style='background:#f5f5f5;border:1px solid #ddd;padding:12px;"
                "border-radius:4px;min-height:40px;text-align:center;color:#999;'>"
                "等待查询结果...</div>",
                6, True,
            )
            self.result_input.isFullWidth = True

            inputs.addTextBoxCommandInput("sep2", "", "<hr style='margin:8px 0;'>", 1, True).isFullWidth = True

            # 查询按钮
            qbtn = inputs.addBoolValueInput("queryBtn", "查询工艺参数 (云端AI)", False, "", True)
            qbtn.tooltip = "调用通义千问AI获取推荐切削参数 (需联网)"
            qbtn.isFullWidth = True

            # 知识库按钮
            kbtn = inputs.addBoolValueInput("kbBtn", "查看知识库基准参数 (离线)", False, "", True)
            kbtn.tooltip = "显示内置知识库参考值 (不消耗API, 断网可用)"
            kbtn.isFullWidth = True

            # 注册事件
            on_exec = CraftCommandExecuteEventHandler(self.status_input, self.result_input)
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)

            on_change = CraftInputChangedEventHandler(self.status_input, self.result_input)
            cmd.inputChanged.add(on_change)
            _handlers.append(on_change)

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(f"构建对话框失败:\n{traceback.format_exc()}")


# ============================================================================
# 输入变化事件处理器 (处理按钮点击)
# ============================================================================
class CraftInputChangedEventHandler(adsk.core.InputChangedEventHandler):
    """监听对话框用户交互, 处理查询按钮和知识库按钮。"""

    def __init__(self, status_input, result_input):
        super().__init__()
        self.status_input = status_input
        self.result_input = result_input

    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            changed = args.input
            inputs = args.firingEvent.sender.commandInputs

            # ================================================================
            # 按钮 A: 查询工艺参数 (调用云端 AI)
            # ================================================================
            if changed.id == "queryBtn" and changed.value:
                changed.value = False  # 复位

                feature = inputs.itemById("featureSelect").selectedItem.name
                material = inputs.itemById("materialSelect").selectedItem.name
                machine = inputs.itemById("machineSelect").selectedItem.name

                self._set_status("正在查询云端AI, 请稍候...", "#2196F3")
                result = self._do_ai_query(feature, material, machine)

                if result:
                    self._show_ai_result(feature, material, machine, result)
                    self._set_status("查询成功! 参数来自通义千问AI", "#4CAF50")
                else:
                    self._set_status("查询失败! 请确认API服务已启动 (端口8000)", "#F44336")

            # ================================================================
            # 按钮 B: 查看知识库基准参数 (离线, 不消耗API)
            # ================================================================
            elif changed.id == "kbBtn" and changed.value:
                changed.value = False  # 复位

                feature = inputs.itemById("featureSelect").selectedItem.name
                material = inputs.itemById("materialSelect").selectedItem.name

                self._set_status("正在查询本地知识库...", "#FF9800")
                result = self._do_kb_query(feature, material)

                if result:
                    self._show_kb_result(feature, material, result)
                    self._set_status("已显示知识库基准参数 (离线查询, 免费)", "#FF9800")
                else:
                    self._set_status("知识库查询失败! 请确认API服务已启动 (端口8000)", "#F44336")

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(f"操作异常:\n{traceback.format_exc()}")

    # ------------------------------------------------------------------
    # 内部: 调用 AI 接口
    # ------------------------------------------------------------------
    def _do_ai_query(self, feature: str, material: str, machine: str) -> str:
        try:
            data = {"feature": feature, "material": material, "machine": machine}
            resp = http_post_json(API_ENDPOINT, data, timeout=30)
            return resp.get("craft_params", "")
        except urllib.error.URLError as e:
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
            self._alert(f"API返回错误 [{e.code}]:\n{body}")
            return ""
        except Exception as e:
            self._alert(f"API调用异常:\n{type(e).__name__}: {e}")
            return ""

    # ------------------------------------------------------------------
    # 内部: 调用知识库接口
    # ------------------------------------------------------------------
    def _do_kb_query(self, feature: str, material: str) -> str:
        try:
            q_feat = urllib.parse.quote(feature, safe="")
            q_mat = urllib.parse.quote(material, safe="")
            url = f"{API_BASE_URL}/knowledge_base/lookup?feature={q_feat}&material={q_mat}"
            resp = http_get_json(url, timeout=10)
            return resp.get("kb_reference", "")
        except urllib.error.URLError as e:
            self._alert(
                f"无法连接到本地服务!\n\n"
                f"请先启动 cam_cloud_api.py (端口8000)\n\n"
                f"错误: {e.reason}"
            )
            return ""
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._alert(f"知识库接口错误 [{e.code}]:\n{body}")
            return ""
        except Exception as e:
            self._alert(f"知识库查询异常:\n{type(e).__name__}: {e}")
            return ""

    # ------------------------------------------------------------------
    # UI 辅助
    # ------------------------------------------------------------------
    def _set_status(self, msg: str, color: str):
        if self.status_input:
            self.status_input.formattedText = (
                f"<div style='color:{color};font-size:10px;text-align:center;'>{msg}</div>"
            )

    def _alert(self, msg: str):
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(msg, "CAM AI 提示")

    def _show_ai_result(self, feature: str, material: str, machine: str, params: str):
        if self.result_input:
            self.result_input.formattedText = (
                f"<div style='background:#E8F5E9;border:2px solid #4CAF50;padding:16px;"
                f"border-radius:6px;text-align:center;'>"
                f"<b style='color:#2E7D32;'>AI 推荐切削参数</b><br><br>"
                f"<span style='font-size:18px;font-weight:bold;color:#000;'>{params}</span><br><br>"
                f"<span style='font-size:10px;color:#666;'>"
                f"特征: {feature} | 材料: {material} | 机床: {machine}<br>"
                f"qwen2.5-14b | temperature=0.1</span></div>"
            )

    def _show_kb_result(self, feature: str, material: str, params: str):
        if self.result_input:
            self.result_input.formattedText = (
                f"<div style='background:#FFF8E1;border:2px solid #FFB300;padding:16px;"
                f"border-radius:6px;text-align:center;'>"
                f"<b style='color:#E65100;'>知识库基准参数 (离线)</b><br><br>"
                f"<span style='font-size:18px;font-weight:bold;color:#333;'>{params}</span><br><br>"
                f"<span style='font-size:10px;color:#999;'>"
                f"特征: {feature} | 材料: {material}<br>"
                f"来源: 内置知识库 (免费, 断网可用)</span></div>"
            )


# ============================================================================
# 命令执行事件处理器 (占位)
# ============================================================================
class CraftCommandExecuteEventHandler(adsk.core.CommandEventHandler):
    def __init__(self, status_input, result_input):
        super().__init__()
        self.status_input = status_input
        self.result_input = result_input

    def notify(self, args: adsk.core.CommandEventArgs):
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
                "基于云端AI的数控切削参数推荐工具 v1.1.0",
                "",
            )

        on_create = CraftCommandCreatedEventHandler()
        cmd_def.commandCreated.add(on_create)
        _handlers.append(on_create)

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
        cmd_def = ui.commandDefinitions.itemById("CAM_AI_CraftCommand")
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass
