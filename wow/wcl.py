# -*- coding: utf-8 -*-
"""Warcraft Logs v2 API 客户端（OAuth2 + GraphQL）。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from .net import get_client

logger = logging.getLogger("astrbot_plugin_wow.wcl")

OAUTH_URL = "https://www.warcraftlogs.com/oauth/token"
GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"
REGION = "CN"

ERR_CREDENTIALS = "未配置 Warcraft Logs API 凭证"

PROFILE_QUERY = """query Character($name: String!, $realm: String!, $region: String!, $zone: Int!, $force: Boolean!) {
  characterData {
    character(name: $name, serverSlug: $realm, serverRegion: $region) {
      id
      name
      server { name slug }
      gameData(forceUpdate: $force)
      zoneRankings(zoneID: $zone)
    }
  }
}"""

ZONES_QUERY = """query ActiveMythicZones { worldData { zones { id name frozen expansion { id name } } } }"""

_SLUG_CLEANER = re.compile(r"[^a-z0-9]+")

_REALM_SLUGS = {
    "白银之手": "silver-hand", "Silver Hand": "silver-hand",
    "回音山": "echo-ridge", "Echo Ridge": "echo-ridge",
    "金色平原": "golden-plains", "Golden Plains": "golden-plains",
    "艾露恩": "elune", "Elune": "elune",
    "亚雷戈斯": "arygos", "Arygos": "arygos",
    "霜之哀伤": "frostmourne", "Frostmourne": "frostmourne",
    "影之哀伤": "shadowmourne", "Shadowmourne": "shadowmourne",
    "阿曼尼": "amani", "Amani": "amani",
    "森金": "senjin", "Sen'jin": "senjin", "Senjin": "senjin",
    "永恒之井": "well-of-eternity", "Well of Eternity": "well-of-eternity",
    "苏拉玛": "suramar", "Suramar": "suramar",
    "罗宁": "rhonin", "Rhonin": "rhonin",
}

_CLASS_CN_EN = {
    "战士": "Warrior", "圣骑士": "Paladin", "猎人": "Hunter", "潜行者": "Rogue",
    "牧师": "Priest", "死亡骑士": "Death Knight", "萨满祭司": "Shaman", "萨满": "Shaman",
    "法师": "Mage", "术士": "Warlock", "武僧": "Monk", "德鲁伊": "Druid",
    "恶魔猎手": "Demon Hunter", "唤魔师": "Evoker",
}


def realm_slug(realm: str) -> str | None:
    realm = realm.strip()
    if slug := _REALM_SLUGS.get(realm):
        return slug
    if not realm or any(ord(c) > 127 for c in realm):
        return None
    slug = _SLUG_CLEANER.sub("-", realm.lower()).strip("-")
    return slug or None


class Profile:
    def __init__(self, **kw):
        self.id = kw.get("id", 0)
        self.name = kw.get("name", "")
        self.realm = kw.get("realm", "")
        self.realm_slug = kw.get("realm_slug", "")
        self.class_name = kw.get("class_name", "")
        self.active_spec = kw.get("active_spec", "")
        self.average_ilvl = kw.get("average_ilvl", 0.0)
        self.equipped_ilvl = kw.get("equipped_ilvl", 0.0)
        self.last_login_at = kw.get("last_login_at", 0)
        self.zone_id = kw.get("zone_id", 0)
        self.zone_name = kw.get("zone_name", "")
        self.score = kw.get("score", 0.0)
        self.rank_world = kw.get("rank_world", 0)
        self.rank_region = kw.get("rank_region", 0)
        self.rank_realm = kw.get("rank_realm", 0)
        self.rank_percent = kw.get("rank_percent", 0.0)
        self.rank_total = kw.get("rank_total", 0)
        self.rank_spec = kw.get("rank_spec", "")
        self.dungeons = kw.get("dungeons", [])


class WCLClient:
    """WCL 客户端：凭证加载 + token 缓存 + 角色查询。"""

    def __init__(self, client_id: str = "", client_secret: str = "", cred_file: str | Path | None = None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._cred_file = Path(cred_file) if cred_file else None
        self._token: str | None = None
        self._token_expire: float = 0
        self._zone_id = 0
        self._zone_name = ""
        self._zone_at: float = 0
        self._profile_cache: dict[str, tuple[Profile, float]] = {}

    # ---- 凭证 ----
    def _load_credentials(self) -> tuple[str, str]:
        cid, secret = self._client_id.strip(), self._client_secret.strip()
        if not cid:
            cid = os.environ.get("WCL_CLIENT_ID", "").strip()
        if not secret:
            secret = os.environ.get("WCL_CLIENT_SECRET", "").strip()
        if cid and secret:
            return cid, secret
        candidates = []
        if self._cred_file:
            candidates.append(self._cred_file)
        candidates.append(Path("wcl_cred.json"))
        candidates.append(Path("data") / "wcl" / "config.json")
        for p in candidates:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                fc, fs = str(data.get("client_id", "")).strip(), str(data.get("client_secret", "")).strip()
                if fc and fs:
                    return fc, fs
            except (OSError, json.JSONDecodeError):
                continue
        return "", ""

    async def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire:
            return self._token
        cid, secret = self._load_credentials()
        if not cid or not secret:
            raise RuntimeError(ERR_CREDENTIALS)
        resp = await get_client().post(
            OAUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(cid, secret),
            timeout=30,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()
        token = body.get("access_token", "")
        if not token:
            raise RuntimeError("Warcraft Logs 授权未返回 access_token")
        ttl = int(body.get("expires_in", 3600))
        self._token = token
        self._token_expire = now + max(ttl - 60, 30)
        return token

    async def _graphql(self, query: str, variables: dict | None) -> dict:
        token = await self._access_token()
        resp = await get_client().post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        envelope = resp.json()
        if envelope.get("errors"):
            raise RuntimeError(f"Warcraft Logs 查询失败: {envelope['errors'][0].get('message', '未知错误')}")
        data = envelope.get("data")
        if not data:
            raise RuntimeError("Warcraft Logs 未返回数据")
        return data

    async def active_mythic_zone(self) -> tuple[int, str]:
        now = time.time()
        if self._zone_id and now - self._zone_at < 3600:
            return self._zone_id, self._zone_name
        data = await self._graphql(ZONES_QUERY, None)
        zones = []
        for z in data.get("worldData", {}).get("zones", []):
            if not z.get("frozen") and str(z.get("name", "")).lower().startswith("mythic+ season"):
                zones.append((int(z["id"]), z.get("name", "")))
        if not zones:
            raise RuntimeError("Warcraft Logs 未返回当前大秘境区域")
        zones.sort(key=lambda x: x[0])
        self._zone_id, self._zone_name = zones[-1]
        self._zone_at = now
        return self._zone_id, self._zone_name

    async def fetch_character(self, name: str, realm: str, force_update: bool = False) -> Profile:
        slug = realm_slug(realm)
        if not slug:
            raise RuntimeError(f"Warcraft Logs 无法识别服务器：{realm}")
        cache_key = f"{REGION}/{slug}/{name.strip().lower()}"
        if not force_update:
            cached = self._profile_cache.get(cache_key)
            if cached and time.time() - cached[1] < 1800:
                return cached[0]
        zone_id, zone_name = await self.active_mythic_zone()
        data = await self._graphql(
            PROFILE_QUERY,
            {
                "name": name.strip(),
                "realm": slug,
                "region": REGION,
                "zone": zone_id,
                "force": force_update,
            },
        )
        ch = data.get("characterData", {}).get("character")
        if not ch:
            raise RuntimeError(f"Warcraft Logs 未找到角色 {name}〈{realm}〉")
        p = Profile(
            id=ch.get("id", 0),
            name=ch.get("name", name.strip()),
            realm=(ch.get("server") or {}).get("name") or realm,
            realm_slug=(ch.get("server") or {}).get("slug") or slug,
            zone_id=zone_id,
            zone_name=zone_name,
        )
        self._parse_game_data(ch.get("gameData"), p)
        self._parse_zone_rankings(ch.get("zoneRankings"), p)
        self._profile_cache[cache_key] = (p, time.time())
        return p

    @staticmethod
    def _parse_game_data(raw, p: Profile) -> None:
        if not raw:
            return
        g = raw.get("global") or {}
        if g.get("name"):
            p.name = g["name"]
        realm = ((g.get("realm") or {}).get("name")) or ""
        if realm:
            p.realm = realm
        class_raw = (g.get("character_class") or {}).get("name", "")
        p.class_name = _CLASS_CN_EN.get(class_raw.strip(), class_raw)
        p.active_spec = ((g.get("active_spec") or {}).get("name")) or ""
        p.average_ilvl = float(g.get("average_item_level", 0) or 0)
        p.equipped_ilvl = float(g.get("equipped_item_level", 0) or 0)
        last_login = int(g.get("last_login_timestamp", 0) or 0)
        if last_login > 1_000_000_000_000:
            last_login //= 1000
        p.last_login_at = last_login

    @staticmethod
    def _parse_zone_rankings(raw, p: Profile) -> None:
        if not raw:
            return
        all_stars = raw.get("allStars") or []
        if all_stars:
            best = max(all_stars, key=lambda s: float(s.get("points", 0) or 0))
            p.score = float(best.get("points", 0) or 0)
            p.rank_world = int(best.get("rank", 0) or 0)
            p.rank_region = int(best.get("regionRank", 0) or 0)
            p.rank_realm = int(best.get("serverRank", 0) or 0)
            p.rank_percent = float(best.get("rankPercent", 0) or 0)
            p.rank_total = int(best.get("total", 0) or 0)
            p.rank_spec = best.get("spec", "")
        dungeons = []
        for r in raw.get("rankings") or []:
            dungeons.append(
                {
                    "name": (r.get("encounter") or {}).get("name", ""),
                    "score": float(r.get("bestAmount", 0) or 0),
                    "total_kills": int(r.get("totalKills", 0) or 0),
                    "spec": r.get("spec", ""),
                }
            )
        dungeons.sort(key=lambda d: d["score"], reverse=True)
        p.dungeons = dungeons


default_client: WCLClient | None = None


def get_wcl_client(client_id: str = "", client_secret: str = "") -> WCLClient:
    global default_client
    if default_client is None:
        default_client = WCLClient(client_id, client_secret)
    return default_client