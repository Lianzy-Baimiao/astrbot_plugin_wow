# -*- coding: utf-8 -*-
"""bestkeystone.com API：大米限时成功率。"""

from __future__ import annotations

import datetime as dt
import logging

from .net import fetch_json

logger = logging.getLogger("astrbot_plugin_wow.bestkeystone")

BASE_URL = "https://bestkeystone.com"

DUNGEON_NAME_MAP = {
    161: "通天峰",
    239: "执政团",
    247: "暴富矿区",
    370: "车车车间",
    378: "赎罪",
    382: "伤逝剧场",
    391: "天街",
    392: "宏图",
    402: "学院",
    499: "修院",
    500: "驭雷栖巢",
    503: "回响",
    504: "暗焰裂口",
    505: "破船",
    506: "燧酿酒庄",
    525: "水闸",
    542: "圆顶",
    556: "萨隆矿坑",
    557: "风行者",
    558: "魔导师",
    559: "节点",
    560: "洞窟",
    584: "夺目谷",
    585: "虚空之痕竞技场",
    586: "纳洛拉克的洞穴",
    587: "密谋小径",
    588: "毒牙祭坛",
    399: "红玉新生法池",
    250: "塞塔里斯神庙",
    249: "诸王之眠",
}


def current_period() -> int:
    """从 2005-12-27 起算的周数（与原实现一致）。"""
    base = dt.datetime(2005, 12, 27, 23, 0)
    return int((dt.datetime.now() - base).total_seconds() / 86400 / 7)


async def fetch_dungeon_names() -> dict[int, str]:
    """动态副本名元数据（keystone_id → 名称）。"""
    data = await fetch_json(f"{BASE_URL}/api/Dungeon/all")
    names: dict[int, str] = {}
    for d in data or []:
        name = (d.get("dungeon_name") or d.get("name") or "").strip()
        if name and d.get("keystone_id"):
            names[int(d["keystone_id"])] = name
    return names


async def ontime_rate(min_level: int = 12) -> list[dict]:
    """限时成功率（按成功率降序），返回带中文名的行。"""
    periode = current_period()
    try:
        names = await fetch_dungeon_names()
    except Exception as e:  # noqa: BLE001
        logger.warning("获取副本名称失败，将使用内置名称: %s", e)
        names = {}
    url = (
        f"{BASE_URL}/api/Dungeon/ontimerate?periode={periode}"
        f"&min_level={min_level}&amount=50000&limitToLowestDungeon=false"
    )
    data = await fetch_json(url)
    rows = []
    for d in data or []:
        did = int(d.get("id", 0))
        name = DUNGEON_NAME_MAP.get(did) or names.get(did) or f"未知副本 ({did})"
        rows.append(
            {
                "id": did,
                "name": name,
                "on_time_percent": float(d.get("ontime_percent", 0) or 0),
                "total_runs": int(d.get("total_runs", 0) or 0),
            }
        )
    rows.sort(key=lambda r: r["on_time_percent"], reverse=True)
    return rows