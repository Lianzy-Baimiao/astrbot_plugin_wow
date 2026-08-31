# -*- coding: utf-8 -*-
"""raider.io v1 API 客户端。"""

from __future__ import annotations

import logging
import time

from .net import fetch_json, post_json

logger = logging.getLogger("astrbot_plugin_wow.raiderio")

BASE = "https://raider.io/api/v1"
UA = "ZeroBot-Plugin-wow-astrbot/1.0"

_affix_cache: dict | None = None
_affix_at: float = 0
_period_cache: dict | None = None
_period_at: float = 0


async def character_profile(
    name: str, realm: str, fields: str = ""
) -> dict:
    """角色资料。fields 示例：gear,guild,raid_progression,mythic_plus_ranks,..."""
    params = {"region": "cn", "realm": realm, "name": name}
    if fields:
        params["fields"] = fields
    try:
        return await fetch_json(
            f"{BASE}/characters/profile", params=params, headers={"User-Agent": UA}
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"raider.io 角色查询失败：{e}") from e


async def guild_profile(name: str, realm: str, fields: str = "raid_progression,raid_rankings,members") -> dict:
    try:
        return await fetch_json(
            f"{BASE}/guilds/profile",
            params={"region": "cn", "realm": realm, "name": name, "fields": fields},
            headers={"User-Agent": UA},
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"raider.io 公会查询失败：{e}") from e


async def raid_static_data(expansion_id: int = 11) -> list[dict]:
    try:
        data = await fetch_json(
            f"{BASE}/raiding/static-data",
            params={"expansion_id": expansion_id},
            headers={"User-Agent": UA},
        )
        return data.get("raids", []) if isinstance(data, dict) else []
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"raider.io 团本列表获取失败：{e}") from e


async def raid_rankings(raid: str, difficulty: str, limit: int = 20, page: int = 0) -> list[dict]:
    try:
        data = await fetch_json(
            f"{BASE}/raiding/raid-rankings",
            params={
                "raid": raid, "difficulty": difficulty,
                "region": "cn", "limit": limit, "page": page,
            },
            headers={"User-Agent": UA},
        )
        if isinstance(data, dict):
            return data.get("raidRankings", []) or data.get("rankings", [])
        return []
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"raider.io 团本排行查询失败：{e}") from e


async def current_affixes() -> list[dict]:
    """本周词缀（返回 affix_details 列表）。"""
    global _affix_cache, _affix_at
    now = time.time()
    if _affix_cache and now - _affix_at < 300:
        return _affix_cache
    data = await fetch_json(
        f"{BASE}/mythic-plus/affixes",
        params={"region": "cn", "locale": "en"},
        headers={"User-Agent": UA},
    )
    details = data.get("affix_details", []) if isinstance(data, dict) else []
    if not details:
        raise RuntimeError("词缀数据为空")
    _affix_cache, _affix_at = details, now
    return details


async def cn_period_end() -> str:
    """国服当前周期结束时间（RFC3339）。"""
    global _period_cache, _period_at
    now = time.time()
    if _period_cache and now - _period_at < 300:
        return _period_cache
    data = await fetch_json(f"{BASE}/periods", headers={"User-Agent": UA})
    for p in data.get("periods", []):
        if p.get("region") == "cn":
            end = p["current"]["end"]
            _period_cache, _period_at = end, now
            return end
    raise RuntimeError("未找到国服周期")