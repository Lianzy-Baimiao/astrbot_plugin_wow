# -*- coding: utf-8 -*-
"""BIS 饰品排行 / 专精强度榜（bis + specrank）服务。"""

from __future__ import annotations

import logging

from ..bloodmallet import (
    DEFAULT_ILVL,
    FIGHT_STYLE_AOE,
    FIGHT_STYLE_AOE5,
    FIGHT_STYLE_ST,
    BloodData,
    get_bis_data,
    get_chart,
    source_cn,
    spec_strength_rank,
)
from ..data.specs import (
    SPEC_DISPLAY_NAME,
    SPEC_SUGGESTION,
    UNSUPPORTED_SPECS,
    resolve_spec,
)

logger = logging.getLogger("astrbot_plugin_wow.bis")

# 满级英雄毕业装等（当前版本，用户确认）
HERO_ILVL = 321

# 数据源确实没有该专精的标准图表（不是网络问题），文案要和网络失败区分开
NO_CHART_HINT = (
    "bloodmallet 当前未提供 {who} 的标准仿真数据。\n"
    "这是数据源侧的缺口（他们的仿真队列还没跑到），不是你打错了。\n"
    "可以先用「强度榜」看看现在哪些专精有数据。"
)


def _parse_trinkets(d: BloodData, ref_ilvl: int = DEFAULT_ILVL) -> tuple[list[dict], float]:
    """饰品数据：data_active 过滤 + 装等档取 DPS + 提升百分比 + 中文名 + 多装等曲线点。

    返回 (行, 基准 DPS)。每行含 points=[(ilvl, dps), ...] 用于 SVG 曲线。
    """
    base = 0.0
    if "baseline" in d.data:
        base = d.pick_dps(d.data["baseline"], ref_ilvl)
    out = []
    for name in d.active_keys():
        m = d.data.get(name)
        if not m:
            continue
        dps = d.pick_dps(m, ref_ilvl)
        if dps <= 0:
            continue
        gain = (dps - base) / base * 100 if base > 0 else 0
        # 多装等曲线点（装等升序）
        points = []
        for ilv, v in sorted(m.items()):
            try:
                points.append((int(ilv), float(v)))
            except (ValueError, TypeError):
                continue
        out.append(
            {
                "name": d.item_cn(name),
                "ilvl": d.best_ilvl(m, ref_ilvl),
                "dps": dps,
                "pct": gain,
                "source": source_cn(d.data_sources.get(name, "")),
                "item_id": int(d.item_ids.get(name, 0) or 0),
                "points": points,
            }
        )
    out.sort(key=lambda x: x["dps"], reverse=True)
    return out[:15], base


def _parse_secondary(d: BloodData) -> tuple[list[dict], float]:
    """最佳副属性分配：内层 key 形如 "10_20_30_40"（暴击_急速_精通_全能）。"""
    best, best_dps = "", 0.0
    for inner in d.data.values():
        for dist, dps in inner.items():
            if dps > best_dps:
                best, best_dps = dist, dps
    if not best:
        return [], 0.0
    parts = best.split("_")
    labels = ["暴击", "急速", "精通", "全能"]
    return [
        {"name": labels[i] if i < len(labels) else f"属性{i}", "value": int(p)}
        for i, p in enumerate(parts) if p.isdigit()
    ], best_dps


def _parse_races(d: BloodData) -> list[dict]:
    """种族按 DPS 降序（races 的 data 是扁平 name -> dps，已被统一成 name -> {"": dps}）。"""
    rows = []
    for name, inner in d.data.items():
        if name == "baseline":
            continue
        v = max(inner.values(), default=0.0)
        rows.append({"name": d.item_cn(name), "value": v})
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


def _resolve(spec_input: str) -> tuple[str, str, str]:
    cls, spec, ok = resolve_spec(spec_input)
    if not ok:
        raise RuntimeError(f"无法识别专精：{spec_input}。试试：{SPEC_SUGGESTION}")
    key = f"{cls}/{spec}"
    if key in UNSUPPORTED_SPECS:
        raise RuntimeError(UNSUPPORTED_SPECS[key])
    return cls, spec, key


def _check(d: BloodData | Exception, who: str) -> BloodData:
    """把「数据源没有该专精」和「网络/解析失败」分开报。"""
    if isinstance(d, Exception):
        raise RuntimeError(f"bloodmallet 数据拉取失败：{d}") from d
    if d.no_standard_chart:
        raise RuntimeError(NO_CHART_HINT.format(who=who))
    if d.is_error:
        raise RuntimeError(f"bloodmallet：{d.message or '返回错误'}")
    return d


