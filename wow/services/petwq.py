# -*- coding: utf-8 -*-
"""宠物对战世界任务（重量级野兽等）服务：todayinwow.com 美服数据 → 国服预测。

数据源与原理
------------
todayinwow.com 的 /api/wqs 只知道**当前激活**的世界任务（无未来排期）。
军团再临宠物对战世界任务是每日一批、持续 24 小时，全部在美服每日重置时刻
（15:00 UTC，夏令时固定；国服换算成北京时间 23:00）一起结束。

美服比国服早 8 小时进入「下一天」：美服 23:00（北京时间）刷新的这批任务，
国服要等到次日 07:00 重置后才会出现——但**任务是同一批**。所以：

    北京时间每天 23:00 后（16 点美服当前 = 次日 0 点北京前，16 点后必然已刷新）
    拉一次美服「当前激活」的宠物任务，就能预测国服明天 07:00–23:00 的任务。

重量级野兽（Beasts of Burden，41935）是其中最值得通报的（驯龙手册日常热点）。
"""

from __future__ import annotations

import datetime as dt
import logging

from ..data.petquests import quest_name_cn, reward_cn, zone_cn
from ..net import post_json
from ..store import load_json, save_json

logger = logging.getLogger("astrbot_plugin_wow.petwq")

WQS_API = "https://www.todayinwow.com/api/wqs"
PET_POI = "worldquest-icon-petbattle"
BOB_ID = 41935  # Beasts of Burden = 重量级野兽
CN_TZ = dt.timezone(dt.timedelta(hours=8))  # 国服 = 北京时间

# 缓存：手动查询与定时推送共用一次抓取（10 分钟）
_cache_at: float = 0
_cache: list[dict] | None = None

# 历史账本：记录重量级野兽每次出现（北京时间日期串），用于「上次出现」展示
_LEDGER = "petwq_bob_seen.json"


def _now_cn() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def _to_cn(ts: str) -> dt.datetime | None:
    """ISO 时间串（UTC）→ 国服时刻。"""
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t.astimezone(CN_TZ)
    except ValueError:
        return None


async def fetch_active_pets(region: str = "NA") -> list[dict]:
    """拉取当前激活的宠物对战世界任务（美服），返回规范化列表。"""
    global _cache, _cache_at
    import time

    now = time.time()
    if _cache is not None and now - _cache_at < 600:
        return _cache
    resp = await post_json(
        WQS_API,
        json_body={"region": region, "expansion": "legion"},
        timeout=30,
    )
    quests = []
    for q in resp.get("data") or []:
        if q.get("poi_type") != PET_POI or q.get("status") != "Active":
            continue
        end = _to_cn(q.get("end_timestamp") or "")
        if end is None:
            continue
        rewards = []
        for r in q.get("rewards") or []:
            nm = reward_cn(r.get("item_name") or "")
            amt = r.get("amount")
            if nm:
                rewards.append(f"{nm} x{amt}" if amt else nm)
        quests.append({
            "quest_id": int(q.get("quest_id") or 0),
            "name_en": q.get("name") or "",
            "name_cn": quest_name_cn(int(q.get("quest_id") or 0), q.get("name") or ""),
            "zone": zone_cn(q.get("zone") or ""),
            "end_cn": end,          # 美服结束时刻（国服时区显示）
            "rewards": rewards,
        })
    quests.sort(key=lambda x: x["quest_id"])
    _cache, _cache_at = quests, now
    return quests


def _fmt(t: dt.datetime) -> str:
    return t.strftime("%m-%d %H:%M")


