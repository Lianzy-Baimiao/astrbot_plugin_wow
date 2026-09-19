# -*- coding: utf-8 -*-
"""角色卡（charinfo）服务：数据组装。"""

from __future__ import annotations

import datetime as dt
import logging
import time
from urllib.parse import quote

from .. import store
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

# raider.io 赛季分里 spec_0..N 的下标按游戏天赋界面顺序排列
# （武僧是织雾在前、踏风在后，与专精 ID 升序不同，已用多角色实测）
CLASS_SPEC_ORDER = {
    "Warrior": ["Arms", "Fury", "Protection"],
    "Paladin": ["Holy", "Protection", "Retribution"],
    "Hunter": ["Beast Mastery", "Marksmanship", "Survival"],
    "Rogue": ["Assassination", "Outlaw", "Subtlety"],
    "Priest": ["Discipline", "Holy", "Shadow"],
    "Death Knight": ["Blood", "Frost", "Unholy"],
    "Shaman": ["Elemental", "Enhancement", "Restoration"],
    "Mage": ["Arcane", "Fire", "Frost"],
    "Warlock": ["Affliction", "Demonology", "Destruction"],
    "Monk": ["Brewmaster", "Mistweaver", "Windwalker"],
    "Druid": ["Balance", "Feral", "Guardian", "Restoration"],
    "Demon Hunter": ["Havoc", "Vengeance"],
    "Evoker": ["Devastation", "Preservation", "Augmentation"],
}

FACTION_CN = {"alliance": "联盟", "horde": "部落"}

# raider.io 官方 M+ 分数配色分档（MN S2，151 档）。
# 来源：https://github.com/RaiderIO/raiderio-addon develop 分支 db/db_score_tiers.lua
# （raider.io 每赛季重新生成；整合分是假想值，只能按此表近似取色，官方实档仍用
#   接口自带的 segments.color）。表按分数降序，命中第一个 ≤ 分数的档。
SCORE_TIERS = [
    (3950, "#ff8000"), (3890, "#ff7d17"), (3865, "#fc7a24"), (3845, "#fa782e"),
    (3820, "#fa7838"), (3795, "#fa7540"), (3770, "#f77345"), (3745, "#f5704c"),
    (3725, "#f56e54"), (3700, "#f26b59"), (3675, "#f26961"), (3650, "#f06666"),
    (3625, "#ed636e"), (3605, "#eb6173"), (3580, "#e86178"), (3555, "#e85e80"),
    (3530, "#e65c85"), (3505, "#e3598c"), (3485, "#e0578f"), (3460, "#de5496"),
    (3435, "#db529c"), (3410, "#d94fa3"), (3385, "#d64fa8"), (3365, "#d14cad"),
    (3340, "#cf4ab2"), (3315, "#cc47ba"), (3290, "#c745bf"), (3265, "#c442c4"),
    (3245, "#c240cc"), (3220, "#bd40d1"), (3195, "#b83dd6"), (3170, "#b23bdb"),
    (3145, "#ad38e3"), (3125, "#a838e8"), (3100, "#a336ed"), (3065, "#9c3ded"),
    (3040, "#9145eb"), (3015, "#8a4ce8"), (2990, "#8054e8"), (2970, "#7559e6"),
    (2945, "#6b5ce6"), (2920, "#6161e3"), (2895, "#5466e3"), (2870, "#4269e0"),
    (2850, "#2e6ede"), (2825, "#0070de"), (2760, "#1c73d9"), (2735, "#2978d6"),
    (2710, "#307ad1"), (2690, "#387dcf"), (2665, "#3d82cc"), (2640, "#4285c7"),
    (2615, "#4787c4"), (2590, "#4a8cbf"), (2570, "#4f8fbd"), (2545, "#5291ba"),
    (2520, "#5496b5"), (2495, "#5799b0"), (2470, "#599ead"), (2450, "#59a1ab"),
    (2425, "#5ca3a6"), (2400, "#5ca8a3"), (2375, "#5eab9e"), (2350, "#5eb099"),
    (2330, "#5eb296"), (2305, "#5eb591"), (2280, "#5eba8f"), (2255, "#5ebd8a"),
    (2230, "#5ec285"), (2210, "#5ec482"), (2185, "#5ec77d"), (2160, "#5ccc78"),
    (2135, "#5ccf73"), (2110, "#59d470"), (2090, "#59d66b"), (2065, "#57d963"),
    (2040, "#54de5e"), (2015, "#4fe059"), (1990, "#4ce654"), (1970, "#4ae84c"),
    (1945, "#45ed45"), (1920, "#40f03d"), (1895, "#3bf536"), (1870, "#33f729"),
    (1850, "#29fa1c"), (1825, "#1fff00"), (1800, "#2bff12"), (1775, "#36ff1c"),
    (1750, "#3dff26"), (1725, "#45ff2b"), (1700, "#4cff33"), (1675, "#52ff38"),
    (1650, "#59ff3d"), (1625, "#5cff42"), (1600, "#61ff47"), (1575, "#66ff4a"),
    (1550, "#6bff4f"), (1525, "#70ff54"), (1500, "#73ff57"), (1475, "#78ff5c"),
    (1450, "#7dff5e"), (1425, "#80ff63"), (1400, "#82ff66"), (1375, "#87ff6b"),
    (1350, "#8aff6e"), (1325, "#8cff70"), (1300, "#91ff75"), (1275, "#94ff78"),
    (1250, "#96ff7a"), (1225, "#99ff80"), (1200, "#9eff82"), (1175, "#a1ff85"),
    (1150, "#a3ff8a"), (1125, "#a6ff8c"), (1100, "#a8ff8f"), (1075, "#abff94"),
    (1050, "#b0ff96"), (1025, "#b2ff99"), (1000, "#b5ff9c"), (975, "#b8ff9e"),
    (950, "#baffa3"), (925, "#bdffa6"), (900, "#bfffa8"), (875, "#c2ffab"),
    (850, "#c4ffb0"), (825, "#c7ffb2"), (800, "#c9ffb5"), (775, "#ccffb8"),
    (750, "#cfffba"), (725, "#d1ffbf"), (700, "#d4ffc2"), (675, "#d6ffc4"),
    (650, "#d6ffc7"), (625, "#d9ffcc"), (600, "#dbffcf"), (575, "#deffd1"),
    (550, "#e0ffd4"), (525, "#e3ffd6"), (500, "#e6ffd9"), (475, "#e8ffde"),
    (450, "#ebffe0"), (425, "#edffe3"), (400, "#edffe6"), (375, "#f0ffeb"),
    (350, "#f2ffed"), (325, "#f5fff0"), (300, "#f7fff2"), (275, "#fafff5"),
    (250, "#fafffa"), (225, "#fcfffc"), (200, "#ffffff"),
]


