# -*- coding: utf-8 -*-
"""wago.tools DB2 CSV 数据：物品中文名 / 团本名 / 副本名。

查询顺序：内置离线字典（data/*_cn.json）→ 插件数据缓存 → 线上 wago.tools 补齐。
离线字典保证无网络时常用物品/副本/团本仍显示中文。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from pathlib import Path

from .net import fetch_text
from .store import load_json, save_json

logger = logging.getLogger("astrbot_plugin_wow.wago")

ITEM_CACHE_FILE = "itemnames.json"
_name_cache: dict[int, str] | None = None
_seed_raids: dict[str, str] | None = None
_seed_dungeons: dict[int, str] | None = None


def _data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def _load_seed_itemnames() -> dict[int, str]:
    """内置离线物品中文名（随插件分发，覆盖当前版本常用装备）。"""
    try:
        raw = json.loads((_data_dir() / "itemnames_cn.json").read_text(encoding="utf-8"))
        return {int(k): str(v) for k, v in raw.items()}
    except Exception as e:  # noqa: BLE001
        logger.warning("内置物品名表读取失败: %s", e)
        return {}


def _load_seed_raids() -> dict[str, str]:
    global _seed_raids
    if _seed_raids is None:
        try:
            raw = json.loads((_data_dir() / "raids_cn.json").read_text(encoding="utf-8"))
            _seed_raids = {str(k): str(v) for k, v in raw.items()}
        except Exception as e:  # noqa: BLE001
            logger.warning("内置团本名表读取失败: %s", e)
            _seed_raids = {}
    return _seed_raids


def _load_seed_dungeons() -> dict[int, str]:
    global _seed_dungeons
    if _seed_dungeons is None:
        try:
            raw = json.loads((_data_dir() / "dungeons_cn.json").read_text(encoding="utf-8"))
            _seed_dungeons = {}
            for k, v in raw.items():
                try:
                    _seed_dungeons[int(k)] = str(v)
                except (ValueError, TypeError):
                    continue
        except Exception as e:  # noqa: BLE001
            logger.warning("内置副本名表读取失败: %s", e)
            _seed_dungeons = {}
    return _seed_dungeons


async def fetch_csv(url: str) -> list[list[str]]:
    text = await fetch_text(url, timeout=30)
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader]


def _load_name_cache() -> dict[int, str]:
    global _name_cache
    if _name_cache is None:
        # 先内置表，再叠加插件持久化缓存（新查到的覆盖同名项）
        _name_cache = dict(_load_seed_itemnames())
        raw = load_json(ITEM_CACHE_FILE, {}) or {}
        for k, v in raw.items():
            try:
                _name_cache[int(k)] = str(v)
            except (ValueError, TypeError):
                continue
    return _name_cache


def _save_name_cache() -> None:
    try:
        save_json(ITEM_CACHE_FILE, {str(k): v for k, v in (_name_cache or {}).items()})
    except Exception as e:  # noqa: BLE001
        logger.warning("物品名缓存落盘失败: %s", e)


def item_name_cn(item_id: int, fallback: str = "") -> str:
    """只读缓存查询，未命中返回 fallback。"""
    if item_id == 0:
        return fallback
    return _load_name_cache().get(item_id) or fallback


async def _fetch_one_item_name(item_id: int) -> str:
    """查单个物品的中文名（wago.tools filter[ID] 为包含匹配，需按 ID 精确挑选行）。
    网络不稳时重试一次（wago.tools 在国内访问偶发超时）。"""
    url = f"https://wago.tools/db2/ItemSparse/csv?locale=zhCN&filter%5BID%5D={item_id}"
    for attempt in range(2):
        try:
            text = await fetch_text(url, timeout=15)
            rows = list(csv.reader(io.StringIO(text)))
            if len(rows) < 2:
                return ""
            header = rows[0]
            try:
                id_idx = header.index("ID")
                name_idx = header.index("Display_lang")
            except ValueError:
                return ""
            want = str(item_id)
            for row in rows[1:]:
                if len(row) > max(id_idx, name_idx) and row[id_idx] == want:
                    return row[name_idx].strip()
            return ""
        except Exception as e:  # noqa: BLE001
            if attempt == 0:
                logger.warning("物品 %d 中文名拉取失败（重试）: %s", item_id, e)
                continue
            logger.warning("物品 %d 中文名拉取失败: %s", item_id, e)
    return ""


async def resolve_item_names_cn(item_ids: list[int]) -> dict[int, str]:
    """并发补齐物品中文名（命中缓存不发请求），返回本次新增映射。"""
    cache = _load_name_cache()
    todo = []
    seen = set()
    for iid in item_ids:
        if iid and iid not in seen and iid not in cache:
            seen.add(iid)
            todo.append(iid)
    if not todo:
        return {}
    sem = asyncio.Semaphore(6)

    async def one(iid: int) -> tuple[int, str]:
        async with sem:
            return iid, await _fetch_one_item_name(iid)

    got = {}
    for iid, name in await asyncio.gather(*(one(i) for i in todo)):
        if name:
            got[iid] = name
    if got:
        cache.update(got)
        _save_name_cache()
    return got


async def item_names(item_ids: set[int]) -> dict[int, str]:
    """按 ID 批量查询物品中文名（含缓存）。"""
    await resolve_item_names_cn(sorted(item_ids))
    cache = _load_name_cache()
    return {iid: cache[iid] for iid in item_ids if iid in cache}


# ---------------------------------------------------------------------------
# 物品图标（IconFileDataID → 暴雪 CDN）
# ---------------------------------------------------------------------------

ICON_CACHE_FILE = "itemicons.json"
_icon_cache: dict[int, str] | None = None
ICON_CDN = "https://render.worldofwarcraft.com/icons/56/{filedataid}.jpg"


def _load_icon_cache() -> dict[int, str]:
    global _icon_cache
    if _icon_cache is None:
        raw = load_json(ICON_CACHE_FILE, {}) or {}
        _icon_cache = {}
        for k, v in raw.items():
            try:
                _icon_cache[int(k)] = str(v)
            except (ValueError, TypeError):
                continue
    return _icon_cache


def _save_icon_cache() -> None:
    try:
        save_json(ICON_CACHE_FILE, {str(k): v for k, v in (_icon_cache or {}).items()})
    except Exception as e:  # noqa: BLE001
        logger.warning("物品图标缓存落盘失败: %s", e)


async def _fetch_one_icon(item_id: int) -> str:
    """从 wago Item 表查单个物品的 IconFileDataID。"""
    url = f"https://wago.tools/db2/Item/csv?locale=enUS&filter%5BID%5D={item_id}"
    try:
        text = await fetch_text(url, timeout=12)
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 2:
            return ""
        header = rows[0]
        try:
            id_idx = header.index("ID")
            icon_idx = header.index("IconFileDataID")
        except ValueError:
            return ""
        want = str(item_id)
        for row in rows[1:]:
            if len(row) > max(id_idx, icon_idx) and row[id_idx] == want:
                return row[icon_idx].strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("物品 %d 图标拉取失败: %s", item_id, e)
    return ""


async def item_icon_urls(item_ids: list[int]) -> dict[int, str]:
    """并发补齐物品图标 CDN 地址（缓存落盘），返回 {item_id: url}。"""
    cache = _load_icon_cache()
    todo = []
    seen = set()
    for iid in item_ids:
        if iid and iid not in seen and iid not in cache:
            seen.add(iid)
            todo.append(iid)
    if todo:
        sem = asyncio.Semaphore(6)

        async def one(iid: int) -> tuple[int, str]:
            async with sem:
                return iid, await _fetch_one_icon(iid)

        got = {}
        for iid, icon in await asyncio.gather(*(one(i) for i in todo)):
            if icon:
                got[iid] = icon
        if got:
            cache.update(got)
            _save_icon_cache()
    return {
        iid: ICON_CDN.format(filedataid=cache[iid])
        for iid in item_ids
        if iid in cache and cache[iid]
    }


async def raid_names() -> dict[str, str]:
    """团本 slug → 中文名（内置离线表，随插件分发，无需联网）。"""
    return dict(_load_seed_raids())


async def mplus_dungeon_names() -> dict[int, str]:
    """大秘境副本 map_challenge_mode_id → 中文名（内置离线表，无需联网）。"""
    return dict(_load_seed_dungeons())