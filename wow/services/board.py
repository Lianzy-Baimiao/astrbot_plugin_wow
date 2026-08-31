# -*- coding: utf-8 -*-
"""魔兽群榜单（wowboard）服务：名单/榜单/周报/查卡。"""

from __future__ import annotations

import datetime as dt
import logging
import re

from ..data.names import class_cn, realm_cn, spec_cn
from ..net import fetch_json
from ..store import get_board_store
from ..wcl import get_wcl_client, realm_slug

logger = logging.getLogger("astrbot_plugin_wow.board")

RIO_FIELDS = "gear,mythic_plus_scores_by_season%3Acurrent,mythic_plus_ranks"


async def fetch_rio_profile(name: str, realm: str) -> dict:
    """raider.io 主源查询。"""
    url = (
        "https://raider.io/api/v1/characters/profile?region=cn"
        f"&realm={realm}&name={name}&fields={RIO_FIELDS}"
    )
    return await fetch_json(url, timeout=30)


def _rio_ok(p: dict) -> bool:
    if not p or not p.get("name"):
        return False
    scores = p.get("mythic_plus_scores_by_season") or []
    if not scores:
        return False
    all_score = (scores[0].get("scores") or {}).get("all", 0) or 0
    if all_score <= 0:
        return False
    gear = p.get("gear") or {}
    if not gear.get("item_level_equipped"):
        return False
    return True


async def fetch_combined_profile(name: str, realm: str, wcl_client=None) -> dict:
    """双源融合：RIO 优先，失败/0分/陈旧时 WCL 回退。"""
    result = {"name": name, "realm": realm, "source": "rio"}
    try:
        p = await fetch_rio_profile(name, realm)
    except Exception as e:  # noqa: BLE001
        logger.warning("RIO 查询 %s-%s 失败: %s", name, realm, e)
        p = None
    if p and _rio_ok(p):
        scores = p.get("mythic_plus_scores_by_season") or []
        ranks = p.get("mythic_plus_ranks") or {}
        cur_rank = next(iter(ranks.values()), {}) if ranks else {}
        gear = p.get("gear") or {}
        result.update(
            {
                "name": p.get("name", name),
                "realm": p.get("realm", realm),
                "class": class_cn(p.get("class", "")),
                "spec": spec_cn(p.get("active_spec_name", "")),
                "score": float((scores[0].get("scores") or {}).get("all", 0) or 0) if scores else 0,
                "ilvl": float(gear.get("item_level_equipped", 0) or 0),
                "rank_realm": cur_rank.get("realm", 0),
                "rank_region": cur_rank.get("region", 0),
                "rank_world": cur_rank.get("world", 0),
                "last_crawled_at": p.get("last_crawled_at", ""),
                "thumbnail_url": p.get("thumbnail_url", ""),
            }
        )
        return result
    # WCL 回退
    if wcl_client is None:
        wcl_client = get_wcl_client()
    try:
        prof = await wcl_client.fetch_character(name, realm, force_update=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("WCL 回退 %s-%s 失败: %s", name, realm, e)
        result["error"] = str(e)
        return result
    result.update(
        {
            "name": prof.name,
            "realm": realm_cn(prof.realm),
            "class": prof.class_name,
            "spec": spec_cn(prof.active_spec),
            "score": prof.score,
            "ilvl": prof.equipped_ilvl,
            "rank_realm": prof.rank_realm,
            "rank_region": prof.rank_region,
            "rank_world": prof.rank_world,
            "source": "wcl",
        }
    )
    return result


def _is_week_key(w: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}", w))


def current_week_key(now: dt.datetime | None = None) -> str:
    """ISO 年-周 键。"""
    if now is None:
        now = dt.datetime.now()
    return f"{now.isocalendar().year:04d}-{now.isocalendar().week:02d}"


def last_week_key() -> str:
    prev = dt.datetime.now() - dt.timedelta(days=7)
    return current_week_key(prev)


async def build_board_data(refresh: bool = False) -> tuple[list[dict], str | None]:
    """组装榜单数据（分数榜）。并发拉取，单人失败不影响整榜。"""
    import asyncio

    store = get_board_store()
    roster = store.list_roster()
    if not roster:
        return [], "名单为空，请先使用「名单 添加」添加成员"
    wcl_client = get_wcl_client()
    sem = asyncio.Semaphore(5)

    async def one(r: dict) -> tuple[dict | None, str | None]:
        async with sem:
            try:
                prof = await fetch_combined_profile(r["char_name"], r["realm"], wcl_client)
            except Exception as e:  # noqa: BLE001
                return None, f"{r['nickname']}: {e}"
        prof["nickname"] = r["nickname"]
        prof["roster_id"] = r["id"]
        # 快照键固定用名单里的角色名/服务器：RIO 与 WCL 回落时返回的 realm 写法不同，
        # 用接口返回值做键会让周报把同一个人算成「新增」。
        prof["key_name"] = r["char_name"]
        prof["key_realm"] = r["realm"]
        return prof, None

    results = await asyncio.gather(*(one(r) for r in roster))
    rows = [p for p, _ in results if p]
    errors = [e for _, e in results if e]
    rows.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
    # 保存本周快照（全部成功角色）
    store.save_snapshot(current_week_key(), [
        {
            "char_name": r.get("key_name") or r.get("name", ""),
            "realm": r.get("key_realm") or r.get("realm", ""),
            "score": r.get("score", 0) or 0,
            "ilvl": r.get("ilvl", 0) or 0,
            "source": r.get("source", ""),
        }
        for r in rows if (r.get("key_name") or r.get("name"))
    ])
    return rows, "\n".join(errors) if errors else None


async def build_weekly_report() -> list[dict]:
    """周报：先拉实时数据（与原版一致），再与上周快照对比。"""
    rows, _err = await build_board_data()
    prev = get_board_store().get_snapshot(last_week_key())
    report = []
    for r in rows:
        key = (r.get("key_name") or r.get("name", ""), r.get("key_realm") or r.get("realm", ""))
        old = prev.get(key)
        score = r.get("score", 0) or 0
        delta = score - (old["score"] or 0) if old else None
        report.append(
            {
                "nickname": r.get("nickname", ""),
                "char_name": key[0],
                "realm": key[1],
                "class": r.get("class", ""),
                "score": score,
                "ilvl": r.get("ilvl", 0) or 0,
                "source": r.get("source", ""),
                "delta": delta,
                "has_prev": old is not None,
            }
        )
    report.sort(key=lambda r: (r["delta"] if r["delta"] is not None else -10**9), reverse=True)
    return report


async def fetch_char_card(nickname: str) -> dict:
    """查卡：按群友名查名单角色并组装资料。"""
    store = get_board_store()
    entry = store.get_roster(nickname)
    if not entry:
        raise RuntimeError(f"名单中没有 {nickname}")
    prof = await fetch_combined_profile(entry["char_name"], entry["realm"], get_wcl_client())
    prof["nickname"] = entry["nickname"]
    return prof