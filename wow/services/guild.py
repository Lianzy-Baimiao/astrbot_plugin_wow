# -*- coding: utf-8 -*-
"""公会与团本排行（wowguild）服务。"""

from __future__ import annotations

import datetime as dt
import logging

from ..net import fetch_json
from ..raiderio import guild_profile, raid_rankings, raid_static_data
from ..wago import raid_names

logger = logging.getLogger("astrbot_plugin_wow.guild")

DIFFICULTY_MAP = {"史诗": "mythic", "m": "mythic", "英雄": "heroic", "h": "heroic", "普通": "normal", "n": "normal", "随机": "lfr", "lfr": "lfr"}
DIFFICULTY_CN = {"mythic": "史诗", "heroic": "英雄", "normal": "普通", "lfr": "随机"}

# 职业英文 slug -> 中文（分布展示用）
CLASS_CN_EN = {
    "Warrior": "战士", "Paladin": "圣骑士", "Hunter": "猎人", "Rogue": "潜行者",
    "Priest": "牧师", "Death Knight": "死亡骑士", "Shaman": "萨满", "Mage": "法师",
    "Warlock": "术士", "Monk": "武僧", "Druid": "德鲁伊",
    "Demon Hunter": "恶魔猎手", "Evoker": "唤魔师",
}


def _rank_triple(r: dict, key: str) -> tuple[int, int, int]:
    """取难度排名的 (world, region, realm)，无排名返回全 0。"""
    rr = (r.get(key) or {})
    return int(rr.get("world", 0) or 0), int(rr.get("region", 0) or 0), int(rr.get("realm", 0) or 0)


async def fetch_guild_card(name: str, realm: str) -> dict:
    """公会资料卡数据（含团本 N/H/M 击杀与难度排名、职业分布）。"""
    try:
        g = await guild_profile(name, realm)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"公会查询失败：{e}") from e
    if not g.get("name"):
        raise RuntimeError(f"未找到公会 {name}〈{realm}〉")
    progression = g.get("raid_progression") or {}
    raids_map = await raid_names()
    members = g.get("members") or []
    class_dist: dict[str, int] = {}
    for m in members:
        cls = (m.get("character") or {}).get("class", "未知")
        class_dist[cls] = class_dist.get(cls, 0) + 1
    # 只保留有击杀、且信息足够的团本
    raids = []
    for slug, prog in progression.items():
        total = int(prog.get("total_bosses", 0) or 0)
        n = int(prog.get("normal_bosses_killed", 0) or 0)
        h = int(prog.get("heroic_bosses_killed", 0) or 0)
        m = int(prog.get("mythic_bosses_killed", 0) or 0)
        if total <= 0 or (n + h + m) == 0:
            continue
        # 排名取已有击杀的最高难度
        rk = (g.get("raid_rankings") or {}).get(slug) or {}
        tag, rw, rg, rr = "", 0, 0, 0
        if m > 0:
            w, rg_, rr_ = _rank_triple(rk, "mythic")
            if w > 0:
                tag, rw, rg, rr = "M", w, rg_, rr_
        if not tag and h > 0:
            w, rg_, rr_ = _rank_triple(rk, "heroic")
            if w > 0:
                tag, rw, rg, rr = "H", w, rg_, rr_
        if not tag and n > 0:
            w, rg_, rr_ = _rank_triple(rk, "normal")
            if w > 0:
                tag, rw, rg, rr = "N", w, rg_, rr_
        raids.append({
            "slug": slug,
            "name": raids_map.get(slug) or slug.replace("-", " "),
            "total": total, "n": n, "h": h, "m": m,
            "rank_tag": tag, "rank_world": rw, "rank_region": rg, "rank_realm": rr,
        })
    raids.sort(key=lambda r: r["total"], reverse=True)
    crawled_t = _parse_rfc3339(g.get("last_crawled_at", ""))
    returned = {
        "name": g.get("name", name),
        "realm": g.get("realm", realm),
        "region": g.get("region", "cn"),
        "faction": g.get("faction", ""),
        "achievement_points": g.get("achievement_points", 0),
        "last_crawled": crawled_t.strftime("%Y-%m-%d %H:%M") if crawled_t else "",
        "members": len(members),
        "raids": raids,
        "class_dist": class_dist,
        "profile_url": g.get("profile_url", ""),
    }
    return returned


def _parse_rfc3339(s: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return None


async def fetch_rank_card(difficulty: str | None = None, raid_keyword: str | None = None) -> dict:
    """团本排行卡数据（含阵营、通关日期、世界排名）。"""
    raids = await raid_static_data(expansion_id=11)
    if not raids:
        raise RuntimeError("团本列表获取失败")
    raids_sorted = sorted(raids, key=lambda r: r.get("order", 0))
    # 找"当前开放且 Boss 最多"的团本
    target = None
    if raid_keyword:
        for r in raids_sorted:
            slug = r.get("slug", "")
            en = r.get("name", "")
            short = r.get("short_name", "")
            if (
                raid_keyword in slug
                or raid_keyword in en
                or raid_keyword in short
                or raid_keyword in _raid_short_cn.get(slug, "")
            ):
                target = r
                break
        if not target:
            raise RuntimeError(f"未找到团本：{raid_keyword}")
    else:
        candidates = [r for r in raids_sorted if r.get("bosses")]
        target = max(candidates, key=lambda r: len(r.get("bosses", []))) if candidates else raids_sorted[-1]

    diff = DIFFICULTY_MAP.get((difficulty or "").strip().lower())
    if not diff:
        diff = "mythic"
    slug = target.get("slug", "")
    try:
        rankings = await raid_rankings(slug, diff, limit=20)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"团本排行查询失败：{e}") from e
    rows = []
    for rank in rankings:
        guild = rank.get("guild") or {}
        realm = guild.get("realm") or {}
        last_kill = ""
        worst = None
        for d in rank.get("encountersDefeated") or []:
            t = _parse_rfc3339(d.get("firstDefeated", ""))
            if t and (worst is None or t > worst):
                worst = t
        if worst:
            last_kill = worst.strftime("%m-%d")
        rows.append(
            {
                "rank": rank.get("rank", 0),
                "guild": guild.get("name", ""),
                "realm": realm.get("name") or realm.get("altName", "") or "",
                "faction": guild.get("faction", ""),
                "score": rank.get("score", ""),
                "progress": rank.get("progress", ""),
                "killed": len(rank.get("encountersDefeated") or []),
                "last_kill": last_kill,
            }
        )
    return {
        "raid": target.get("name", slug),
        "slug": slug,
        "difficulty": DIFFICULTY_CN.get(diff, diff),
        "rows": rows,
    }


# 常用团本简称（防中文检索失效）
_raid_short_cn = {
    "liberation-of-undermine": "解放安德麦",
    "nerubar-palace": "尼鲁巴尔王宫",
    "amirdrassil": "阿梅达希尔",
    "aberration-of-the-void": "虚空根源",
    "vault-of-the-incarnates": "化身巨龙牢窟",
    "castle-nathria": "纳斯利亚堡",
}