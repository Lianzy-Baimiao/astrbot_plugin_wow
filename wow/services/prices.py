# -*- coding: utf-8 -*-
"""物价查询：读 tools/export_prices.py 导出的 prices.json。

游戏在本机、AstrBot 在云服务器，所以拍卖行数据走「本地导出 → 上传」这条路：
本机 `python tools/export_prices.py` 解 Auctionator 的 CBOR 价格库，产出
`prices.json` 放到插件数据目录即可。物品中文名在导出时就烤进了 JSON，
云端不查名字、不联网。

同名条目很常见（工艺品质、装备按装等分键各占一条），所以按「名字 + 装等」
归组，每组取最近扫到的那条。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

logger = logging.getLogger("astrbot_plugin_wow.prices")

PRICES_FILE = "prices.json"
STALE_DAYS = 7          # 超过这么久的条目标记为旧数据
MAX_PER_TERM = 3        # 每个查询词最多列几条
MAX_TOTAL = 12          # 单次回复最多几条

_cache: dict | None = None
_cache_mtime: float = 0


def _fmt_gold(copper: int) -> str:
    """铜 → 金。上万金改用「万金」，避免一长串数字。"""
    gold = copper / 10000
    if gold >= 10000:
        return f"{gold / 10000:,.2f} 万金"
    if gold >= 100:
        return f"{gold:,.0f} 金"
    return f"{gold:,.2f} 金"


def _load() -> dict | None:
    """读 prices.json（按 mtime 缓存，文件更新后自动重载）。"""
    global _cache, _cache_mtime
    from ..store import data_dir

    p = data_dir() / PRICES_FILE
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _cache, _cache_mtime = None, 0
        return None
    if _cache is not None and mtime == _cache_mtime:
        return _cache

    import json

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("物价表读取失败：%s（%s）", p, e)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        logger.warning("物价表格式不对：%s", p)
        return None

    _cache, _cache_mtime = data, mtime
    logger.info("物价表已加载：%s 条（%s）", len(data["items"]), data.get("realm", "?"))
    return data


def _day_date(data: dict, day: int) -> str:
    """Auctionator 天号 → 日期串。"""
    day0 = int(data.get("day0") or 0)
    if not day0 or not day:
        return ""
    return dt.date.fromtimestamp(day0 + day * 86400).isoformat()


def _match(data: dict, term: str) -> list[dict]:
    """按名字子串找条目，返回最多 MAX_PER_TERM 条。

    归组键用「itemID + 装等」——同名不同 ID 是不同物品（工艺品质三档共享名字、
    ID 相邻），不能按名字合并；同一 itemID 的装备按装等分档。同键取最近扫到的那条。
    """
    term = term.strip()
    if not term:
        return []
    low = term.lower()

    groups: dict[tuple[int, int], dict] = {}
    for row in data["items"]:
        name = row.get("n") or ""
        if low not in name.lower():
            continue
        key = (int(row.get("i") or 0), int(row.get("il") or 0))
        cur = groups.get(key)
        # 同组取最近扫到的那条；同一天则取更低价
        if cur is None or (row.get("d", 0), -row.get("p", 0)) > (cur.get("d", 0), -cur.get("p", 0)):
            groups[key] = row
    if not groups:
        return []

    hits = list(groups.values())
    # 完全同名的优先，其次按新鲜度，最后按价格；同 itemID 按 ID 稳定排序（工艺品质档）
    hits.sort(key=lambda r: (0 if (r.get("n") or "").lower() == low else 1,
                             -r.get("d", 0), r.get("p", 0), r.get("i", 0)))
    return hits[:MAX_PER_TERM]


def _query_sync(items: list[str]) -> str:
    data = _load()
    if data is None:
        return (
            "物价表还没上传。在装了游戏的机器上跑 `python tools/export_prices.py`，"
            "把产出的 `prices.json` 放到插件数据目录即可。"
        )

    newest_day = int(data.get("newest_day") or 0)
    lines: list[str] = []
    missing: list[str] = []
    total = 0
    for term in items:
        if total >= MAX_TOTAL:
            break
        hits = _match(data, term)
        if not hits:
            missing.append(term.strip())
            continue
        # 同名不同 itemID（工艺品质三档）时附序号区分。
        # 按 itemID 去重：同名同 ID 只是装等不同的装备，装等已在标签里，不该再标档位。
        by_name: dict[str, list[int]] = {}
        for r in hits:
            ids = by_name.setdefault(r.get("n") or "?", [])
            iid = int(r.get("i") or 0)
            if iid not in ids:
                ids.append(iid)
        for ids in by_name.values():
            ids.sort()
        for row in hits:
            if total >= MAX_TOTAL:
                break
            total += 1
            name = row.get("n") or "?"
            ilvl = row.get("il") or 0
            label = f"{name}（{ilvl}）" if ilvl else name
            same = by_name.get(name) or []
            if len(same) > 1:
                # 工艺品质三档 ID 相邻、低→高，用①②③标注档位
                tier = same.index(int(row.get("i") or 0)) + 1
                label += f" {'①②③④⑤'[tier - 1] if tier <= 5 else f'#{tier}'}"
            qty = row.get("q") or 0
            qty_s = f"× {qty}" if qty else "挂售量未知"
            day = int(row.get("d") or 0)
            mark = ""
            if newest_day and day and newest_day - day > STALE_DAYS:
                mark = f"　⚠ {_day_date(data, day)} 的旧价"
            lines.append(f"- {label}：`{_fmt_gold(int(row.get('p') or 0))}`　{qty_s}{mark}")

    if not lines:
        return f"没查到「{('、'.join(missing)) or '？'}」，换个关键词试试（支持部分匹配）"

    realm = data.get("realm") or "?"
    scanned = data.get("scanned_at")
    head = f"**物价** · {realm}"
    if scanned:
        head += f" · 数据截止 {time.strftime('%m-%d %H:%M', time.localtime(int(scanned)))}"
    out = [head] + lines
    if missing:
        out.append(f"未找到：{'、'.join(missing)}")
    return "\n".join(out)


async def query_price(items: list[str]) -> str:
    """查询物价（JSON 读取走线程池，避免大表阻塞事件循环）。"""
    return await asyncio.to_thread(_query_sync, items)