def _score_tier_color(score: float) -> str:
    for sc, hexc in SCORE_TIERS:
        if score >= sc:
            return hexc
    return "#ffffff"


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


_INT_PROFILE_TTL = 1800
_int_profile_cache: dict[str, tuple[dict, float]] = {}
_search_cache: dict[str, tuple[list, float]] = {}


async def _search_same_name_records(realm_slug: str, name: str) -> list[tuple[int, str]]:
    """高级搜索（/cn/search 页面同款接口）按名字找同服所有档案。

    转子战网/删号重建产生的冻结旧档案也在结果里，名字带 -旧档案ID 后缀
    （如 神之宣告-8729964）。带 30 分钟缓存。
    """
    key = f"cn/{realm_slug}/{name}"
    cached = _search_cache.get(key)
    now = time.time()
    if cached and now - cached[1] < _INT_PROFILE_TTL:
        return cached[0]
    url = ("https://raider.io/api/search-advanced?type=character"
           f"&name[0][contains]={quote(name)}&timezone=UTC&sort[name]=desc&limit=100&offset=0")
    try:
        data = await fetch_json(url, timeout=30)
    except Exception as e:  # noqa: BLE001
        logger.info("同档搜索失败（%s）：%s", name, e)
        return []
    out: list[tuple[int, str]] = []
    for m in (data or {}).get("matches") or []:
        d = m.get("data") or {}
        realm = d.get("realm") or {}
        rslug = realm.get("slug") if isinstance(realm, dict) else None
        nm = str(d.get("name") or "")
        rid = d.get("id")
        if not rid or rslug != realm_slug:
            continue
        if nm != name and not nm.startswith(f"{name}-"):
            continue
        out.append((int(rid), nm))
    _search_cache[key] = (out, now)
    return out


async def _fetch_internal_profile(realm_slug: str, name_part: str, season: str) -> dict | None:
    """raider.io 站内接口（非公开 /api/v1）：按「名字」或「名字-旧档案ID」取档案详情。

    转子战网/删号重建后，旧成绩滞留在旧档案里；旧档案只能用 名字-ID 后缀路径访问
    （公开 /api/v1 按 name+realm 只回活体档案，且无按 ID 查询）。带 30 分钟缓存。
    """
    key = f"cn/{realm_slug}/{name_part}/{season}"
    cached = _int_profile_cache.get(key)
    now = time.time()
    if cached and now - cached[1] < _INT_PROFILE_TTL:
        return cached[0]
    url = f"https://raider.io/api/characters/cn/{realm_slug}/{quote(name_part)}?season={season}"
    try:
        data = await fetch_json(url, timeout=30)
    except Exception as e:  # noqa: BLE001
        logger.info("raider.io 档案详情获取失败（%s）：%s", name_part, e)
        return None
    _int_profile_cache[key] = (data, now)
    return data


def _runs_map(blk: dict) -> dict[int, float]:
    """mythicPlusScores 某一块（all/dps/healer/tank/spec_N）的 runs → {zoneId: score}。"""
    return {r["zoneId"]: float(r.get("score") or 0)
            for r in ((blk or {}).get("runs") or []) if r.get("zoneId") is not None}


