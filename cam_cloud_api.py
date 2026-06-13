"""
================================================================================
 cam_cloud_api.py — Fusion360 CAM 云端智能工艺推荐系统 | 本地FastAPI中转服务
 功能: 接收 Fusion360 脚本的加工特征/材料/机床请求, 拼装内置工艺知识库 +
       阿里云通义千问 qwen2.5-14b-instruct API, 返回标准化切削参数。
 端口: 8000
 接口: POST /get_craft
 作者: CAM_AI_System
 日期: 2026-06-13
 版本: 1.0.0
 许可证: MIT License
 仓库: https://github.com/your-org/cam-cloud-api
================================================================================
"""

__version__ = "1.1.0"
__author__ = "CAM_AI_System"
__license__ = "MIT"

import os
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import dashscope
from dashscope import Generation

# ============================================================================
# 日志配置
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cam_cloud_api")

# ============================================================================
# 阿里云 DashScope API Key 配置
# ★★★ 必须修改为你自己的 Key ★★★
# 获取地址: https://dashscope.console.aliyun.com/apiKey
# ============================================================================
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
dashscope.api_key = DASHSCOPE_API_KEY

# 模型固定配置
MODEL_NAME = "qwen2.5-14b-instruct"
TEMPERATURE = 0.1       # 低温减少幻觉, 参数稳定
MAX_TOKENS = 200        # 输出极短, 仅工艺参数字符串
TOP_P = 0.1             # 极窄采样, 输出确定性高

# ============================================================================
# 内置数控工艺知识库 (精简车间高频参数)
# 格式: 知识库[材料][加工特征] = (刀具, S转速, F进给, ap切深)
# 单位: S(rpm), F(mm/min), ap(mm)
# ============================================================================
CRAFT_KNOWLEDGE_BASE = {
    "6061铝": {
        "平面铣削":   "Φ63端铣刀(5刃) | S6000 | F1200 | ap0.5~1.5",
        "型腔加工":   "Φ12硬质合金立铣刀(2刃) | S8000 | F1500 | ap0.3~1.0",
        "键槽加工":   "Φ8键槽铣刀(2刃) | S5000 | F800 | ap0.2~0.5",
        "钻孔":       "Φ6高速钢麻花钻 | S4000 | F300 | 啄钻深度2.0",
        "攻丝":       "M6机用丝锥(螺旋槽) | S800 | F800 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃) | S10000 | F2000 | ap0.1~0.2",
    },
    "45#钢": {
        "平面铣削":   "Φ63端铣刀(5刃) | S2500 | F500 | ap0.3~1.0",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃) | S3500 | F600 | ap0.2~0.5",
        "键槽加工":   "Φ8键槽铣刀(2刃) | S2500 | F400 | ap0.1~0.3",
        "钻孔":       "Φ6高速钢麻花钻 | S1800 | F150 | 啄钻深度1.5",
        "攻丝":       "M6机用丝锥(螺旋槽) | S300 | F300 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃) | S5000 | F800 | ap0.05~0.15",
    },
    "304不锈钢": {
        "平面铣削":   "Φ63端铣刀(5刃,涂层) | S1200 | F250 | ap0.2~0.5",
        "型腔加工":   "Φ12硬质合金立铣刀(4刃,AlTiN涂层) | S2000 | F300 | ap0.1~0.3",
        "键槽加工":   "Φ8键槽铣刀(2刃,涂层) | S1500 | F200 | ap0.05~0.2",
        "钻孔":       "Φ6含钴高速钢麻花钻 | S800 | F80 | 啄钻深度1.0",
        "攻丝":       "M6机用丝锥(含钴高速钢) | S150 | F150 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃,涂层) | S3500 | F500 | ap0.05~0.1",
    },
    "H62黄铜": {
        "平面铣削":   "Φ63端铣刀(5刃) | S5000 | F1000 | ap0.5~1.5",
        "型腔加工":   "Φ12硬质合金立铣刀(2刃) | S7000 | F1200 | ap0.3~1.0",
        "键槽加工":   "Φ8键槽铣刀(2刃) | S4000 | F600 | ap0.2~0.5",
        "钻孔":       "Φ6高速钢麻花钻 | S3500 | F250 | 啄钻深度2.0",
        "攻丝":       "M6机用丝锥(螺旋槽) | S600 | F600 | 螺距1.0",
        "曲面精加工": "R5球头铣刀(2刃) | S8000 | F1500 | ap0.1~0.2",
    },
}

# 合法的输入枚举值（用于校验）
VALID_FEATURES = list(CRAFT_KNOWLEDGE_BASE["6061铝"].keys())
VALID_MATERIALS = list(CRAFT_KNOWLEDGE_BASE.keys())
VALID_MACHINES = ["三轴立式加工中心", "数控铣床", "钻攻中心", "五轴加工中心", "龙门铣床"]


