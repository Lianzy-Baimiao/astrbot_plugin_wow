# -*- coding: utf-8 -*-
"""mythicstats.com 大秘境排行抓取（输出 / 防御 / 治疗三段）。"""

from __future__ import annotations

import html as html_mod
import logging
import re

from .net import fetch_text

logger = logging.getLogger("astrbot_plugin_wow.mythicstats")

TALENT_CN = {
    # —— 输出 ——
    "unholy death-knight": "邪DK", "outlaw rogue": "狂徒", "feral druid": "猫德",
    "elemental shaman": "元素萨", "balance druid": "平衡德", "assassination rogue": "刺杀",
    "retribution paladin": "惩戒", "demonology warlock": "恶魔术", "windwalker monk": "踏风",
    "marksmanship hunter": "射击猎", "enhancement shaman": "增强萨", "fire mage": "火法",
    "beast-mastery hunter": "兽王", "havoc demon-hunter": "浩劫", "devastation evoker": "湮灭",
    "arms warrior": "武器战", "destruction warlock": "毁灭术", "affliction warlock": "痛苦术",
    "shadow priest": "暗牧", "frost death-knight": "冰DK", "frost mage": "冰法",
    "subtlety rogue": "敏锐", "fury warrior": "狂暴战", "survival hunter": "生存猎",
    "arcane mage": "奥法", "augmentation evoker": "增辉",
    # Midnight(12.0) 新增的恶魔猎手第三专精（Devourer，虚空系）
    # 中文名取自 wago.tools ChrSpecialization locale=zhCN，ClassID 12
    "devourer demon-hunter": "噬灭DH",
    # —— 防御 ——
    "blood death-knight": "血DK", "protection warrior": "防战",
    "vengeance demon-hunter": "复仇DH", "guardian druid": "熊德",
    "brewmaster monk": "酒仙", "protection paladin": "防骑",
    # —— 治疗 ——
    "preservation evoker": "恩护", "mistweaver monk": "织雾",
    "restoration shaman": "恢复萨", "holy paladin": "奶骑",
    "holy priest": "神牧", "discipline priest": "戒律",
    "restoration druid": "奶德",
}

# 页面把三种定位分成三段（Damage / Tank / Healer specs），列名与量纲一致：
# # / Diff / Tier / Avg / Top / Runs，全部是 DPS。
ROLE_LABEL = {"damage": "输出", "tank": "防御", "healer": "治疗"}
_SECTION_RE = re.compile(
    r"(?s)(Damage|Tank|Healer)\s*specs(.*?)(?=(?:Damage|Tank|Healer)\s*specs|$)", re.I
)
# 每行 stats：grid grid-cols-6 gap-px w-56 块，匹配到下一行/a 标签/结尾
_ROW_RE = re.compile(
    r'(?s)<div class="grid grid-cols-6 gap-px w-56">(.*?)(?=<a class="flex"|<div class="grid grid-cols-6 gap-px w-56"|$)',
    re.I,
)
_CELL_RE = re.compile(r'(?s)<div[^>]*>(.*?)</div>')
# talent：随后的 <a> 标签
_TALENT_RE = re.compile(r'(?s)<a class="flex"[^>]*>(.*?)</a>')
_SPAN_RE = re.compile(r'(?s)<span[^>]*>(.*?)</span>')
_IMG_RE = re.compile(r'<img[^>]*src="([^"]*)"')


