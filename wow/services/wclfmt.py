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
        lines.append("**大秘境详情**：暂无")
        return "\n".join(lines)
    # 全量副本清单：赛季全部 8 本（season_dungeons，含未打）；
    # 取不到清单时（WCL zone 探测失败）退回角色实际打过的
    played = {d["name"]: d for d in p.dungeons}
    all_names = p.season_dungeon_names or list(played)
    lines.append(f"**大秘境详情**（{len(all_names)} 个）：")
    for name_en in all_names:
        d = played.get(name_en)
        if d:
            lvl = f"+{d['level']}" if d.get("level") else "?"
            suffix = f"（完成 {d['total_kills']} 次）" if d["total_kills"] > 0 else ""
            lines.append(f"- {dungeon_cn(name_en)}：{lvl} ｜ `{d['score']:.2f}`{suffix}")
        else:
            lines.append(f"- {dungeon_cn(name_en)}：未打")
    return "\n".join(lines)