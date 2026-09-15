# -*- coding: utf-8 -*-
"""wow.kernel.moe 页面解析：事件卡片（wowinfo）与事件日历（wowcal）共用。"""

from __future__ import annotations

import html
import logging
import re
import time

from .net import fetch_text
from .store import load_json, save_json

logger = logging.getLogger("astrbot_plugin_wow.kernel")

SCHED_URL = "https://wow.kernel.moe/Schedule"
CACHE_TTL = 1800  # 30 分钟

_CARD_OPEN_RE = re.compile(r'<div class="card(?:[ "])')
_HEADER_RE = re.compile(r'(?s)<div class="card-header[^"]*">(.*?)</div>')
_ROW_RE = re.compile(r'(?s)<tr[^>]*>(.*?)</tr>')
_EVENT_DIV_RE = re.compile(r'(?s)<div class="event-schedule">(.*?)</div>')
_TAG_RE = re.compile(r'<[^>]+>')
_TIME_RE = re.compile(r'(\d{2}/\d{2}\s+\d{2}:\d{2})')
_GEN_RE = re.compile(r'页面生成时间[:：\s]*([\d\- :]+)')
_EXP_RE = re.compile(r'<i class="bi bi-star"></i>\s*([^<]+)')
_FW_RE = re.compile(r'(?s)class="fw-bold[^"]*"[^>]*>(.*?)</')

_cache: dict | None = None
_cache_at: float = 0


def _extract_cards(page: str) -> list[str]:
    """平衡提取所有完整卡片块（.card 容器，含嵌套 div）。"""
    cards = []
    for m in _CARD_OPEN_RE.finditer(page):
        start = m.end()
        depth = 1
        i = start
        while i < len(page) and depth > 0:
            nxt_open = page.find("<div", i)
            nxt_close = page.find("</div>", i)
            if nxt_open != -1 and (nxt_close == -1 or nxt_open < nxt_close):
                depth += 1
                i = nxt_open + 4
            elif nxt_close != -1:
                depth -= 1
                i = nxt_close + 6
            else:
                break
        cards.append(page[start : max(i - 6, start)])
    return cards


def _strip_tags(s: str) -> str:
    s = _TAG_RE.sub(" ", s)
    return " ".join(s.split()).strip()


def _split_time(detail: str) -> tuple[str, str]:
    m = _TIME_RE.search(detail)
    if not m:
        return detail, ""
    return detail.replace(m.group(1), "", 1).strip(), m.group(1)


async def fetch_schedule(force: bool = False) -> dict:
    """获取事件日历数据（带 30 分钟缓存 + 落盘）。"""
    global _cache, _cache_at
    now = time.time()
    if not force and _cache and now - _cache_at < CACHE_TTL:
        return _cache
    disk = load_json("wowcal_sched.json")
    if not force and disk and disk.get("rows") and now - disk.get("at", 0) < CACHE_TTL:
        _cache, _cache_at = disk, disk["at"]
        return _cache
    page = await fetch_text(SCHED_URL)
    page = html.unescape(page)

    gen_m = _GEN_RE.search(page)
    generated = gen_m.group(1).strip() if gen_m else ""

    cards = _extract_cards(page)
    card = None
    for c in cards:
        if _HEADER_RE.search(c):
            card = c
            break
    if card is None:
        raise RuntimeError("页面结构变化，未找到版本卡片")
    header_m = _HEADER_RE.search(card)
    expansion = _strip_tags(header_m.group(1)) if header_m else ""
    exp_m = _EXP_RE.search(card)
    if exp_m:
        expansion = exp_m.group(1).strip()

    rows = []
    for row in _ROW_RE.findall(card):
        tds = [t.strip() for t in re.findall(r'(?s)<td>(.*?)</td>', row)]
        if len(tds) < 2:
            continue
        left = _strip_tags(tds[0])
        if not left:
            continue
        divs = _EVENT_DIV_RE.findall(tds[1])
        if not divs:
            detail, t = _split_time(_strip_tags(tds[1]))
            if detail or t:
                rows.append({"name": left, "detail": detail, "time": t})
            continue
        for d in divs:
            right = _strip_tags(d)
            if not right:
                continue
            detail, t = _split_time(right)
            rows.append({"name": left, "detail": detail, "time": t})
    if not rows:
        raise RuntimeError("未解析到事件行")
    out = {"expansion": expansion, "generated": generated, "rows": rows, "at": now}
    _cache, _cache_at = out, now
    save_json("wowcal_sched.json", out)
    return out


async def fetch_event_card(index: int = 1) -> str:
    """获取第 index 张事件卡片文本（wowinfo 事件）。"""
    page = await fetch_text(SCHED_URL)
    page = html.unescape(page)

    gen_m = _GEN_RE.search(page)
    generated = gen_m.group(1).strip() if gen_m else ""

    cards = [c for c in _extract_cards(page) if _HEADER_RE.search(c)]
    if index - 1 >= len(cards):
        raise RuntimeError(f"未找到编号为 {index} 的卡片")
    card = cards[index - 1]
    header_m = _HEADER_RE.search(card)
    header = _strip_tags(header_m.group(1)) if header_m else ""

    lines = [f"**{header}**"]
    if index == 1:
        lines.append("可输入 版本+事件，获取相应版本信息")
        if generated:
            lines.append(f"**页面生成时间**: {generated}")
    for row in _ROW_RE.findall(card):
        tds = re.findall(r'(?s)<td>(.*?)</td>', row)
        if len(tds) < 2:
            continue
        title_m = _FW_RE.search(tds[0])
        title = _strip_tags(title_m.group(1)) if title_m else _strip_tags(tds[0])
        details = re.sub(r"\s+", " ", _strip_tags(tds[1]))
        if title:
            lines.append(f"- **{title}**：{details}")
    return "\n".join(lines)


CARD_ID_MAP = {
    "地心之战": "1",
    "巨龙时代": "2",
    "暗影国度": "3",
    "争霸艾泽拉斯": "4",
    "军团再临": "5",
    "德拉诺": "6",
}


def translate_card_id(input_str: str) -> str:
    return CARD_ID_MAP.get(input_str, input_str)


def is_card_key(input_str: str) -> bool:
    """是否是已知的版本名/卡片编号（免前缀触发时用来过滤正常聊天）。"""
    s = (input_str or "").strip()
    return s in CARD_ID_MAP or (s.isdigit() and 1 <= int(s) <= 20)