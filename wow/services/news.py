# -*- coding: utf-8 -*-
"""暴雪新闻（blizzardnews）服务：按群去重。"""

from __future__ import annotations

import logging
import re

from ..net import fetch_text
from ..store import load_json, save_json

logger = logging.getLogger("astrbot_plugin_wow.news")

NEWS_URL = "https://wow.blizzard.cn/news/"

# 页面结构：<a href="..."><div class="br-top"></div><div class="list-item">
#   <div class="list-img">…<img src="…"></div>
#   <div class="list-content"><div class="list-title">…</div><div class="list-desc">…</div>…
# 逐个 <a> 块解析比一条长正则稳：中间插了 br-top，且 img 嵌在 img-box 里。
_ANCHOR_RE = re.compile(r'(?s)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>')
_TITLE_RE = re.compile(r'(?s)<div class="list-title[^"]*">(.*?)</div>')
_DESC_RE = re.compile(r'(?s)<div class="list-desc[^"]*">(.*?)</div>')
_IMG_RE = re.compile(r'<img[^>]*src="([^"]+)"')


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def _abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://wow.blizzard.cn" + href
    return NEWS_URL + href


def parse_news_items(page: str) -> list[dict]:
    """解析新闻列表页，返回 [{url,title,description,image_url}]（按页面顺序）。"""
    items = []
    for href, body in _ANCHOR_RE.findall(page):
        t = _TITLE_RE.search(body)
        if not t:
            continue
        title = _strip(t.group(1))
        if not title:
            continue
        d = _DESC_RE.search(body)
        img = _IMG_RE.search(body)
        items.append({
            "url": _abs_url(href),
            "title": title,
            "description": _strip(d.group(1)) if d else "",
            "image_url": img.group(1) if img else "",
        })
    return items


async def latest_news() -> dict | None:
    """拉取暴雪新闻首页第一条。"""
    page = await fetch_text(NEWS_URL, timeout=20)
    items = parse_news_items(page)
    if items:
        return items[0]
    # 兜底：只拿到标题也比什么都没有好
    m2 = _TITLE_RE.search(page)
    if not m2:
        logger.warning("暴雪新闻页面结构可能已变化，未解析到任何条目")
        return None
    m3 = _DESC_RE.search(page)
    return {
        "url": "",
        "title": _strip(m2.group(1)),
        "description": _strip(m3.group(1)) if m3 else "",
        "image_url": "",
    }


def last_title(group_key: str) -> str:
    data = load_json("news_titles.json", {}) or {}
    return data.get(group_key, "")


def set_last_title(group_key: str, title: str) -> None:
    data = load_json("news_titles.json", {}) or {}
    data[group_key] = title
    save_json("news_titles.json", data)


async def get_news(group_key: str, force: bool = False) -> dict | None:
    """获取最新新闻；已发送过且非强制时返回 None。"""
    news = await latest_news()
    if not news:
        return None
    if not force and last_title(group_key) == news["title"]:
        return None
    set_last_title(group_key, news["title"])
    return news