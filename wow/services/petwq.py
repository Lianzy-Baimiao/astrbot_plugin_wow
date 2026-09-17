# -*- coding: utf-8 -*-
"""宠物对战世界任务（重量级野兽等）服务：todayinwow.com 欧服数据 → 国服预测。

数据源与原理
------------
todayinwow.com 的 /api/wqs 只知道**当前激活**的世界任务（无未来排期）。
军团再临宠物对战世界任务是每日一批、持续 24 小时。

取 **EU（欧服）** 数据（2026-09-16 起改用，比原美服源提前 11 小时拿新批）：
- EU 与 NA 同批（实测两边 Active 的 quest_id 完全一致）
- EU 每日重置 04:00 UTC = **北京 12:00** 切批（NA 是北京 23:00）
- 国服与同批窗口错位 8 小时：批 D-1 日 12:00 ~ D 日 12:00（EU 视角）→ 国服同批
  D 日 07:00 ~ D+1 日 07:00（07:00 对齐国服每日重置）
- 所以北京 12:05（EU 切批后）拉 Active = 国服**明天** 07:00 开始的批次
  ——推送做到提前 19 小时预告

模型（2026-09-16 实测定稿）：EU 批次 end（北京时间 E 时刻）→ 国服同批窗口
= end 所在日 07:00 ~ 次日 07:00。手动查询任何时刻都看 Active（国服今天
07:00 已开始的批次）。

重量级野兽（Beasts of Burden，41935，风暴峡湾）是通报重点。
"""

from __future__ import annotations

import datetime as dt
import logging

from ..data.petquests import quest_name_cn, zone_cn
from ..net import post_json
from ..store import load_json, save_json

logger = logging.getLogger("astrbot_plugin_wow.petwq")

WQS_API = "https://www.todayinwow.com/api/wqs"
WQS_REGION = "EU"  # 欧服：北京 12:00 切批，比美服早 11 小时拿到国服明天的新批
PET_POI = "worldquest-icon-petbattle"
BOB_ID = 41935  # Beasts of Burden = 重量级野兽（风暴峡湾）
BOB_CN = "重量级野兽"
CN_TZ = dt.timezone(dt.timedelta(hours=8))  # 国服 = 北京时间

# 缓存：手动查询与定时推送共用一次抓取（10 分钟）。
# _cache_all 存 (quest, end_cn) 原始对，可按结束日反复过滤而不重抓。
_cache_at: float = 0
_cache_all: list[tuple[dict, dt.datetime]] | None = None
_cache_pets: list[dict] | None = None
_cache_bob_last: dt.datetime | None = None

# 账本：记录重量级野兽每次出现的国服日期，用于「上次出现」展示
_LEDGER = "petwq_bob_seen.json"
# 推送状态：记录「哪天已推过明日预告」，避免轮询重复推送（跨重启保持）
_PUSH_STATE = "petwq_push_day.json"
# v1.1.16~v1.1.20 的旧模型把国服窗口算成 end+1 日，账本日期整体晚了一天。
# 2026-09-16 定稿模型（窗口 = end 所在日 07:00）后，首次读到旧账本时平移回来。
_LEDGER_OLD_MODEL_UNTIL = "2026-09-16"


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
    """EU 批次结束时刻（北京时间 12:00）→ 国服可做窗口（**同一批**，窗口错位）。

    EU 批次：D-1 日 12:00 ~ D 日 12:00（end_cn = D 日 12:00）；
    国服同批：D 日 07:00 ~ D+1 日 07:00（07:00 对齐国服每日重置）。
    2026-09-16 实测定稿（NA 数据验证同批）：国服上午正在做的就是 Active 批（弗鲁莫斯等 5 个），
    剩余约 22h（= D 日 07:00 起算），并非「等美服结束后次日后才开始」。
    """
    end_cn = end_cn.astimezone(CN_TZ)
    # EU 切批落在北京 12:00（偶有秒级抖动）；防御：落在凌晨/上午算前一天的批次
    day = end_cn.date() if end_cn.hour >= 12 else (end_cn - dt.timedelta(days=1)).date()
    start = dt.datetime.combine(day, dt.time(7, 0), tzinfo=CN_TZ)
    return start, start + dt.timedelta(days=1)


