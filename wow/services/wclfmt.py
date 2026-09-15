# -*- coding: utf-8 -*-
"""WCL 查询文本格式化。"""

from __future__ import annotations

from ..data.names import class_cn, dungeon_cn, realm_cn, spec_cn


def format_profile(p) -> str:
    name = p.name or "未知角色"
    realm = realm_cn(p.realm) or "未知服务器"
    cls = class_cn(p.class_name) or "未知"
    spec = spec_cn(p.active_spec) or "未知"

    lines = ["**Warcraft Logs 大秘境**"]
    lines.append(f"**{name}**〈{realm}〉")
    ilvl = f"{p.equipped_ilvl:.0f}" if p.equipped_ilvl > 0 else "暂无"
    lines.append(f"职业：{cls} ｜ 专精：{spec} ｜ 装备装等：{ilvl}")
    zone = p.zone_name or "未知"
    if p.zone_id > 0:
        lines.append(f"**当前 Mythic+**：{zone}（Zone {p.zone_id}）")
    else:
        lines.append(f"**当前 Mythic+**：{zone}")
    score = f"{p.score:.2f}" if p.score > 0 else "暂无"
    lines.append(f"**WCL playerscore**：{score}")
    lines.append(
        "**排名**：世界 {} ｜ 国服 {} ｜ 服务器 {}".format(
            f"#{p.rank_world}" if p.rank_world > 0 else "暂无",
            f"#{p.rank_region}" if p.rank_region > 0 else "暂无",
            f"#{p.rank_realm}" if p.rank_realm > 0 else "暂无",
        )
    )
    if not p.dungeons:
        lines.append("**地城分项**：暂无")
        return "\n".join(lines)
    lines.append("**地城分项**：")
    for i, d in enumerate(p.dungeons[:5]):
        suffix = f"（完成 {d['total_kills']} 次）" if d["total_kills"] > 0 else ""
        lines.append(f"{i + 1}. {dungeon_cn(d['name'])}：`{d['score']:.2f}`{suffix}")
    return "\n".join(lines)