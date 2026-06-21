"""
知识库增强模块 — 从 cam_process_library.md 提炼
v1.8.0 新增: HR强制规则、ERR修正规则、余量标准、切削参数库、Fusion360策略矩阵
"""
# ===================================================================
# 第1章：HR 强制约束规则 (Hard Rules) — 最高优先级，绝对不可违反
# ===================================================================
HR_RULES = {
    "HR-01": {
        "id": "HR-01",
        "trigger": "零件内圆角半径 R < 开粗刀半径（D_rough / 2）",
        "action": "必须添加残料铣（Rest Milling / Pencil Cleanup）工序，使用更小刀具",
        "consequence": "过多残料积压，精铣刀入刀瞬间过载崩刃",
        "check_field": "min_inner_radius",
    },
    "HR-02": {
        "id": "HR-02",
        "trigger": "壁厚 ≤ 3mm 的薄壁特征",
        "action": "轴向切深 ap 必须 ≤ 0.2mm；分层精铣；采用对称交替走刀",
        "consequence": "薄壁振动变形，形位公差超差报废",
        "check_field": "wall_thickness",
    },
    "HR-03": {
        "id": "HR-03",
        "trigger": "腔深 > 5 × 刀具直径（深腔）",
        "action": "必须在精铣前执行等高轮廓（Contour）半精加工陡峭侧壁",
        "consequence": "残料不均匀导致精铣颤振，侧壁有振纹",
        "check_field": "pocket_depths",
    },
    "HR-04": {
        "id": "HR-04",
        "trigger": "执行任何精铣工序前",
        "action": "该区域必须已完成开粗 + 半精铣，余量均匀 ≤ 0.25mm",
        "consequence": "余量过大导致精铣刀崩刃或尺寸不稳定",
        "check_field": None,
    },
    "HR-05": {
        "id": "HR-05",
        "trigger": "执行任何钻孔工序前",
        "action": "所有孔位必须已执行中心钻（Spot Drill）",
        "consequence": "钻头游移定位偏差，位置度超差",
        "check_field": "has_thread",
    },
    "HR-06": {
        "id": "HR-06",
        "trigger": "执行攻丝前",
        "action": "底孔必须已钻完，孔径符合底孔要求表，沉头孔已完成",
        "consequence": "丝锥折断，孔损工件报废",
        "check_field": "has_thread",
    },
    "HR-07": {
        "id": "HR-07",
        "trigger": "不锈钢 / 硬钢精铣侧壁",
        "action": "必须使用顺铣（Climb Milling）；禁止逆铣精铣",
        "consequence": "逆铣产生加工硬化层，下刀面质量恶化",
        "check_field": "material",
    },
    "HR-08": {
        "id": "HR-08",
        "trigger": "球刀精铣曲面前",
        "action": "必须用平底刀/圆鼻刀完成半精铣，余量均匀控制在 0.15~0.2mm",
        "consequence": "球刀直接精铣余量不均区域，点接触力集中崩刃",
        "check_field": None,
    },
    "HR-09": {
        "id": "HR-09",
        "trigger": "开粗后余量 > 1mm 就进行精铣",
        "action": "必须插入半精铣工序，将余量减至 0.15~0.25mm",
        "consequence": "精铣无法保证尺寸精度和表面粗糙度",
        "check_field": None,
    },
    "HR-10": {
        "id": "HR-10",
        "trigger": "键槽铣削下刀",
        "action": "禁止直接轴向垂直插铣；必须使用螺旋下刀或斜线切入",
        "consequence": "键槽铣刀底部切削能力弱，直插导致刀具折断",
        "check_field": None,
    },
    "HR-11": {
        "id": "HR-11",
        "trigger": "不锈钢加工中退刀",
        "action": "退刀前主轴不得在材料内停转；必须边走边退",
        "consequence": "停转点产生摩擦热，工件局部硬化或刀具烧损",
        "check_field": "material",
    },
    "HR-12": {
        "id": "HR-12",
        "trigger": "转速设置",
        "action": "所有计算转速必须钳制在 ≤ 8000 RPM 上限",
        "consequence": "超限报警停机，或主轴超速损坏",
        "check_field": None,
    },
}

