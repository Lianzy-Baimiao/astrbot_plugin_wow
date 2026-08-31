# -*- coding: utf-8 -*-
"""持久化存储：sqlite（榜单/开箱）+ JSON 缓存。"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path

from .const import PLUGIN_NAME

logger = logging.getLogger("astrbot_plugin_wow")

_lock = threading.Lock()
_data_dir: Path | None = None


def set_data_dir(path: Path) -> None:
    """由 main.py 在插件初始化时注入数据目录（AstrBot data/plugin_data/...）。"""
    global _data_dir
    _data_dir = path
    path.mkdir(parents=True, exist_ok=True)


def data_dir() -> Path:
    if _data_dir is None:
        raise RuntimeError("数据目录未初始化")
    return _data_dir


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# JSON 缓存
# ---------------------------------------------------------------------------

def load_json(rel_path: str, default=None):
    p = data_dir() / rel_path
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return default
    except ValueError as e:  # JSONDecodeError / UnicodeDecodeError 都是 ValueError
        logger.warning("缓存文件损坏，已忽略：%s（%s）", p, e)
        return default


def save_json(rel_path: str, obj) -> None:
    p = data_dir() / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# sqlite
# ---------------------------------------------------------------------------

class BoardStore:
    """魔兽群榜单存储：名单 + 周报快照。"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS roster ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "nickname TEXT NOT NULL, char_name TEXT NOT NULL, realm TEXT NOT NULL,"
            "UNIQUE(nickname, char_name, realm))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshot ("
            "char_name TEXT NOT NULL, realm TEXT NOT NULL, week TEXT NOT NULL,"
            "score REAL DEFAULT 0, ilvl REAL DEFAULT 0, source TEXT DEFAULT '',"
            "PRIMARY KEY(char_name, realm, week))"
        )
        self._conn.commit()

    def list_roster(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, nickname, char_name, realm FROM roster ORDER BY id"
        )
        return [
            {"id": r[0], "nickname": r[1], "char_name": r[2], "realm": r[3]}
            for r in cur.fetchall()
        ]

    def add_roster(self, nickname: str, char_name: str, realm: str) -> tuple[int, bool]:
        with _lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO roster (nickname, char_name, realm) VALUES (?,?,?)",
                    (nickname, char_name, realm),
                )
                self._conn.commit()
                return cur.lastrowid, True
            except sqlite3.IntegrityError:
                return 0, False

    def delete_roster(self, row_id: int) -> bool:
        with _lock:
            cur = self._conn.execute("DELETE FROM roster WHERE id=?", (row_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def get_roster(self, keyword: str) -> dict | None:
        """按「群友名 或 角色名」子串匹配（与原版 wowboard 查卡一致）。"""
        like = f"%{keyword}%"
        cur = self._conn.execute(
            "SELECT id, nickname, char_name, realm FROM roster "
            "WHERE nickname=? OR char_name=? ORDER BY id LIMIT 1",
            (keyword, keyword),
        )
        row = cur.fetchone()
        if row is None:
            cur = self._conn.execute(
                "SELECT id, nickname, char_name, realm FROM roster "
                "WHERE nickname LIKE ? OR char_name LIKE ? ORDER BY id LIMIT 1",
                (like, like),
            )
            row = cur.fetchone()
        if row:
            return {"id": row[0], "nickname": row[1], "char_name": row[2], "realm": row[3]}
        return None

    def save_snapshot(self, week: str, rows: list[dict]) -> None:
        with _lock:
            for r in rows:
                self._conn.execute(
                    "INSERT OR REPLACE INTO snapshot (char_name, realm, week, score, ilvl, source)"
                    " VALUES (?,?,?,?,?,?)",
                    (r["char_name"], r["realm"], week, r.get("score", 0), r.get("ilvl", 0), r.get("source", "")),
                )
            self._conn.commit()

    def get_snapshot(self, week: str) -> dict[tuple[str, str], dict]:
        cur = self._conn.execute(
            "SELECT char_name, realm, score, ilvl, source FROM snapshot WHERE week=?",
            (week,),
        )
        return {
            (r[0], r[1]): {"score": r[2], "ilvl": r[3], "source": r[4]}
            for r in cur.fetchall()
        }

    def close(self) -> None:
        self._conn.close()


class GachaStore:
    """开箱积分存储。

    gid/uid 一律按 TEXT 存：QQ 官方平台的 openid 是字母数字串，塞不进 INTEGER。
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS gacha_score ("
            "gid TEXT NOT NULL, uid TEXT NOT NULL, score INTEGER DEFAULT 0,"
            "count INTEGER DEFAULT 0, nick TEXT DEFAULT '', PRIMARY KEY(gid, uid))"
        )
        # 旧库（v1.0.x）没有 nick 列，补一次
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(gacha_score)")}
        if "nick" not in cols:
            self._conn.execute("ALTER TABLE gacha_score ADD COLUMN nick TEXT DEFAULT ''")
        self._conn.commit()

    def add(self, gid: str, uid: str, score: int, nick: str = "") -> tuple[int, int]:
        gid, uid = str(gid), str(uid)
        with _lock:
            self._conn.execute(
                "INSERT INTO gacha_score (gid, uid, score, count, nick) VALUES (?,?,?,1,?)"
                " ON CONFLICT(gid, uid) DO UPDATE SET score=score+?, count=count+1,"
                " nick=CASE WHEN ?='' THEN nick ELSE ? END",
                (gid, uid, score, nick, score, nick, nick),
            )
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT score, count FROM gacha_score WHERE gid=? AND uid=?",
                (gid, uid),
            )
            row = cur.fetchone()
            return (row[0], row[1]) if row else (score, 1)

    def top(self, gid: str, limit: int = 10) -> list[dict]:
        cur = self._conn.execute(
            "SELECT uid, score, count, nick FROM gacha_score WHERE gid=? "
            "ORDER BY score DESC, count DESC LIMIT ?",
            (str(gid), limit),
        )
        return [
            {"uid": r[0], "score": r[1], "count": r[2], "nick": r[3] or str(r[0])}
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()


_board_store: BoardStore | None = None
_gacha_store: GachaStore | None = None


def get_board_store() -> BoardStore:
    global _board_store
    if _board_store is None:
        _board_store = BoardStore(data_dir() / "board.db")
    return _board_store


def get_gacha_store() -> GachaStore:
    global _gacha_store
    if _gacha_store is None:
        _gacha_store = GachaStore(data_dir() / "gacha.db")
    return _gacha_store


def close_stores() -> None:
    global _board_store, _gacha_store
    for s in (_board_store, _gacha_store):
        if s is not None:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
    _board_store = None
    _gacha_store = None