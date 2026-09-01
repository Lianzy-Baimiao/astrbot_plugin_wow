# -*- coding: utf-8 -*-
"""处罚名单查询：扫描目录下 xlsx 表格（角色名/服务器名两列），按角色/服务器匹配。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger("astrbot_plugin_wow.punish")

_lock = threading.Lock()
_cache: dict[str, tuple[int, int, list[dict]]] = {}

_ROLE_KEYS = ("角色名", "角色", "昵称", "名字", "游戏名", "玩家")
_REALM_KEYS = ("服务器名", "服务器", "区服", "服务区")


def _detect_header(row: list) -> tuple[int, int]:
    """判断一行是否为表头，返回 (角色列索引, 服务器列索引)；非表头返回 (-1, -1)。"""
    role_idx = realm_idx = -1
    for i, cell in enumerate(row):
        s = str(cell or "").strip()
        if role_idx < 0 and s in _ROLE_KEYS:
            role_idx = i
        elif realm_idx < 0 and s in _REALM_KEYS:
            realm_idx = i
    return role_idx, realm_idx


def _load(xlsx: Path) -> list[dict]:
    """读取一个 xlsx：返回 [{name, realm}]。按 mtime+size 缓存，文件变了自动重读。

    通用表头识别：任一整行命中「角色/服务器」关键词即视为表头（支持多表合并的
    工作簿，表头位置不限第一行），其余行按当前列索引取值。
    """
    stat = xlsx.stat()
    key = str(xlsx)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
            return hit[2]

    from openpyxl import load_workbook

    rows: list[dict] = []
    role_idx = realm_idx = -1
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                if not r or not any(v is not None for v in r):
                    continue
                vals = [str(v).strip() if v is not None else "" for v in r]
                ri, re_ = _detect_header(vals)
                if ri >= 0:
                    role_idx, realm_idx = ri, re_
                    continue
                if role_idx < 0:
                    continue
                name = vals[role_idx] if role_idx < len(vals) else ""
                realm = vals[realm_idx] if realm_idx >= 0 and realm_idx < len(vals) else ""
                if name:
                    rows.append({"name": name, "realm": realm})
    finally:
        wb.close()

    with _lock:
        _cache[key] = (stat.st_mtime_ns, stat.st_size, rows)
    return rows


def query(punish_dir: Path, name: str, realm: str | None = None) -> list[dict]:
    """全目录扫描，返回 [{file, name, realm}, ...]（按表名排序）。"""
    if not punish_dir.is_dir():
        raise RuntimeError(f"处罚名单目录不存在：{punish_dir}")
    out: list[dict] = []
    for xlsx in sorted(punish_dir.glob("*.xlsx")):
        try:
            for row in _load(xlsx):
                if row["name"] == name and (realm is None or row["realm"] == realm):
                    out.append({"file": xlsx.name, "name": row["name"], "realm": row["realm"]})
        except Exception as e:  # noqa: BLE001
            logger.warning("处罚名单读取失败 %s: %s", xlsx.name, e)
    return out