# ===================================================================
# 第1章补充：余量分配标准
# ===================================================================
ALLOWANCE_TABLE = {
    "开粗后": {
        "side_mm": "0.4 ~ 0.8",
        "bottom_mm": "0.3 ~ 0.6",
        "note": "铝件取小值；钢/不锈钢取大值",
        "fusion_param": "侧面=0.5~0.8mm, 底面=0.3~0.6mm",
    },
    "半精铣后": {
        "side_mm": "0.15 ~ 0.25",
        "bottom_mm": "0.1 ~ 0.2",
        "note": "均匀余量是精铣质量的前提",
        "fusion_param": "侧面=0.15~0.25mm, 底面=0.1~0.2mm",
    },
    "残料铣后": {
        "side_mm": "0.15 ~ 0.2",
        "bottom_mm": "0.1 ~ 0.2",
        "note": "与半精铣余量保持一致",
        "fusion_param": "侧面=0.15~0.2mm, 底面=0.1~0.2mm",
    },
    "精铣后": {
        "side_mm": "0",
        "bottom_mm": "0",
        "note": "到尺寸，不留余量",
        "fusion_param": "侧面=0mm, 底面=0mm",
    },
}

# ===================================================================
# 第2章：增强切削参数数据库 (替代/补充 CRAFT_KNOWLEDGE_BASE)
# 格式: 材料 -> 工序 -> 刀具直径D -> 参数
# ===================================================================
ENHANCED_CUTTING_PARAMS = {
    "铝合金_6061": {
        "开粗": {
            "D10": {"Vc": "200~250", "n": "6366~7958(≤8000)", "fz": "0.05~0.09", "ap": "0.5~1.0×D", "ae": "30~45%×D", "note": "3刃,无涂层或DLC,乳化液"},
            "D12": {"Vc": "200~250", "n": "5305~6631",          "fz": "0.06~0.10", "ap": "0.5~1.0×D", "ae": "30~45%×D", "note": "3刃"},
            "D16": {"Vc": "200~250", "n": "3979~4974",          "fz": "0.07~0.12", "ap": "0.5~1.2×D", "ae": "30~50%×D", "note": "3刃"},
            "D20": {"Vc": "200~250", "n": "3183~3979",          "fz": "0.08~0.15", "ap": "0.5~1.5×D", "ae": "30~50%×D", "note": "3刃"},
        },
        "半精铣": {
            "D8":  {"Vc": "250~300", "n": "≤8000", "fz": "0.04~0.08", "ap": "0.3×D",  "ae": "15~25%×D"},
            "D12": {"Vc": "250~300", "n": "≤8000", "fz": "0.04~0.08", "ap": "0.3×D",  "ae": "15~25%×D"},
            "D16": {"Vc": "250~300", "n": "≤8000", "fz": "0.04~0.08", "ap": "0.3×D",  "ae": "15~25%×D"},
        },
        "精铣侧壁": {
            "D6":  {"Vc": "280~350", "n": "≤8000", "fz": "0.03~0.06", "ap": "0.05~0.2×D", "ae": "5~8%×D"},
            "D10": {"Vc": "280~350", "n": "≤8000", "fz": "0.03~0.06", "ap": "0.05~0.2×D", "ae": "5~8%×D"},
            "D12": {"Vc": "280~350", "n": "≤8000", "fz": "0.03~0.06", "ap": "0.05~0.2×D", "ae": "5~8%×D"},
        },
        "精铣底面": {
            "D10": {"Vc": "280~350", "n": "≤8000", "fz": "0.05~0.10", "ap": "0.1~0.3mm", "ae": "60~75%×D"},
            "D16": {"Vc": "280~350", "n": "≤8000", "fz": "0.05~0.10", "ap": "0.1~0.3mm", "ae": "60~75%×D"},
            "D20": {"Vc": "280~350", "n": "≤8000", "fz": "0.05~0.10", "ap": "0.1~0.3mm", "ae": "60~75%×D"},
        },
    },
    "碳素钢_45": {
        "开粗": {
            "D10": {"Vc": "80~100", "n": "2546~3183", "fz": "0.025~0.045", "ap": "0.3~0.5×D", "ae": "20~35%×D", "note": "4刃,TiAlN涂层,乳化液"},
            "D16": {"Vc": "80~100", "n": "1592~1989", "fz": "0.030~0.060", "ap": "0.3~0.5×D", "ae": "20~35%×D"},
            "D20": {"Vc": "80~100", "n": "1273~1592", "fz": "0.035~0.070", "ap": "0.3~0.5×D", "ae": "25~35%×D"},
        },
        "半精铣": {
            "D8":  {"Vc": "100~130", "n": "1989~5170", "fz": "0.020~0.040", "ap": "0.2~0.3×D", "ae": "15~20%×D"},
            "D12": {"Vc": "100~130", "n": "2652~3459", "fz": "0.020~0.040", "ap": "0.2~0.3×D", "ae": "15~20%×D"},
            "D16": {"Vc": "100~130", "n": "1989~2590", "fz": "0.020~0.040", "ap": "0.2~0.3×D", "ae": "15~20%×D"},
        },
        "精铣侧壁": {
            "D6":  {"Vc": "120~150", "n": "3183~7958", "fz": "0.010~0.025", "ap": "0.05~0.15×D", "ae": "4~6%×D", "note": "顺铣"},
            "D10": {"Vc": "120~150", "n": "3820~4775", "fz": "0.010~0.025", "ap": "0.05~0.15×D", "ae": "4~6%×D"},
            "D12": {"Vc": "120~150", "n": "3183~3979", "fz": "0.010~0.025", "ap": "0.05~0.15×D", "ae": "4~6%×D"},
        },
        "精铣底面": {
            "D12": {"Vc": "120~150", "n": "3183~3979", "fz": "0.020~0.040", "ap": "0.1~0.3mm", "ae": "60~75%×D"},
            "D16": {"Vc": "120~150", "n": "2387~3183", "fz": "0.020~0.040", "ap": "0.1~0.3mm", "ae": "60~75%×D"},
            "D20": {"Vc": "120~150", "n": "1909~2387", "fz": "0.020~0.040", "ap": "0.1~0.3mm", "ae": "60~75%×D"},
        },
    },
    "不锈钢_304": {
        "开粗": {
            "D10": {"Vc": "40~60", "n": "1273~1910", "fz": "0.015~0.030", "ap": "0.2~0.4×D", "ae": "15~25%×D", "note": "4刃,AlTiN涂层,高压切削液>20bar"},
            "D16": {"Vc": "40~60", "n": "796~1194",  "fz": "0.020~0.040", "ap": "0.2~0.4×D", "ae": "15~25%×D"},
            "D20": {"Vc": "40~60", "n": "637~955",   "fz": "0.025~0.050", "ap": "0.2~0.4×D", "ae": "15~25%×D"},
        },
        "半精铣": {
            "D8":  {"Vc": "55~75",  "n": "1460~2984", "fz": "0.012~0.025", "ap": "0.15~0.25×D", "ae": "10~15%×D", "note": "顺铣,ap≥0.05mm"},
            "D12": {"Vc": "55~75",  "n": "1460~1989", "fz": "0.012~0.025", "ap": "0.15~0.25×D", "ae": "10~15%×D"},
        },
        "精铣侧壁": {
            "D6":  {"Vc": "65~85",  "n": "2069~4507", "fz": "0.008~0.018", "ap": "0.05~0.1×D", "ae": "3~5%×D", "note": "顺铣"},
            "D10": {"Vc": "65~85",  "n": "2069~2705", "fz": "0.008~0.018", "ap": "0.05~0.1×D", "ae": "3~5%×D"},
        },
        "精铣底面": {
            "D10": {"Vc": "65~85",  "n": "2069~2705", "fz": "0.015~0.030", "ap": "0.08~0.15mm", "ae": "55~70%×D"},
            "D16": {"Vc": "65~85",  "n": "1295~1683", "fz": "0.015~0.030", "ap": "0.08~0.15mm", "ae": "55~70%×D"},
        },
    },
    "铜合金_H62": {
        "开粗": {
            "D10": {"Vc": "150~220", "n": "≤8000", "fz": "0.040~0.080", "ap": "0.5~1.0×D", "ae": "25~40%×D", "note": "2~3刃,无涂层,压缩空气"},
            "D20": {"Vc": "150~220", "n": "≤8000", "fz": "0.040~0.080", "ap": "0.5~1.0×D", "ae": "25~40%×D"},
        },
        "半精铣": {
            "D8":  {"Vc": "200~260", "n": "≤8000", "fz": "0.030~0.060", "ap": "0.3×D",  "ae": "15~20%×D"},
            "D16": {"Vc": "200~260", "n": "≤8000", "fz": "0.030~0.060", "ap": "0.3×D",  "ae": "15~20%×D"},
        },
        "精铣侧壁": {
            "D6":  {"Vc": "220~300", "n": "≤8000", "fz": "0.020~0.050", "ap": "0.05~0.15×D", "ae": "5~8%×D"},
            "D12": {"Vc": "220~300", "n": "≤8000", "fz": "0.020~0.050", "ap": "0.05~0.15×D", "ae": "5~8%×D"},
        },
    },
    "工程塑料_PC": {
        "开粗": {
            "D10": {"Vc": "100~200", "n": "≤8000", "fz": "0.03~0.08", "ap": "1.0×D", "ae": "40%×D", "note": "2刃O型大螺旋角,压缩空气"},
        },
        "精铣": {
            "D6":  {"Vc": "150~250", "n": "≤8000", "fz": "0.03~0.06", "ap": "0.05×D", "ae": "5%×D", "note": "PMMA禁用切削液,ABS可用压缩空气"},
        },
    },
}