def build_system_prompt(feature: str, material: str, machine: str) -> str:
    """构建带有完整知识库上下文的 System Prompt, 强制模型输出固定格式。"""
    # 收集该材料+特征对应的知识库参考值
    ref_params = CRAFT_KNOWLEDGE_BASE.get(material, {}).get(feature, "无内置参考,请根据材料特性推荐")

    prompt = f"""你是一个数控加工工艺专家, 专精于CNC铣削、钻孔、攻丝工艺参数推荐。

## 内置工艺知识库 (参考基准)
当前加工场景:
- 加工特征: {feature}
- 工件材料: {material}
- 机床类型: {machine}

知识库基准参数: {ref_params}

完整知识库 (所有材料 × 所有特征, 供比对参考):
{json.dumps(CRAFT_KNOWLEDGE_BASE, ensure_ascii=False, indent=2)}

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
# FastAPI 应用初始化
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时校验API Key配置。"""
    logger.info("=" * 60)
    logger.info("CAM云端工艺推荐系统 本地中转服务启动中...")
    logger.info(f"模型: {MODEL_NAME} | 温度: {TEMPERATURE} | 端口: 8000")
    key_preview = dashscope.api_key[:8] + "****" + dashscope.api_key[-4:] if len(dashscope.api_key) > 12 else "***未配置***"
    logger.info(f"API Key: {key_preview}")
    logger.info(f"支持材料: {', '.join(VALID_MATERIALS)}")
    logger.info(f"支持特征: {', '.join(VALID_FEATURES)}")
    logger.info("=" * 60)
    yield
    logger.info("CAM云端工艺推荐系统 服务已关闭")


app = FastAPI(
    title="Fusion360 CAM 云端工艺推荐系统",
    description="本地中转服务: 接收加工特征→调用通义千问→返回标准化切削参数",
    version="1.0.0",
    lifespan=lifespan,
)

# 允许本地跨域 (Fusion360 脚本可能从不同 origin 请求)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API 路由
# ============================================================================
@app.get("/")
async def root():
    """健康检查根路由。"""
    return {
        "service": "Fusion360 CAM 云端工艺推荐系统",
        "version": "1.0.0",
        "model": MODEL_NAME,
        "status": "running",
        "endpoints": {
            "get_craft": "POST /get_craft",
            "health": "GET /health",
            "knowledge_base": "GET /knowledge_base",
        },
    }


@app.get("/health")
async def health_check():
    """健康检查接口。"""
    api_key_set = bool(dashscope.api_key) and not dashscope.api_key.startswith("sk-xxx")
    return {
        "status": "healthy",
        "version": __version__,
        "model": MODEL_NAME,
        "api_configured": api_key_set,
        "hint": None if api_key_set else (
            "API Key 未配置! 请编辑 start_service.bat 第18行填入从 "
            "https://dashscope.console.aliyun.com/apiKey 获取的真实Key后重启服务"
        ),
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


@app.post("/get_craft", response_model=CraftResponse)
async def get_craft(request: CraftRequest):
    """
    核心接口: 接收加工特征+材料+机床, 调用通义千问API生成切削参数。

    处理流程:
    1. 校验输入参数合法性
    2. 构建 System Prompt (含完整知识库)
    3. 调用 qwen2.5-14b-instruct 模型
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

    # ---- 3. 调用通义千问 API ----
    try:
        response = Generation.call(
            model=MODEL_NAME,
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
            result_format="message",
        )

        # 检查API返回状态
        if response.status_code != 200:
            code = getattr(response, "code", str(response.status_code))
            msg = getattr(response, "message", "unknown error")
            error_msg = f"DashScope API error [{code}]: {msg}"
            logger.error(error_msg)

            # 区分认证错误
            if response.status_code == 401 or "Invalid API-key" in str(msg):
                raise HTTPException(
                    status_code=401,
                    detail="DashScope API Key 无效! 请到 https://dashscope.console.aliyun.com/apiKey 获取有效Key, "
                           "然后修改 start_service.bat 第18行 或 cam_cloud_api.py 第40行。",
                )
            raise HTTPException(status_code=502, detail=error_msg)

        raw_output = response.output.choices[0].message.content.strip()
        logger.info(f"AI原始输出: {raw_output}")

    except HTTPException:
        raise  # 直接抛出已构造的 HTTPException
    except dashscope.error.AuthenticationError:
        logger.error("DashScope API Key 认证失败")
        raise HTTPException(
            status_code=401,
            detail="API Key 认证失败! 请到 https://dashscope.console.aliyun.com/apiKey 重新获取Key, "
                   "然后修改 cam_cloud_api.py 第40行。",
        )
    except dashscope.error.InvalidParameter as e:
        logger.error(f"DashScope 参数错误: {e}")
        raise HTTPException(status_code=400, detail=f"API调用参数错误: {str(e)}")
    except Exception as e:
        logger.error(f"调用AI服务异常: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"AI服务调用失败 [{type(e).__name__}]: {str(e)}")

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
# 程序入口
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    # 启动 uvicorn 服务器
    # host="0.0.0.0" 允许本机所有网络接口访问 (也可用 127.0.0.1 仅本地)
    uvicorn.run(
        "cam_cloud_api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,       # 生产模式不启用热重载
        log_level="info",
    )
