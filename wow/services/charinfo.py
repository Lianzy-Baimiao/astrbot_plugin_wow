# -*- coding: utf-8 -*-
"""角色卡（charinfo）服务：数据组装。"""

from __future__ import annotations

import datetime as dt
import logging

from ..net import fetch_json
from ..wago import item_names, mplus_dungeon_names, raid_names

logger = logging.getLogger("astrbot_plugin_wow.charinfo")

GEAR_SLOTS = [
    ("head", "头部"), ("neck", "颈部"), ("shoulder", "肩部"), ("back", "背部"),
    ("chest", "胸部"), ("wrist", "手腕"), ("hands", "手"), ("waist", "腰部"),
    ("legs", "腿部"), ("feet", "脚"), ("finger1", "戒指"), ("finger2", "戒指"),
    ("trinket1", "饰品"), ("trinket2", "饰品"), ("mainhand", "主手"), ("offhand", "副手"),
]

RACE_CN = {
    "Human": "人类", "Dwarf": "矮人", "Night Elf": "暗夜精灵", "Gnome": "侏儒",
    "Draenei": "德莱尼", "Worgen": "狼人", "Pandaren": "熊猫人", "Void Elf": "虚空精灵",
    "Lightforged Draenei": "光铸德莱尼", "Dark Iron Dwarf": "黑铁矮人",
    "Kul Tiran": "库尔提拉斯人", "Mechagnome": "机械侏儒", "Dracthyr": "龙希尔",
    "Orc": "兽人", "Undead": "亡灵", "Tauren": "牛头人", "Troll": "巨魔",
    "Blood Elf": "血精灵", "Goblin": "地精", "Nightborne": "夜之子",
    "Highmountain Tauren": "至高岭牛头人", "Mag'har Orc": "玛格汉兽人",
    "Zandalari Troll": "赞达拉巨魔", "Vulpera": "狐人", "Earthen": "土灵",
}

CLASS_COLOR_EN = {
    "Warrior": "#C79C6E", "Paladin": "#F58CBA", "Hunter": "#ABD473", "Rogue": "#FFF569",
    "Priest": "#F5F5F5", "Death Knight": "#C41E3A", "Shaman": "#0070DE", "Mage": "#3FC7EB",
    "Warlock": "#8788EE", "Monk": "#00FF98", "Druid": "#FF7C0A", "Demon Hunter": "#A330C9",
    "Evoker": "#33937F",
}

CLASS_CN_EN = {
    "Warrior": "战士", "Paladin": "圣骑士", "Hunter": "猎人", "Rogue": "潜行者",
    "Priest": "牧师", "Death Knight": "死亡骑士", "Shaman": "萨满", "Mage": "法师",
    "Warlock": "术士", "Monk": "武僧", "Druid": "德鲁伊",
    "Demon Hunter": "恶魔猎手", "Evoker": "唤魔师",
}

SPEC_CN = {
    "Arms": "武器", "Fury": "狂暴", "Protection": "防护", "Holy": "神圣",
    "Retribution": "惩戒", "Beast Mastery": "野兽控制", "Marksmanship": "射击",
    "Survival": "生存", "Assassination": "刺杀", "Outlaw": "狂徒", "Subtlety": "敏锐",
    "Discipline": "戒律", "Shadow": "暗影", "Blood": "鲜血", "Frost": "冰霜",
    "Unholy": "邪恶", "Elemental": "元素", "Enhancement": "增强", "Restoration": "恢复",
    "Arcane": "奥术", "Fire": "火焰", "Brewmaster": "酒仙", "Mistweaver": "织雾",
    "Windwalker": "踏风", "Balance": "平衡", "Feral": "野性", "Guardian": "守护",
    "Affliction": "痛苦", "Demonology": "恶魔", "Destruction": "毁灭",
    "Havoc": "浩劫", "Vengeance": "复仇", "Devastation": "湮灭",
    "Preservation": "恩护", "Augmentation": "增辉",
}

FACTION_CN = {"alliance": "联盟", "horde": "部落"}

ROLE_CN = {"DPS": "输出", "HEALING": "治疗", "TANK": "坦克"}

EXPANSION_CN = {
    "mn": "至暗之夜", "tww": "地心之战", "df": "巨龙时代",
    "sl": "暗影国度", "bfa": "争霸艾泽拉斯", "legion": "军团再临",
}