def _merge_records(spec_names: list[dict], live_ms: dict,
                   old_mss: list[tuple[str, dict]], live_all: float) -> dict | None:
    """合并同一角色的多条 raider.io 档案（转子战网/删号重建后旧成绩滞留旧档案）。

    两条档案的 mythicPlusScores 同构（all/dps/healer/tank/spec_0..N 的 runs 按
    zoneId 给分），逐副本取各档案较高者即为整合口径——总分、角色条、专精行全部
    出自 raider.io 自身数据。没有旧档案或合并不涨分时返回 None。
    """
    live_total = _runs_map(live_ms.get("all"))
    merged_total = dict(live_total)
    merged_roles = {r: _runs_map(live_ms.get(r)) for r in ("dps", "healer", "tank")}
    merged_specs = [_runs_map(live_ms.get(f"spec_{i}")) for i in range(len(spec_names))]
    for _oid, old_ms in old_mss:
        for zid, sc in _runs_map(old_ms.get("all")).items():
            if sc > merged_total.get(zid, 0):
                merged_total[zid] = sc
        for role, m in merged_roles.items():
            for zid, sc in _runs_map(old_ms.get(role)).items():
                if sc > m.get(zid, 0):
                    m[zid] = sc
        for i, m in enumerate(merged_specs):
            for zid, sc in _runs_map(old_ms.get(f"spec_{i}")).items():
                if sc > m.get(zid, 0):
                    m[zid] = sc
    total = sum(merged_total.values())
    if total <= live_all + 1:
        return None
    return {
        "total": total,
        "extra_count": sum(1 for zid in merged_total if zid not in live_total),
        "role_scores": tuple(sum(m.values()) for m in merged_roles.values()),
        "spec_scores": [
            {**spec_names[i], "score": sum(merged_specs[i].values())}
            for i in range(len(spec_names))
        ],
    }


async def build_char_card(name: str, realm: str, old_ref: str | None = None) -> dict:
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

    # 分专精分数（下标含义见 CLASS_SPEC_ORDER；en 保留给映射记录）
    cls_name = p.get("class", "")
    spec_names = [{"name": SPEC_CN.get(en, en), "en": en}
                  for en in CLASS_SPEC_ORDER.get(cls_name, [])]
    spec_scores = [
        {**spec_names[i], "score": float(cur_scores.get(f"spec_{i}", 0) or 0)}
        for i in range(len(spec_names))
    ]

    # 整合同名旧档案：转子战网/删号重建后旧成绩滞留在旧档案。旧档案由高级搜索自动
    # 发现（冻结档案名字带 -旧ID 后缀）；也可手动带 旧档案ID/链接 指定。发现过即记忆。
    integrated = None
    season_slug = season.get("season", "")
    realm_slug = (p.get("realm") or "").lower().replace(" ", "-")
    char_name = p.get("name", "")
    link_key = f"cn/{realm_slug}/{char_name}"
    try:
        links = store.load_json("char_links.json", {}) or {}
    except Exception:  # noqa: BLE001
        links = {}
    old_ids = {str(x) for x in (links.get(link_key) or [])}
    if old_ref:
        old_ids.add(str(old_ref))
    if season_slug:
        live_detail = await _fetch_internal_profile(realm_slug, char_name, season_slug)
        live_det = ((live_detail or {}).get("characterDetails") or {}).get("character") or {}
        live_ms = ((live_detail or {}).get("characterMythicPlusProgress") or {}).get("mythicPlusScores") or {}
        for rid, _nm in await _search_same_name_records(realm_slug, char_name):
            if str(rid) != str(live_det.get("id")):
                old_ids.add(str(rid))
        old_mss: list[tuple[str, dict]] = []
        for oid in sorted(old_ids):
            detail = await _fetch_internal_profile(realm_slug, f"{char_name}-{oid}", season_slug)
            old_det = ((detail or {}).get("characterDetails") or {}).get("character") or {}
            old_ms = ((detail or {}).get("characterMythicPlusProgress") or {}).get("mythicPlusScores")
            if not old_ms:
                continue
            # 名字被他人复用过的旧档案（职业不同）不并
            ocls = old_det.get("class")
            ocls = ocls.get("name") if isinstance(ocls, dict) else ocls
            if ocls and ocls != p.get("class", ""):
                logger.info("旧档案 %s 职业不同（%s），跳过整合", oid, ocls)
                continue
            old_mss.append((oid, old_ms))
        if old_mss:
            integrated = _merge_records(spec_names, live_ms, old_mss, score_all)
    if integrated:
        integrated["old_ids"] = [oid for oid, _ in old_mss]
        want = sorted(old_ids)
        if links.get(link_key) != want:
            links[link_key] = want
            try:
                store.save_json("char_links.json", links)
            except Exception as e:  # noqa: BLE001
                logger.warning("旧档案映射保存失败：%s", e)
        score_dps, score_healer, score_tank = integrated["role_scores"]
        spec_scores = integrated["spec_scores"]
        # 整合分是假想值，raider.io 没有对应实档的 segments.color，按官方分档表取色
        score_color = _score_tier_color(integrated["total"])

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
        "spec_scores": spec_scores,
        "integrated": integrated,
        "score_color": score_color,
        "season_cn": _season_cn(season.get("season", "")),
        "rank_rows": rank_rows,
        "runs": runs,
        "raids": raids,
        "last_crawled": last_crawled,
    }