# ===================================================================
# 第3章：Fusion 360 CAM 策略选用矩阵 (增强版 TOOLPATH_STRATEGIES)
# ===================================================================
FUSION360_STRATEGY_MATRIX = {
    "大体积毛坯开粗": {
        "recommended": ["Adaptive Clearing（自适应清除）"],
        "not_recommended": ["Pocket（效率低30%+）"],
        "key_params": "Optimal Load = 0.2~0.45×D",
        "fusion_path": "Manufacture → Milling → Adaptive Clearing",
    },
    "平面_顶面去料": {
        "recommended": ["Face Milling（面铣）"],
        "not_recommended": ["Parallel（刀纹方向不佳）"],
        "key_params": "Stepover = 60~75%×D",
        "fusion_path": "Manufacture → Milling → Face",
    },
    "陡峭侧壁半精_精铣": {
        "recommended": ["Contour（等高轮廓）"],
        "not_recommended": ["Parallel（留扇贝纹）"],
        "key_params": "Stepdown 半精0.2~0.3mm；精0.05~0.15mm",
        "fusion_path": "Manufacture → Milling → Contour",
    },
    "平底腔底面精铣": {
        "recommended": ["Pocket / Floor（平行精铣）"],
        "not_recommended": ["Contour（仅适合壁）"],
        "key_params": "Stepover = 50~60%×D",
        "fusion_path": "Manufacture → Milling → Pocket → Floor",
    },
    "浅平缓曲面精铣": {
        "recommended": ["Parallel（平行铣）"],
        "not_recommended": ["Contour"],
        "key_params": "Stepover = 0.1~0.3mm（依Ra要求）",
        "fusion_path": "Manufacture → Milling → Parallel",
    },
    "复杂曲面精铣": {
        "recommended": ["Parallel + Contour 组合"],
        "not_recommended": ["单独使用任一"],
        "key_params": "平行主切，等高收边",
        "fusion_path": "Manufacture → Milling → Parallel + Contour",
    },
    "内圆角_清根": {
        "recommended": ["Rest Machining（残料铣）"],
        "not_recommended": ["手动补刀"],
        "key_params": "参考前序刀具直径自动计算",
        "fusion_path": "Manufacture → Milling → Adaptive/Pocket → Rest Machining",
    },
    "笔式清角_尖角": {
        "recommended": ["Pencil（铅笔铣）"],
        "not_recommended": ["残料铣（步距太大）"],
        "key_params": "单遍；仅适合外圆角清根",
        "fusion_path": "Manufacture → Milling → Pencil",
    },
    "标准孔位": {
        "recommended": ["Drilling（钻孔）"],
        "not_recommended": ["铣削替代（精度差）"],
        "key_params": "L/D > 5 必启用 Peck Drilling",
        "fusion_path": "Manufacture → Drilling → Drill",
    },
    "精度孔_H7_H8": {
        "recommended": ["Bore / Reaming（铰孔）"],
        "not_recommended": ["单纯钻孔"],
        "key_params": "底孔留 0.1~0.2mm 铰削余量",
        "fusion_path": "Manufacture → Drilling → Ream",
    },
    "小径螺纹_硬材料": {
        "recommended": ["Thread Milling（螺纹铣）"],
        "not_recommended": ["攻丝（丝锥折断风险）"],
        "key_params": "螺距必须精确匹配",
        "fusion_path": "Manufacture → Thread Milling",
    },
}

