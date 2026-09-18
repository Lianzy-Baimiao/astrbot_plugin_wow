# -*- coding: utf-8 -*-
"""把本机 Auctionator 的拍卖价格库导出成插件能读的 prices.json。

**在自己的电脑上跑**（游戏在这里，AstrBot 在云服务器上），产物上传到
云端的 `data/plugin_data/astrbot_plugin_wow/prices.json` 即可。

    python tools/export_prices.py                      # 自动找 WTF、自动选服务器
    python tools/export_prices.py --realm 白银之手      # 指定服务器
    python tools/export_prices.py -o D:\\prices.json    # 指定输出路径

原理
----
Auctionator 在 PLAYER_LOGOUT 时把每个服务器的价格库用 C_EncodingUtil.SerializeCBOR
序列化成一个字符串写进 SavedVariables（`__dbversion = 8`）。这里做三件事：

1. 从 Auctionator.lua 里抠出 AUCTIONATOR_PRICE_DATABASE 各服务器的字符串字面量，
   按 Lua 规则反转义成原始字节（WoW 写 `\\ddd` 十进制转义）。
2. 用内置的极简 CBOR 解码器解出 {dbKey: {m=最近最低价, a={天号:数量}, h=..., l=...}}。
   不依赖 cbor2，标准库即可。
3. 物品名来自 wago.tools 的 zhCN ItemSparse 全量 CSV（约 50MB，缓存在临时目录），
   **名字在这一步就烤进 JSON**，云端不需要再查名字。

注意：只有「当前在玩的那个服务器」的数据是可靠的。其它服务器可能是旧 schema 被
惰性 CBOR 化的残留——一条最新价都没有，脚本会自动跳过这种。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import struct
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# Auctionator 的天号原点：time({year=2020, month=1, day=1, hour=0})，客户端本地时区
SCAN_DAY_0 = int(time.mktime((2020, 1, 1, 0, 0, 0, 0, 0, -1)))

ITEMSPARSE_URL = "https://wago.tools/db2/ItemSparse/csv?locale=zhCN"
CSV_CACHE = Path(tempfile.gettempdir()) / "wow_itemsparse_zhCN.csv"
CSV_MAX_AGE = 7 * 86400

DEFAULT_WTF = Path(r"E:\World of Warcraft\_retail_\WTF\Account")


# ---------------------------------------------------------------------------
# Lua 字符串字面量 -> 原始字节
# ---------------------------------------------------------------------------

_ESC = re.compile(r"\\(\d{1,3}|.)", re.S)
_ESC_MAP = {
    "n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"',
    "a": "\a", "b": "\b", "f": "\f", "v": "\v",
}


def lua_unquote(lit: str) -> bytes:
    out = bytearray()
    i = 0
    while i < len(lit):
        if lit[i] != "\\":
            out.extend(lit[i].encode("utf-8", "surrogateescape"))
            i += 1
            continue
        m = _ESC.match(lit, i)
        g = m.group(1)
        if g.isdigit():
            out.append(int(g) & 0xFF)
        else:
            out.extend(_ESC_MAP.get(g, g).encode("utf-8", "surrogateescape"))
        i = m.end()
    return bytes(out)


# ---------------------------------------------------------------------------
# 极简 CBOR 解码器（只覆盖 Auctionator 会写出的类型）
# ---------------------------------------------------------------------------

class CborDecoder:
    def __init__(self, buf: bytes):
        self.b = buf
        self.i = 0

    def _u8(self) -> int:
        v = self.b[self.i]
        self.i += 1
        return v

    def _take(self, n: int) -> bytes:
        v = self.b[self.i : self.i + n]
        self.i += n
        return v

    def _len(self, ai: int):
        if ai < 24:
            return ai
        if ai == 24:
            return self._u8()
        if ai == 25:
            return int.from_bytes(self._take(2), "big")
        if ai == 26:
            return int.from_bytes(self._take(4), "big")
        if ai == 27:
            return int.from_bytes(self._take(8), "big")
        if ai == 31:
            return None  # 不定长
        raise ValueError(f"非法附加信息 {ai}")

    def item(self):
        ib = self._u8()
        mt, ai = ib >> 5, ib & 0x1F
        if mt == 0:
            return self._len(ai)
        if mt == 1:
            return -1 - self._len(ai)
        if mt in (2, 3):
            n = self._len(ai)
            if n is None:  # 不定长分片串
                parts = []
                while self.b[self.i] != 0xFF:
                    parts.append(self.item())
                self.i += 1
                if mt == 2:
                    return b"".join(parts)
                return "".join(parts)
            raw = self._take(n)
            return raw if mt == 2 else raw.decode("utf-8", "replace")
        if mt == 4:
            n = self._len(ai)
            if n is None:
                out = []
                while self.b[self.i] != 0xFF:
                    out.append(self.item())
                self.i += 1
                return out
            return [self.item() for _ in range(n)]
        if mt == 5:
            n = self._len(ai)
            out = {}
            if n is None:
                while self.b[self.i] != 0xFF:
                    k = self.item()
                    out[_as_key(k)] = self.item()
                self.i += 1
                return out
            for _ in range(n):
                k = self.item()
                out[_as_key(k)] = self.item()
            return out
        if mt == 6:
            self._len(ai)  # tag 透传
            return self.item()
        if mt == 7:
            if ai == 20:
                return False
            if ai == 21:
                return True
            if ai in (22, 23):
                return None
            if ai == 25:
                return struct.unpack(">e", self._take(2))[0]
            if ai == 26:
                return struct.unpack(">f", self._take(4))[0]
            if ai == 27:
                return struct.unpack(">d", self._take(8))[0]
        raise ValueError(f"非法主类型 {mt}/{ai}")


def _as_key(k) -> str:
    """CBOR 的键可能是字节串也可能是文本串，一律归一成 str。"""
    if isinstance(k, bytes):
        return k.decode("utf-8", "replace")
    return str(k)


# ---------------------------------------------------------------------------
# SavedVariables 读取
# ---------------------------------------------------------------------------

_REALM_RE = re.compile(r'\["([^"]+)"\]\s*=\s*"((?:[^"\\]|\\.)*)"', re.S)


def find_savedvars(wtf_account: Path) -> Path:
    """在 WTF/Account/*/SavedVariables/ 下挑最新的 Auctionator.lua。"""
    cands = sorted(
        wtf_account.glob("*/SavedVariables/Auctionator.lua"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not cands:
        raise SystemExit(f"没在 {wtf_account} 下找到 Auctionator.lua，用 --sv 指定路径")
    return cands[0]


