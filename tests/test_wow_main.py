# -*- coding: utf-8 -*-
"""魔兽世界 main.py 冒烟 + 面板落库集成测试：桩掉 astrbot 把插件类拉起来。

    python tests/test_wow_main.py
全绿打印 OK。

重点覆盖「面板保存 → 插件的读取路径能读到」，也就是面板和聊天命令改的是同一份配置。
"""
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import types

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_ROOT)


class _Logger:
    def info(self, *a, **k):
        pass

    warning = error = debug = info


class _EventMessageType:
    ALL = "all"


def _passthrough(*d_args, **d_kwargs):
    def deco(func):
        return func

    return deco


class _Star:
    def __init__(self, context=None):
        self.context = context

    async def html_render(self, tmpl, data, options=None):
        return "http://t2i/card.png"


_DATA_ROOT = tempfile.mkdtemp(prefix="wow-main-")


def _install_astrbot_stub():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = _Logger()
    api.AstrBotConfig = dict

    event_mod = types.ModuleType("astrbot.api.event")
    event_mod.filter = types.SimpleNamespace(
        command=_passthrough,
        regex=_passthrough,
        event_message_type=_passthrough,
        on_astrbot_loaded=_passthrough,
        EventMessageType=_EventMessageType,
    )
    event_mod.AstrMessageEvent = object

    star_mod = types.ModuleType("astrbot.api.star")
    star_mod.Context = object
    star_mod.Star = _Star
    star_mod.StarTools = types.SimpleNamespace(get_data_dir=lambda name="": _DATA_ROOT)
    star_mod.register = lambda *a, **k: (lambda cls: cls)

    core = types.ModuleType("astrbot.core")
    core_utils = types.ModuleType("astrbot.core.utils")
    path_mod = types.ModuleType("astrbot.core.utils.astrbot_path")
    path_mod.get_astrbot_data_path = lambda: _DATA_ROOT
    core.utils = core_utils
    core_utils.astrbot_path = path_mod

    api.star = star_mod
    api.event = event_mod
    astrbot.api = api
    astrbot.core = core

    for name, mod in {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event_mod,
        "astrbot.api.star": star_mod,
        "astrbot.core": core,
        "astrbot.core.utils": core_utils,
        "astrbot.core.utils.astrbot_path": path_mod,
    }.items():
        sys.modules[name] = mod


_install_astrbot_stub()

import main as wow_main  # noqa: E402
from wow import page as page_mod  # noqa: E402
from wow import store as wow_store  # noqa: E402
from wow import webmatrix as wm  # noqa: E402


class FakeQuery:
    def __init__(self, data):
        self._data = {k: str(v) for k, v in (data or {}).items()}

    def get(self, key, default=""):
        return self._data.get(key, default)


class FakeRequest:
    def __init__(self, query=None, body=None, method="GET"):
        self.query = FakeQuery(query)
        self.args = self.query
        self.method = method
        self._body = body

    async def json(self, default=None):
        return self._body if self._body is not None else default


def unwrap(resp):
    payload = resp["data"] if "data" in resp and isinstance(resp.get("data"), dict) else resp
    if "status" in payload:
        return (
            payload["status"] == "ok",
            payload.get("data") or {},
            payload.get("message", ""),
        )
    return False, {}, payload.get("message", "")


class FakeConfig(dict):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.save_count = 0

    def save_config(self):
        self.save_count += 1


