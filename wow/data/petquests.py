# -*- coding: utf-8 -*-
"""宠物对战世界任务名表（中文离线表，随插件分发）。

来源：wowhead.com/cn/quest=<id> 重定向 URL 中的中文 slug（2026-09 抓取）。
数据源 todayinwow.com 只给英文任务名，本表把军团再临 + 破碎海滩/阿古斯
全部 58 个宠物对战世界任务映射成国服中文名；未收录的新任务回退英文名。
"""

from __future__ import annotations

# quest_id -> 中文名（除注明外均抓自 wowhead.com/cn 重定向，2026-09 验证）
QUEST_CN: dict[int, str] = {
    40277: "决斗之夜-蒂梵妮-尼尔森",
    40278: "为了我的宠物",
    40279: "杜里安的训练",
    40280: "布蕾达的训练",
    40282: "小动物偷猎者",
    40298: "决斗之夜-加尔维斯顿先生",
    40299: "决斗之夜-博迪-日轨",
    40337: "弗鲁莫斯",
    41624: "罗克要瘦身",
    41687: "蜗牛大战",
    41766: "野生动物保护力量",
    41855: "勇敢面对",
    41860: "解决萨特",
    41861: "面对恶魔之喉",
    41862: "只有宠物可以预防森林火灾",
    41881: "决斗之夜-赫里奥苏斯",
    41886: "决斗之夜-鼠辈",
    41895: "宠物大师",
    41914: "清理墓穴",
    41931: "法力分流",
    41935: "重量级野兽",
    41944: "贾伦之梯",
    41948: "宠物登天",
    41958: "全能金刚",
    41990: "斩获",
    42015: "命运丝线",
    42062: "决斗之夜-缝合三世",
    42063: "体型不重要",
    42064: "是伊利-等等。",
    42067: "声音大雨点小",
    42146: "稀里糊涂小可爱",
    42148: "酒水坏了",
    42154: "帮助雏龙",
    42159: "守夜人训练",
    42165: "阿苏纳样本",
    42190: "野生动物保护者",
    42442: "决斗之夜-阿玛利亚",
    46111: "伊利达雷大师-希丝克斯",
    46112: "伊利达雷大师-薇希萨夫人",
    46113: "伊利达雷大师-无名秘术师",
    49041: "毁灭之蹄",
    49042: "污染之爪",
    49043: "毒光鳐",
    49044: "小脏",
    49045: "死亡之啸",
    49046: "小牙",
    49047: "巴基",
    49048: "鼠鼠",
    49049: "烁光之翼",
    # 以下 2 条（49057/49058）抓取时被 wowhead 限流，暂用通行译名，
    # 后续版本对表更新后替换（见 tasks/todo.md）
    49050: "曳影兽",
    49051: "阿古斯的腐化之血",
    49052: "马库斯",
    49053: "凝视者",
    49054: "小胖",
    49055: "啮耳者",
    49056: "小贼",
    49057: "迷你克西斯",
    49058: "众多之一",
}


def quest_name_cn(quest_id: int, fallback: str = "") -> str:
    """任务中文名；未收录返回 fallback（英文原名）。"""
    return QUEST_CN.get(int(quest_id)) or fallback


# 军团再临宠物任务出现的区域（英文 → 国服中文名）
ZONE_CN: dict[str, str] = {
    "Azsuna": "阿苏纳",
    "Stormheim": "风暴峡湾",
    "Val'sharah": "瓦尔莎拉",
    "Highmountain": "至高岭",
    "Suramar": "苏拉玛",
    "Dalaran": "达拉然",
    "Broken Shore": "破碎海滩",
    "Krokuun": "克罗库恩",
    "Eredath": "埃瑞达斯",
    "Antoran Wastes": "安托兰废土",
}


def zone_cn(zone: str) -> str:
    return ZONE_CN.get(zone, zone)


# 宠物任务常见奖励（英文 → 中文；未收录回退英文）
REWARD_CN: dict[str, str] = {
    "Battle Pet Bandage": "宠物绷带",
    "Polished Pet Charm": "抛光宠物符咒",
    "Order Resources": "职业大厅资源",
    "Battle Pet Bandage x19": "宠物绷带 x19",
}

# 军团再临阵营声望（rewards 里 reward_type=reputation 的 item_name）
FACTION_CN: dict[str, str] = {
    "Valarjar": "瓦拉加尔",
    "Court of Farondis": "法罗迪斯宫廷",
    "Dreamweavers": "织梦者",
    "Highmountain Tribe": "至高岭部族",
    "Nightfallen": "堕夜精灵",
    "Wardens": "守望者",
    "Armies of Legionfall": "抗魔联军",
    "Army of the Light": "圣光军团",
    "Argussian Reach": "阿古斯守望者",
}


def reward_cn(name: str) -> str:
    if name in REWARD_CN:
        return REWARD_CN[name]
    if name in FACTION_CN:
        return FACTION_CN[name] + "声望"
    return name
