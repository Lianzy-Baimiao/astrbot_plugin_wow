# -*- coding: utf-8 -*-
"""魔兽世界插件的 Web 面板后端接口（AstrBot Plugin Pages）。

路由挂在 ``/astrbot_plugin_wow/page/*`` 下，前端 ``pages/wow-panel/`` 通过
``window.AstrBotPluginPage`` 的 apiGet / apiPost 调用（bridge 会自动补插件名前缀）。

    GET  /page/meta           8 份群名单的说明、可选值、上限
    GET  /page/status         定时任务（下一次触发时间）+ 数据新鲜度概览
    GET  /page/groups         群 × 功能 矩阵（带群名），refresh=1 现问平台群列表
    POST /page/groups/save    保存矩阵（写回 8 份群名单配置 + 落盘）
    POST /page/settings/save  保存标量设置（重置时间/周报日/节日时间/Markdown 范围等）
    GET  /page/data           数据目录清单（物价表/榜单/开箱/处罚名单）

设计要点：群名单配置里原本允许「裸群号」和「完整 umo」两种写法，面板统一按**完整 umo**
写回（避免多平台时裸号被补全到错误的平台），配置读取仍然兼容旧写法（``wow.webmatrix``
的 normalize_umo 会把两者都认下来）。保存走插件既有的 ``self.config[键] = [...]`` +
``save_config()``，与聊天命令改的是同一份数据。
"""

from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any, Callable

try:  # AstrBot >= 4.26
    from astrbot.api.web import error_response, json_response, request

    _HAS_WEB_API = True