# ===================================================================
# 第3章补充：Fusion 360 关键参数设置
# ===================================================================
FUSION360_ADAPTIVE_SETTINGS = {
    "Optimal_Load": {
        "铝合金":   "0.30~0.45 × D（可激进）",
        "碳素钢":   "0.20~0.30 × D",
        "不锈钢":   "0.15~0.25 × D（比钢更保守）",
    },
    "Max_Roughing_Stepdown": {
        "铝合金":   "0.5~1.5 × D",
        "碳素钢":   "0.3~0.5 × D",
        "不锈钢":   "0.2~0.4 × D",
    },
    "Stock_to_Leave_侧面": {
        "钢_不锈钢": "0.5~0.8 mm",
        "铝合金":     "0.3~0.5 mm",
    },
    "Stock_to_Leave_底面": {
        "钢_不锈钢": "0.4~0.6 mm",
        "铝合金":     "0.2~0.4 mm",
    },
}

FUSION360_CONTOUR_SETTINGS = {
    "Stepdown_半精": "0.15~0.30 mm",
    "Stepdown_精":   "0.05~0.15 mm（表面质量 Ra1.6 取下限）",
    "Stock_半精":   "侧面 0.15~0.25mm，底面 0.1~0.2mm",
    "Stock_精":     "0mm（到尺寸）",
    "Direction":   "✅ 精铣必须选 Climb（顺铣）| ❌ 禁止选 Conventional（逆铣）用于精铣钢/不锈钢",
    "Min_Cutting_Radius": "设为 0，避免内轮廓缺失",
    "Rest_Machining": "勾选 Use Rest Machining → 参考前序余量，避免空切",
}

