# -*- coding: utf-8 -*-
"""bloodmallet 数据源：BIS 饰品排行 / 专精强度榜。"""

from __future__ import annotations

import asyncio
import logging

from .net import fetch_json

logger = logging.getLogger("astrbot_plugin_wow.bloodmallet")

BASE = "https://bloodmallet.com/chart/get"
DEFAULT_ILVL = 298
# 原版 bis.go 的两种战斗风格：单体木桩 / 多目标
FIGHT_STYLE_ST = "castingpatchwerk"
FIGHT_STYLE_AOE5 = "castingpatchwerk5"
FIGHT_STYLE_AOE = "castingpatchwerk5"
FIGHT_STYLE = FIGHT_STYLE_ST

# 输出向专精 + 中文名（原版 specrank.go 的 specs 是 26 个；
# Midnight(12.0) 恶魔猎手新增 devourer/噬灭 后为 27 个，不含坦克专精）
OUTPUT_SPECS: list[tuple[str, str, str]] = [
    ("death_knight", "frost", "冰霜DK"), ("death_knight", "unholy", "邪恶DK"),
    ("mage", "fire", "火法"), ("mage", "frost", "冰法"), ("mage", "arcane", "奥法"),
    ("warlock", "destruction", "毁灭术"), ("warlock", "affliction", "痛苦术"),
    ("warlock", "demonology", "恶魔术"),
    ("hunter", "marksmanship", "射击猎"), ("hunter", "survival", "生存猎"),
    ("hunter", "beast_mastery", "兽王猎"),
    ("rogue", "outlaw", "狂徒"), ("rogue", "subtlety", "敏锐贼"),
    ("rogue", "assassination", "刺杀贼"),
    ("priest", "shadow", "暗牧"),
    ("paladin", "retribution", "惩戒骑"),
    ("warrior", "arms", "武器战"), ("warrior", "fury", "狂暴战"),
    ("monk", "windwalker", "踏风"),
    ("druid", "balance", "平衡德"), ("druid", "feral", "野德"),
    ("shaman", "elemental", "元素萨"), ("shaman", "enhancement", "增强萨"),
    ("demon_hunter", "havoc", "浩劫DH"),
    ("demon_hunter", "devourer", "噬灭DH"),
    ("evoker", "devastation", "湮灭龙"), ("evoker", "augmentation", "增辉龙"),
]

# 饰品来源中文化（原版 bis.go srcCN）
SOURCE_CN = {
    "Raid": "团本", "Dungeon": "地下城", "World Boss": "世界首领",
    "Profession": "制作", "Delve": "地下堡", "Reputation": "声望",
    "High PvP": "高阶PVP", "World Quest": "世界任务", "PvP": "PVP",
    "Seasonal": "赛季", "Crafting": "制作", "Mythic+": "大秘境",
}


def source_cn(s: str) -> str:
    """饰品来源英文 → 中文，未收录则原样返回。"""
    return SOURCE_CN.get(s, s or "")


