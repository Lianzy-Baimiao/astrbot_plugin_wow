# -*- coding: utf-8 -*-
"""Web 面板用的纯逻辑：群 × 功能 矩阵 ↔ 配置列表，以及定时任务下一次触发时间。

这里刻意不 import astrbot、也不 import wow.services（那些会拉 httpx / astrbot logger），
所以可以脱离运行环境直接单测。

配置里 8 份「群名单」原本只能在插件配置页里手填群号/umo，面板把它们合成一张
「群 × 功能」的勾选矩阵；本模块只负责两个方向的转换和校验，读写配置的活在 page.py。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Mapping

# (配置键, 显示名, 说明) —— 顺序就是面板列的顺序
GROUP_LISTS: tuple[tuple[str, str, str], ...] = (
    ("news_groups", "魔兽新闻", "每 5 分钟检查一次，有更新就推"),
    ("reset_groups", "重置提醒", "周四重置时刻提醒"),
    ("weekly_report_groups", "周报", "每周固定日 20:00 推榜单周报"),
    ("wowboard_whitelist", "wowboard 指令", "名单/榜单/周报/查卡 只对这些群开放"),
    ("punish_notify_groups", "处罚名单", "收录到新处罚名单后通报"),
    ("pet_push_groups", "宠物世界任务", "每日 12:00 起轮询，拿到批次就推"),
    ("festival_push_groups", "节日通告", "每天按设定时间播报节日/活动"),
    ("markdown_groups", "Markdown 名单", "配合「Markdown 生效范围」使用"),
)

GROUP_LIST_KEYS: tuple[str, ...] = tuple(key for key, _, _ in GROUP_LISTS)
GROUP_LIST_LABELS: dict[str, str] = {key: label for key, label, _ in GROUP_LISTS}
GROUP_LIST_HINTS: dict[str, str] = {key: hint for key, _, hint in GROUP_LISTS}

# 标量设置（面板表单）及其默认值
DEFAULT_RESET_TIME = "06:50"
DEFAULT_FESTIVAL_TIME = "07:05"
DEFAULT_WEEKLY_DAY = 3
DEFAULT_NEWS_INTERVAL = 300
DEFAULT_PUNISH_INTERVAL = 3600

MARKDOWN_MODES: tuple[tuple[str, str], ...] = (
    ("all", "所有会话"),
    ("whitelist", "仅名单内的群"),
    ("blacklist", "名单内的群除外"),
)

WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 单个名单最多放多少个群（防止面板批量勾选把配置撑爆）
MAX_UMOS_PER_LIST = 300
# 群号 / umo 的长度上限
_MAX_UMO_LEN = 200

# umo 三段各自允许的字符。会话号**不能按「纯数字」过滤**：QQ 官方机器人（qq_official）
# 的群 id 是 32 位十六进制 openid（21E86DB833C12870E3287DF3C5704B5F），Telegram 超群
# id 是负数——用 isdigit 当门槛会把这些群整批判非法：面板里勾选显示不出来、统计少算，
# 点「保存群名单」还会把它们静默删掉。这里按「标识符」校验：比 isdigit 宽，比不校验严。
_PLATFORM_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_MSG_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,31}$")
_SESSION_RE = re.compile(r"^-?[A-Za-z0-9_]{1,64}$")

# 仅用于「裸群号 → 完整 umo」补全时的消息类型
GROUP_MSG_TYPE = "GroupMessage"

# 裸群号在面板上的展示名
BARE_LABEL = "裸群号"

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{1,2})$")


# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------


def parse_hhmm(text: Any) -> tuple[int, int] | None:
    """解析 "HH:MM"，不合法返回 None。

    比 ``wow.services.reset.parse_reset_time`` 严格：那个是「坏值静默回落 06:50」，
    面板保存时必须能报错，不能让用户以为改生效了。
    """
    m = _HHMM_RE.match(str(text or "").strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def format_hhmm(hour: int, minute: int) -> str:
    return f"{int(hour):02d}:{int(minute):02d}"


def next_daily(now: dt.datetime, hour: int, minute: int) -> dt.datetime:
    """下一次「每天 hour:minute」。今天已过就顺延到明天。"""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target


def next_weekly(now: dt.datetime, weekday: int, hour: int, minute: int) -> dt.datetime:
    """下一次「每周 weekday（0=周一）的 hour:minute」。"""
    days = (int(weekday) - now.weekday()) % 7
    target = (now + dt.timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if target <= now:
        target += dt.timedelta(days=7)
    return target


def humanize_delta(delta: dt.timedelta) -> str:
    """把时间差说成人话（面板上的「还有多久」）。"""
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "即将"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} 天后"
    if hours:
        return f"{hours} 小时 {minutes} 分钟后" if minutes else f"{hours} 小时后"
    if minutes:
        return f"{minutes} 分钟后"
    return f"{seconds} 秒后"


# ---------------------------------------------------------------------------
# 群名单矩阵
# ---------------------------------------------------------------------------


def normalize_umo(entry: Any) -> str:
    """清洗一项群目标：保留完整 umo 或裸群号，其它一律丢弃（返回 ""）。

    完整 umo 要求 ``平台:消息类型:会话号`` 三段都非空、字符集正常；裸值必须是纯群号
    （手填的数字群号）。会话号放得比较宽：纯数字（QQ 群号）、32 位 openid（QQ 官方
    机器人）、带负号的 snowflake（Telegram 超群）都算合法。
    """
    text = str(entry or "").strip()
    if not text or len(text) > _MAX_UMO_LEN:
        return ""
    if ":" in text:
        parts = [p.strip() for p in text.split(":")]
        if len(parts) < 3 or not all(parts[:3]):
            return ""
        platform, kind, session = parts[0], parts[1], ":".join(parts[2:])
        if not (
            _PLATFORM_RE.match(platform)
            and _MSG_TYPE_RE.match(kind)
            and _SESSION_RE.match(session)
        ):
            return ""
        return text
    return text if text.isdigit() else ""


def clean_umo_list(entries: Iterable[Any]) -> list[str]:
    """去重 + 清洗 + 限长，保持输入顺序。"""
    out: list[str] = []
    for entry in list(entries or []):
        umo = normalize_umo(entry)
        if umo and umo not in out:
            out.append(umo)
        if len(out) >= MAX_UMOS_PER_LIST:
            break
    return out


def matrix_from_lists(lists: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``{配置键: [群目标]}`` → 面板行 ``[{umo, flags: {键: bool}}]``。

    行序：按 GROUP_LISTS 的列顺序扫一遍，同一个群出现在多个名单里只占一行。
    """
    rows: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for key in GROUP_LIST_KEYS:
        for entry in list((lists or {}).get(key) or []):
            umo = normalize_umo(entry)
            if not umo:
                continue
            row = index.get(umo)
            if row is None:
                row = {"umo": umo, "flags": {k: False for k in GROUP_LIST_KEYS}}
                index[umo] = row
                rows.append(row)
            row["flags"][key] = True
    return rows


