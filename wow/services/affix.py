# -*- coding: utf-8 -*-
"""词缀（mpaffix）服务。"""

from __future__ import annotations

import datetime as dt

from ..data.affixes import (
    card_from_rio,
    card_from_rotation,
    next_rotation_key,
    rotation_key,
)
from ..raiderio import cn_period_end, current_affixes


async def build_affix_data() -> dict:
    """本周/下周词缀 + 重置倒计时。"""
    details = await current_affixes()
    key = rotation_key(details)
    current = card_from_rio(details, "本周词缀", key)
    next_card = None
    nk = next_rotation_key(key)
    if nk:
        next_card = card_from_rotation(nk, "下周词缀")
    period_end = None
    try:
        end_str = await cn_period_end()
        end = dt.datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        period_end = end.astimezone().strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        pass
    return {"current": current, "next": next_card, "period_end": period_end}