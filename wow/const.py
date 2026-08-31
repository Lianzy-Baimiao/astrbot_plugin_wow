# -*- coding: utf-8 -*-
"""魔兽世界综合插件 - 常量与配色。"""

# 职业色（与游戏内职业色一致）
CLASS_COLORS = {
    "战士": "#C79C6E",
    "圣骑士": "#F58CBA",
    "猎人": "#ABD473",
    "潜行者": "#FFF569",
    "牧师": "#FFFFFF",
    "死亡骑士": "#C41F3B",
    "萨满祭司": "#0070DE",
    "法师": "#69CCF0",
    "术士": "#9482C9",
    "武僧": "#00FF96",
    "德鲁伊": "#FF7D0A",
    "恶魔猎手": "#A330C9",
    "唤魔师": "#33937F",
    "死亡骑士(DK)": "#C41F3B",
    "萨满": "#0070DE",
    "潜行": "#FFF569",
    "武僧(WS)": "#00FF96",
    "恶魔猎手(DH)": "#A330C9",
    "唤魔师(Evoker)": "#33937F",
    "德鲁伊(XD)": "#FF7D0A",
    "战士(ZS)": "#C79C6E",
    "圣骑士(SQ)": "#F58CBA",
    "猎人(LR)": "#ABD473",
    "潜行者(DZ)": "#FFF569",
    "牧师(MS)": "#FFFFFF",
    "死亡骑士(DK)": "#C41F3B",
    "萨满祭司(SM)": "#0070DE",
    "法师(FS)": "#69CCF0",
    "术士(SS)": "#9482C9",
}

# 英文职业名 -> 中文
CLASS_EN_CN = {
    "warrior": "战士",
    "paladin": "圣骑士",
    "hunter": "猎人",
    "rogue": "潜行者",
    "priest": "牧师",
    "deathknight": "死亡骑士",
    "shaman": "萨满祭司",
    "mage": "法师",
    "warlock": "术士",
    "monk": "武僧",
    "druid": "德鲁伊",
    "demonhunter": "恶魔猎手",
    "evoker": "唤魔师",
}

CLASS_CN_EN = {v: k for k, v in CLASS_EN_CN.items()}

# 品质色（0-6 对应 灰色/白色/绿色/蓝色/紫色/橙色/神话）
QUALITY_COLORS = {
    0: "#9D9D9D",
    1: "#FFFFFF",
    2: "#1EFF00",
    3: "#0070DD",
    4: "#A335EE",
    5: "#FF8000",
    6: "#E268A8",
}

# 品质中文名
QUALITY_NAMES = {
    0: "垃圾",
    1: "普通",
    2: "优秀",
    3: "精良",
    4: "史诗",
    5: "传说",
    6: "神话",
}

# 背景色
BG_COLOR = "#141519"
PANEL_COLOR = "#1E2027"
TEXT_COLOR = "#E8E8E8"
SUB_TEXT_COLOR = "#9CA3AF"
GOLD = "#D4AF37"
SILVER = "#C0C0C0"
BRONZE = "#CD7F32"

# 限流（秒）
LIMIT_DEFAULT = 5
LIMIT_HEAVY = 10  # 耗时查询
LIMIT_LIGHT = 2  # 轻量查询

# HTTP
HTTP_TIMEOUT = 20.0
HTTP_TIMEOUT_SLOW = 30.0
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PLUGIN_NAME = "astrbot_plugin_wow"