def read_realms(sv: Path) -> dict[str, bytes]:
    raw = sv.read_text(encoding="utf-8", errors="surrogateescape")
    try:
        start = raw.index("AUCTIONATOR_PRICE_DATABASE = {")
    except ValueError:
        raise SystemExit("SavedVariables 里没有 AUCTIONATOR_PRICE_DATABASE，Auctionator 还没扫过拍卖行？")
    # 块的结尾 = 下一个顶层变量赋值，或文件末尾
    nxt = re.compile(r"^\w+ = ", re.M).search(raw, start + 30)
    block = raw[start : nxt.start()] if nxt else raw[start:]

    realms = {}
    for m in _REALM_RE.finditer(block):
        name = m.group(1)
        if name == "__dbversion":
            continue
        realms[name] = lua_unquote(m.group(2))
    if not realms:
        raise SystemExit(
            "价格库里没有序列化的服务器数据。请把游戏完全退出（登出会触发写盘）后再跑一次。"
        )
    return realms


def decode_realm(blob: bytes) -> dict:
    obj = CborDecoder(blob).item()
    if not isinstance(obj, dict):
        raise ValueError(f"顶层不是 map，而是 {type(obj).__name__}")
    return obj


# ---------------------------------------------------------------------------
# 物品名（wago.tools zhCN ItemSparse）
# ---------------------------------------------------------------------------

def load_item_names(refresh: bool = False) -> dict[int, tuple[str, int]]:
    """下载/复用 zhCN 全量物品表，返回 {itemID: (中文名, 品质)}。"""
    stale = (
        refresh
        or not CSV_CACHE.exists()
        or time.time() - CSV_CACHE.stat().st_mtime > CSV_MAX_AGE
    )
    if stale:
        print(f"下载 zhCN 物品表（约 50MB）…", flush=True)
        req = urllib.request.Request(
            ITEMSPARSE_URL, headers={"User-Agent": "astrbot_plugin_wow/export_prices"}
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
        tmp = CSV_CACHE.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, CSV_CACHE)
        print(f"  已缓存到 {CSV_CACHE}（{len(data)/1048576:.1f}MB）")
    else:
        age = (time.time() - CSV_CACHE.stat().st_mtime) / 3600
        print(f"复用物品表缓存 {CSV_CACHE}（{age:.1f} 小时前，--refresh-names 可强制更新）")

    text = CSV_CACHE.read_text(encoding="utf-8", errors="replace")
    rows = csv.reader(io.StringIO(text))
    header = next(rows)
    i_id = header.index("ID")
    i_name = header.index("Display_lang")
    try:
        i_q = header.index("OverallQualityID")
    except ValueError:
        i_q = -1
    need = max(i_id, i_name, i_q)

    names: dict[int, tuple[str, int]] = {}
    for row in rows:
        if len(row) <= need:
            continue
        name = row[i_name].strip()
        if not name:
            continue
        try:
            iid = int(row[i_id])
        except ValueError:
            continue
        quality = 1
        if i_q >= 0:
            try:
                quality = int(row[i_q])
            except ValueError:
                pass
        names[iid] = (name, quality)
    print(f"物品名表 {len(names)} 条")
    return names


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------

def latest_day(entry: dict) -> int:
    """条目里最近一次被扫到的天号。"""
    best = 0
    for field in ("a", "h", "l"):
        sub = entry.get(field)
        if isinstance(sub, dict):
            for k in sub:
                try:
                    best = max(best, int(k))
                except (TypeError, ValueError):
                    continue
    return best