def cn_window(end_cn: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """由美服结束时刻推国服可做窗口。

    美服批次在北京时间 D 日 23:00 结束（= 新批次出现）。该批任务在国服
    D+1 日 07:00 重置后出现、D+1 日 23:00 结束（国服只保留重置后的 16 小时）。
    """
    start = (end_cn + dt.timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    close = (end_cn + dt.timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
    return start, close


def _bob_last_seen() -> dict:
    """账本：{dates: [...]} 记录重量级野兽历次出现（北京时间日期）。"""
    return load_json(_LEDGER, {}) or {}


def record_bob(dates: list[str]) -> None:
    """把本轮观察到的出现日期并进账本（去重、保序）。"""
    data = _bob_last_seen()
    seen = data.get("dates") or []
    for d in dates:
        if d not in seen:
            seen.append(d)
    seen.sort()
    data["dates"] = seen[-60:]  # 只留最近 60 次
    save_json(_LEDGER, data)


def bob_last_text() -> str:
    """「上次重量级野兽出现」文案（基于账本 + 数据源 last-seen 兜底）。"""
    dates = (_bob_last_seen().get("dates") or [])
    if dates:
        d = dt.datetime.strptime(dates[-1], "%Y-%m-%d")
        days_ago = (_now_cn().date() - d.date()).days
        if days_ago <= 0:
            return f"上次出现：{dates[-1]}（今天）"
        if days_ago == 1:
            return f"上次出现：{dates[-1]}（昨天）"
        return f"上次出现：{dates[-1]}（{days_ago} 天前）"
    return "上次出现：暂无记录"


def _quests_text(pets: list[dict], start: dt.datetime, close: dt.datetime) -> str:
    lines = []
    for p in pets:
        nm = p["name_cn"] if p["name_cn"] != p["name_en"] else p["name_en"]
        r = f"（{'、'.join(p['rewards'][:3])}）" if p["rewards"] else ""
        lines.append(f"· **{nm}** {p['zone']}{r}")
    return "\n".join(lines)


async def query_text(detail: bool = False) -> str:
    """手动查询文本：当前美服激活的宠物任务 + 国服预测窗口。

    detail=True 时带奖励明细。
    """
    pets = await fetch_active_pets()
    if not pets:
        return "暂时拉不到宠物对战世界任务数据（todayinwow.com），请稍后再试"
    end = pets[0]["end_cn"]  # 同批任务结束时刻一致
    start, close = cn_window(end)
    bob = next((p for p in pets if p["quest_id"] == BOB_ID), None)
    lines = ["**🐾 宠物对战世界任务（预测）**"]
    lines.append(f"数据源：美服当前激活（国服 {_fmt(start)} – {_fmt(close)} 可做）")
    if bob:
        lines.append("")
        lines.append("**🔥 明天国服有「重量级野兽」！**（风暴峡湾，囤驯龙手册日常）")
    lines.append("")
    lines.append(f"今日批次（{len(pets)} 个）：")
    lines.append(_quests_text(pets, start, close))
    if not detail and any(p["rewards"] for p in pets):
        lines.append("\n发「宠物 详情」看奖励明细")
    lines.append("")
    lines.append(bob_last_text())
    return "\n".join(lines)


async def push_check() -> str | None:
    """定时推送检查：返回推送文本，无重量级野兽时返回 None。

    每天北京时间 16:03 调用（美服 16:00 后数据必然已刷新，即次日国服批次）。
    """
    pets = await fetch_active_pets()
    if not pets:
        logger.warning("[petwq] 拉取宠物任务失败，本轮跳过")
        return None
    bob = next((p for p in pets if p["quest_id"] == BOB_ID), None)
    if bob is None:
        return None
    end = pets[0]["end_cn"]
    start, close = cn_window(end)
    # 记账：以「国服可做日」为准
    record_bob([start.strftime("%Y-%m-%d")])
    lines = [
        "**🔥 重量级野兽预警**",
        "",
        "明天国服刷新「重量级野兽」宠物世界任务（风暴峡湾）！",
        f"可做时间：**{_fmt(start)} – {_fmt(close)}**（国服时间）",
        "",
        "驯龙手册日常别错过，明早 7 点后去风暴峡湾。",
        "",
        f"同批宠物任务（{len(pets)} 个）：",
        _quests_text(pets, start, close),
    ]
    return "\n".join(lines)