class FakeClient:
    def __init__(self, group_info=None, group_list=None, fail=False):
        self._info = group_info or {}
        self._list = group_list or []
        self._fail = fail
        self.calls = []

    async def call_action(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if self._fail:
            raise RuntimeError("平台炸了")
        return self._list if action == "get_group_list" else self._info


class FakePlatformInst:
    def __init__(self, platform_id, client, adapter="aiocqhttp"):
        self._pid = platform_id
        self._client = client
        self._adapter = adapter

    def meta(self):
        return types.SimpleNamespace(id=self._pid, name=self._adapter)

    def get_client(self):
        return self._client


class FakeContext:
    def __init__(self, platform_insts=None):
        self.routes = []
        self._insts = list(platform_insts or [])
        # 真实 AstrBot 两套取法都有，这里保持一致
        self.platform_manager = types.SimpleNamespace(
            platform_insts=self._insts,
            get_insts=lambda: list(self._insts),
        )

    def register_web_api(self, path, handler, methods, desc):
        self.routes.append((path, handler, tuple(methods), desc))


def make_event(text="魔兽帮助", umo="napcat:GroupMessage:1001", gid="1001", group_name=None):
    ev = types.SimpleNamespace(
        message_str=text,
        unified_group=None,
        unified_msg_origin=umo,
        message_obj=types.SimpleNamespace(
            group_id=gid,
            group=types.SimpleNamespace(group_id=gid, group_name=group_name),
        ),
    )
    ev.get_platform_id = lambda: "napcat"
    return ev


def make_plugin(platform_insts=None, **cfg):
    data_dir = tempfile.mkdtemp(prefix="wow-case-")
    wow_main.get_astrbot_data_path = lambda: data_dir
    ctx = FakeContext(platform_insts=platform_insts)
    plugin = wow_main.WowPlugin(ctx, FakeConfig(**cfg))
    return plugin, ctx, pathlib.Path(data_dir) / "plugin_data" / "astrbot_plugin_wow"


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 接线
# ---------------------------------------------------------------------------


def test_import_and_routes():
    plugin, ctx, data_dir = make_plugin()
    paths = [p for p, *_ in ctx.routes]
    for suffix in (
        "/page/meta",
        "/page/status",
        "/page/groups",
        "/page/groups/save",
        "/page/groups/dedupe",
        "/page/settings/save",
        "/page/data",
    ):
        assert f"/astrbot_plugin_wow{suffix}" in paths, suffix
    assert plugin.page.plugin is plugin
    assert plugin.groups.path.name == "groups.json"
    assert plugin.groups.path.parent == data_dir


def test_data_dir_shared_with_store():
    plugin, _, data_dir = make_plugin()
    assert wow_store.data_dir() == data_dir
    assert data_dir.is_dir()
    # 面板的榜单/开箱统计走的是插件自己那份数据目录
    assert plugin.page._data_dir() == data_dir


def test_group_name_memory_and_refresh():
    client = FakeClient(
        group_info={"group_id": 1001, "group_name": "魔兽交流群", "member_count": 300},
        group_list=[
            {"group_id": 1001, "group_name": "魔兽交流群", "member_count": 300},
            {"group_id": 2002, "group_name": "活动通知群"},
        ],
    )
    plugin, _, data_dir = make_plugin(platform_insts=[FakePlatformInst("napcat", client)])

    run(plugin.on_any_message(make_event()))
    assert plugin.groups.get("napcat:GroupMessage:1001") is not None
    assert plugin.groups.name_of("napcat:GroupMessage:1001") == ""

    run(plugin._learn_group_name(client, "napcat:GroupMessage:1001", "1001", "napcat"))
    assert plugin.groups.name_of("napcat:GroupMessage:1001") == "魔兽交流群"

    client.calls.clear()
    assert run(plugin.refresh_group_names(force=True)) == 1  # 多了一个 2002
    assert plugin.groups.name_of("napcat:GroupMessage:2002") == "活动通知群"
    assert len(client.calls) == 1
    assert run(plugin.refresh_group_names()) == 0
    assert len(client.calls) == 1  # 节流窗口内不再问平台
    assert (data_dir / "groups.json").is_file()


def test_learn_group_name_failure_is_silent():
    plugin, _, _ = make_plugin()
    run(plugin._learn_group_name(FakeClient(fail=True), "napcat:GroupMessage:9", "9", "napcat"))
    assert plugin.groups.name_of("napcat:GroupMessage:9") == ""


# ---------------------------------------------------------------------------
# 面板保存 → 插件读取（同一份配置）
# ---------------------------------------------------------------------------


def test_panel_save_then_plugin_reads():
    plugin, _, _ = make_plugin(news_groups=["1001", "1002"])
    plugin.groups.remember("1001", group_name="魔兽交流群")
    plugin.groups.remember("napcat:GroupMessage:2002", group_name="活动通知群")

    page_mod.request = FakeRequest()
    ok, data, _ = unwrap(run(plugin.page.get_groups()))
    page_mod.request = None
    assert ok
    by_umo = {r["umo"]: r for r in data["rows"]}
    assert by_umo["1001"]["label"] == "魔兽交流群（1001）"
    # 2002 只在群名缓存里 → 也出现在矩阵里（可以顺手勾上）
    assert by_umo["napcat:GroupMessage:2002"]["count"] == 0

    # 面板会把没勾选的行也提交上来，所以「移除 1002」= 提交它的行且不勾
    rows = [
        {"umo": "1001", "flags": {"news_groups": True, "pet_push_groups": True}},
        {"umo": "napcat:GroupMessage:2002", "flags": {"festival_push_groups": True}},
        {"umo": "1002", "flags": {}},
    ]
    page_mod.request = FakeRequest(body={"rows": rows}, method="POST")
    ok, saved, _ = unwrap(run(plugin.page.save_groups()))
    page_mod.request = None
    assert ok
    assert plugin.config.save_count == 1
    assert saved["kept"] == []

    # 插件自己的归一化读取路径能读到面板写的内容（裸群号会被补全成 umo，行为不变）
    assert plugin._norm_umo_list("news_groups") == ["aiocqhttp:GroupMessage:1001"]
    assert plugin._norm_umo_list("pet_push_groups") == ["aiocqhttp:GroupMessage:1001"]
    assert plugin._norm_umo_list("festival_push_groups") == ["napcat:GroupMessage:2002"]
    # 配置里存的确实是面板写进去的形态（裸群号原样保留，没被强改成 umo）
    assert plugin.config["news_groups"] == ["1001"]
    # 没提交上来的目标不会被静默删掉（前端版本旧 / 配置刚被别的命令改过）
    assert plugin.config["reset_groups"] == []
    # 没勾的列被清空
    assert plugin._norm_umo_list("reset_groups") == []
    summary = wm.matrix_summary({k: list(plugin.config.get(k, []) or []) for k in wm.GROUP_LIST_KEYS})
    assert summary["groups"] == 2 and summary["links"] == 3


def test_panel_settings_save_then_schedule_uses_them():
    plugin, _, _ = make_plugin(reset_groups=["1001"])
    page_mod.request = FakeRequest(
        body={
            "reset_time": "09:15",
            "festival_push_time": "07:05",
            "weekly_report_day": 2,
            "markdown_group_mode": "whitelist",
        },
        method="POST",
    )
    ok, data, _ = unwrap(run(plugin.page.save_settings()))
    page_mod.request = None
    assert ok
    # 面板把设置写回真正的插件配置
    page_mod.request = FakeRequest()
    ok, status, _ = unwrap(run(plugin.page.get_status()))
    page_mod.request = None
    assert ok
    rows = {r["key"]: r for r in status["schedule"]["rows"]}
    assert rows["reset"]["when"] == "周四 09:15"
    assert rows["weekly"]["when"] == "周二 20:00"
    assert plugin.config["markdown_group_mode"] == "whitelist"


def test_bare_group_number_gets_routable_instance_id():
    """裸群号要补成**实例 id**：写 aiocqhttp 这种适配器类型名的话 send_message 匹配不到。"""
    insts = [
        FakePlatformInst("webchat", None, adapter="webchat"),
        FakePlatformInst("napcat", None, adapter="aiocqhttp"),
    ]
    plugin, _, _ = make_plugin(platform_insts=insts)
    assert plugin._bare_id_platform() == "napcat"
    # 8 份群名单的归一化都受益
    plugin.config["news_groups"] = ["123456", "napcat:GroupMessage:999"]
    assert plugin._norm_umo_list("news_groups") == [
        "napcat:GroupMessage:123456",
        "napcat:GroupMessage:999",
    ]

    # 只有 webchat 时也不能写死 aiocqhttp
    only_web = [FakePlatformInst("webchat", None, adapter="webchat")]
    plugin2, _, _ = make_plugin(platform_insts=only_web)
    assert plugin2._bare_id_platform() == "webchat"

    # 探不到平台：保持旧行为（回落 aiocqhttp）
    plugin3, _, _ = make_plugin()
    assert plugin3._bare_id_platform() == "aiocqhttp"


def test_type_name_platform_is_rewritten_to_instance_id():
    """现场问题回归：配置里写的 aiocqhttp 是适配器**类型名**，按实例 id 路由会静默发不出去。"""
    insts = [
        FakePlatformInst("webchat", None, adapter="webchat"),
        FakePlatformInst("napcat", None, adapter="aiocqhttp"),
        FakePlatformInst("default_102737249", None, adapter="qq_official"),
    ]
    plugin, _, _ = make_plugin(platform_insts=insts)
    plugin.config["punish_notify_groups"] = ["aiocqhttp:GroupMessage:723978808"]
    plugin.config["markdown_groups"] = ["qq_official:GroupMessage:ABC123"]
    plugin.config["news_groups"] = [
        "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F",
        "napcat:GroupMessage:723978808",
    ]
    # 类型名 → 该类型的实例 id（napcat 的适配器就是 aiocqhttp / 官方的是 qq_official）
    assert plugin._norm_umo_list("punish_notify_groups") == ["napcat:GroupMessage:723978808"]
    assert plugin._norm_umo_list("markdown_groups") == [
        "default_102737249:GroupMessage:ABC123"
    ]
    # 已经是实例 id 的（含官方机器人的 openid 群）一个字都不动
    assert plugin._norm_umo_list("news_groups") == [
        "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F",
        "napcat:GroupMessage:723978808",
    ]
    # 认不出来的平台：原样保留（不能乱猜平台），但要 warning 一次，别静默失败
    plugin.config["reset_groups"] = ["old_bot:GroupMessage:555"]
    assert plugin._norm_umo_list("reset_groups") == ["old_bot:GroupMessage:555"]
    assert plugin._bad_umo_warned == {"old_bot:GroupMessage:555"}
    assert plugin._norm_umo_list("reset_groups") == ["old_bot:GroupMessage:555"]
    assert len(plugin._bad_umo_warned) == 1  # 只记一次，不刷屏


def test_norm_umo_degrades_when_webmatrix_is_old():
    """混装（新 main.py + 旧 wow/webmatrix.py）时不能崩，退回旧逻辑并 warn。"""
    from wow import webmatrix as wm_mod

    plugin, _, _ = make_plugin(platform_insts=[FakePlatformInst("napcat", None)])
    saved = wm_mod.rewrite_umo
    del wm_mod.rewrite_umo  # 模拟旧版 webmatrix 里没有这个函数
    try:
        assert plugin._norm_umo("1001") == "napcat:GroupMessage:1001"
        assert plugin._norm_umo("aiocqhttp:GroupMessage:555") == "aiocqhttp:GroupMessage:555"
        assert plugin._norm_umo("") == ""
    finally:
        wm_mod.rewrite_umo = saved
    # 恢复正常后照旧会改写类型名
    assert plugin._norm_umo("aiocqhttp:GroupMessage:555") == "napcat:GroupMessage:555"


def test_norm_umo_rewrites_type_name_and_keeps_reachable():
    plugin, _, _ = make_plugin(platform_insts=[FakePlatformInst("napcat", None)])
    assert plugin._norm_umo("aiocqhttp:GroupMessage:1001") == "napcat:GroupMessage:1001"
    assert plugin._norm_umo("napcat:GroupMessage:1001") == "napcat:GroupMessage:1001"
    assert plugin._norm_umo("1001") == "napcat:GroupMessage:1001"
    assert plugin._norm_umo("") == ""
    # 探不到任何平台实例时不许瞎改写（保持原样，让上层 warning）
    plugin2, _, _ = make_plugin()
    assert plugin2._norm_umo("qq_official:GroupMessage:ABC") == "qq_official:GroupMessage:ABC"
    assert plugin2._norm_umo("1001") == "aiocqhttp:GroupMessage:1001"


def test_terminate_flushes_group_names():
    plugin, _, data_dir = make_plugin()
    run(plugin.on_any_message(make_event(group_name="魔兽交流群")))
    plugin._scheduler_task = None
    run(plugin.terminate())
    saved = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
    assert saved["groups"]["napcat:GroupMessage:1001"]["group_name"] == "魔兽交流群"


def main():
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        fn()
        print(f"  {name} ok")
    print(f"OK ({len(tests)} tests)")


if __name__ == "__main__":
    main()