def lists_from_matrix(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """面板行 → ``{配置键: [umo]}``：未知列忽略、重复去掉、每列限长。"""
    out: dict[str, list[str]] = {key: [] for key in GROUP_LIST_KEYS}
    for row in list(rows or []):
        if isinstance(row, Mapping):
            umo = normalize_umo(row.get("umo"))
            flags = row.get("flags")
        else:
            umo = ""
            flags = None
        if not umo or not isinstance(flags, Mapping):
            continue
        for key in GROUP_LIST_KEYS:
            if flags.get(key) and umo not in out[key]:
                out[key].append(umo)
    for key in GROUP_LIST_KEYS:
        out[key] = out[key][:MAX_UMOS_PER_LIST]
    return out


def diff_lists(
    old: Mapping[str, Any], new: Mapping[str, Any]
) -> dict[str, dict[str, list[str]]]:
    """两份名单的差异，面板保存后用来回显「新增/移除了哪些群」。"""
    result: dict[str, dict[str, list[str]]] = {}
    for key in GROUP_LIST_KEYS:
        before = clean_umo_list((old or {}).get(key) or [])
        after = clean_umo_list((new or {}).get(key) or [])
        added = [u for u in after if u not in before]
        removed = [u for u in before if u not in after]
        if added or removed:
            result[key] = {"added": added, "removed": removed}
    return result


def matrix_summary(lists: Mapping[str, Any]) -> dict[str, Any]:
    """每列几个群 + 一共几个不同的群。"""
    per_key = {
        key: len(clean_umo_list((lists or {}).get(key) or [])) for key in GROUP_LIST_KEYS
    }
    umos = {
        u for key in GROUP_LIST_KEYS for u in clean_umo_list((lists or {}).get(key) or [])
    }
    return {"per_key": per_key, "groups": len(umos), "links": sum(per_key.values())}


# ---------------------------------------------------------------------------
# 平台写法：实例 id vs 适配器类型名
# ---------------------------------------------------------------------------
#
# AstrBot 的 ``context.send_message()`` 按平台**实例 id** 精确匹配（napcat /
# default_102737249），而 ``aiocqhttp`` / ``qq_official`` 是适配器**类型名**——
# 写成类型名的订阅走完实例循环直接返回 False，不抛异常，静默发不出去。
# 这一节负责把两种写法认出来、把能救的救回来，并区分「官方 / napcat」这类同号异平台。


def split_umo(umo: Any) -> tuple[str, str, str]:
    """拆 umo → (平台段, 消息类型, 会话号)；裸群号返回 ("", "", 群号)。"""
    text = str(umo or "").strip()
    if not text:
        return "", "", ""
    if ":" not in text:
        return "", "", text
    parts = [p.strip() for p in text.split(":")]
    if len(parts) < 3:
        return parts[0], parts[1] if len(parts) > 1 else "", ""
    return parts[0], parts[1], ":".join(parts[2:])


def platform_of(umo: Any) -> str:
    """umo 第一段（平台标识）；裸群号返回空串。"""
    return split_umo(umo)[0]


def session_of(umo: Any) -> str:
    """umo 第三段（群号 / openid）；裸群号返回它自己。"""
    return split_umo(umo)[2]


def is_bare(umo: Any) -> bool:
    """是不是「裸群号」写法（没有平台段）。"""
    return bool(str(umo or "").strip()) and ":" not in str(umo or "").strip()


def normalize_instances(instances: Iterable[Any]) -> list[tuple[str, str]]:
    """清洗平台实例列表 → [(实例 id, 适配器类型名)]，去空、按 id 去重、保序。

    接受 ``(id, type)`` 二元组，也接受 ``{"id":..., "type":...}`` 字典。
    """
    out: list[tuple[str, str]] = []
    for item in list(instances or []):
        pid = ptype = ""
        if isinstance(item, Mapping):
            pid = str(item.get("id") or "").strip()
            ptype = str(item.get("type") or item.get("name") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            pid = str(item[0] or "").strip()
            ptype = str(item[1] or "").strip()
        if not pid or any(pid == seen for seen, _ in out):
            continue
        out.append((pid, ptype))
    return out


def platform_alias_map(instances: Iterable[Any]) -> dict[str, str]:
    """适配器类型名 → 实例 id（``aiocqhttp`` → ``napcat``）。

    同一个类型有多个实例时取第一个：配置里写了类型名本来就指定不到具体实例，
    AstrBot 也只按实例 id 路由，只能挑一个最可能的。id 与类型名相同的实例跳过。
    """
    alias: dict[str, str] = {}
    for pid, ptype in normalize_instances(instances):
        if ptype and ptype != pid and ptype not in alias:
            alias[ptype] = pid
    return alias


def platform_type_map(instances: Iterable[Any]) -> dict[str, str]:
    """实例 id → 适配器类型名（面板显示「napcat（aiocqhttp）」）。"""
    return {pid: ptype for pid, ptype in normalize_instances(instances)}


def resolve_platform(platform: Any, instances: Iterable[Any] = ()) -> tuple[str, str]:
    """平台段 → (实例 id, 判定)。

    判定：``id``=本来就是实例 id；``type``=写的是适配器类型名（可改写成实例 id）；
    ``unknown``=既不是已加载实例 id 也不是类型名（发不出去）；``bare``=裸群号。
    """
    plat = str(platform or "").strip()
    if not plat:
        return "", "bare"
    insts = normalize_instances(instances)
    if any(plat == pid for pid, _ in insts):
        return plat, "id"
    alias = platform_alias_map(insts)
    if plat in alias:
        return alias[plat], "type"
    return "", "unknown"


def rewrite_umo(
    umo: Any, instances: Iterable[Any] = (), default_platform: str = ""
) -> tuple[str, str]:
    """把一条群目标改成「真发得出去」的写法，返回 (umo, 判定)。

    判定就是 ``resolve_platform`` 那几个，外加 ``plain``：

    - ``id``      平台段就是已加载实例 id，原样可发
    - ``type``    平台段是适配器类型名，已换成该类型的实例 id
    - ``bare``    裸群号，已补上默认平台实例 id
    - ``unknown`` 平台段认不出来，原样返回（发不出去，调用方该提醒）
    - ``plain``   裸群号但拿不到默认平台，原样返回（同样发不出去）
    """
    text = str(umo or "").strip()
    if not text:
        return "", ""
    if is_bare(text):
        plat = str(default_platform or "").strip()
        if not plat:
            return text, "plain"
        return f"{plat}:{GROUP_MSG_TYPE}:{text}", "bare"
    platform, kind, session = split_umo(text)
    if not (platform and kind and session):
        return text, "unknown"
    target, how = resolve_platform(platform, instances)
    if how == "id":
        return text, "id"
    if how == "type":
        return f"{target}:{kind}:{session}", "type"
    return text, "unknown"


def rewrite_umos(
    umos: Iterable[Any], instances: Iterable[Any] = (), default_platform: str = ""
) -> tuple[list[str], list[dict[str, Any]]]:
    """批量改写 + 去重（保序），返回 (新列表, 记录)。

    记录里 ``action``：``type``/``bare``=改了写法，``unknown``/``plain``=没救回来，
    ``merge``=与前面某条写法撞了被吸收。
    """
    out: list[str] = []
    report: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(umos or []):
        umo = normalize_umo(raw)
        if not umo:
            continue
        fixed, state = rewrite_umo(umo, instances, default_platform)
        if not fixed:
            continue
        if state in ("type", "bare", "unknown", "plain"):
            report.append(
                {"from": umo, "to": fixed, "action": state, "platform": platform_of(umo)}
            )
        if fixed in seen:
            report.append(
                {"from": umo, "to": fixed, "action": "merge", "platform": platform_of(umo)}
            )
            continue
        seen.add(fixed)
        out.append(fixed)
    return out, report


def unreachable_umos(
    umos: Iterable[Any], instances: Iterable[Any] = ()
) -> list[dict[str, str]]:
    """列出「平台段认不出来」的写法（面板标红 + 诊断区显示）。"""
    out: list[dict[str, str]] = []
    for raw in list(umos or []):
        umo = normalize_umo(raw)
        if not umo or is_bare(umo):
            continue
        _, state = rewrite_umo(umo, instances)
        if state == "unknown":
            out.append({"umo": umo, "platform": platform_of(umo)})
    return out


def all_umos(lists: Mapping[str, Any]) -> list[str]:
    """把 8 份名单里的目标合成一个去重列表（保序）。"""
    out: list[str] = []
    for key in GROUP_LIST_KEYS:
        for raw in list((lists or {}).get(key) or []):
            umo = normalize_umo(raw)
            if umo and umo not in out:
                out.append(umo)
    return out


def group_targets(umos: Iterable[Any]) -> list[dict[str, Any]]:
    """按会话号归并目标（保序）：``[{group_id, umos: [...]}]``。

    用来找「同一个群写了两遍」。只按**会话号**归并、不跨平台合并——官方机器人
    （32 位 openid）和 OneBot（数字群号）本来就是两个不同的会话。
    """
    order: list[str] = []
    by_gid: dict[str, list[str]] = {}
    for raw in list(umos or []):
        umo = normalize_umo(raw)
        if not umo:
            continue
        gid = session_of(umo)
        if not gid:
            continue
        if gid not in by_gid:
            by_gid[gid] = []
            order.append(gid)
        if umo not in by_gid[gid]:
            by_gid[gid].append(umo)
    return [{"group_id": gid, "umos": by_gid[gid]} for gid in order]


def duplicate_targets(lists_or_umos: Any) -> list[dict[str, Any]]:
    """配置里「同一个群号有多种写法」的项（面板诊断用）。"""
    if isinstance(lists_or_umos, Mapping):
        umos = all_umos(lists_or_umos)
    else:
        umos = list(lists_or_umos or [])
    return [item for item in group_targets(umos) if len(item["umos"]) > 1]


def platform_stats(
    lists: Mapping[str, Any], instances: Iterable[Any] = ()
) -> list[dict[str, Any]]:
    """配置里每个平台段有多少个群（面板「官方 3 个 ｜ napcat 1 个」那行）。"""
    counts: dict[str, int] = {}
    states: dict[str, str] = {}
    for umo in all_umos(lists):
        platform = platform_of(umo)
        label = platform or BARE_LABEL
        counts[label] = counts.get(label, 0) + 1
        if platform:
            _, states[label] = resolve_platform(platform, instances)
        else:
            states.setdefault(label, "bare")
    return [
        {"platform": label, "count": counts[label], "state": states.get(label, "unknown")}
        for label in counts
    ]


def normalize_lists(
    lists: Mapping[str, Any], instances: Iterable[Any] = (), default_platform: str = ""
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """把 8 份名单整体整理一遍：类型名换实例 id、裸号补平台、合并重复。

    返回 ``(新名单, 报告)``。报告每项带 ``key``/``label``（哪一列）和 ``action``：
    ``type``/``bare``（改写）、``merge``（并进同写法的另一条）、``unknown``/``plain``
    （没救回来）。只改写法，不动「哪个群在哪些列里」。
    """
    out: dict[str, list[str]] = {key: [] for key in GROUP_LIST_KEYS}
    report: list[dict[str, Any]] = []
    for key in GROUP_LIST_KEYS:
        fixed, records = rewrite_umos(
            list((lists or {}).get(key) or []), instances, default_platform
        )
        out[key] = fixed
        for rec in records:
            report.append({"key": key, "label": GROUP_LIST_LABELS.get(key, key), **rec})
    return out, report



# ---------------------------------------------------------------------------
# 定时任务
# ---------------------------------------------------------------------------


def schedule_rows(
    config: Mapping[str, Any], now: dt.datetime | None = None
) -> list[dict[str, Any]]:
    """面板「定时任务」表格：开关状态、配置文案与下一次触发时间。

    只按配置算「应该什么时候跑」；实际跑没跑过看插件自己的 _last_* 时间戳，
    由 page.py 再补进来。
    """
    cfg = config or {}
    now = now or dt.datetime.now()

    def has(key: str | None) -> bool:
        return bool(clean_umo_list((cfg or {}).get(key) or [])) if key else True

    rows: list[dict[str, Any]] = []

    def add(
        key: str,
        name: str,
        groups_key: str | None,
        mode: str,
        when: str,
        next_at: dt.datetime | None,
        *,
        note: str = "",
        interval_sec: int | None = None,
        extra_enabled: bool = True,
    ) -> None:
        rows.append(
            {
                "key": key,
                "name": name,
                "groups_key": groups_key or "",
                "groups": len(clean_umo_list(cfg.get(groups_key) or [])) if groups_key else 0,
                "enabled": bool(has(groups_key) and extra_enabled),
                "mode": mode,
                "when": when,
                "interval_sec": interval_sec,
                "next_at": next_at.timestamp() if next_at else None,
                "next_text": (
                    next_at.strftime("%Y-%m-%d %H:%M") + f"（{humanize_delta(next_at - now)}）"
                    if next_at
                    else ""
                ),
                "note": note,
            }
        )

    h, m = parse_hhmm(cfg.get("reset_time", DEFAULT_RESET_TIME)) or (6, 50)
    add(
        "reset",
        "重置提醒",
        "reset_groups",
        "weekly",
        f"周四 {format_hhmm(h, m)}",
        next_weekly(now, 3, h, m),
    )

    fh, fm = parse_hhmm(cfg.get("festival_push_time", DEFAULT_FESTIVAL_TIME)) or (7, 5)
    add(
        "festival",
        "节日通告",
        "festival_push_groups",
        "daily",
        f"每天 {format_hhmm(fh, fm)}",
        next_daily(now, fh, fm),
        note="空档日也发（播报当前节日/活动）",
    )

    try:
        wday = int(cfg.get("weekly_report_day", DEFAULT_WEEKLY_DAY) or DEFAULT_WEEKLY_DAY)
    except (TypeError, ValueError):
        wday = DEFAULT_WEEKLY_DAY
    wday = min(7, max(1, wday))
    add(
        "weekly",
        "榜单周报",
        "weekly_report_groups",
        "weekly",
        f"{WEEKDAY_NAMES[wday - 1]} 20:00",
        next_weekly(now, wday - 1, 20, 0),
    )

    add(
        "news",
        "魔兽新闻",
        "news_groups",
        "interval",
        "每 5 分钟检查",
        None,
        interval_sec=DEFAULT_NEWS_INTERVAL,
        note="有更新才推（按群去重）",
    )

    add(
        "pet",
        "宠物世界任务",
        "pet_push_groups",
        "daily",
        "每天 12:00 起每 5 分钟轮询",
        next_daily(now, 12, 0),
        note="拿到国服下一批任务就推，出现重量级野兽时加预警",
    )

    try:
        punish_interval = max(
            300, int(cfg.get("punish_fetch_interval", DEFAULT_PUNISH_INTERVAL) or 0)
        )
    except (TypeError, ValueError):
        punish_interval = DEFAULT_PUNISH_INTERVAL
    add(
        "punish_fetch",
        "处罚名单自动抓取",
        None,
        "interval",
        f"每 {punish_interval // 60} 分钟检查",
        None,
        interval_sec=punish_interval,
        note="抓到新名单后通报到「处罚名单」列勾选的群",
        extra_enabled=bool(cfg.get("punish_auto_fetch", False)),
    )

    return rows