# ===================================================================
# 第3章补充：残料铣（Rest Machining）触发规则
# ===================================================================
REST_MACHINING_RULES = {
    "trigger_condition": "零件内圆角半径 R_corner < 开粗刀半径 R_rough（= D_rough / 2）",
    "example": "开粗刀 Ø16mm → R_rough=8mm；零件内圆角 R5 < 8mm → 必须残料铣",
    "tool_selection": "残料铣刀直径 = (内圆角半径 R_corner × 2) × 0.8 [取整到标准刀具]",
    "fusion_setup": [
        "1. 新建刀路（刀具直径 < 开粗刀 2~4mm）",
        "2. Passes 选项卡 → 勾选 Use Rest Machining",
        "3. Rest Machining Source → 选 From previous operation(s)",
        "4. 余量设置与半精铣相同（0.15~0.25mm）",
        "5. 策略选 Adaptive Clearing 或 Contour（按特征选）",
    ],
}

# ===================================================================
# 第4章：典型零件工艺路线库 (供AI参考输出格式)
# ===================================================================
TYPICAL_PROCESS_ROUTES = {
    "模具型腔_Mold_Cavity": {
        "material": "P20/718模具钢（预硬≤38HRC）",
        "features": "深腔 + 复杂曲面 + 多内圆角",
        "tolerance": "尺寸公差 ±0.05mm，Ra ≤ 1.6μm",
        "process_order": [
            "Step1 【开粗】Adaptive Clearing | Ø20 4刃(TiAlN) | n=1432 | fz=0.04 | ap=0.4×D | 留余量侧0.6底0.5",
            "Step2 【型腔壁半精】Contour | Ø12 4刃(TiAlN) | n=2920 | fz=0.025 | Stepdown=0.25 | 余量0.2mm顺铣",
            "Step3 【残料铣内圆角】Rest Machining | Ø8 4刃 | 参考Ø20开粗余量 | 余量0.2mm",
            "Step4 【精铣底面】Floor(Pocket) | Ø16 4刃 | n=2387 | fz=0.02 | Stepover=50%D | 到尺寸",
            "Step5 【精铣侧壁】Contour | Ø12 4刃 | n=3183 | fz=0.015 | Stepdown=0.1mm | 顺铣到尺寸",
            "Step6 【曲面精铣】Parallel+Contour | Ø8R4球刀(TiAlN) | n=3979 | fz=0.012 | Stepover=0.15mm",
            "Step7 【孔加工】中心钻→钻孔→沉锪(如有)→攻丝(如有)",
        ],
    },
    "铝合金箱体框架_Box_Frame": {
        "material": "6061-T6 铝合金",
        "features": "多型腔 + 薄侧壁（2~5mm）+ 安装孔群",
        "process_order": [
            "Step1 【面铣顶面】Face Milling | Ø32面铣刀 | n=7000 | fz=0.08 | ae=60%D | ap=0.3~0.5mm",
            "Step2 【开粗各型腔】Adaptive Clearing | Ø16 3刃铝用 | n=4580 | fz=0.09 | OL=0.375×D | 留余量侧0.4底0.3",
            "Step3 【薄壁半精】Contour | Ø10 3刃铝用 | ⚠️ ap≤0.2mm 分层 | n=7000 | 余量0.15mm",
            "Step4 【残料铣内R】Rest Machining | Ø6 3刃 | 如内角R<8mm",
            "Step5 【精铣底面】Pocket | Ø16 3刃 | Stepover=62%D | 到尺寸",
            "Step6 【精铣侧壁】Contour | Ø10 3刃 | ap=0.15mm 全高单向 | 夹紧注意防变形",
            "Step7 【孔加工】中心钻→钻孔→沉锪→攻丝",
        ],
    },
    "薄壁异形件_ThinWall": {
        "material": "铝合金/不锈钢，壁厚1~3mm，高径比大",
        "constraints": "开粗:①对称交替开粗 ②ap减50% ③Optimal Load降20%；半精:①ap≤0.3mm ②等高Contour从底向上；精铣:①分层ap=0.1~0.15mm ②对称交替 ③蜡填充/减振刀柄 ④顺铣fz降30%",
        "process_order": "开粗(对称交替,ap减半) → 半精(等高从底向上,ap≤0.3mm) → 精铣侧壁(分层0.1mm,对称交替) → 精铣底面 → 孔加工(最后执行,同侧连续)",
    },
    "平板小工件_Flat_Plate": {
        "material": "铝/钢/不锈钢平板，厚度<30mm",
        "features": "外形轮廓 + 台阶面 + 孔位群",
        "process_order": [
            "Step1 【面铣顶面】Face Milling | 去余量保平行度",
            "Step2 【外形/内腔开粗】2D Adaptive或Contour | 每层ap=0.5×D 分层",
            "Step3 【精铣外形】2D Contour | 顺铣一刀到深 | 余量0mm | ⚠️ 板件易翘起需压牢",
            "Step4 【孔加工】中心钻→钻孔→铰孔(精度孔)→攻丝",
        ],
    },
    "键槽_端面孔_辅助工序": {
        "note": "适用轴类/活塞类铣削部分，车削工序在独立文档",
        "process_order": [
            "键槽铣削: 键槽铣刀(直径=槽宽) | 螺旋下刀(禁直插,HR-10) | 45钢Vc=80,fz=0.025 | ap≤0.5mm/层分层",
            "端面平台铣削: 同标准面铣",
            "端面孔群: 中心钻→钻孔→铰孔(精度孔)→攻丝",
        ],
    },
}

