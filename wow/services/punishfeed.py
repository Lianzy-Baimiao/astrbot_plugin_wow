# -*- coding: utf-8 -*-
"""处罚名单自动抓取：扫暴雪新闻 → 认出处罚公告 → 下载 PDF → 转 xlsx 落到 punish/。

流程（由 main.py 的定时任务驱动）：
1. `find_candidates()` 拉新闻列表页，挑出标题像「处罚公告/处罚名单」的条目
2. 逐条打开正文，取「名单」按钮指向的 .pdf 直链
3. PDF 直链里带日期段（.../images/20260828/xxx.pdf），赛季名从公告标题提取
4. 目标 xlsx 已存在就跳过；否则下载 + 解析 + 写盘，返回战报给上层推送

命名：`yyyymmdd_赛季名_PVE|PVP_处罚名单.xlsx`（与 punish._source 的解析口径一致）。
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..net import fetch_bytes, fetch_text
from ..store import data_dir, load_json, save_json
from . import news as news_svc
from . import punish as punish_svc

logger = logging.getLogger("astrbot_plugin_wow.punishfeed")

# 标题里出现这些词才算处罚公告（「治理公告」有时不带名单，一并扫、没 PDF 自然跳过）
_TITLE_HINT = re.compile(r"处罚(?:公告|名单)|违规处理|治理公告")
# 正文里指向名单的锚点：<a ... href="....pdf" ...>8月28日处罚名单</a>
_PDF_ANCHOR = re.compile(r'(?s)<a\s[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.I)
# PDF 直链里的日期段：https://wow.res.netease.com/images/20260828/xxx.pdf
_URL_DATE = re.compile(r"/(\d{8})/")
# 标题里的日期：8月28日 / 12月4日
_TITLE_DATE = re.compile(r"(\d{1,2})月(\d{1,2})日")
# 标题里的赛季名：“至暗之夜”第二赛季 / “地心之战”第三赛季
_SEASON = re.compile(r"[“\"']([^”\"']{2,12})[”\"']\s*第([一二三四五六七八九十\d]+)赛季")
# PvE / PvP 归类
_MODE = re.compile(r"pv([ep])", re.I)
# 语义关键词：一条公告挂多份名单时，按钮文案往往不写 PvE/PvP，只写玩法
# （如「史诗钥石地下城处罚名单」+「PVP处罚名单」），这时靠玩法词判类别。
_PVE_HINT = re.compile(r"钥石|地下城|大秘境|团本|首领|头衔|副本|史诗难度")
_PVP_HINT = re.compile(r"竞技场|评级战场|战场|排位|角斗士")

_SEEN_FILE = "punish_feed_seen.json"


def _cn_num(s: str) -> str:
    """「2」/「二」都归一成中文数字，避免同一赛季出现两种目录名。"""
    table = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五",
             "6": "六", "7": "七", "8": "八", "9": "九", "10": "十"}
    return table.get(s, s)


def _detect_mode(title: str, anchor_text: str) -> str:
    """判 PVE / PVP。优先级从高到低：

    1. 按钮文案里的 PvE/PvP 字样（最直接，如「PVP处罚名单」）
    2. 按钮文案里的玩法词（如「史诗钥石地下城处罚名单」→ PVE）
    3. 标题里的 PvE/PvP —— 但**标题同时出现两者时不可信**：
       「第1赛季PvP/PvE赛季奖励处罚公告」这种一条挂两份名单，
       只取第一个匹配会把大秘境名单也判成 PVP。
    4. 标题里的玩法词
    5. 兜底 PVE（历史上不带类别标记的周更名单都是 PVE）
    """
    m = _MODE.search(anchor_text)
    if m:
        return "PVE" if m.group(1).lower() == "e" else "PVP"
    if _PVE_HINT.search(anchor_text):
        return "PVE"
    if _PVP_HINT.search(anchor_text):
        return "PVP"
    marks = {g.lower() for g in _MODE.findall(title)}
    if len(marks) == 1:
        return "PVE" if marks.pop() == "e" else "PVP"
    if _PVE_HINT.search(title):
        return "PVE"
    if _PVP_HINT.search(title):
        return "PVP"
    return "PVE"


def parse_meta(title: str, pdf_url: str, anchor_text: str = "") -> dict | None:
    """从公告标题 + 按钮文案 + PDF 直链推出 {date, season, mode}；缺日期返回 None。

    日期 = **公告发布日**，取直链的 /yyyymmdd/ 段（与标题里的「M月D日」一致），
    不用按钮文案里的日期：8月6日那份公告的按钮写的是「8月5日PVE处罚名单」，
    按按钮命名会得到 20260805，与公告日 20260806 的归档口径不一致。

    mode 见 _detect_mode：按钮优先于标题，玩法词可补按钮没写类别的情况。
    """
    url_m = _URL_DATE.search(pdf_url)
    date = url_m.group(1) if url_m else ""
    if not date:
        md = _TITLE_DATE.search(title)
        year = re.search(r"(20\d{2})", pdf_url)
        if not (md and year):
            return None
        date = f"{year.group(1)}{int(md.group(1)):02d}{int(md.group(2)):02d}"

    sm = _SEASON.search(title)
    season = f"{sm.group(1)}第{_cn_num(sm.group(2))}赛季" if sm else "未知赛季"
    return {"date": date, "season": season,
            "mode": _detect_mode(title, anchor_text)}


def target_name(meta: dict) -> str:
    return f"{meta['date']}_{meta['season']}_{meta['mode']}_处罚名单"


# 按钮文案 -> 文件名里的类别后缀（用于一条公告挂多份名单时区分）
_KIND_TAGS = (
    ("钥石", "史诗钥石地下城"), ("地下城", "史诗钥石地下城"), ("大秘境", "大秘境"),
    ("团本", "团本"), ("首领", "团本"), ("头衔", "头衔"),
    ("竞技场", "竞技场"), ("评级战场", "评级战场"), ("战场", "战场"),
)


def _existing_path(base, name: str):
    """已归档到子目录的同名 xlsx 路径；没有则 None。force 重抓时原地覆盖，
    不会在根目录再造一份重复文件。"""
    for p in base.rglob(f"{name}.xlsx"):
        return p
    return None


def _disambiguate(name: str, anchor: str, claimed: dict, base, force: bool = False) -> str | None:
    """同名冲突时，按按钮文案里的玩法词给类别段加后缀。

    `20260901_至暗之夜第一赛季_PVE_处罚名单`
      -> `20260901_至暗之夜第一赛季_PVE史诗钥石地下城_处罚名单`
    仍冲突或找不到玩法词时返回 None（宁可跳过也不覆盖已有数据）。
    """
    parts = name.split("_")
    if len(parts) != 4:
        return None
    tag = next((t for kw, t in _KIND_TAGS if kw in anchor), None)
    if not tag:
        return None
    alt = f"{parts[0]}_{parts[1]}_{parts[2]}{tag}_{parts[3]}"
    if alt in claimed:
        return None
    if not force and any(base.rglob(f"{alt}.xlsx")):
        return None
    return alt


async def find_candidates(max_articles: int = 8) -> list[dict]:
    """扫新闻列表 → 返回 [{title, article_url, pdf_url, meta}]（新→旧）。"""
    page = await fetch_text(news_svc.NEWS_URL, timeout=25)
    items = [it for it in news_svc.parse_news_items(page)
             if _TITLE_HINT.search(it["title"])][:max_articles]
    logger.info("[punishfeed] 列表页命中处罚类公告 %d 条", len(items))

    out: list[dict] = []
    for it in items:
        if not it["url"]:
            continue
        try:
            body = await fetch_text(it["url"], timeout=25)
        except Exception as e:  # noqa: BLE001
            logger.warning("[punishfeed] 打开公告失败 %s: %s", it["url"], e)
            continue
        for pdf_url, anchor in _PDF_ANCHOR.findall(body):
            anchor = re.sub(r"<[^>]+>", "", anchor).strip()
            meta = parse_meta(it["title"], pdf_url, anchor)
            if meta is None:
                logger.warning("[punishfeed] 认不出日期，跳过：%s | %s", it["title"], pdf_url)
                continue
            out.append({"title": it["title"], "article_url": it["url"],
                        "pdf_url": pdf_url, "anchor": anchor, "meta": meta})
    return out


def _seed_realms(base) -> set[str]:
    """从已有 xlsx 学服务器名词库，供粘连单元格拆分用。"""
    seed: set[str] = set()
    if not base.is_dir():
        return seed
    for x in sorted(base.rglob("*.xlsx")):
        try:
            for row in punish_svc._load(x):  # noqa: SLF001
                if row["realm"]:
                    seed.add(row["realm"])
        except Exception:  # noqa: BLE001
            continue
    return seed


def default_dir():
    """名单目录的默认值；实际目录由 main.py 按 punish_xlsx_dir 配置传入。"""
    return data_dir() / "punish"


def _seen() -> dict:
    return load_json(_SEEN_FILE, {}) or {}


def _mark_seen(pdf_url: str, name: str, rows: int) -> None:
    data = _seen()
    data[pdf_url] = {"file": name, "rows": rows}
    save_json(_SEEN_FILE, data)


def valid_seen(base) -> dict:
    """账本里**可信**的记录（url -> 记录）。不可信的一律剔除以便重抓。

    两种不可信，都是「账本说收录了，其实数据不在」：

    1. 多条 url 指向同一个 file —— 说明发生过同名覆盖，只有最后写入的那份留在盘上，
       其余数据已丢失。v1.1.8 抓「PvP/PvE 赛季奖励处罚公告」就是这样把 3179 行的
       大秘境名单覆盖没了，而账本仍认为它已收录、导致永远跳过。**冲突各方全部作废。**
    2. 记录里的 file 在磁盘上找不到（含子目录）—— 用户手动删过、换过目录，
       或当初写盘后又被清理。

    纯内存判断 + 一次目录列举，不读 xlsx 内容，每轮开销可忽略。
    """
    seen = _seen()
    if not seen:
        return {}
    owners: dict[str, list[str]] = {}
    for url, rec in seen.items():
        owners.setdefault((rec or {}).get("file", ""), []).append(url)
    on_disk = {p.stem for p in base.rglob("*.xlsx")} if base.is_dir() else set()

    good: dict[str, dict] = {}
    for url, rec in seen.items():
        name = (rec or {}).get("file", "")
        if not name:
            continue
        if len(owners.get(name, ())) > 1:
            logger.warning("[punishfeed] 账本冲突（%d 条记录指向 %s），作废以便重抓",
                           len(owners[name]), name)
            continue
        if name not in on_disk:
            logger.warning("[punishfeed] 账本记的 %s 已不在磁盘上，作废以便重抓", name)
            continue
        good[url] = rec
    return good


def _write_xlsx(path, header: list[str], rows: list[list[str]]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "数据"
    ws.append(header)
    for r in rows:
        ws.append(r)
    for i in range(1, len(header) + 1):
        ws.column_dimensions[chr(64 + i)].width = 22 if i == 1 else 16
    wb.properties.creator = "lianzy"
    wb.properties.lastModifiedBy = "lianzy"
    wb.save(str(path))


def _convert_sync(pdf_bytes: bytes, dest, seed: set[str]) -> tuple[int, list[str]]:
    """在线程里跑：PDF bytes → xlsx。返回 (行数, 警告)。空表视为失败。"""
    import tempfile
    from pathlib import Path

    from ..pdftable import extract_rows

    tmp = Path(tempfile.mkdtemp(prefix="punishpdf_"))
    tmp_pdf = tmp / "in.pdf"
    try:
        tmp_pdf.write_bytes(pdf_bytes)
        rows, header, warns = extract_rows(tmp_pdf, seed)
        if not rows:
            raise RuntimeError(f"没解析出数据行（表头识别失败？列：{' / '.join(header)}）")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_xlsx(dest, header, rows)
        return len(rows), warns
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


async def sync_once(base=None, max_articles: int = 8, force: bool = False) -> list[dict]:
    """跑一轮抓取。返回本轮**新收录**的 [{file, rows, title, warns}]。

    base 为名单目录（默认 plugin_data/punish）。目标 xlsx 已存在（含子目录）
    或 pdf_url 在**可信**账本里的直接跳过，所以可以放心每 N 分钟跑。
    force=True 时忽略账本、也忽略磁盘上的同名文件，全部重抓一遍（覆盖写）。
    """
    base = base or default_dir()
    try:
        cands = await find_candidates(max_articles)
    except Exception as e:  # noqa: BLE001
        logger.warning("[punishfeed] 扫新闻失败: %s", e)
        return []

    seen = {} if force else valid_seen(base)
    todo = []
    claimed: dict[str, str] = {}  # name -> pdf_url，防同一轮内两份名单撞同名
    for c in cands:
        name = target_name(c["meta"])
        # rglob：用户可能把名单归档进子目录，别重复下载
        if not force and any(base.rglob(f"{name}.xlsx")):
            continue
        if c["pdf_url"] in seen:
            continue
        if name in claimed:
            # 一条公告挂多份名单且类别判成了同一个（如「史诗钥石地下城」+「PVP」都
            # 落到 PVP）。绝不能让后者覆盖前者，用按钮文案加后缀区分。
            alt = _disambiguate(name, c["anchor"], claimed, base, force=force)
            if alt is None:
                logger.warning("[punishfeed] 命名冲突且无法区分，跳过：%s ← %s | %s",
                               name, c["anchor"], c["pdf_url"])
                continue
            name = alt
        claimed[name] = c["pdf_url"]
        todo.append((c, name, _existing_path(base, name) or base / f"{name}.xlsx"))
    if not todo:
        return []

    seed = await asyncio.to_thread(_seed_realms, base)
    done: list[dict] = []
    for c, name, dest in todo:
        try:
            raw = await fetch_bytes(c["pdf_url"], timeout=120)
        except Exception as e:  # noqa: BLE001
            logger.warning("[punishfeed] 下载 PDF 失败 %s: %s", c["pdf_url"], e)
            continue
        try:
            rows, warns = await asyncio.to_thread(_convert_sync, raw, dest, seed)
        except Exception as e:  # noqa: BLE001
            logger.warning("[punishfeed] 转换失败 %s: %s", name, e)
            continue
        punish_svc.invalidate_cache()
        _mark_seen(c["pdf_url"], name, rows)
        logger.info("[punishfeed] 已收录 %s：%d 行，警告 %d", name, rows, len(warns))
        done.append({"file": name, "rows": rows, "title": c["title"],
                     "warns": len(warns), "meta": c["meta"]})
    return done


def report_text(done: list[dict]) -> str:
    """新收录战报 -> 群消息。"""
    if not done:
        return ""
    lines = [f"已自动收录 {len(done)} 份处罚名单：", ""]
    for d in done:
        m = d["meta"]
        date = f"{m['date'][:4]}年{int(m['date'][4:6])}月{int(m['date'][6:])}日"
        lines.append(f"  · {date} {m['mode']}（{m['season']}）{d['rows']} 条")
    lines.append("")
    lines.append("现在可以直接查了，例：处罚 张三丰 白银之手")
    return "\n".join(lines)