REALM_CN = {
    "Shadowmourne": "影之哀伤", "Silver Hand": "白银之手", "Echo Ridge": "回音山",
    "Kings Valley": "国王之谷", "Doomwalker": "末日行者", "Shadowmoon": "暗影之月",
    "Scarlet Crusade": "血色十字军", "Golden Plains": "金色平原", "Anzu": "安苏",
    "Burning Steppes": "燃烧平原", "Argus": "阿古斯", "Deathwing": "死亡之翼",
    "Dragon Soul": "巨龙之魂", "Rhonin": "罗宁", "Lightning's Blade": "闪电之刃",
}


def _comma(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _season_cn(season: str) -> str:
    s = season.removeprefix("season-")
    parts = s.split("-")
    if len(parts) == 2 and parts[0] in EXPANSION_CN:
        return f"{EXPANSION_CN[parts[0]]} S{parts[1]}"
    return season


def _level_color(lvl: int) -> str:
    if lvl >= 20:
        return "#FF8000"
    if lvl >= 15:
        return "#A335EE"
    if lvl >= 10:
        return "#0098FF"
    return "#C8C8D2"


def _ms_to_clock(ms) -> str:
    if not ms or ms <= 0:
        return ""
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _run_date(s: str) -> str:
    if not s:
        return ""
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().strftime("%m-%d")
    except ValueError:
        return ""


def _raid_fallback_name(slug: str) -> str:
    if slug.startswith("tier-"):
        rest = slug[5:]
        i = rest.rfind("-")
        if i > 0 and rest[:i] in EXPANSION_CN:
            return f"{EXPANSION_CN[rest[:i]]} S{rest[i + 1:]}"
    return slug


async def fetch_char(name: str, realm: str) -> dict:
    """拉取 raider.io 角色全量资料。"""
    url = (
        "https://raider.io/api/v1/characters/profile?region=cn"
        f"&realm={realm}&name={name}"
        "&fields=gear,guild,raid_progression,mythic_plus_ranks,"
        "mythic_plus_recent_runs,mythic_plus_scores_by_season%3Acurrent"
    )
    try:
        p = await fetch_json(url, timeout=30)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"未找到角色 {name}-{realm}（{e}）") from e
    if not p.get("name"):
        raise RuntimeError(f"未找到角色 {name}-{realm}")
    return p