class BloodData:
    """bloodmallet 图表数据。"""

    def __init__(self, raw: dict):
        self.raw = raw
        self.status = raw.get("status", "")
        self.message = raw.get("message", "")
        self.data: dict[str, dict[str, float]] = self._normalize(raw.get("data"))
        self.data_active: dict[str, bool] = raw.get("data_active") or {}
        self.data_sources: dict[str, str] = raw.get("data_sources") or {}
        self.translations: dict = raw.get("translations") or {}
        self.sim_steps: list[int] = raw.get("simulated_steps") or []
        self.item_ids: dict[str, int] = raw.get("item_ids") or {}

    @staticmethod
    def _normalize(data) -> dict[str, dict[str, float]]:
        """data 兼容嵌套（name -> {档位: dps}）与扁平（name -> dps）两种形状。"""
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict[str, float]] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                try:
                    out[k] = {str(ik): float(iv) for ik, iv in v.items()}
                except (TypeError, ValueError):
                    continue
            else:
                try:
                    out[k] = {"": float(v)}
                except (TypeError, ValueError):
                    continue
        return out

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def no_standard_chart(self) -> bool:
        return self.is_error and "no standard chart" in self.message.lower()

    def pick_dps(self, m: dict[str, float], ref_ilvl: int = DEFAULT_ILVL) -> float:
        """取 <= ref_ilvl 的最高装等档 DPS。"""
        if str(ref_ilvl) in m:
            return m[str(ref_ilvl)]
        best, best_il = 0.0, -1
        for k, v in m.items():
            if not k:
                return v
            try:
                il = int(k)
            except ValueError:
                continue
            if il <= ref_ilvl and il > best_il:
                best_il, best = il, v
        return best

    def best_ilvl(self, m: dict[str, float], ref_ilvl: int = DEFAULT_ILVL) -> int:
        """与 pick_dps 对应的实际装等档位。"""
        if str(ref_ilvl) in m:
            return ref_ilvl
        best = -1
        for k in m:
            try:
                il = int(k)
            except ValueError:
                continue
            if il <= ref_ilvl and il > best:
                best = il
        return best

    def item_cn(self, name: str) -> str:
        """中文名，兜底英文。bloodmallet 的 translations 是扁平的 name -> {locale: 名字}。"""
        cn = self.translations.get(name)
        if isinstance(cn, dict):
            return cn.get("cn_CN") or cn.get("zh_CN") or cn.get("zhCN") or name
        return name

    def active_keys(self) -> list[str]:
        """仍在启用的条目，跳过基准行（与原版 activeTrinketKeys 一致）。"""
        return [
            n for n in self.data
            if n != "baseline" and self.data_active.get(n, True)
        ]


async def get_chart(
    chart_type: str, class_name: str, spec: str, fight_style: str = FIGHT_STYLE_ST
) -> BloodData:
    url = f"{BASE}/{chart_type}/{fight_style}/{class_name}/{spec}"
    try:
        raw = await fetch_json(url, timeout=30)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"bloodmallet 数据拉取失败：{e}") from e
    if not isinstance(raw, dict):
        raise RuntimeError("bloodmallet 返回数据格式异常")
    return BloodData(raw)


async def get_bis_data(
    class_name: str, spec: str, fight_style: str = FIGHT_STYLE_ST
) -> dict[str, BloodData | Exception]:
    """并发拉取三类图表。单类失败只记在对应键上，由调用方决定降级策略。"""
    results = await asyncio.gather(
        get_chart("trinkets", class_name, spec, fight_style),
        get_chart("secondary_distributions", class_name, spec, fight_style),
        get_chart("races", class_name, spec, fight_style),
        return_exceptions=True,
    )
    return dict(zip(("trinkets", "secondary", "races"), results))


async def spec_strength_rank(fight_style: str = FIGHT_STYLE_ST) -> tuple[list[dict], int]:
    """专精强度榜：并发拉取全部输出向专精的 races 数据。

    返回 (排序后的行, 数据源暂无数据而被跳过的专精数)。
    """
    sem = asyncio.Semaphore(8)

    async def one(cls: str, spec: str, cn: str) -> dict | None:
        async with sem:
            try:
                d = await get_chart("races", cls, spec, fight_style)
                if d.is_error or not d.data:
                    return None
                top = max((max(v.values()) for v in d.data.values()), default=0.0)
                if top <= 0:
                    return None
                return {"class": cls, "spec": spec, "cn_name": cn, "dps": top}
            except Exception as e:  # noqa: BLE001
                logger.warning("强度榜 %s/%s 失败: %s", cls, spec, e)
                return None

    got = await asyncio.gather(*(one(c, s, cn) for c, s, cn in OUTPUT_SPECS))
    rows = [r for r in got if r]
    skipped = len(OUTPUT_SPECS) - len(rows)
    if not rows:
        raise RuntimeError("强度榜数据拉取失败")
    rows.sort(key=lambda r: r["dps"], reverse=True)
    top = rows[0]["dps"]
    for r in rows:
        r["pct"] = r["dps"] / top * 100 if top else 0
    return rows, skipped