def _ref_ilvl(d: BloodData) -> int:
    """基准装等：满级英雄毕业装等（当前版本 = 321，用户确认）。"""
    steps = sorted({int(s) for s in d.sim_steps if str(s).isdigit()})
    if not steps:
        return HERO_ILVL
    hero = max((s for s in steps if s <= HERO_ILVL), default=steps[0])
    return hero


async def build_bis(spec_input: str) -> dict:
    """BIS 推荐数据（出图用，与原版 drawBIS 对齐）。

    只硬依赖 trinkets；secondary / races 拿不到就降级为空段，不整体失败。
    """
    cls, spec, key = _resolve(spec_input)
    who = SPEC_DISPLAY_NAME.get(key, key)
    data = await get_bis_data(cls, spec)
    trinkets_d = _check(data["trinkets"], who)
    ref = _ref_ilvl(trinkets_d)
    trinkets, base = _parse_trinkets(trinkets_d, ref)
    if not trinkets:
        raise RuntimeError(NO_CHART_HINT.format(who=who))

    secondary: list[dict] = []
    secondary_dps = 0.0
    sec = data["secondary"]
    if isinstance(sec, BloodData) and not sec.is_error:
        secondary, secondary_dps = _parse_secondary(sec)
    else:
        logger.warning("BIS %s 副属性数据不可用: %s", key, sec)

    races: list[dict] = []
    rc = data["races"]
    if isinstance(rc, BloodData) and not rc.is_error:
        races = _parse_races(rc)
    else:
        logger.warning("BIS %s 种族数据不可用: %s", key, rc)

    return {
        "spec": who,
        "ref_ilvl": trinkets[0]["ilvl"],
        "base": base,
        "trinkets": trinkets[:3],
        "secondary": secondary,
        "secondary_dps": secondary_dps,
        "race": races[0] if races else None,
    }


async def build_trinket_rank(spec_input: str) -> dict:
    """饰品排行（单体 + 5 目标双区块，各 Top10）。"""
    cls, spec, key = _resolve(spec_input)
    who = SPEC_DISPLAY_NAME.get(key, key)
    d_st = _check(await _safe_chart("trinkets", cls, spec, FIGHT_STYLE_ST), who)
    ref_st = _ref_ilvl(d_st)
    trinkets_st, base_st = _parse_trinkets(d_st, ref_st)

    d_aoe = _check(await _safe_chart("trinkets", cls, spec, FIGHT_STYLE_AOE5), who)
    ref_aoe = _ref_ilvl(d_aoe)
    trinkets_aoe, base_aoe = _parse_trinkets(d_aoe, ref_aoe)

    if not trinkets_st and not trinkets_aoe:
        raise RuntimeError(NO_CHART_HINT.format(who=who))

    # 图标统一补齐（两区块合并去重）
    item_ids = list({t["item_id"] for t in trinkets_st + trinkets_aoe if t.get("item_id")})
    try:
        from ..wago import item_icon_urls
        icons = await item_icon_urls(item_ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("饰品图标补齐失败: %s", e)
        icons = {}
    for t in trinkets_st + trinkets_aoe:
        t["icon_url"] = icons.get(t.get("item_id", 0), "")

    return {
        "spec": who,
        "st": {
            "label": "单体木桩",
            "ref_ilvl": ref_st,
            "base": base_st,
            "trinkets": trinkets_st[:10],
        },
        "aoe5": {
            "label": "5 目标",
            "ref_ilvl": ref_aoe,
            "base": base_aoe,
            "trinkets": trinkets_aoe[:10],
        },
    }


async def _safe_chart(chart: str, cls: str, spec: str, style: str | None = None) -> BloodData | Exception:
    try:
        return await get_chart(chart, cls, spec, fight_style=style or FIGHT_STYLE_ST)
    except Exception as e:  # noqa: BLE001
        return e


async def build_spec_rank(aoe: bool = False) -> tuple[list[dict], int, bool]:
    """专精强度榜。返回 (行, 被跳过的专精数, 是否 AoE 榜)。"""
    style = FIGHT_STYLE_AOE if aoe else FIGHT_STYLE_ST
    rows, skipped = await spec_strength_rank(style)
    return rows, skipped, aoe