def quantity_at(entry: dict, day: int) -> int:
    a = entry.get("a")
    if not isinstance(a, dict):
        return 0
    v = a.get(str(day))
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def build_items(db: dict, names: dict[int, tuple[str, int]]) -> tuple[list[dict], dict]:
    """把解码后的价格库转成紧凑条目表，顺带统计跳过的原因。"""
    items = []
    stats = {"pet": 0, "no_price": 0, "no_name": 0}
    for key, entry in db.items():
        if key == "version" or not isinstance(entry, dict):
            continue
        price = entry.get("m")
        if not price:
            stats["no_price"] += 1
            continue

        ilvl = 0
        if key.startswith("p:"):
            # 宠物按 speciesID 存，名字要另一张表（BattlePetSpecies），暂不导出
            stats["pet"] += 1
            continue
        if key.startswith("g:"):
            # 装备按 g:<itemID>:<装等> 分键
            parts = key.split(":")
            if len(parts) < 3:
                continue
            raw_id, raw_ilvl = parts[1], parts[2]
            try:
                iid, ilvl = int(raw_id), int(raw_ilvl)
            except ValueError:
                continue
        else:
            try:
                iid = int(key)
            except ValueError:
                continue

        meta = names.get(iid)
        if meta is None:
            stats["no_name"] += 1
            continue
        name, quality = meta

        day = latest_day(entry)
        row = {"i": iid, "n": name, "p": int(price), "q": quantity_at(entry, day), "d": day}
        if ilvl:
            row["il"] = ilvl
        if quality:
            row["Q"] = quality
        items.append(row)

    items.sort(key=lambda r: r["n"])
    return items, stats


def pick_realm(realms: dict[str, bytes], want: str | None) -> tuple[str, dict]:
    """选出真正有价格数据的服务器。"""
    decoded: dict[str, dict] = {}
    scored: list[tuple[int, str]] = []
    for realm, blob in realms.items():
        if len(blob) < 64:
            continue
        try:
            db = decode_realm(blob)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {realm} 解码失败，跳过（{type(e).__name__}: {e}）")
            continue
        decoded[realm] = db
        n = sum(
            1 for k, v in db.items()
            if k != "version" and isinstance(v, dict) and v.get("m")
        )
        scored.append((n, realm))
        print(f"  {realm}: {len(db)} 个键，其中 {n} 个有最新价")

    if want:
        if want not in decoded:
            raise SystemExit(f"价格库里没有服务器「{want}」，可选：{', '.join(decoded) or '（无）'}")
        return want, decoded[want]

    scored.sort(reverse=True)
    if not scored or scored[0][0] == 0:
        raise SystemExit(
            "所有服务器都没有最新价数据。在游戏里打开拍卖行让 Auctionator 扫一次，"
            "然后登出（登出才写盘）再跑本脚本。"
        )
    return scored[0][1], decoded[scored[0][1]]


def main() -> None:
    ap = argparse.ArgumentParser(description="导出 Auctionator 价格库为 prices.json")
    ap.add_argument("--sv", type=Path, help="Auctionator.lua 路径（默认自动在 WTF 下找最新的）")
    ap.add_argument("--wtf", type=Path, default=DEFAULT_WTF, help="WTF/Account 目录")
    ap.add_argument("--realm", help="指定服务器名（默认选有最新价条目最多的那个）")
    ap.add_argument("-o", "--out", type=Path, default=Path("prices.json"), help="输出路径")
    ap.add_argument("--refresh-names", action="store_true", help="强制重新下载物品名表")
    args = ap.parse_args()

    sv = args.sv or find_savedvars(args.wtf)
    mtime = sv.stat().st_mtime
    print(f"读取 {sv}")
    print(f"  写盘时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))}")

    realms = read_realms(sv)
    realm, db = pick_realm(realms, args.realm)
    print(f"选用服务器：{realm}")

    names = load_item_names(args.refresh_names)
    items, stats = build_items(db, names)
    if not items:
        raise SystemExit("没有可导出的条目")

    newest = max(r["d"] for r in items)
    out = {
        "realm": realm,
        "exported_at": int(time.time()),
        "scanned_at": int(mtime),
        "day0": SCAN_DAY_0,
        "newest_day": newest,
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.out)

    newest_date = time.strftime("%Y-%m-%d", time.localtime(SCAN_DAY_0 + newest * 86400))
    size_mb = args.out.stat().st_size / 1048576
    print(f"\n导出 {len(items)} 条 -> {args.out}（{size_mb:.2f}MB）")
    print(f"  最近扫描日 {newest_date}")
    print(f"  跳过：宠物 {stats['pet']}、无价 {stats['no_price']}、查不到名字 {stats['no_name']}")
    print("\n把这个文件放到云服务器的 data/plugin_data/astrbot_plugin_wow/prices.json 即可。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