def _text(s: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _parse_metric(v: str) -> float:
    """解析 "203K"/"9.6K"/"1.2M" 为数值。"""
    v = v.strip().replace(",", "")
    if not v:
        return 0.0
    try:
        if v.endswith("M"):
            return float(v[:-1]) * 1_000_000
        if v.endswith("K"):
            return float(v[:-1]) * 1000
        return float(v)
    except ValueError:
        return 0.0


def _fmt_cn(v: float) -> str:
    """数值转中文习惯：22.6万 / 1.5千 / 342。"""
    if v >= 10000:
        s = f"{v / 10000:.1f}"
        return s.rstrip("0").rstrip(".") + "万"
    if v >= 1000:
        s = f"{v / 1000:.1f}"
        return s.rstrip("0").rstrip(".") + "千"
    return f"{v:.0f}"


def _parse_section(body: str, limit: int) -> tuple[list[dict], list[str]]:
    """解析一段（输出/防御/治疗）的行。返回 (行, 未映射的英文专精名)。"""
    stats_rows = []
    for m in _ROW_RE.finditer(body):
        cells = [_text(c) for c in _CELL_RE.findall(m.group(1))]
        if len(cells) >= 6 and cells[2] and cells[2] not in ("Tier", "Rating", "#"):
            stats_rows.append({"pos": m.start(), "cells": cells})
    talent_rows = []
    for m in _TALENT_RE.finditer(body):
        span = _SPAN_RE.search(m.group(1))
        talent = _text(span.group(1)) if span else ""
        img_m = _IMG_RE.search(m.group(1))
        img = img_m.group(1) if img_m else ""
        if img.startswith("//"):
            img = "https:" + img
        elif img and not img.startswith("http"):
            img = "https://mythicstats.com" + img
        talent_rows.append({"pos": m.start(), "talent": talent, "img": img})

    rows: list[dict] = []
    unmapped: list[str] = []
    for s in stats_rows:
        partner = None
        for t in talent_rows:
            if t["pos"] > s["pos"]:
                partner = t
                break
        label = (partner or {}).get("talent", "")
        if not label:
            continue
        # 认不出的专精**不能静默丢掉**：暴雪加新专精（如 Midnight 的噬灭DH）时，
        # 丢行会让榜单默默少一条、没人发现。这里回落英文名并记日志，宁难看不缺行。
        cn = TALENT_CN.get(label)
        if not cn:
            cn = label
            unmapped.append(label)
        cells = s["cells"]
        avg_num = _parse_metric(cells[3])
        top_num = _parse_metric(cells[4])
        sample_num = _parse_metric(cells[5])
        rows.append(
            {
                "spec": cn,
                "rating": cells[2],
                "average": cells[3],
                "average_num": avg_num,
                "average_cn": _fmt_cn(avg_num),
                "top": cells[4],
                "top_num": top_num,
                "top_cn": _fmt_cn(top_num),
                "sample": cells[5],
                "sample_num": sample_num,
                "sample_cn": _fmt_cn(sample_num),
                "img": partner["img"] if partner else "",
            }
        )
        if len(rows) >= limit:
            break
    return rows, unmapped


async def fetch_role_ranks(limit: int = 40) -> list[dict]:
    """抓取 mythicstats.com/dps 的输出 / 防御 / 治疗三段排行。

    返回 [{"role","label","rows"}, ...]，按页面顺序（输出→防御→治疗），空段不返回。
    三段量纲一致（都是 DPS），但各段自成一榜（页面的 Tier 与名次都是段内相对），
    所以条长要在段内归一化，不能跟输出段的榜首比。
    limit 只是防页面结构异常时无限膨胀的安全上限。
    """
    page = await fetch_text("https://mythicstats.com/dps", timeout=20)
    groups: list[dict] = []
    unmapped: list[str] = []
    for m in _SECTION_RE.finditer(page):
        role = m.group(1).lower()
        rows, un = _parse_section(m.group(2), limit)
        unmapped += un
        if rows:
            groups.append({"role": role, "label": ROLE_LABEL.get(role, role), "rows": rows})
    if not groups:
        logger.warning("mythicstats 页面结构变化：三段都没解析到行")
    if unmapped:
        logger.warning(
            "mythicstats 有 %d 个专精没有中文映射，已按英文名显示，请补 TALENT_CN：%s",
            len(unmapped), "、".join(dict.fromkeys(unmapped)),
        )
    return groups


async def fetch_dps_rank(limit: int = 40) -> list[dict]:
    """只要输出段（保留旧接口，供老调用方/降级路径使用）。"""
    for g in await fetch_role_ranks(limit):
        if g["role"] == "damage":
            return g["rows"]
    return []