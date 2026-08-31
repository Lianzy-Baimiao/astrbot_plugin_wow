# -*- coding: utf-8 -*-
"""重置提醒（wowreset）服务。"""

from __future__ import annotations

import datetime as dt
import logging
import re

from ..data.affixes import AFFIX_CN, short_name
from ..raiderio import cn_period_end, current_affixes

logger = logging.getLogger("astrbot_plugin_wow.reset")

_affix_cache: list[str] | None = None
_affix_at: float = 0


async def fetch_affix_names() -> list[str]:
    """本周词缀中文名列表（5 分钟缓存）。"""
    import time
    global _affix_cache, _affix_at
    now = time.time()
    if _affix_cache and now - _affix_at < 300:
        return _affix_cache
    try:
        details = await current_affixes()
        names = []
        for a in details:
            cn = AFFIX_CN.get(int(a.get("id", 0)))
            names.append(cn or short_name(a.get("name", "")))
        _affix_cache, _affix_at = names, now
        return names
    except Exception as e:  # noqa: BLE001
        logger.warning("词缀获取失败: %s", e)
        return _affix_cache or []


def next_reset_time(now: dt.datetime | None = None) -> dt.datetime:
    """国服重置的本地兜底推算：周四 07:00（拿不到 raider.io 周期时用）。"""
    if now is None:
        now = dt.datetime.now()
    days = (3 - now.weekday()) % 7  # 周四=3
    t = (now + dt.timedelta(days=days)).replace(hour=7, minute=0, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=7)
    return t


async def reset_time() -> dt.datetime:
    """真实重置时刻：优先取 raider.io 国服周期 current.end，失败回落本地推算。"""
    try:
        raw = await cn_period_end()
        end = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if end.tzinfo is not None:
            end = end.astimezone().replace(tzinfo=None)
        if end > dt.datetime.now():
            return end
        logger.warning("raider.io 周期结束时间已过期（%s），回落本地推算", raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("raider.io 周期获取失败，回落本地推算: %s", e)
    return next_reset_time()


def next_push_time(reset_hhmm: str = "06:50", now: dt.datetime | None = None) -> dt.datetime:
    """下次推送时刻：周四 + 配置的推送时间（与原版 nextPushTime 一致）。"""
    if now is None:
        now = dt.datetime.now()
    h, m = parse_reset_time(reset_hhmm)
    days = (3 - now.weekday()) % 7
    t = (now + dt.timedelta(days=days)).replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=7)
    return t


async def remind_text() -> str:
    """重置提醒文本：倒计时 + 本周词缀 + 低保提示。"""
    end = await reset_time()
    d = end - dt.datetime.now()
    lines = ["⚔️ 魔兽周常提醒"]
    if d.total_seconds() > 0:
        dh = int(d.total_seconds() // 3600)
        if dh >= 48:
            lines.append(f"🕐 距重置还有 {dh // 24} 天 {dh % 24} 小时（{end.strftime('%m-%d %H:%M')} 重置）")
        else:
            lines.append(f"🕐 距重置还有约 {dh} 小时（{end.strftime('%m-%d %H:%M')} 重置）")
    affixes = await fetch_affix_names()
    if affixes:
        lines.append("📜 本周词缀：" + " / ".join(affixes))
    lines.append("💠 低保提醒：打满 4 次 ≥10 层大秘境，或击败 1 次团本首领")
    return "\n".join(lines)


def parse_reset_time(s: str) -> tuple[int, int]:
    """解析 "HH:MM" 配置。"""
    m = re.match(r"^(\d{1,2}):(\d{2})$", s.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return 6, 50