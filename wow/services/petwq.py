# -*- coding: utf-8 -*-
"""宠物对战世界任务（重量级野兽等）服务：todayinwow.com 美服数据 → 国服时间。

数据源与原理
------------
todayinwow.com 的 /api/wqs 只知道**当前激活**的世界任务（无未来排期）。
军团再临宠物对战世界任务是每日一批、持续 24 小时，全部在美服每日重置时刻
（15:00 UTC = 北京时间 23:00）结束。

美服比国服早 8 小时刷新：美服 23:00（北京时间）刷新的批次，国服要等次日
07:00 重置后才出现，因此：
- 北京时间 23:00–次日 07:00 拉取 → 拿到国服**明早 07:00** 才出现的新批次（预测）
- 北京时间 07:00–23:00 拉取 → 拿到国服**当天 07:00 已刷新**的批次
两种情况共用同一条窗口公式（见 cn_window）。

重量级野兽（Beasts of Burden，41935，风暴峡湾）是通报重点。
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
BOB_CN = "重量级野兽"
BOB_ZONE = "风暴峡湾"
CN_TZ = dt.timezone(dt.timedelta(hours=8))  # 国服 = 北京时间

# 缓存：手动查询与定时推送共用一次抓取（10 分钟）
_cache_at: float = 0
_cache_pets: list[dict] | None = None
_cache_bob_last: dt.datetime | None = None

# 账本：记录重量级野兽每次出现的国服日期，用于「上次出现」展示
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


def cn_window(end_cn: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """美服批次结束时刻（北京时间 23:00）→ 国服可做窗口（次日 07:00 起 24 小时）。

    美服批次于北京时间 D-1 日 23:00 出现、D 日 23:00 结束（end_cn）。
    国服在 D 日 07:00 重置后套用同一批，D+1 日 07:00 结束。
    """
    end_cn = end_cn.astimezone(CN_TZ)
    # end 落在北京 23:00（偶有秒级抖动）；防御：落在凌晨算前一天的批次
    day = end_cn.date() if end_cn.hour >= 12 else (end_cn - dt.timedelta(days=1)).date()
    start = dt.datetime.combine(day, dt.time(7, 0), tzinfo=CN_TZ)
    return start, start + dt.timedelta(days=1)


async def fetch_data() -> tuple[list[dict], dt.datetime | None]:
    """拉取当前激活的宠物任务 + 重量级野兽上次出现时刻（10 分钟缓存）。

    返回 (pets, bob_last)：bob_last 为野兽上次批次的美服结束时刻（国服时区），
    当前正在活跃时即本批结束时刻。
    """
    global _cache_pets, _cache_bob_last, _cache_at
    import time

    now = time.time()
    if _cache_pets is not None and now - _cache_at < 600:
        return _cache_pets, _cache_bob_last
    resp = await post_json(
        WQS_API,
        json_body={"region": "NA", "expansion": "legion"},
        timeout=30,
    )
    pets: list[dict] = []
    bob_last: dt.datetime | None = None
    for q in resp.get("data") or []:
        if q.get("poi_type") != PET_POI:
            continue
        qid = int(q.get("quest_id") or 0)
        end = _to_cn(q.get("end_timestamp") or "")
        if qid == BOB_ID and end is not None:
            bob_last = end
        if q.get("status") != "Active" or end is None:
            continue
        rewards = []
        for r in q.get("rewards") or []:
            nm = reward_cn(r.get("item_name") or "")
            amt = r.get("amount")
            if nm:
                rewards.append(f"{nm} x{amt}" if amt else nm)
        pets.append({
            "quest_id": qid,
            "name_en": q.get("name") or "",
            "name_cn": quest_name_cn(qid, q.get("name") or ""),
            "zone": zone_cn(q.get("zone") or ""),
            "end_cn": end,          # 本批美服结束时刻（国服时区显示）
            "rewards": rewards,
        })
    pets.sort(key=lambda x: x["quest_id"])
    _cache_pets, _cache_bob_last, _cache_at = pets, bob_last, now
    return pets, bob_last


# ---------------------------------------------------------------------------
# 账本（重量级野兽出现记录）
# ---------------------------------------------------------------------------

def record_bob(dates: list[str]) -> None:
    """把出现日期并进账本（去重、保序、只留最近 60 条）。"""
    data = load_json(_LEDGER, {}) or {}
    seen = data.get("dates") or []
    for d in dates:
        if d not in seen:
            seen.append(d)
    seen.sort()
    data["dates"] = seen[-60:]
    save_json(_LEDGER, data)


def bob_last_text() -> str:
    dates = (_bob_last_seen().get("dates") or [])
    if dates:
        d = dt.datetime.strptime(dates[-1], "%Y-%m-%d")
        days_ago = (_now_cn().date() - d.date()).days
        if days_ago <= 0:
            return f"上次重量级野兽：{dates[-1]}（今天）"
        if days_ago == 1:
            return f"上次重量级野兽：{dates[-1]}（昨天）"
        return f"上次重量级野兽：{dates[-1]}（{days_ago} 天前）"
    return "上次重量级野兽：暂无记录"


def _bob_last_seen() -> dict:
    return load_json(_LEDGER, {}) or {}


def _bob_cn_date(end_cn: dt.datetime) -> str:
    """野兽批次美服结束时刻 → 国服出现日期（= 窗口起始日）。"""
    start, _ = cn_window(end_cn)
    return start.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 文案
# ---------------------------------------------------------------------------

def _fmt(t: dt.datetime) -> str:
    return t.strftime("%m-%d %H:%M")


def _remaining(close: dt.datetime) -> str:
    delta = close - _now_cn()
    hours = delta.total_seconds() / 3600
    if hours >= 1:
        return f"（还剩约 {round(hours)} 小时）"
    if hours > 0:
        return f"（还剩约 {int(hours * 60)} 分钟）"
    return ""


def build_text(
    pets: list[dict], bob_last: dt.datetime | None,
    detail: bool = False, push: bool = False,
) -> str | None:
    """组装查询/推送文案。pets 为空返回 None（数据拉取失败由调用方兜底）。"""
    if not pets:
        return None
    # 账本自动补记：数据源给出的最近一次野兽出现（含当前批次）
    if bob_last is not None:
        record_bob([_bob_cn_date(bob_last)])
    end = pets[0]["end_cn"]  # 同批任务结束时刻一致
    start, close = cn_window(end)
    bob = next((p for p in pets if p["quest_id"] == BOB_ID), None)

    lines = []
    if bob:
        lines.append(f"**🔥 {BOB_CN}预警**" if push else f"**🔥 今天国服有「{BOB_CN}」！**（{BOB_ZONE}）")
    else:
        lines.append("**🐾 国服宠物对战世界任务**" if push else "**🐾 宠物对战世界任务**")
    lines.append(f"可做时间：**{_fmt(start)} – {_fmt(close)}**（国服时间）{_remaining(close)}")
    if bob:
        lines.append("")
        lines.append(f"「{BOB_CN}」在{BOB_ZONE}，今天记得做！")
    lines.append("")
    lines.append(f"本批任务（{len(pets)} 个）：")
    for p in pets:
        r = f"（{'、'.join(p['rewards'][:3])}）" if (detail and p["rewards"]) else ""
        lines.append(f"· **{p['name_cn']}** {p['zone']}{r}")
    if not detail and any(p["rewards"] for p in pets):
        lines.append("\n发「宠物 详情」看奖励明细")
    lines.append("")
    lines.append(bob_last_text())
    return "\n".join(lines)


async def query_text(detail: bool = False) -> str:
    """手动查询：当前批次 + 国服窗口 + 上次野兽出现时间。"""
    pets, bob_last = await fetch_data()
    text = build_text(pets, bob_last, detail=detail)
    if text is None:
        return "暂时拉不到宠物对战世界任务数据（todayinwow.com），请稍后再试"
    return text


async def push_text() -> str | None:
    """每日推送文案（16:05）：通报当前批次；有重量级野兽时加预警横幅。"""
    try:
        pets, bob_last = await fetch_data()
    except Exception as e:  # noqa: BLE001
        logger.warning("[petwq] 拉取宠物任务失败: %s", e)
        return None
    return build_text(pets, bob_last, push=True)
