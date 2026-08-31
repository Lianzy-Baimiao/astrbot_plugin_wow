# -*- coding: utf-8 -*-
"""开箱抽奖（wowgacha）服务。"""

from __future__ import annotations

from ..data.gacha import roll_item_name, roll_quality
from ..store import get_gacha_store


def roll_once() -> dict:
    q = roll_quality()
    return {"name": roll_item_name(q), "quality": q["name"], "color": q["color"], "score": q["score"]}


def open_boxes(count: int = 1) -> dict:
    rows = [roll_once() for _ in range(count)]
    total = sum(r["score"] for r in rows)
    return {"rows": rows, "total": total}


def add_score(gid: str, uid: str, total: int, nick: str = "") -> tuple[int, int]:
    return get_gacha_store().add(str(gid), str(uid), total, nick)


def rank_top(gid: str, limit: int = 10) -> list[dict]:
    return get_gacha_store().top(str(gid), limit)