# ===================================================================
# 第5章：孔加工专项规范
# ===================================================================
HOLE_MACHINING_RULES = {
    "standard_sequence": "中心钻(Spot Drill) → 钻孔(Drilling) → 铰孔(Reaming)[精度孔] → 锪孔/沉头孔(Countersink)[如有] → 攻丝(Tapping)[螺纹孔]",
    "center_drill": {
        "tool": "Ø3~Ø5 中心钻（90°或120°锥角）",
        "depth": "仅打引导坑（深度 ≈ 孔径 × 0.1~0.2）",
        "purpose": "防止钻头游移，保证位置精度（HR-05）",
    },
    "drilling": {
        "note": "L/D > 5时必须启用啄钻（Peck Drilling），每啄 0.5~1×D 退出排屑",
        "stainless_steel": "进给为铝件40~50%，使用专用不锈钢钻头",
    },
    "reaming": {
        "when": "精度孔（H7/H8级别）才用",
        "allowance": "铰削余量：0.1~0.2mm（底孔孔径 = 铰孔直径 - 0.15mm）",
        "speed": "Vc = 钻孔Vc × 0.6，进给加倍",
        "caution": "禁止逆转退出铰刀（会刮伤孔壁）",
    },
    "countersink": {
        "when": "在底孔完成后进行，直径精确匹配螺钉规格",
    },
    "tapping": {
        "when": "必须最后执行（HR-06）",
        "fusion_strategy": "Fusion 360 中选 Tapping 策略",
        "pitch": "螺距必须与丝锥规格完全一致（不可估算）",
        "rigid_tapping": "使用刚性攻丝（机床需支持主轴同步进给）",
        "stainless_steel": "攻丝转速降至碳钢50%，使用含硫攻丝油",
    },
    "bottom_hole_chart": {
        "M3×0.5":   {"bottom_dia": "Ø2.5 mm", "ref_drill": "Ø2.5", "carbon_rpm": "600~1000", "aluminum_rpm": "1500~2500"},
        "M4×0.7":   {"bottom_dia": "Ø3.3 mm", "ref_drill": "Ø3.3", "carbon_rpm": "450~700",  "aluminum_rpm": "1200~2000"},
        "M5×0.8":   {"bottom_dia": "Ø4.2 mm", "ref_drill": "Ø4.2", "carbon_rpm": "380~600",  "aluminum_rpm": "1000~1800"},
        "M6×1.0":   {"bottom_dia": "Ø5.0 mm", "ref_drill": "Ø5.0", "carbon_rpm": "300~500",  "aluminum_rpm": "800~1500"},
        "M8×1.25":  {"bottom_dia": "Ø6.8 mm", "ref_drill": "Ø6.8", "carbon_rpm": "250~400",  "aluminum_rpm": "600~1200"},
        "M10×1.5":  {"bottom_dia": "Ø8.5 mm", "ref_drill": "Ø8.5", "carbon_rpm": "200~350",  "aluminum_rpm": "500~1000"},
        "M12×1.75": {"bottom_dia": "Ø10.2mm", "ref_drill": "Ø10.2","carbon_rpm": "150~280",  "aluminum_rpm": "400~800"},
        "M16×2.0":  {"bottom_dia": "Ø14.0mm", "ref_drill": "Ø14.0","carbon_rpm": "100~200",  "aluminum_rpm": "300~600"},
    },
}

