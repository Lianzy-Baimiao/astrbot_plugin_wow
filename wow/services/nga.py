# -*- coding: utf-8 -*-
"""NGA 帖子解析（ngajiexi）：链接嗅探 → 帖子卡片（对齐原 ZeroBot ngajiexi）。"""

from __future__ import annotations

import datetime as dt
import html
import logging
import re

from ..net import get_client

logger = logging.getLogger("astrbot_plugin_wow.nga")

LINK_RE = re.compile(r"(ngabbs\.com|nga\.178\.com|bbs\.nga\.cn)/read\.php\?tid=(\d+)")
TID_RE = re.compile(r"(?:ngabbs\.com|nga\.178\.com|bbs\.nga\.cn)/read\.php\?tid=(\d+)")
_DOMAINS = ["ngabbs.com", "bbs.nga.cn"]
VIEW_URL = "https://ngabbs.com/read.php?tid=%s"
MIRROR_URL = "https://nga.178.com/read.php?tid=%s"
ATTACH_BASE = "img.nga.cn/attachments"

MAX_POSTS = 4        # 主楼 + 前 3 条回复
OP_LIMIT = 1200      # 主楼正文字数上限
REPLY_LIMIT = 300    # 每条回复字数上限
MAX_IMAGES = 6

# ---- 正文清洗（与原版 card.go cleanContent 一致）----
_QUOTE_RE = re.compile(r"(?s)\[quote\].*?\[/quote\]")
_IMG_RE = re.compile(r"(?s)\[img\].*?\[/img\]")
_SMILE_RE = re.compile(r"\[s:[^\]]*\]")
_BBCODE_RE = re.compile(r"\[/?[a-zA-Z*][^\]]*\]")
_TAG_RE = re.compile(r"<[^>]*>")
_BLANK_RE = re.compile(r"\n{3,}")


def _clean_text(s: str) -> str:
    s = _TAG_RE.sub("", s)
    return html.unescape(s).strip()


def _clean_content(s: str) -> str:
    s = s.replace("<br/>", "\n").replace("<br>", "\n")
    s = _QUOTE_RE.sub("", s)
    s = _IMG_RE.sub("", s)
    s = _SMILE_RE.sub("", s)
    s = _BBCODE_RE.sub("", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    s = _BLANK_RE.sub("\n\n", s)
    return s.strip()


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "…（省略）"


def extract_tid(text: str) -> str | None:
    m = TID_RE.search(text)
    return m.group(1) if m else None


def match_link(text: str) -> tuple[str, str] | None:
    """返回 (域名, tid)。域名用于「连接转化」提示（nga.178.com 不需再提示）。"""
    m = LINK_RE.search(text)
    if not m:
        return None
    return m.group(1), m.group(2)


def convert_line(domain: str, tid: str) -> str:
    """连接转化提示行（与原版 convertLine 一致）。"""
    if domain == "nga.178.com":
        return ""
    return "连接转化: " + MIRROR_URL % tid + "\n"


def header_text(title: str, author: str, replies: int, tid: str) -> str:
    """随图片一起发出的文字部分（与原版 header() 一致）。"""
    return (
        f"【NGA】{title}\n"
        f"作者：{author} | 回复：{replies}\n"
        f"{VIEW_URL % tid}"
    )


async def fetch_topic(tid: str) -> dict:
    """拉取 NGA 帖子（游客接口 __output=8，GBK 编码→UTF-8）。"""
    last_err: Exception | None = None
    for domain in _DOMAINS:
        url = f"https://{domain}/read.php?tid={tid}&__output=8"
        try:
            text = await _fetch_raw(url)
            return _parse_topic(text, tid)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("NGA %s 拉取失败: %s", domain, e)
    raise RuntimeError(f"NGA 拉取失败：{last_err}") from last_err


async def _fetch_raw(url: str) -> str:
    """GET NGA 接口：任何状态码都返回 body 文本（GBK→UTF-8）。"""
    resp = await get_client().get(url, headers={"User-Agent": "Nga_Official"}, timeout=20)
    body = resp.content.decode("gbk", errors="replace")
    # NGA 的错误原因在 body 里，优先报它
    m = re.search(r'"error"\s*:\s*\{\s*"0"\s*:\s*"([^"]*)"', body)
    if m:
        raise RuntimeError(m.group(1))
    if resp.status_code != 200:
        raise RuntimeError(f"NGA 返回 {resp.status_code}")
    if '"encode"' not in body:
        raise RuntimeError("NGA 响应不完整，请重试")
    return body


_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _clean_json_strings(s: str) -> str:
    """把 JSON 字符串值内的裸控制字符转义，使 json.loads 可用。"""

    def repl(m):
        buf = []
        for ch in m.group(0):
            if ch == "\r":
                buf.append("\\r")
            elif ch == "\n":
                buf.append("\\n")
            elif ch == "\t":
                buf.append("\\t")
            elif ord(ch) < 0x20:
                buf.append(f"\\u{ord(ch):04x}")
            else:
                buf.append(ch)
        return "".join(buf)

    return _STR_RE.sub(repl, s)


def _parse_topic(text: str, tid: str) -> dict:
    """解析 __T/__F/__U/__R 数据（NGA JSON 字符串含裸 \\r\\n，需先清洗）。"""
    try:
        import json
        data = json.loads(_clean_json_strings(text))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"NGA 数据解析失败：{e}") from e

    payload = data.get("data") or {}
    topic = payload.get("__T") or {}
    title = _clean_text(str(topic.get("subject", "")))
    if not title:
        raise RuntimeError("接口未返回帖子标题，可能是需要登录才能看的版块")
    forum = _clean_text(str((payload.get("__F") or {}).get("name", "")))
    author = _clean_text(str(topic.get("author", ""))) or "匿名"
    try:
        replies = int(topic.get("replies", 0) or 0)
    except (TypeError, ValueError):
        replies = 0
    users = payload.get("__U") or {}
    base = (payload.get("__GLOBAL") or {}).get("_ATTACH_BASE_VIEW", "") or ATTACH_BASE
    replies_map = payload.get("__R") or {}

    def _user_name(uid) -> str:
        u = users.get(str(uid)) or {}
        return _clean_text(str(u.get("username", ""))) or ""

    posts = []
    for i in range(MAX_POSTS):
        post = replies_map.get(str(i))
        if not post:
            break
        lou = int(post.get("lou", 0) or 0)
        # 主楼作者用 __T.author（游客拿不到 __U 的真实用户名）；回复作者查 __U
        p_author = author if lou == 0 else _user_name(post.get("authorid", ""))
        if not p_author:
            p_author = "匿名"
        try:
            ts = int(post.get("postdatetimestamp", 0) or 0)
            date_str = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
        except (TypeError, ValueError, OSError):
            date_str = ""
        images = []
        attachs = post.get("attachs") or {}
        for att in attachs.values():
            if isinstance(att, dict) and att.get("type") == "img" and att.get("attachurl"):
                images.append("https://" + base + "/" + str(att["attachurl"]))
                if len(images) >= MAX_IMAGES:
                    break
        limit = OP_LIMIT if lou == 0 else REPLY_LIMIT
        content = _truncate(_clean_content(str(post.get("content", ""))), limit)
        posts.append({
            "floor": lou,
            "floor_label": "主楼" if lou == 0 else f"{lou}楼",
            "author": p_author,
            "date": date_str,
            "content": content,
            "images": images,
        })
    if not posts:
        raise RuntimeError("NGA 未返回任何楼层")
    return {"title": title, "forum": forum, "author": author, "replies": replies, "tid": tid, "posts": posts}