async def build_char_card(name: str, realm: str) -> dict:
    """组装角色卡渲染数据（布局与原 ZeroBot 版一致）。"""
    p = await fetch_char(name, realm)
    gear = p.get("gear") or {}
    items = gear.get("items") or {}
    item_ids = {it.get("item_id", 0) for it in items.values() if it.get("item_id", 0) > 0}
    try:
        names = await item_names(item_ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("物品名拉取失败: %s", e)
        names = {}
    try:
        mplus_names = await mplus_dungeon_names()
    except Exception as e:  # noqa: BLE001
        logger.warning("副本名拉取失败: %s", e)
        mplus_names = {}
    try:
        raid_names_map = await raid_names()
    except Exception as e:  # noqa: BLE001
        logger.warning("团本名拉取失败: %s", e)
        raid_names_map = {}

    slots = []
    for key, cn in GEAR_SLOTS:
        it = items.get(key) or {}
        item_id = it.get("item_id", 0)
        slots.append(
            {
                "slot": cn,
                "name": names.get(item_id) or it.get("name", ""),
                "icon": it.get("icon", ""),
                "icon_url": f"https://cdn.raiderio.net/images/wow/icons/large/{it['icon']}.jpg" if it.get("icon") else "",
                "ilvl": it.get("item_level", 0),
                "quality": it.get("item_quality", 1),
                "tier": it.get("tier", ""),
                "enchant": it.get("enchant", 0),
                "gems": it.get("gems") or [],
            }
        )

    # 大秘境赛季
    scores = p.get("mythic_plus_scores_by_season") or []
    season = scores[0] if scores else {}
    cur_scores = season.get("scores") or {}
    score_all = float(cur_scores.get("all", 0) or 0)
    score_dps = float(cur_scores.get("dps", 0) or 0)
    score_healer = float(cur_scores.get("healer", 0) or 0)
    score_tank = float(cur_scores.get("tank", 0) or 0)
    has_mp = score_all > 0 or any(v > 0 for v in (score_dps, score_healer, score_tank))
    score_color = ((season.get("segments") or {}).get("all") or {}).get("color", "") or "#FFC878"

    # 排名行（综合/职业/角色）
    ranks = p.get("mythic_plus_ranks") or {}
    rank_rows = []

    def _rank_line(w, r, realm_r) -> str:
        return f"世界 #{_comma(w)}      国服 #{_comma(r)}      本服 #{_comma(realm_r)}"

    def _has_rank(rk) -> bool:
        r = ranks.get(rk) or {}
        return int(r.get("world", 0) or 0) > 0

    if _has_rank("overall"):
        r = ranks["overall"]
        rank_rows.append(("综合", _rank_line(r.get("world"), r.get("region"), r.get("realm"))))
    cls_name = p.get("class", "")
    if _has_rank("class"):
        r = ranks["class"]
        rank_rows.append((CLASS_CN_EN.get(cls_name, cls_name), _rank_line(r.get("world"), r.get("region"), r.get("realm"))))
    role_key = {"DPS": "dps", "HEALING": "healer", "TANK": "tank"}.get(p.get("active_spec_role", ""), "")
    if role_key and _has_rank(role_key):
        r = ranks[role_key]
        rank_rows.append((ROLE_CN.get(p.get("active_spec_role", ""), ""), _rank_line(r.get("world"), r.get("region"), r.get("realm"))))

    # 最近大秘境
    runs = []
    for r in (p.get("mythic_plus_recent_runs") or [])[:5]:
        upgrades = int(r.get("num_keystone_upgrades", 0) or 0)
        runs.append(
            {
                "level": r.get("mythic_level", 0),
                "level_color": _level_color(int(r.get("mythic_level", 0) or 0)),
                "dungeon": mplus_names.get(r.get("map_challenge_mode_id", 0)) or r.get("dungeon", ""),
                "tag": f"限时+{upgrades}" if upgrades > 0 else "超时",
                "tag_color": "#68BE7E" if upgrades > 0 else "#BE6060",
                "duration": _ms_to_clock(r.get("clear_time_ms", 0)),
                "date": _run_date(r.get("completed_at", "")),
                "score": r.get("score", 0),
            }
        )

    # 团本进度（按总 BOSS 数降序，只显示有击杀的）
    raids = []
    progression = p.get("raid_progression") or {}
    for slug, prog in progression.items():
        total = int(prog.get("total_bosses", 0) or 0)
        killed = int(prog.get("normal_bosses_killed", 0) or 0) + int(prog.get("heroic_bosses_killed", 0) or 0) + int(prog.get("mythic_bosses_killed", 0) or 0)
        if total <= 0 or killed <= 0:
            continue
        raids.append(
            {
                "slug": slug,
                "name": raid_names_map.get(slug) or _raid_fallback_name(slug),
                "total": total,
                "n": int(prog.get("normal_bosses_killed", 0) or 0),
                "h": int(prog.get("heroic_bosses_killed", 0) or 0),
                "m": int(prog.get("mythic_bosses_killed", 0) or 0),
            }
        )
    raids.sort(key=lambda r: r["total"], reverse=True)

    cls_slug = cls_name.lower().replace(" ", "")
    spec_raw = p.get("active_spec_name", "")
    spec_cn_name = SPEC_CN.get(spec_raw, spec_raw)
    if cls_name == "Death Knight" and spec_raw == "Frost":
        spec_cn_name = "冰霜"

    # 信息更新时间（本地时间，供页脚显示）
    last_crawled = ""
    try:
        t = dt.datetime.fromisoformat((p.get("last_crawled_at", "") or "").replace("Z", "+00:00"))
        last_crawled = t.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        last_crawled = ""

    return {
        "name": p.get("name", ""),
        "realm": REALM_CN.get(p.get("realm", ""), p.get("realm", "")),
        "faction": FACTION_CN.get(p.get("faction", ""), p.get("faction", "")),
        "faction_color": "#68A8F5" if p.get("faction") == "alliance" else "#E46060",
        "race": RACE_CN.get(p.get("race", ""), p.get("race", "")),
        "class": CLASS_CN_EN.get(cls_name, cls_name),
        "spec": spec_cn_name,
        "guild": (p.get("guild") or {}).get("name", ""),
        "achievement_points": p.get("achievement_points", 0),
        "class_color": CLASS_COLOR_EN.get(cls_name, "#8D8F9C"),
        "class_icon": f"https://cdn.raiderio.net/images/wow/icons/large/classicon_{cls_slug}.jpg",
        "thumbnail_url": p.get("thumbnail_url", ""),
        "ilvl": gear.get("item_level_equipped", 0) or 0,
        "slots": slots,
        "has_mp": has_mp,
        "score_all": score_all,
        "score_dps": score_dps,
        "score_healer": score_healer,
        "score_tank": score_tank,
        "score_color": score_color,
        "season_cn": _season_cn(season.get("season", "")),
        "rank_rows": rank_rows,
        "runs": runs,
        "raids": raids,
        "last_crawled": last_crawled,
    }