except (ImportError, AttributeError):  # 老版本回落到 quart
    _HAS_WEB_API = False
    try:
        from quart import jsonify as _quart_jsonify
        from quart import request  # type: ignore[assignment]
    except ImportError:  # 本地单测环境两个都没有
        request = None  # type: ignore[assignment]
        _quart_jsonify = None  # type: ignore[assignment]

    def json_response(  # type: ignore[misc]
        data: Any = None,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if _quart_jsonify is None:
            return {"status_code": status_code, "data": data}
        resp = _quart_jsonify(data)
        resp.status_code = status_code
        for key, value in (headers or {}).items():
            resp.headers[key] = value
        return resp

    def error_response(  # type: ignore[misc]
        message: str = "",
        *,
        status_code: int = 400,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return json_response(
            {"status": "error", "message": message, "data": data if data is not None else {}},
            status_code=status_code,
            headers=headers,
        )


from . import webmatrix as wm
from .groups import GroupNameResolver, session_label, split_umo

PLUGIN_NAME = "astrbot_plugin_wow"

# 面板可改的标量设置：(配置键, 中文名, 类型)
SCALAR_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("reset_time", "重置提醒时间（周四）", "hhmm"),
    ("festival_push_time", "节日通告时间（每天）", "hhmm"),
    ("weekly_report_day", "周报推送日（1=周一 … 7=周日）", "weekday"),
    ("markdown_group_mode", "Markdown 生效范围", "mode"),
)


def _log_warn(message: str) -> None:
    try:
        from astrbot.api import logger

        logger.warning(f"[wow] {message}")
    except Exception:
        pass


def _fmt_time(ts: Any) -> str:
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return "从未"
    if ts <= 0:
        return "从未"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return "未知"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class WowPageController:
    """把魔兽世界插件的能力包成 HTTP 接口。"""

    def __init__(self, context: Any, plugin: Any = None) -> None:
        self.context = context
        self.plugin = plugin

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register_routes(self) -> None:
        routes: list[tuple[str, Callable[..., Any], list[str], str]] = [
            ("/page/meta", self.get_meta, ["GET"], "魔兽世界：面板说明与上限"),
            ("/page/status", self.get_status, ["GET"], "魔兽世界：定时任务与数据概览"),
            ("/page/groups", self.get_groups, ["GET"], "魔兽世界：群 × 功能 矩阵"),
            ("/page/groups/save", self.save_groups, ["POST"], "魔兽世界：保存群名单"),
            ("/page/groups/dedupe", self.dedupe_groups, ["POST"], "魔兽世界：整理群名单写法"),
            ("/page/groups/rename", self.rename_group, ["POST"], "魔兽世界：给会话起备注名"),
            ("/page/settings/save", self.save_settings, ["POST"], "魔兽世界：保存定时与格式设置"),
            ("/page/data", self.get_data, ["GET"], "魔兽世界：数据目录清单"),
        ]
        for path, handler, methods, desc in routes:
            try:
                self.context.register_web_api(
                    f"/{PLUGIN_NAME}{path}", handler, methods, desc
                )
            except Exception as exc:  # 老版本 AstrBot / 单测：注册不上也不该炸插件
                _log_warn(f"注册接口 {path} 失败: {exc}")

    # ------------------------------------------------------------------
    # 请求 / 响应小工具
    # ------------------------------------------------------------------

    @staticmethod
    def _ok(data: Any = None, message: str = "") -> Any:
        payload: dict[str, Any] = {
            "status": "ok",
            "data": data if data is not None else {},
        }
        if message:
            payload["message"] = message
        return json_response(payload)

    @staticmethod
    def _err(message: str, status_code: int = 400) -> Any:
        return error_response(message, status_code=status_code)

    @staticmethod
    def _query_get(key: str, default: str = "") -> str:
        if request is None:
            return default
        for holder in ("query", "args"):
            bag = getattr(request, holder, None)
            if bag is None:
                continue
            try:
                value = bag.get(key, default)
            except Exception:
                continue
            if value is not None:
                return str(value)
        return default

    @staticmethod
    async def _read_json() -> dict[str, Any]:
        if request is None:
            return {}
        for method_name in ("json", "get_json"):
            method = getattr(request, method_name, None)
            if not callable(method):
                continue
            try:
                data = method()
                if hasattr(data, "__await__"):
                    data = await data
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return {}

    async def _payload(self) -> dict[str, Any]:
        payload = await self._read_json()
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------

    def _config(self) -> Any:
        return getattr(self.plugin, "config", None)

    def _cfg(self, key: str, default: Any = None) -> Any:
        config = self._config()
        try:
            value = config.get(key, default)  # type: ignore[union-attr]
        except Exception:
            return default
        return default if value is None else value

    def _config_lists(self) -> dict[str, list[str]]:
        """8 份群名单的当前值（顺序与 GROUP_LISTS 一致）。"""
        return {
            key: list(self._cfg(key, []) or []) for key in wm.GROUP_LIST_KEYS
        }

    async def _save_config(self) -> bool:
        config = self._config()
        saver = getattr(config, "save_config_async", None)
        if callable(saver):
            await saver()
            return True
        saver = getattr(config, "save_config", None)
        if callable(saver):
            saver()
            return True
        saver = getattr(self.plugin, "save_config_now", None)
        if callable(saver):
            await saver()
            return True
        return False

    def _resolver(self) -> GroupNameResolver | None:
        resolver = getattr(self.plugin, "groups", None)
        return resolver if isinstance(resolver, GroupNameResolver) else None

    def _instances(self) -> list[tuple[str, str]]:
        """当前已加载平台的 (实例 id, 适配器类型名)；取不到就返回空列表。"""
        getter = getattr(self.plugin, "_platform_instances", None)
        if not callable(getter):
            return []
        try:
            items = getter() or []
        except Exception as exc:  # noqa: BLE001
            _log_warn(f"取平台实例失败: {exc}")
            return []
        return wm.normalize_instances(items)

    def _default_platform(self) -> str:
        """裸群号会被补到哪个平台实例上（判断在插件侧，面板保持一致）。"""
        getter = getattr(self.plugin, "_bare_id_platform", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:  # noqa: BLE001
                pass
        return ""

    @staticmethod
    def _platform_text(platform: str, state: str, target: str) -> str:
        """平台列显示的一行文案（说人话：这条订阅实际走哪个实例）。"""
        if state == "id":
            return platform
        if state == "type":
            return f"{platform} → {target}"
        if state == "bare":
            return f"{wm.BARE_LABEL} → {target}"
        if state == "plain":
            return f"{wm.BARE_LABEL}（没探到平台）"
        return f"{platform}（实例不存在）"

    def _label(self, umo: str) -> str:
        resolver = self._resolver()
        return session_label(umo) if resolver is None else resolver.label(umo)

    def _data_dir(self):
        getter = getattr(self.plugin, "_data_dir_path", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        try:
            from .store import data_dir

            return data_dir()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 接口：群 × 功能 矩阵
    # ------------------------------------------------------------------

    def _group_rows(self, instances: list[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
        """矩阵行：配置里出现过的群 + 群名缓存里见过的群（都带群名与平台信息）。

        平台信息是给「分不清官方 / napcat」用的：每行标明这条订阅走哪个平台实例，
        写成适配器类型名（aiocqhttp / qq_official）的标「可能要改写」，实例不存在的标红。
        """
        insts = self._instances() if instances is None else instances
        default_platform = self._default_platform()
        type_map = wm.platform_type_map(insts)
        rows = wm.matrix_from_lists(self._config_lists())
        seen = {row["umo"]: row for row in rows}
        resolver = self._resolver()
        if resolver is not None:
            for umo in resolver.entries():
                if umo in seen:
                    continue
                seen[umo] = {
                    "umo": umo,
                    "flags": {key: False for key in wm.GROUP_LIST_KEYS},
                }
                rows.append(seen[umo])
        for row in rows:
            umo = row["umo"]
            _, _, sid = split_umo(umo)
            entry = resolver.get(umo) if resolver is not None else None
            platform = wm.platform_of(umo)
            target, state = wm.rewrite_umo(umo, insts, default_platform)
            # 实际会走哪个实例：类型名/裸号看改写后的 umo，认不出来的留空
            if state == "id":
                resolved = platform
            elif state in ("type", "bare"):
                resolved = wm.platform_of(target)
            else:
                resolved = ""
            row["label"] = self._label(umo)
            row["group_id"] = str((entry or {}).get("group_id") or sid)
            row["group_name"] = str((entry or {}).get("group_name") or "")
            row["count"] = len([k for k, v in row["flags"].items() if v])
            row["platform"] = platform
            row["platform_state"] = state
            row["platform_resolved"] = resolved
            row["platform_type"] = type_map.get(resolved, "")
            row["platform_text"] = self._platform_text(platform, state, resolved)
            # 类型名写法在插件里会自动改写，所以也算「发得出去」
            row["reachable"] = state in ("id", "type", "bare")
        rows.sort(
            key=lambda item: (
                item["count"] == 0,
                not bool(item["group_name"]),
                item["group_id"] or item["label"],
            )
        )
        return rows

    def _diagnose(self, lists: dict[str, list[str]], insts: list[tuple[str, str]]) -> dict[str, Any]:
        """面板诊断区：认不出来的平台写法 + 同一个群号的多种写法。"""
        umos = wm.all_umos(lists)
        dead = [
            {**item, "label": self._label(item["umo"])}
            for item in wm.unreachable_umos(umos, insts)
        ]
        duplicates = [
            {**item, "label": self._label(item["umos"][0])}
            for item in wm.duplicate_targets(lists)
        ]
        return {"dead": dead, "duplicates": duplicates}

    async def get_groups(self) -> Any:
        refresh = self._query_get("refresh", "0").strip().lower() in {"1", "true", "yes"}
        refreshed = 0
        if refresh and self.plugin is not None:
            refresher = getattr(self.plugin, "refresh_group_names", None)
            if callable(refresher):
                try:
                    refreshed = int(await refresher(force=True) or 0)
                except Exception as exc:
                    _log_warn(f"刷新群列表失败: {exc}")
        insts = self._instances()
        default_platform = self._default_platform()
        rows = self._group_rows(insts)
        lists = self._config_lists()
        summary = wm.matrix_summary(lists)
        diag = self._diagnose(lists, insts)
        return self._ok(
            {
                "rows": rows,
                "columns": [
                    {"key": key, "label": wm.GROUP_LIST_LABELS[key], "hint": wm.GROUP_LIST_HINTS[key]}
                    for key in wm.GROUP_LIST_KEYS
                ],
                "summary": summary,
                "refreshed": refreshed,
                "named": len([r for r in rows if r["group_name"]]),
                "max_per_list": wm.MAX_UMOS_PER_LIST,
                "instances": [
                    {
                        "id": pid,
                        "type": ptype,
                        "label": f"{pid}（{ptype}）" if ptype and ptype != pid else pid,
                        "bare_id": pid == default_platform,
                    }
                    for pid, ptype in insts
                ],
                "default_platform": default_platform,
                "platforms": wm.platform_stats(lists, insts),
                "dead": diag["dead"],
                "duplicates": diag["duplicates"],
            }
        )

    async def save_groups(self) -> Any:
        """保存矩阵：写回 8 份群名单 + 落盘。"""
        config = self._config()
        if config is None:
            return self._err("插件配置不可用", status_code=500)
        payload = await self._payload()
        rows = payload.get("rows")
        if not isinstance(rows, (list, tuple)):
            return self._err("rows 需要是数组")
        cleaned = wm.lists_from_matrix(list(rows))

        before = self._config_lists()

        # 面板根本没提交上来的目标一律保留：前端被过滤掉/版本不匹配时，
        # 一次「保存群名单」不该把它们静默删掉（真踩过：群号带字母的写法被整批丢）。
        submitted: set[str] = set()
        for row in list(rows or []):
            if isinstance(row, dict):
                umo = wm.normalize_umo(row.get("umo"))
                if umo:
                    submitted.add(umo)
        kept: list[str] = []
        for key in wm.GROUP_LIST_KEYS:
            leftover = [
                str(raw)
                for raw in list(before.get(key) or [])
                if wm.normalize_umo(raw) and wm.normalize_umo(raw) not in submitted
            ]
            if leftover:
                cleaned[key] = wm.clean_umo_list(cleaned[key] + leftover)
            kept.extend(leftover)
        kept = list(dict.fromkeys(kept))  # 同一目标挂在多列时只报一次

        for key in wm.GROUP_LIST_KEYS:
            raw = [r for r in (rows or []) if isinstance(r, dict)]
            picked = len([r for r in raw if (r.get("flags") or {}).get(key)])
            if picked > wm.MAX_UMOS_PER_LIST:
                return self._err(f"「{wm.GROUP_LIST_LABELS[key]}」最多 {wm.MAX_UMOS_PER_LIST} 个群")
        try:
            for key in wm.GROUP_LIST_KEYS:
                config[key] = cleaned[key]
        except Exception as exc:
            return self._err(f"写入配置失败：{exc}", status_code=500)
        try:
            saved = await self._save_config()
        except Exception as exc:
            _log_warn(f"保存配置失败: {exc}")
            return self._err("配置保存失败，请查看服务端日志", status_code=500)

        diff = wm.diff_lists(before, cleaned)
        changes = [
            {
                "key": key,
                "label": wm.GROUP_LIST_LABELS.get(key, key),
                "added": [{"umo": u, "label": self._label(u)} for u in item["added"]],
                "removed": [{"umo": u, "label": self._label(u)} for u in item["removed"]],
            }
            for key, item in diff.items()
        ]
        message = "已保存" if not changes else f"已保存 {len(changes)} 列的改动"
        if kept:
            message += f"（保留了 {len(kept)} 条本次没提交的目标）"
        if not saved:
            message += "（⚠️ 配置对象没有保存方法，可能不会持久化）"
        return self._ok(
            {
                "lists": cleaned,
                "summary": wm.matrix_summary(cleaned),
                "changes": changes,
                "kept": kept,
            },
            message,
        )

    async def dedupe_groups(self) -> Any:
        """整理群名单写法：适配器类型名换实例 id、裸号补平台、同写法合并。

        只动「写法」，不动勾选——每个群在哪些列里完全不变，所以不会改变推送范围。
        改不动的（平台实例真的不存在）原样保留并在返回里报出来，前端提示用户。
        """
        config = self._config()
        if config is None:
            return self._err("插件配置不可用", status_code=500)
        before = self._config_lists()
        insts = self._instances()
        cleaned, report = wm.normalize_lists(before, insts, self._default_platform())
        changed = [key for key in wm.GROUP_LIST_KEYS if list(before.get(key) or []) != cleaned[key]]
        items = [
            {
                **item,
                "from_label": self._label(item["from"]),
                "to_label": self._label(item["to"]) if item["to"] != item["from"] else "",
            }
            for item in report
        ]
        unreachable = [
            {**item, "label": self._label(item["umo"])}
            for item in wm.unreachable_umos(wm.all_umos(cleaned), insts)
        ]
        if not changed:
            return self._ok(
                {
                    "report": items,
                    "changed": [],
                    "lists": cleaned,
                    "summary": wm.matrix_summary(cleaned),
                    "unreachable": unreachable,
                },
                "没有需要整理的地方",
            )
        try:
            for key in wm.GROUP_LIST_KEYS:
                config[key] = cleaned[key]
        except Exception as exc:
            return self._err(f"写入配置失败：{exc}", status_code=500)
        try:
            await self._save_config()
        except Exception as exc:
            _log_warn(f"整理后保存配置失败: {exc}")
            return self._err("配置保存失败，请查看服务端日志", status_code=500)

        fixed_count = len([i for i in items if i["action"] in ("type", "bare")])
        merged_count = len([i for i in items if i["action"] == "merge"])
        stuck = len(unreachable)
        parts = []
        if fixed_count:
            parts.append(f"改写 {fixed_count} 处写法")
        if merged_count:
            parts.append(f"合并 {merged_count} 处重复")
        message = "已整理：" + "、".join(parts) if parts else "已整理（名单未变）"
        if stuck:
            message += f"；还有 {stuck} 处平台实例不存在，需要手动改"
        return self._ok(
            {
                "report": items,
                "changed": changed,
                "lists": cleaned,
                "summary": wm.matrix_summary(cleaned),
                "unreachable": unreachable,
            },
            message,
        )

    async def rename_group(self) -> Any:
        """给会话起 / 清备注名（面板显示用）。

        QQ 官方机器人（qq_official）不给群名，那边的群只能靠备注认出是哪个群；
        备注保存在群名缓存里（source=manual），平台报来的名字不会覆盖它。
        """
        resolver = self._resolver()
        if resolver is None:
            return self._err("群名缓存不可用", status_code=500)
        payload = await self._payload()
        umo = wm.normalize_umo(payload.get("umo"))
        if not umo:
            return self._err("umo 不合法")
        name = str(payload.get("name") or "").strip()
        if len(name) > 40:
            return self._err("备注名最多 40 个字")
        try:
            resolver.rename(umo, name)
        except Exception as exc:  # noqa: BLE001
            _log_warn(f"保存备注失败: {exc}")
            return self._err("备注保存失败，请查看服务端日志", status_code=500)
        return self._ok(
            {"umo": umo, "name": name, "label": self._label(umo)},
            "备注已保存" if name else "备注已清空",
        )

    # ------------------------------------------------------------------
    # 接口：标量设置
    # ------------------------------------------------------------------

    def _scalar_values(self) -> dict[str, Any]:
        return {
            "reset_time": str(self._cfg("reset_time", wm.DEFAULT_RESET_TIME) or ""),
            "festival_push_time": str(
                self._cfg("festival_push_time", wm.DEFAULT_FESTIVAL_TIME) or ""
            ),
            "weekly_report_day": _as_int(
                self._cfg("weekly_report_day", wm.DEFAULT_WEEKLY_DAY),
                wm.DEFAULT_WEEKLY_DAY,
            ),
            "markdown_group_mode": str(self._cfg("markdown_group_mode", "all") or "all"),
            "punish_auto_fetch": bool(self._cfg("punish_auto_fetch", False)),
            "markdown_output": bool(self._cfg("markdown_output", True)),
            "markdown_strip_platforms": list(self._cfg("markdown_strip_platforms", []) or []),
        }

    async def save_settings(self) -> Any:
        config = self._config()
        if config is None:
            return self._err("插件配置不可用", status_code=500)
        payload = await self._payload()
        current = self._scalar_values()
        updates: dict[str, Any] = {}

        for key, label in (
            ("reset_time", "重置提醒时间"),
            ("festival_push_time", "节日通告时间"),
        ):
            parsed = wm.parse_hhmm(payload.get(key, current[key]))
            if parsed is None:
                return self._err(f"「{label}」格式应为 HH:MM")
            updates[key] = wm.format_hhmm(*parsed)

        try:
            day = int(payload.get("weekly_report_day", current["weekly_report_day"]))
        except (TypeError, ValueError):
            return self._err("周报推送日需要是 1-7 的整数")
        if not 1 <= day <= 7:
            return self._err("周报推送日需要是 1-7 的整数")
        updates["weekly_report_day"] = day

        raw_mode = str(payload.get("markdown_group_mode", current["markdown_group_mode"]) or "")
        valid_modes = [m for m, _ in wm.MARKDOWN_MODES]
        if raw_mode not in valid_modes:
            return self._err(f"Markdown 生效范围只能是 {'/'.join(valid_modes)}")
        updates["markdown_group_mode"] = raw_mode

        try:
            for key, value in updates.items():
                config[key] = value
        except Exception as exc:
            return self._err(f"写入配置失败：{exc}", status_code=500)
        try:
            saved = await self._save_config()
        except Exception as exc:
            _log_warn(f"保存配置失败: {exc}")
            return self._err("配置保存失败，请查看服务端日志", status_code=500)

        message = "设置已保存"
        if not saved:
            message += "（⚠️ 配置对象没有保存方法，可能不会持久化）"
        return self._ok(self._scalar_values(), message)

    # ------------------------------------------------------------------
    # 接口：状态与数据
    # ------------------------------------------------------------------

    def _cfg_plain(self) -> dict[str, Any]:
        """配置对象的浅拷贝（schedule_rows 只读，给它普通 dict 更省心）。"""
        config = self._config()
        try:
            return {k: config[k] for k in list(config.keys())}  # type: ignore[union-attr]
        except Exception:
            return {}

    def _schedule(self) -> dict[str, Any]:
        rows = wm.schedule_rows(self._cfg_plain(), dt.datetime.now())
        # 键要跟 schedule_rows 里的 key 对齐（处罚是 punish_fetch，不是 punish）
        last = {
            "news": float(getattr(self.plugin, "_last_news_check", 0) or 0),
            "punish_fetch": float(getattr(self.plugin, "_last_punish_check", 0) or 0),
        }
        for row in rows:
            row["last_text"] = ""
            row["remaining_sec"] = 0
            if row["key"] in last:
                stamp = last[row["key"]]
                row["last_text"] = _fmt_time(stamp) if stamp else "插件启动后还没跑过"
                if stamp and row["interval_sec"]:
                    row["remaining_sec"] = max(
                        0, int(row["interval_sec"] - (time.time() - stamp))
                    )
        return {"rows": rows, "now_text": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    def _prices_info(self) -> dict[str, Any]:
        """物价表新鲜度：条数、服务器、数据截止、文件时间。"""
        base = self._data_dir()
        info: dict[str, Any] = {
            "exists": False,
            "path": "",
            "items": 0,
            "realm": "",
            "scanned_text": "",
            "stale_days": None,
        }
        if base is None:
            return info
        path = base / "prices.json"
        info["path"] = str(path)
        if not path.is_file():
            return info
        info["exists"] = True
        try:
            stat = path.stat()
            info["size"] = stat.st_size
            info["mtime_text"] = _fmt_time(stat.st_mtime)
        except OSError:
            pass
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return info
        if not isinstance(data, dict):
            return info
        items = data.get("items")
        info["items"] = len(items) if isinstance(items, list) else 0
        info["realm"] = str(data.get("realm") or "")
        info["scanned_text"] = _fmt_time(data.get("scanned_at"))
        day0 = _as_int(data.get("day0"), 0)
        newest = _as_int(data.get("newest_day"), 0)
        if day0 and newest:
            try:
                newest_date = dt.datetime.fromtimestamp(day0 + newest * 86400)
                info["stale_days"] = max(0, (dt.datetime.now() - newest_date).days)
                info["newest_text"] = newest_date.strftime("%Y-%m-%d")
            except (OverflowError, OSError, ValueError):
                pass
        return info

    def _store_getter(self, name: str) -> Any:
        getter = getattr(self.plugin, name, None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        try:
            from . import store

            return getattr(store, name)()
        except Exception:
            return None

    def _board_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"available": False, "roster": 0}
        board = self._store_getter("get_board_store")
        if board is None:
            return info
        try:
            info["available"] = True
            info["roster"] = len(board.list_roster())
        except Exception:
            pass
        base = self._data_dir()
        if base is not None:
            path = base / "board.db"
            if path.is_file():
                info["size"] = path.stat().st_size
        return info

    def _gacha_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"available": False, "players": 0}
        gacha = self._store_getter("get_gacha_store")
        if gacha is None:
            return info
        try:
            info["available"] = True
            cur = gacha._conn.execute("SELECT COUNT(*) FROM gacha_score")
            info["players"] = int(cur.fetchone()[0])
        except Exception:
            pass
        base = self._data_dir()
        if base is not None:
            path = base / "gacha.db"
            if path.is_file():
                info["size"] = path.stat().st_size
        return info

    def _punish_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"dir": "", "files": [], "count": 0}
        getter = getattr(self.plugin, "_punish_dir", None)
        directory = None
        if callable(getter):
            try:
                directory = getter()
            except Exception:
                directory = None
        if directory is None:
            base = self._data_dir()
            directory = (base / "punish") if base is not None else None
        if directory is None:
            return info
        info["dir"] = str(directory)
        try:
            if directory.is_dir():
                files = sorted(
                    (p for p in directory.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                info["count"] = len(files)
                info["files"] = [
                    {
                        "name": p.name,
                        "size": p.stat().st_size,
                        "modified_text": _fmt_time(p.stat().st_mtime),
                    }
                    for p in files[:20]
                ]
        except OSError:
            pass
        return info

    def _cache_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"dir": "", "files": 0, "bytes": 0}
        base = self._data_dir()
        if base is None:
            return info
        directory = base / "cache"
        info["dir"] = str(directory)
        try:
            if directory.is_dir():
                files = [p for p in directory.rglob("*") if p.is_file()]
                info["files"] = len(files)
                info["bytes"] = sum(p.stat().st_size for p in files)
        except OSError:
            pass
        return info

    def _modifiers(self) -> dict[str, Any]:
        return {
            "markdown_modes": [{"value": v, "label": lbl} for v, lbl in wm.MARKDOWN_MODES],
            "weekdays": [{"value": i + 1, "label": wm.WEEKDAY_NAMES[i]} for i in range(7)],
        }

    async def get_status(self) -> Any:
        return self._ok(
            {
                "schedule": self._schedule(),
                "summary": wm.matrix_summary(self._config_lists()),
                "settings": self._scalar_values(),
                "modifiers": self._modifiers(),
                "prices": self._prices_info(),
                "running": bool(getattr(self.plugin, "_scheduler_task", None) is not None),
                "data_dir": str(self._data_dir() or ""),
            }
        )

    async def get_data(self) -> Any:
        return self._ok(
            {
                "prices": self._prices_info(),
                "board": self._board_info(),
                "gacha": self._gacha_info(),
                "punish": self._punish_info(),
                "cache": self._cache_info(),
                "data_dir": str(self._data_dir() or ""),
            }
        )

    async def get_meta(self) -> Any:
        return self._ok(
            {
                "plugin": PLUGIN_NAME,
                "columns": [
                    {
                        "key": key,
                        "label": wm.GROUP_LIST_LABELS[key],
                        "hint": wm.GROUP_LIST_HINTS[key],
                    }
                    for key in wm.GROUP_LIST_KEYS
                ],
                "limits": {"max_per_list": wm.MAX_UMOS_PER_LIST},
                "defaults": {
                    "reset_time": wm.DEFAULT_RESET_TIME,
                    "festival_push_time": wm.DEFAULT_FESTIVAL_TIME,
                    "weekly_report_day": wm.DEFAULT_WEEKLY_DAY,
                },
                "scalar_settings": [
                    {"key": key, "label": label, "type": kind}
                    for key, label, kind in SCALAR_SETTINGS
                ],
                "modifiers": self._modifiers(),
            }
        )
