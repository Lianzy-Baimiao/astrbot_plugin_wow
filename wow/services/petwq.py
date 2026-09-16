# -*- coding: utf-8 -*-
"""宠物对战世界任务（重量级野兽等）服务：todayinwow.com 美服数据 → 国服预测。

数据源与原理
------------
todayinwow.com 的 /api/wqs 只知道**当前激活**的世界任务（无未来排期）。
军团再临宠物对战世界任务是每日一批、持续 24 小时，全部在美服每日重置时刻
（15:00 UTC = 北京时间 23:00）结束。

国服比美服晚套用一批：每个批次在美服结束后 8 小时，国服才在次日上午 07:00
重置时开始同一批（美服 16 点 = 北京早上 7 点查到的当前批次，是国服**下一天
07:00** 才开始的）。所以任何时刻查美服「当前」都是对国服的预测：
- 白天（北京 07:00–23:00）查 → 国服**明天** 07:00 的批次
- 夜里（北京 23:00–次日 07:00）查 → 国服**后天** 07:00 的批次（美服刚刷的新批）

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

# 缓存：手动查询与定时推送共用一次抓取（10 分钟）。
# _cache_all 存 (quest, end_cn) 原始对，可按结束日反复过滤而不重抓。
_cache_at: float = 0
_cache_all: list[tuple[dict, dt.datetime]] | None = None
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
    """美服批次结束时刻（北京时间 23:00）→ 国服可做窗口（结束后次日上午 07:00 起 24 小时）。

    美服批次于北京时间 D 日 23:00 结束（end_cn）；国服在 D+1 日 07:00 重置时
    才开始同一批，D+2 日 07:00 结束。
    """
    end_cn = end_cn.astimezone(CN_TZ)
    # end 落在北京 23:00（偶有秒级抖动）；防御：落在凌晨算前一天的批次
    day = end_cn.date() if end_cn.hour >= 12 else (end_cn - dt.timedelta(days=1)).date()
    start = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(7, 0), tzinfo=CN_TZ)
    return start, start + dt.timedelta(days=1)


async def fetch_data(target_end_day: dt.date | None = None) -> tuple[list[dict], dt.datetime | None]:
    """拉取宠物任务 + 重量级野兽上次出现时刻（10 分钟缓存）。

    返回 (pets, bob_last)：bob_last 为野兽上次批次的美服结束时刻（国服时区），
    当前正在活跃时即本批结束时刻。

    target_end_day：只保留美服结束时刻落在北京该日（默认 23:00 前后）的任务。
    None = 不过滤（当前 Active 的批次）。数据源偶发**提前翻页**（如北京 15:30 就
    把 Active 换成明晚结束的下一批）时，上一批任务仍留在返回里、状态变为其结束
    时刻字符串——按结束日过滤就能把「今晚结束的那批」（= 国服明天的批次）捞回来。
    """
    global _cache_pets, _cache_bob_last, _cache_all, _cache_at
    import time

    now = time.time()
    if _cache_all is not None and now - _cache_at < 600:
        raw = _cache_all
    else:
        resp = await post_json(
            WQS_API,
            json_body={"region": "NA", "expansion": "legion"},
            timeout=30,
        )
        raw = []
        for q in resp.get("data") or []:
            if q.get("poi_type") != PET_POI:
                continue
            end = _to_cn(q.get("end_timestamp") or "")
            if end is None:
                continue
            raw.append((q, end))
        _cache_all = raw
        _cache_at = now

    def _row(q: dict, end: dt.datetime) -> dict:
        rewards = []
        for r in q.get("rewards") or []:
            nm = reward_cn(r.get("item_name") or "")
            amt = r.get("amount")
            if nm:
                rewards.append(f"{nm} x{amt}" if amt else nm)
        return {
            "quest_id": int(q.get("quest_id") or 0),
            "name_en": q.get("name") or "",
            "name_cn": quest_name_cn(int(q.get("quest_id") or 0), q.get("name") or ""),
            "zone": zone_cn(q.get("zone") or ""),
            "end_cn": end,          # 本批美服结束时刻（国服时区显示）
            "rewards": rewards,
        }

    pets: list[dict] = []
    bob_last: dt.datetime | None = None
    for q, end in raw:
        qid = int(q.get("quest_id") or 0)
        if qid == BOB_ID:
            bob_last = end
        # 归一化结束日：end 常落在北京 23:00（偶有秒级抖动）；凌晨落前一天的批次
        day = end.date() if end.hour >= 12 else (end - dt.timedelta(days=1)).date()
        if target_end_day is not None and day != target_end_day:
            continue
        if q.get("status") != "Active" and target_end_day is None:
            continue
        pets.append(_row(q, end))
    pets.sort(key=lambda x: x["quest_id"])
    _cache_pets, _cache_bob_last = pets, bob_last
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


def _rel_day(d: dt.date) -> str:
    n = (d - _now_cn().date()).days
    if n == 0:
        return "今天"
    if n == 1:
        return "明天"
    if n == 2:
        return "后天"
    return d.strftime("%m-%d")


def _window_status(start: dt.datetime, close: dt.datetime) -> str:
    now = _now_cn()
    if now < start:
        return f"（{_rel_day(start.date())} 07:00 开始）"
    if now < close:
        hours = (close - now).total_seconds() / 3600
        if hours >= 1:
            return f"（还剩约 {round(hours)} 小时）"
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
    rel = _rel_day(start.date())
    bob = next((p for p in pets if p["quest_id"] == BOB_ID), None)

    lines = []
    if bob:
        lines.append(f"**🔥 {BOB_CN}预警（国服{rel}）**")
    else:
        lines.append(f"**🐾 宠物对战世界任务（国服{rel}）**")
    lines.append(f"可做时间：**{_fmt(start)} – {_fmt(close)}**（国服时间）{_window_status(start, close)}")
    if bob:
        lines.append("")
        lines.append(f"「{BOB_CN}」在{BOB_ZONE}，{rel} 07:00 重置后可做！")
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
    pets, bob_last = await fetch_data()  # 不过滤：当前 Active 批次
    text = build_text(pets, bob_last, detail=detail)
    if text is None:
        return "暂时拉不到宠物对战世界任务数据（todayinwow.com），请稍后再试"
    return text


async def push_text() -> str | None:
    """每日推送文案（16:05）：通报国服明天的批次；有重量级野兽时加预警横幅。

    国服明天的批次 = **今晚**（北京 23:00）美服结束的那批。按结束日过滤而不是
    只看 Active：数据源偶发提前翻页时（Active 已换成明晚结束的下一批），今晚
    结束的那批仍留在历史记录里，按结束日照样捞得回来，不会漏推/推错。
    """
    try:
        today = _now_cn().date()
        pets, bob_last = await fetch_data(target_end_day=today)
    except Exception as e:  # noqa: BLE001
        logger.warning("[petwq] 拉取宠物任务失败: %s", e)
        return None
    if not pets:
        # 兜底：极端情况（历史记录也丢了今晚那批）退回 Active 批次
        try:
            pets, bob_last = await fetch_data()
        except Exception as e:  # noqa: BLE001
            logger.warning("[petwq] 拉取宠物任务失败: %s", e)
            return None
    return build_text(pets, bob_last, push=True)
