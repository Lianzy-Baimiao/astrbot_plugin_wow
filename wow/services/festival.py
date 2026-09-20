# -*- coding: utf-8 -*-
"""魔兽世界节日通告服务：FlowUs「下周大事件」分享页 → 国服当前节日/活动。

数据源与原理
------------
FlowUs 分享页「下周大事件」（作者每周三左右更新，国服口径）是纯前端 SPA，HTML 空壳无数据，
真实数据走**公开 JSON 接口**（无需 token）：

    GET https://flowus.cn/api/docs/{docUuid}

返回 {code:200, data:{blocks:{uuid→block}}}（约 5MB）。结构（2026-09-20 实测）：

- 正文文字在 block.data.segments[]；type:0 段是纯文本；type:4 段是**内联引用**——
  节日名藏在 segment.uuid 指向的另一个 block 里，需递归取其文字并用《》包起来，
  才能拼出「《美酒节》（9月20日~10月6日）」。
- 每周是一个 block（type 38），标题形如「9月17日~9月24日：S3赛季第6周」。节日在其子孙块中
  「特殊事件：」段到「本周上限：」段之间，格式 《名称》（M月D日[~M月D日]）。
- **当前周 = 根 block 的 subNodes[0]**（最新周被包在 type:31 列容器里，作者置顶维护）。
  文档含**两条并行时间线**（国服/外服、跨年份 M/D 重复），所以**不能全文扫**，必须锚定 subNodes[0]。
- 日期无年份：用「离今天最近」推断当前周锚点年份；结束月 < 开始月则结束年 +1（跨年如冬幕节）。
- 真节日库：全文 type:0 且以「（游戏内）」结尾的 block（如「🍺美酒节（游戏内）」），
  去 emoji 前缀得规范名，用来给推送里的真节日打标（🎉）区分普通活动（增益周、暗月马戏团等，🎪）。
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time

from ..net import fetch_json
from ..store import load_json, save_json

logger = logging.getLogger("astrbot_plugin_wow.festival")

DOC_UUID = "9ca6e3b7-3309-4344-a8ea-12a6042ff36d"
DOC_API = f"https://flowus.cn/api/docs/{DOC_UUID}"
DOC_REFERER = "https://flowus.cn/"
CN_TZ = dt.timezone(dt.timedelta(hours=8))  # 国服 = 北京时间

_CACHE_FILE = "festival_doc.json"     # 落盘缓存（原始文档）
# 源站每周才更新一次，缓存放宽到 6 小时：手动查询大多命中缓存，既少抓一次、也不易撞限流。
# 每天 07:05 定时推送用 force=True 强抓一次拿最新（失败则回落缓存）。
_CACHE_TTL = 21600                    # 6 小时内存/磁盘缓存

# 内存缓存
_cache_doc: dict | None = None
_cache_at: float = 0


# 周标题日期段：「9月17日~9月24日：...」
_WK_RE = re.compile(r"^\s*(\d{1,2})月(\d{1,2})日\s*[~～\-]\s*(\d{1,2})月(\d{1,2})日")
# 特殊事件条目：《名称》（M月D日[ ~ M月D日]）
_EVT_RE = re.compile(
    r"《([^》]+)》\s*[（(](\d{1,2})月(\d{1,2})日"
    r"(?:[^0-9）)]*?(\d{1,2})月(\d{1,2})日)?"
)


def _now_cn() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


# ---------------------------------------------------------------------------
# 抓取（6 小时内存缓存 + 落盘，失败/限流回落缓存）
# ---------------------------------------------------------------------------

def _valid_doc(d) -> bool:
    return isinstance(d, dict) and bool(d.get("blocks"))


async def _fetch_doc(force: bool = False) -> dict:
    """抓取整篇文档的 blocks 字典。6 小时缓存；抓取失败（含限流 429）依次回落磁盘、过期内存缓存。"""
    global _cache_doc, _cache_at
    now = time.time()
    if not force and _cache_doc is not None and now - _cache_at < _CACHE_TTL:
        return _cache_doc

    disk = load_json(_CACHE_FILE, None)
    if not force and _valid_doc(disk) and now - float(disk.get("at", 0)) < _CACHE_TTL:
        _cache_doc, _cache_at = disk, float(disk.get("at", 0))
        return _cache_doc

    try:
        resp = await fetch_json(DOC_API, headers={"referer": DOC_REFERER})
        blocks = ((resp or {}).get("data") or {}).get("blocks") or {}
        if not blocks:
            raise RuntimeError("文档 blocks 为空")
        doc = {"blocks": blocks, "at": now}
        _cache_doc, _cache_at = doc, now
        save_json(_CACHE_FILE, doc)
        return doc
    except Exception as e:  # noqa: BLE001
        # 抓取失败（网络/限流等）：用尽量新的缓存兜底——磁盘 vs 内存取较新的那份
        logger.warning("[festival] 抓取失败: %s；回落缓存", e)
        candidates = [c for c in (disk, _cache_doc) if _valid_doc(c)]
        if candidates:
            best = max(candidates, key=lambda c: float(c.get("at", 0)))
            _cache_doc, _cache_at = best, float(best.get("at", 0))
            return best
        raise


# ---------------------------------------------------------------------------
# 文本还原（内联引用递归解析）
# ---------------------------------------------------------------------------

def _rtxt(block: dict, blocks: dict, _seen: set | None = None) -> str:
    """还原 block 文字：type:0 纯文本原样，type:4 内联引用取被引 block 文字并《》包裹。"""
    _seen = _seen if _seen is not None else set()
    out: list[str] = []
    for s in (block.get("data") or {}).get("segments") or []:
        if s.get("type") == 4 and s.get("uuid") in blocks and s["uuid"] not in _seen:
            _seen.add(s["uuid"])
            out.append("《" + _rtxt(blocks[s["uuid"]], blocks, _seen) + "》")
        else:
            out.append(s.get("text", ""))
    return "".join(out)


def _infer_year(month: int, base: dt.date) -> int:
    """日期无年份时，取让该「月」离 base 最近的年份。"""
    cands = [dt.date(base.year + dy, month, 1) for dy in (-1, 0, 1)]
    return min(cands, key=lambda x: abs((x - base).days)).year


# ---------------------------------------------------------------------------
# 当前周定位 + 事件解析
# ---------------------------------------------------------------------------

def _week_title_child(block: dict, blocks: dict) -> str | None:
    """容器块（type 31）的周标题：在直接子块里找带日期段的那条（当前周标题是 type 7）。"""
    for c in block.get("subNodes") or []:
        cb = blocks.get(c)
        if cb and _WK_RE.match(_rtxt(cb, blocks)):
            return _rtxt(cb, blocks)
    return None


def _week_units(blocks: dict) -> list[tuple[str, dict]]:
    """按文档顺序列出所有「周单元」→ (标题, 正文块)。

    两种形态：
    - 归档周：type 38 块，标题即自身文字，正文在其子孙块。
    - 当前周：type 31 列容器（作者置顶），标题是它的某个子块（type 7），正文在容器子孙块。
    正文块统一用来喂 _parse_events（都走 subNodes 递归）。
    """
    root = blocks.get(DOC_UUID)
    if not root:
        return []
    units: list[tuple[str, dict]] = []
    for uid in root.get("subNodes") or []:
        b = blocks.get(uid)
        if not b:
            continue
        t = b.get("type")
        if t == 38 and _WK_RE.match(_rtxt(b, blocks)):
            units.append((_rtxt(b, blocks), b))
        elif t == 31:
            title = _week_title_child(b, blocks)
            if title:
                units.append((title, b))
    return units


def _current_week(blocks: dict) -> dict | None:
    """当前周 = 文档顺序第一个周单元的正文块（作者把最新周置顶在 subNodes[0] 的列容器里）。

    不按「日期含今天」全文匹配：文档有国服/外服两条时间线且跨年份 M/D 重复，
    只有「置顶第一条」才唯一对应当前周。
    """
    units = _week_units(blocks)
    return units[0][1] if units else None


def _holiday_set(blocks: dict) -> set[str]:
    """真节日库：全文 type:0 且以「（游戏内）」结尾的 block，去 emoji 前缀得规范名。"""
    out: set[str] = set()
    for b in blocks.values():
        if b.get("type") != 0:
            continue
        t = _rtxt(b, blocks)
        if t.endswith("（游戏内）"):
            name = re.sub(r"^[^一-鿿]+", "", t.replace("（游戏内）", "")).strip()
            if name:
                out.add(name)
    return out


def _week_children_lines(week: dict, blocks: dict) -> list[str]:
    """当前周块所有子孙块（文档顺序）的还原文字。"""
    lines: list[str] = []

    def walk(uid: str):
        b = blocks.get(uid)
        if not b:
            return
        lines.append(_rtxt(b, blocks))
        for c in b.get("subNodes") or []:
            walk(c)

    for c in week.get("subNodes") or []:
        walk(c)
    return lines


def _parse_events(week: dict, blocks: dict, base: dt.date) -> list[dict]:
    """抽当前周「特殊事件：」段到「本周上限：」段之间的 《名》（日期），补全年份。"""
    holidays = _holiday_set(blocks)
    events: list[dict] = []
    grabbing = False
    for line in _week_children_lines(week, blocks):
        stripped = line.strip()
        if stripped.startswith("特殊事件"):
            grabbing = True
        if grabbing and stripped.startswith("本周上限"):
            break
        if not grabbing:
            continue
        for m in _EVT_RE.finditer(line):
            name = m.group(1).strip()
            sm, sd = int(m.group(2)), int(m.group(3))
            sy = _infer_year(sm, base)
            start = dt.date(sy, sm, sd)
            if m.group(4):
                em, ed = int(m.group(4)), int(m.group(5))
                ey = sy + 1 if em < sm else sy
                end = dt.date(ey, em, ed)
            else:
                end = start
            events.append({
                "name": name,
                "start": start,
                "end": end,
                "is_holiday": name in holidays,
            })
    return events


# ---------------------------------------------------------------------------
# 单个节日的历史周期（上次 / 进行中 / 下次）
# ---------------------------------------------------------------------------
# 文档的周单元按文档顺序**从新到旧连续排列**（实测只有 12→1 月的正常跨年跳变，
# 无多时间线交错）。据此给每个周单元推出**绝对起始日**：锚定当前周（subNodes[0]）的
# 年份，往后（更旧）遍历，月份较上一周「跳升」即回退一年。再用每周的绝对起始日做
# 锚点推断该周内节日日期的年份，就能把全库 ~2 年历史里同名节日的每次出现还原成绝对日期。

def _week_start_dates(units: list[tuple[str, dict]], today: dt.date) -> list[dt.date]:
    """每个周单元的绝对起始日（新→旧连续，跨年回退）。"""
    starts: list[dt.date] = []
    if not units:
        return starts
    m0 = _WK_RE.match(units[0][0])
    year = _infer_year(int(m0.group(1)), today)
    prev_m: int | None = None
    for title, _ in units:
        m = _WK_RE.match(title)
        sm, sd = int(m.group(1)), int(m.group(2))
        if prev_m is not None and sm > prev_m:  # 往旧走月份跳升 = 越过年界
            year -= 1
        starts.append(dt.date(year, sm, sd))
        prev_m = sm
    return starts


def _merge_occurrences(
    occ: list[tuple[dt.date, dt.date]], gap_days: int = 12
) -> list[tuple[dt.date, dt.date]]:
    """把同一次节日在相邻周里被重复登记的日期段合并（起始日相差 ≤gap 视作同一次，取并集）。"""
    out: list[tuple[dt.date, dt.date]] = []
    for s, e in sorted(set(occ)):
        if out and abs((s - out[-1][0]).days) <= gap_days:
            ps, pe = out[-1]
            out[-1] = (min(ps, s), max(pe, e))
        else:
            out.append((s, e))
    return out


def _festival_occurrences(
    name: str, blocks: dict, today: dt.date
) -> list[tuple[dt.date, dt.date]]:
    """全库历史里 name 这个节日的所有出现（绝对日期，去重合并，按时间升序）。"""
    units = _week_units(blocks)
    starts = _week_start_dates(units, today)
    occ: list[tuple[dt.date, dt.date]] = []
    for (title, body), wstart in zip(units, starts):
        for line in _week_children_lines(body, blocks):
            for m in _EVT_RE.finditer(line):
                if m.group(1).strip() != name:
                    continue
                sm, sd = int(m.group(2)), int(m.group(3))
                sy = _infer_year(sm, wstart)  # 用本周绝对起始日做锚，避免跨年错配
                start = dt.date(sy, sm, sd)
                if m.group(4):
                    em, ed = int(m.group(4)), int(m.group(5))
                    ey = sy + 1 if em < sm else sy
                    end = dt.date(ey, em, ed)
                else:
                    end = start
                occ.append((start, end))
    return _merge_occurrences(occ)


def _resolve_festival_name(query: str, blocks: dict) -> str | None:
    """把用户输入对到真节日库里的规范名：精确 > 去掉「节」等宽松包含。"""
    q = (query or "").strip().strip("《》").replace("节日", "").strip()
    if not q:
        return None
    holidays = _holiday_set(blocks)
    if q in holidays:
        return q
    # 宽松：库名包含输入，或输入包含库名（如「美酒」↔「美酒节」、「啤酒节」不匹配）
    cands = [h for h in holidays if q in h or h in q]
    if len(cands) == 1:
        return cands[0]
    # 多个候选时优先取最短（最接近整词）
    if cands:
        return min(cands, key=len)
    return None


# ---------------------------------------------------------------------------
# 状态判定与文案
# ---------------------------------------------------------------------------

def _sort_key(ev: dict, today: dt.date) -> tuple:
    """排序：今天开始 > 进行中 > 未开始（按开始日），已结束不展示（调用方过滤）。"""
    s, e = ev["start"], ev["end"]
    if s == today:
        bucket = 0
    elif s < today <= e:
        bucket = 1
    else:  # 未开始
        bucket = 2
    return (bucket, s, e)


def _status_text(ev: dict, today: dt.date) -> str:
    s, e = ev["start"], ev["end"]
    if s == today:
        return "今天开始！"
    if s < today <= e:
        left = (e - today).days
        if e == s:
            return "仅今天"
        return f"进行中，还剩 {left} 天" if left >= 1 else "今天最后一天"
    if today < s:
        d = (s - today).days
        if d == 1:
            return "明天开始"
        return f"{d} 天后开始"
    return "已结束"


def _fmt_range(ev: dict) -> str:
    s, e = ev["start"], ev["end"]
    if e == s:
        return f"{s:%m/%d}"
    return f"{s:%m/%d} → {e:%m/%d}"


def _build_text(events: list[dict], today: dt.date) -> str:
    """组装文案：今天开始/进行中/未开始的活动。真节日打 🎉、普通活动打 🎪，名称加粗（MD）。

    横幅点名**今天正在进行的全部**（节日 + 活动，如美酒节、神秘运势之风）；已结束的不展示。
    """
    live = [ev for ev in events if ev["end"] >= today]
    live.sort(key=lambda ev: _sort_key(ev, today))

    ongoing = [ev for ev in live if ev["start"] <= today]

    # 标题：点名今天正在进行的全部（节日 + 活动）；今天没有进行中的就给预告标题
    if ongoing:
        names = "、".join(ev["name"] for ev in ongoing)
        lines = [f"**🎉 今日魔兽节日活动：{names}**"]
    else:
        lines = ["**🎉 今日魔兽节日活动**", "", "今天暂无进行中的节日活动，近期预告："]

    if live:
        if lines[-1] != "":
            lines.append("")
        for ev in live:
            mark = "🎉" if ev["is_holiday"] else "🎪"
            lines.append(f"{mark} **{ev['name']}** ｜ {_fmt_range(ev)}（{_status_text(ev, today)}）")

    return "\n".join(lines)


def _fmt_occ(s: dt.date, e: dt.date) -> str:
    """一次出现的日期段：同年省略重复年份。"""
    if s == e:
        return f"{s:%Y-%m-%d}"
    if s.year == e.year:
        return f"{s:%Y-%m-%d} → {e:%m-%d}"
    return f"{s:%Y-%m-%d} → {e:%Y-%m-%d}"


def _plus_one_year(d: dt.date) -> dt.date:
    """同月同日 +1 年（2/29 落到 3/1）。多数魔兽节日是固定日历日，据此推下次。"""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 2/29
        return dt.date(d.year + 1, 3, 1)


def _build_cycle_text(name: str, occ: list[tuple[dt.date, dt.date]], today: dt.date) -> str:
    """单个节日的周期文案：进行中 / 上次 / 下次 + 历年记录。

    下次：数据里已有未来段就用真值；否则按「最近一次 +1 年（同月日）」推算——多数魔兽
    节日锚在固定日历日（如美酒节 9/20、海盗日 9/19），同月日 +1 年即为下次。
    """
    if not occ:
        return f"没查到「{name}」的历史记录（数据源只整理了近两年的国服大事件）"

    current = next((o for o in occ if o[0] <= today <= o[1]), None)
    past = [o for o in occ if o[1] < today]
    future = [o for o in occ if o[0] > today]

    lines = [f"**🎉 {name}**"]

    if current:
        left = (current[1] - today).days
        tail = f"还剩 {left} 天" if left >= 1 else "今天最后一天"
        lines.append(f"进行中：{_fmt_occ(*current)}（{tail}）")

    if past:
        lines.append(f"上次：{_fmt_occ(*past[-1])}")

    if future:
        # 数据里已有远期日期 = 真值，不加「预计」
        lines.append(f"下次：{_fmt_occ(*future[0])}")
    else:
        # 数据没有远期日期，按最近一次（含进行中）同月日 +1 年推算 = 预计
        base = current or (past[-1] if past else None)
        if base:
            ns = _plus_one_year(base[0])
            ne = ns + dt.timedelta(days=(base[1] - base[0]).days)
            lines.append(f"下次：预计 {_fmt_occ(ns, ne)}")

    # 历年记录（最多列近 5 次，倒序）
    if occ:
        lines.append("")
        lines.append("历年时间：")
        for s, e in occ[::-1][:5]:
            flag = "（进行中）" if current and (s, e) == current else ""
            lines.append(f"· {_fmt_occ(s, e)}{flag}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

async def _events_now(force: bool = False) -> tuple[list[dict], dt.date]:
    doc = await _fetch_doc(force=force)
    blocks = doc["blocks"]
    today = _now_cn().date()
    week = _current_week(blocks)
    if week is None:
        raise RuntimeError("未能定位当前周（页面结构可能变化）")
    events = _parse_events(week, blocks, today)
    return events, today


async def query_text() -> str:
    """手动查询：当前周全部特殊事件（含节日），带状态。"""
    try:
        events, today = await _events_now(force=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[festival] 查询失败: %s", e)
        return "暂时拉不到节日活动数据，请稍后再试"
    return _build_text(events, today)


async def push_text() -> str:
    """定时推送：与查询同口径；空档日也返回文案（照常发）。"""
    try:
        events, today = await _events_now(force=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("[festival] 推送生成失败: %s", e)
        return "暂时拉不到节日活动数据，请稍后再试"
    return _build_text(events, today)


async def cycle_text(query: str) -> str:
    """查询单个节日的周期：上次 / 进行中 / 下次 + 历年时间。

    query 是用户输入的节日名（如「美酒节」「美酒」）。对不上真节日库时给出可选清单。
    """
    try:
        doc = await _fetch_doc(force=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[festival] 周期查询失败: %s", e)
        return "暂时拉不到节日活动数据，请稍后再试"
    blocks = doc["blocks"]
    name = _resolve_festival_name(query, blocks)
    if name is None:
        names = "、".join(sorted(_holiday_set(blocks)))
        return f"没找到「{query.strip()}」这个节日。可查的节日有：\n{names}"
    today = _now_cn().date()
    occ = _festival_occurrences(name, blocks, today)
    return _build_cycle_text(name, occ, today)