# ===================================================================
# 第6章：AI 编程错误修正规则库 (ERR代码)
# 调用优先级: HR强制规则 > ERR修正规则 > 参数数据库 > 策略矩阵 > 典型工艺路线
# ===================================================================
ERROR_CORRECTION_RULES = {
    "ERR-01": {
        "code": "ERR-01",
        "description": "缺失半精铣",
        "ai_typical_output": "开粗后直接排精铣",
        "detection_condition": "工序中无半精铣 Operation",
        "forced_correction": "在精铣前插入 Contour 半精铣，余量设 0.2mm（HR-09）",
        "severity": "high",
    },
    "ERR-02": {
        "code": "ERR-02",
        "description": "缺失残料铣/清角",
        "ai_typical_output": "内圆角未清角",
        "detection_condition": "R_corner < D_rough/2 且无 Rest Machining",
        "forced_correction": "添加残料铣，刀具直径 ≤ R_corner × 1.6（HR-01）",
        "severity": "high",
    },
    "ERR-03": {
        "code": "ERR-03",
        "description": "工序顺序颠倒",
        "ai_typical_output": "精铣在开粗之前",
        "detection_condition": "检查 Operation 排列顺序",
        "forced_correction": "强制按第1章工序链重排所有 Operation",
        "severity": "high",
    },
    "ERR-04": {
        "code": "ERR-04",
        "description": "余量不合理",
        "ai_typical_output": "精铣余量设为 0.8mm 或负值",
        "detection_condition": "余量 > 0.3mm（精铣）或 < 0mm",
        "forced_correction": "按第1章余量分配表统一修正",
        "severity": "medium",
    },
    "ERR-05": {
        "code": "ERR-05",
        "description": "孔加工缺中心钻",
        "ai_typical_output": "直接排钻孔 Operation",
        "detection_condition": "无 Spot Drill 在钻孔之前",
        "forced_correction": "所有钻孔前插入中心钻工序（HR-05）",
        "severity": "high",
    },
    "ERR-06": {
        "code": "ERR-06",
        "description": "孔加工顺序错误",
        "ai_typical_output": "攻丝在钻孔前，或无底孔",
        "detection_condition": "检查孔加工操作顺序",
        "forced_correction": "修正为：中心钻→钻孔→沉锪→攻丝（HR-06）",
        "severity": "high",
    },
    "ERR-07": {
        "code": "ERR-07",
        "description": "逆铣精铣",
        "ai_typical_output": "Direction 设为 Conventional",
        "detection_condition": "精铣钢/不锈钢使用逆铣",
        "forced_correction": "强制改为 Climb（顺铣）（HR-07）",
        "severity": "medium",
    },
    "ERR-08": {
        "code": "ERR-08",
        "description": "刀具选型错误（铝合金用4刃）",
        "ai_typical_output": "铝合金工序使用4刃立铣刀",
        "detection_condition": "铝合金加工使用4刃立铣刀",
        "forced_correction": "更换为 2~3 刃铝专用立铣刀（排屑槽窄，粘刀风险高）",
        "severity": "medium",
    },
    "ERR-09": {
        "code": "ERR-09",
        "description": "转速超过机床限制",
        "ai_typical_output": "n 计算值 > 8000 RPM",
        "detection_condition": "自动计算 n = Vc×1000/(π×D)",
        "forced_correction": "钳制 n ≤ 8000 RPM，反算实际 Vc（HR-12）",
        "severity": "high",
    },
    "ERR-10": {
        "code": "ERR-10",
        "description": "薄壁大切深",
        "ai_typical_output": "薄壁件 ap = 2mm",
        "detection_condition": "壁厚≤3mm 且 ap > 0.3mm",
        "forced_correction": "强制设 ap ≤ 0.2mm，增加分层数（HR-02）",
        "severity": "high",
    },
    "ERR-11": {
        "code": "ERR-11",
        "description": "深腔无排屑策略",
        "ai_typical_output": "腔深>5D，钻孔无啄钻",
        "detection_condition": "深腔 L/D > 5 且 Peck Drill 未启用",
        "forced_correction": "启用 Peck Drilling，每啄深 0.5~1×D（HR-03）",
        "severity": "medium",
    },
    "ERR-12": {
        "code": "ERR-12",
        "description": "球刀开粗",
        "ai_typical_output": "用球刀执行开粗工序",
        "detection_condition": "Roughing 工序刀具为球刀",
        "forced_correction": "更换为平底立铣刀；球刀仅用于曲面精铣（HR-08）",
        "severity": "medium",
    },
}

