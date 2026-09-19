# -*- coding: utf-8 -*-
"""WCL 查询文本格式化（Markdown，紧凑对齐式）。"""

from __future__ import annotations

import unicodedata

from ..data.names import class_cn, dungeon_cn, realm_cn, spec_cn


def _disp_width(s: str) -> int:
    """显示宽度：CJK/全角算 2，其余算 1（QQ 客户端的近似渲染宽度）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad_to(s: str, width: int, fill: str = " ") -> str:
    """按显示宽度右侧补 fill 到 width（fill 重复、最后截到恰好补齐）。"""
    gap = width - _disp_width(s)
    if gap <= 0:
        return s
    unit = len(fill)
    reps = gap // unit
    out = s + fill * reps
    if gap % unit:
        out += fill[: gap % unit]
    return out


def format_profile(p) -> str:
    name = p.name or "未知角色"
    realm = realm_cn(p.realm) or "未知服务器"
    cls = class_cn(p.class_name) or "未知"
    spec = spec_cn(p.active_spec) or "未知"

    # 头部：角色行 + 属性行 + 排名行（原本 6 行压成 4 行）
    lines = [f"**⚔ {name}**〈{realm}〉"]
    ilvl = f"{p.equipped_ilvl:.0f}" if p.equipped_ilvl > 0 else "暂无"
    score = f"{p.score:.2f}" if p.score > 0 else "暂无"
    lines.append(f"{spec}{cls} · 装等 {ilvl} · WCL评分 **{score}**")
    lines.append(
        "世界 {} ｜ 国服 {} ｜ 服务器 {}".format(
            f"#{p.rank_world}" if p.rank_world > 0 else "暂无",
            f"#{p.rank_region}" if p.rank_region > 0 else "暂无",
            f"#{p.rank_realm}" if p.rank_realm > 0 else "暂无",
        )
    )

    if not p.dungeons:
        lines.append("")
        lines.append("**🏆 大秘境详情**：暂无")
        return "\n".join(lines)

    # 全量副本清单：赛季全部 8 本（season_dungeon_names，含未打）；
    # 取不到清单时（WCL zone 探测失败）退回角色实际打过的。
    # 列表按「层数降序 → 分数降序」排，强的本排前面。
    played = {d["name"]: d for d in p.dungeons}
    all_names = p.season_dungeon_names or list(played)
    rows = []
    for name_en in all_names:
        d = played.get(name_en)
        if d:
            lvl = d.get("level") or 0
            rows.append((1, -lvl, -d["score"], dungeon_cn(name_en),
                         f"+{lvl}", f"{d['score']:.2f}", d["total_kills"]))
        else:
            rows.append((2, 0, 0, dungeon_cn(name_en), "—", None, 0))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))

    lines.append("")
    lines.append(f"**🏆 大秘境详情**（{len(rows)} 个）")
    name_w = max(_disp_width(r[3]) for r in rows) + 2  # 名称列宽 + 间隔
    lvl_w = max(_disp_width(r[4]) for r in rows) + 2   # 层数列宽 + 间隔
    for _, _, _, cn, lvl, score_s, kills in rows:
        if score_s is None:
            lines.append(f"{_pad_to(cn, name_w)}未打")
            continue
        suffix = f"（×{kills}）" if kills > 0 else ""
        lines.append(f"{_pad_to(cn, name_w)}{_pad_to(lvl, lvl_w)}{score_s}{suffix}")
    return "\n".join(lines)
