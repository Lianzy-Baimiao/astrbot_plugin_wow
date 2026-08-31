# -*- coding: utf-8 -*-
"""内置数据表：词缀本地化与 8 周轮换。"""

AFFIX_CN = {
    9: "残暴",
    10: "强韧",
    147: "萨拉塔斯的狡诈",
    148: "萨拉塔斯的交易：扬升",
    152: "挑战者的危境",
    153: "萨拉塔斯的交易：狂暴",
    158: "萨拉塔斯的交易：虚缚",
    159: "萨拉塔斯的交易：湮灭",
    160: "萨拉塔斯的交易：吞噬",
    162: "萨拉塔斯的交易：脉冲",
    165: "林多尔米的指引",
}

AFFIX_DESC_CN = {
    9: "首领生命值提高 25%。首领及其爪牙造成的伤害提高最多 15%。",
    10: "非首领敌人生命值提高 20%，造成的伤害提高最多 20%。",
    147: "萨拉塔斯背叛玩家，撤销她的交易，并使死亡扣除 15 秒剩余时间。",
    148: "战斗中，萨拉塔斯降下宇宙能量宝珠，强化敌方或玩家。",
    158: "战斗中，萨拉塔斯召唤虚缚使者，强化附近敌人。",
    159: "战斗中，萨拉塔斯召唤湮灭相关效果。",
    160: "战斗中，萨拉塔斯撕开裂隙，吞噬玩家精华。",
    162: "战斗中，萨拉塔斯召唤环绕玩家的脉冲星。",
    165: "林多尔米指引玩家，高亮并削弱特定非首领敌人。击败这些敌人即可完成敌方部队进度；玩家死亡不再扣除剩余时间。",
}

AFFIX_BY_SHORT = {
    "Devour": {"id": 160, "name": "Xal'atath's Bargain: Devour", "icon": "inv_ability_voidweaverpriest_entropicrift"},
    "Ascendant": {"id": 148, "name": "Xal'atath's Bargain: Ascendant", "icon": "inv_nullstone_cosmicvoid"},
    "Voidbound": {"id": 158, "name": "Xal'atath's Bargain: Voidbound", "icon": "inv_cosmicvoid_buff"},
    "Pulsar": {"id": 162, "name": "Xal'atath's Bargain: Pulsar", "icon": "inv_cosmicvoid_nova"},
    "Oblivion": {"id": 159, "name": "Xal'atath's Bargain: Oblivion", "icon": "spell_priest_void-blast"},
    "Fortified": {"id": 10, "name": "Fortified", "icon": "ability_toughness"},
    "Tyrannical": {"id": 9, "name": "Tyrannical", "icon": "achievement_boss_archaedas"},
    "Guile": {"id": 147, "name": "Xal'atath's Guile", "icon": "ability_racial_chillofnight"},
}

# 8 周轮换表（与 mythicpl.us 一致）
# 顺序: +5 Bargain, +7 主词缀, +10 副词缀, +12 Guile
# key 规则: 主词缀前 2 字母 + Bargain 短名前 2 字母
ROTATION_ORDER = ["tyas", "fopu", "tyvo", "fode", "typu", "foas", "tyde", "fovo"]

ROTATION = {
    "tyas": ["Ascendant", "Tyrannical", "Fortified", "Guile"],
    "fopu": ["Pulsar", "Fortified", "Tyrannical", "Guile"],
    "tyvo": ["Voidbound", "Tyrannical", "Fortified", "Guile"],
    "fode": ["Devour", "Fortified", "Tyrannical", "Guile"],
    "typu": ["Pulsar", "Tyrannical", "Fortified", "Guile"],
    "foas": ["Ascendant", "Fortified", "Tyrannical", "Guile"],
    "tyde": ["Devour", "Tyrannical", "Fortified", "Guile"],
    "fovo": ["Voidbound", "Fortified", "Tyrannical", "Guile"],
}

LEVEL_LABELS = ["+5", "+7", "+10", "+12"]


def short_name(name: str) -> str:
    """取词缀短名：去掉 "Xal'atath's Bargain: " / "Xal'atath's " 前缀。"""
    name = name.strip()
    for prefix in ("Xal'atath's Bargain: ", "Xal'atath's "):
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name


def rotation_key(details: list) -> str:
    """根据本周前两个词缀生成轮换 key（与 mythicpl.us 算法一致）。"""
    if len(details) < 2:
        return ""
    a0 = short_name(details[0]["name"]).lower()
    a1 = short_name(details[1]["name"]).lower()
    if len(a0) < 2 or len(a1) < 2:
        return ""
    return a1[:2] + a0[:2]


def next_rotation_key(cur: str) -> str:
    if cur in ROTATION_ORDER:
        idx = ROTATION_ORDER.index(cur)
        return ROTATION_ORDER[(idx + 1) % len(ROTATION_ORDER)]
    return ""


def make_affix_info(affix_id: int, name_en: str, desc_en: str, icon: str, icon_url: str, level: str) -> dict:
    return {
        "id": affix_id,
        "name_cn": AFFIX_CN.get(affix_id) or short_name(name_en),
        "name_en": short_name(name_en),
        "desc": AFFIX_DESC_CN.get(affix_id) or desc_en,
        "icon": icon,
        "icon_url": icon_url or (f"https://cdn.raiderio.net/images/wow/icons/large/{icon}.jpg" if icon else ""),
        "level": level,
    }


def card_from_rio(details: list, title: str, key: str) -> dict:
    card = {"title": title, "key": key, "affixes": []}
    for i, a in enumerate(details):
        lv = LEVEL_LABELS[i] if i < len(LEVEL_LABELS) else ""
        card["affixes"].append(make_affix_info(a["id"], a["name"], a["description"], a.get("icon", ""), a.get("icon_url", ""), lv))
    return card


def card_from_rotation(key: str, title: str) -> dict | None:
    row = ROTATION.get(key)
    if not row:
        return None
    card = {"title": title, "key": key, "affixes": []}
    for i, short in enumerate(row):
        meta = AFFIX_BY_SHORT.get(short)
        if not meta:
            continue
        lv = LEVEL_LABELS[i] if i < len(LEVEL_LABELS) else ""
        card["affixes"].append(make_affix_info(meta["id"], meta["name"], "", meta["icon"], "", lv))
    return card