# ===================================================================
# 知识库调用优先级 (复制自 cam_process_library.md 第6.2节)
# ===================================================================
KNOWLEDGE_PRIORITY = {
    "Priority_1": "第1章 HR 强制约束规则 [绝对执行，任何情况下不允许覆盖或跳过]",
    "Priority_2": "第6章 ERR 错误修正规则 [AI 输出生成后必须过检，逐条核对 ERR 列表]",
    "Priority_3": "第2章 切削参数数据库 [按材料+刀具直径+工序类型精确匹配参数]",
    "Priority_4": "第3章 策略选用矩阵 [按特征类型选择 Fusion360 策略和关键参数]",
    "Priority_5": "第4章 典型工艺路线 [参考整体工序结构，按最相近零件类型匹配]",
    "conflict_handling": "当 Priority 1~2 规则与 AI 建议冲突时，强制以规则为准，输出修正说明，不允许静默采纳 AI 输出",
}

# ===================================================================
# 公式与单位换算 (附录A)
# ===================================================================
FORMULAS = {
    "rpm": "n(RPM) = Vc × 1000 / (π × D)   [Vc: m/min | D: mm]",
    "feed_rate": "Vf(mm/min) = fz × Z × n   [fz: mm/tooth | Z: 刃数 | n: RPM]",
    "cutting_speed": "Vc(m/min) = (n × π × D) / 1000",
    "mrr": "材料去除率 MRR = Vf × ae × ap   [单位：mm³/min]",
    "tool_life": "刀具寿命参考（Taylor近似）: Vc每增加10%，刀具寿命约降低50%；反之Vc降低10%，寿命约延长100%",
}
