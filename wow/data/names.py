# -*- coding: utf-8 -*-
"""内置数据表：职业/专精/服务器/副本中文映射。"""

CLASS_CN = {
    "Warrior": "战士", "Paladin": "圣骑士", "Hunter": "猎人", "Rogue": "潜行者",
    "Priest": "牧师", "Death Knight": "死亡骑士", "Shaman": "萨满", "Mage": "法师",
    "Warlock": "术士", "Monk": "武僧", "Druid": "德鲁伊", "Demon Hunter": "恶魔猎手",
    "Evoker": "唤魔师",
}

SPEC_CN = {
    "Arms": "武器", "Fury": "狂暴", "Protection": "防护",
    "Holy": "神圣", "Retribution": "惩戒",
    "Beast Mastery": "野兽控制", "Marksmanship": "射击", "Survival": "生存",
    "Assassination": "刺杀", "Outlaw": "狂徒", "Subtlety": "敏锐",
    "Discipline": "戒律", "Shadow": "暗影",
    "Blood": "鲜血", "Frost": "冰霜", "Unholy": "邪恶",
    "Elemental": "元素", "Enhancement": "增强", "Restoration": "恢复",
    "Arcane": "奥术", "Fire": "火焰",
    "Brewmaster": "酒仙", "Mistweaver": "织雾", "Windwalker": "踏风",
    "Balance": "平衡", "Feral": "野性", "Guardian": "守护",
    "Affliction": "痛苦", "Demonology": "恶魔", "Destruction": "毁灭",
    "Havoc": "浩劫", "Vengeance": "复仇",
    "Devastation": "湮灭", "Preservation": "恩护", "Augmentation": "增辉",
}

REALM_CN = {
    "Silver Hand": "白银之手", "Echo Ridge": "回音山", "Kings Valley": "国王之谷",
    "Doomwalker": "末日行者", "Shadowmoon": "暗影之月", "Scarlet Crusade": "血色十字军",
    "Golden Plains": "金色平原", "Anzu": "安苏", "Burning Steppes": "燃烧平原",
    "Argus": "阿古斯", "Deathwing": "死亡之翼", "Phoenix God": "凤凰之神",
    "Dragon Soul": "巨龙之魂", "Shadowmourne": "影之哀伤", "Frostmourne": "霜之哀伤",
    "Well of Eternity": "永恒之井",
}

DUNGEON_CN = {
    "Altar of Fangs": "毒牙祭坛",
    "Murder Row": "密谋小径",
    "Voidscar Arena": "虚空之痕竞技场",
    "Nexus-Point Xenas": "节点希纳斯",
    "Pit of Saron": "萨隆矿坑",
    "Magisters' Terrace": "魔导师平台",
    "Algeth'ar Academy": "艾杰斯亚学院",
    "Windrunner Spire": "风行者之塔",
    "Seat of the Triumvirate": "执政团之座",
    "Skyreach": "通天峰",
    "Maysara Cavern": "迈萨拉洞窟",
    "Maisara Caverns": "迈萨拉洞窟",
    "Grim Batol": "格瑞姆巴托",
    "The Stonevault": "矶石宝库",
    "City of Threads": "千丝之城",
    "Ara-Kara, City of Echoes": "艾拉-卡拉，回响之城",
    "The Dawnbreaker": "破晨号",
    "Mists of Tirna Scithe": "塞兹仙林的迷雾",
    "Siege of Boralus": "围攻伯拉勒斯",
    "The Necrotic Wake": "通灵战潮",
    "Necrotic Wake": "通灵战潮",
    "Temple of the Jade Serpent": "青龙寺",
    "Halls of Infusion": "注能大厅",
    "Ruby Life Pools": "红玉新生法池",
    "Brackenhide Hollow": "蕨皮山谷",
    "Halls of Valor": "英灵殿",
    "Neltharus": "奈萨鲁斯",
    "Freehold": "自由镇",
    "Underrot": "地渊孢林",
    "Atal'Dazar": "阿塔达萨",
    "Kings' Rest": "诸王之眠",
    "Operation: Mechagon": "麦卡贡行动",
    "Tazavesh, the Veiled Market": "塔扎维什，帷纱集市",
    "Spires of Ascension": "晋升高塔",
    "Theater of Pain": "伤逝剧场",
    "De Other Side": "彼界",
    "Sanguine Depths": "赤红深渊",
    "Plaguefall": "凋魂之殇",
    "Halls of Atonement": "赎罪大厅",
}


def class_cn(name: str) -> str:
    return CLASS_CN.get(name, name)


def spec_cn(name: str) -> str:
    return SPEC_CN.get(name, name)


def realm_cn(name: str) -> str:
    return REALM_CN.get(name, name)


def dungeon_cn(name: str) -> str:
    return DUNGEON_CN.get(name, name)