async def fetch_data(
    target_end_day: dt.date | None = None, force: bool = False
) -> tuple[list[dict], dt.datetime | None]:
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
    if not force and _cache_all is not None and now - _cache_at < 600:
        raw = _cache_all
    else:
        resp = await post_json(
            WQS_API,
            json_body={"region": WQS_REGION, "expansion": "legion"},
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
        return {
            "quest_id": int(q.get("quest_id") or 0),
            "name_en": q.get("name") or "",
            "name_cn": quest_name_cn(int(q.get("quest_id") or 0), q.get("name") or ""),
            "zone": zone_cn(q.get("zone") or ""),
            "end_cn": end,          # 本批 EU 结束时刻（国服时区显示）
        }

    pets: list[dict] = []
    bob_last: dt.datetime | None = None
    for q, end in raw:
        qid = int(q.get("quest_id") or 0)
        if qid == BOB_ID:
            bob_last = end
        # 归一化批次日：EU 切批落在北京 12:00（偶有秒级抖动）；下午/夜里算当天批次
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
    """把出现日期并进账本（去重、保序、只留最近 60 条）。

    先触发一次 _bob_last_seen()：旧模型的日期要在**本函数写入新日期之前**完成平移，
    否则首次运行时会把自己刚写入的正确日期也平移一天（旧账本 vs 新写入同一个文件）。
    """
    _bob_last_seen()  # 先迁移旧账本（见 docstring 的说明）
    data = load_json(_LEDGER, {}) or {}
    seen = data.get("dates") or []
    for d in dates:
        if d not in seen:
            seen.append(d)
    seen.sort()
    data["dates"] = seen[-60:]
    # 本函数写入的都是新模型日期：打上 migrated 标记，避免后续读取时被当成旧模型值平移
    data["migrated"] = True
    save_json(_LEDGER, data)


def bob_last_text() -> str:
    """「上次重量级野兽」尾行；日期只写月-日，与正文口径一致。"""
    dates = (_bob_last_seen().get("dates") or [])
    if dates:
        d = dt.datetime.strptime(dates[-1], "%Y-%m-%d")
        md = d.strftime("%m-%d")
        days_ago = (_now_cn().date() - d.date()).days
        if days_ago < 0:
            return f"上次重量级野兽：{md}（{_rel_day(d.date())}）"
        if days_ago == 0:
            return f"上次重量级野兽：{md}（今天）"
        if days_ago == 1:
            return f"上次重量级野兽：{md}（昨天）"
        return f"上次重量级野兽：{md}（{days_ago} 天前）"
    return "上次重量级野兽：暂无记录"


def today_str() -> str:
    """国服今天的日期串（YYYY-MM-DD）。"""
    return _now_cn().date().isoformat()


def pushed_day() -> str:
    """已推送明日预告的日期；未推过返回空串。"""
    return str((load_json(_PUSH_STATE, {}) or {}).get("date", ""))


def mark_pushed(day: str) -> None:
    save_json(_PUSH_STATE, {"date": day})


def _bob_last_seen() -> dict:
    """读账本；v1.1.20 及之前按旧模型（晚一天）写入的日期平移一天。"""
    data = load_json(_LEDGER, {}) or {}
    dates = data.get("dates") or []
    if dates and not data.get("migrated"):
        shift = []
        for d in dates:
            if d <= _LEDGER_OLD_MODEL_UNTIL:
                try:
                    t = dt.datetime.strptime(d, "%Y-%m-%d") - dt.timedelta(days=1)
                    shift.append(t.strftime("%Y-%m-%d"))
                except ValueError:
                    shift.append(d)
            else:
                shift.append(d)
        data["dates"] = sorted(set(shift))[-60:]
        data["migrated"] = True
        save_json(_LEDGER, data)
    return data


def _bob_cn_date(end_cn: dt.datetime) -> str:
    """野兽批次美服结束时刻 → 国服出现日期（= 窗口起始日）。"""
    start, _ = cn_window(end_cn)
    return start.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 文案
# ---------------------------------------------------------------------------

_SEP = "──────────"  # 今天/明天两批之间的分隔线（box-drawing 字符，不是 MD 语法，各端都按原样显示）


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
    """窗口进行中给剩余时长，结束了给「已结束」；还没开始返回空串（时间行已写明几点开始）。"""
    now = _now_cn()
    if now < start:
        return ""
    if now < close:
        hours = (close - now).total_seconds() / 3600
        if hours >= 1:
            return f"还剩约 {round(hours)} 小时"
        return f"还剩约 {int(hours * 60)} 分钟"
    return "已结束"


def _day_block(pets: list[dict]) -> list[str]:
    """一天的批次 -> 文案块：日期行、时间行、任务行。

    版式约束：MD 渲染会吞掉连续半角空格，列与列之间用全角「｜」分隔而不是靠
    空格对齐；任务名不加粗（整段都是粗体反而没有重点），只给重量级野兽加粗。
    窗口恒为 07:00 起 24h，所以时间只写「7点」，不写完整时分。
    """
    start, close = cn_window(pets[0]["end_cn"])
    status = _window_status(start, close)
    lines = [
        f"**{_rel_day(start.date())}**（{start.strftime('%m-%d')}）",
        f"时间：{_rel_day(start.date())} 7点 → {_rel_day(close.date())} 7点"
        + (f"（{status}）" if status else ""),
    ]
    for p in pets:
        name = f"**{p['name_cn']}**" if p["quest_id"] == BOB_ID else p["name_cn"]
        lines.append(f"· {name} ｜ {p['zone']}")
    return lines


def build_text(
    today_pets: list[dict] | None, tomorrow_pets: list[dict] | None,
    bob_last: dt.datetime | None,
) -> str | None:
    """组装查询/推送文案：今天批次 + （拿得到时）明天批次。

    today_pets / tomorrow_pets 分别是国服今天、明天 07:00 开始的两批任务；
    12:05 后 EU 已切批，两批都有；早上只有今天的批次（明天的还没生成）。
    都为空返回 None（数据拉取失败由调用方兜底）。
    """
    if not today_pets and not tomorrow_pets:
        return None
    # 账本自动补记：数据源给出的最近一次野兽出现（含当前批次）
    if bob_last is not None:
        record_bob([_bob_cn_date(bob_last)])
    batches = [b for b in (today_pets, tomorrow_pets) if b]
    # 总标题只出一次：哪天有野兽就直接点出来（预警横幅），否则是普通日报
    bob_days = [
        _rel_day(cn_window(b[0]["end_cn"])[0].date())
        for b in batches if any(p["quest_id"] == BOB_ID for p in b)
    ]
    lines = [f"**🔥 {'、'.join(bob_days)}有{BOB_CN}**" if bob_days else "**🐾 宠物对战世界任务**"]
    for i, b in enumerate(batches):
        lines.append("")
        if i:
            lines += [_SEP, ""]
        lines += _day_block(b)
    lines.append("")
    lines.append(bob_last_text())
    return "\n".join(lines)


async def query_text() -> str:
    """手动查询：国服今天的批次（+ EU 切批后能拿到的明天批次）。"""
    try:
        now = _now_cn()
        # EU 在北京 12:00 切批；切批后 Active = 明天的批次，今天那批从历史里按结束日捞
        today = now.date()
        if now.hour >= 12:
            tomorrow = today + dt.timedelta(days=1)
            today_pets, bob = await fetch_data(target_end_day=today)
            tmr_pets, _ = await fetch_data(target_end_day=tomorrow)
            if not tmr_pets:  # EU 尚未翻页：退回 Active（= 今天的批次）
                tmr_pets = None
        else:
            today_pets, bob = await fetch_data()
            tmr_pets = None
    except Exception as e:  # noqa: BLE001
        logger.warning("[petwq] 拉取宠物任务失败: %s", e)
        return "暂时拉不到宠物对战世界任务数据（todayinwow.com），请稍后再试"
    text = build_text(today_pets, tmr_pets, bob)
    if text is None:
        return "暂时拉不到宠物对战世界任务数据（todayinwow.com），请稍后再试"
    return text


async def push_text(require_tomorrow: bool = False) -> str | None:
    """推送文案：预告国服**明天**的批次（附今天批次）；有重量级野兽时加预警。

    数据源（欧服）在北京 12:00 切批，但源站**放出新批有延迟**（实测 12:20 仍未
    看到新批），所以定时任务从 12:00 起每 5 分钟轮询，本函数即轮询用的探针：
    require_tomorrow=True 时，明天的批次还没就绪就返回 None（调用方稍后再试）。
    """
    try:
        # force=True：轮询必须看源站最新状态，不能被 10 分钟缓存挡住
        today_pets, bob = await fetch_data(target_end_day=_now_cn().date(), force=True)
        tmr_pets, _ = await fetch_data(
            target_end_day=_now_cn().date() + dt.timedelta(days=1), force=True
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[petwq] 拉取宠物任务失败: %s", e)
        return None
    if not tmr_pets:
        tmr_pets = None
        if require_tomorrow:
            return None  # 源站还没放出新批，等下一轮
    if not today_pets:
        today_pets = None
    if not today_pets and not tmr_pets:
        return None
    return build_text(today_pets, tmr_pets, bob)
