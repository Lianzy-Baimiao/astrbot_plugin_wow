# -*- coding: utf-8 -*-
"""魔兽世界面板单测：wow/page.py 各接口（桩掉 astrbot，不联网）。

    python tests/test_wow_panel.py
全绿打印 OK。
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import types

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_ROOT)


class _Logger:
    def info(self, *a, **k):
        pass

    warning = error = debug = info


def _install_astrbot_stub():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api


_install_astrbot_stub()

from wow import page as page_mod  # noqa: E402
from wow import webmatrix as wm  # noqa: E402
from wow.groups import GroupNameResolver  # noqa: E402


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


def with_request(req):
    page_mod.request = req


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


class FakePlatformInst:
    """平台实例桩：meta() 同时给出实例 id 与适配器类型名（现场是 napcat/aiocqhttp）。"""

    def __init__(self, platform_id, adapter="aiocqhttp"):
        self._pid = platform_id
        self._adapter = adapter

    def meta(self):
        return types.SimpleNamespace(id=self._pid, name=self._adapter)


class FakePlugin:
    def __init__(self, data_dir, platform_insts=None, **cfg):
        self.config = FakeConfig(**cfg)
        self.groups = GroupNameResolver(os.path.join(data_dir, "groups.json"))
        self.groups.load()
        self._last_news_check = 0.0
        self._last_punish_check = 0.0
        self._scheduler_task = types.SimpleNamespace()
        self.refresh_calls = []
        self._dir = data_dir
        self._insts = list(platform_insts or [])
        self._data_dir_path = lambda: __import__("pathlib").Path(data_dir)

    async def refresh_group_names(self, force=False, interval=300):
        self.refresh_calls.append(force)
        return 4

    # 与 main.py 里的实现一致：页面靠这两个方法认平台
    def _platform_instances(self):
        return [(inst.meta().id, inst.meta().name) for inst in self._insts]

    def _bare_id_platform(self):
        insts = self._platform_instances()
        for pid, ptype in insts:
            if ptype == "aiocqhttp":
                return pid
        return insts[0][0] if insts else "aiocqhttp"


def make_case(platform_insts=None, **cfg):
    data_dir = tempfile.mkdtemp(prefix="wow-panel-")
    plugin = FakePlugin(data_dir, platform_insts=platform_insts, **cfg)
    ctrl = page_mod.WowPageController(None, plugin)
    return plugin, ctrl, data_dir


def run(coro):
    return asyncio.run(coro)


class FakeContext:
    def __init__(self):
        self.routes = []

    def register_web_api(self, path, handler, methods, desc):
        self.routes.append((path, handler, tuple(methods), desc))


# ---------------------------------------------------------------------------
# 路由与元信息
# ---------------------------------------------------------------------------


def test_page_module_without_astrbot_web():
    assert page_mod._HAS_WEB_API is False
    resp = page_mod.WowPageController._ok({"a": 1}, "hi")
    assert resp["data"]["status"] == "ok" and resp["data"]["message"] == "hi"
    assert page_mod.WowPageController._err("x", 500)["status_code"] == 500


def test_routes_registered():
    ctx = FakeContext()
    ctrl = page_mod.WowPageController(ctx, None)
    ctrl.register_routes()
    paths = [p for p, *_ in ctx.routes]
    for suffix in (
        "/page/meta",
        "/page/status",
        "/page/groups",
        "/page/groups/save",
        "/page/groups/dedupe",
        "/page/groups/rename",
        "/page/settings/save",
        "/page/data",
    ):
        assert f"/astrbot_plugin_wow{suffix}" in paths, suffix
    assert all(p.startswith("/astrbot_plugin_wow/") for p in paths)


def test_meta_lists_columns_and_defaults():
    _, ctrl, _ = make_case()
    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_meta()))
    assert ok
    assert [c["key"] for c in data["columns"]] == list(wm.GROUP_LIST_KEYS)
    assert data["columns"][0]["label"] == "魔兽新闻"
    assert data["limits"]["max_per_list"] == wm.MAX_UMOS_PER_LIST
    assert data["defaults"]["reset_time"] == "06:50"
    assert [m["value"] for m in data["modifiers"]["markdown_modes"]] == ["all", "whitelist", "blacklist"]
    assert [d["label"] for d in data["modifiers"]["weekdays"]][0] == "周一"


# ---------------------------------------------------------------------------
# 群 × 功能 矩阵
# ---------------------------------------------------------------------------


def test_groups_matrix_with_labels_and_refresh():
    plugin, ctrl, _ = make_case(
        news_groups=["1001", "napcat:GroupMessage:1002"], reset_groups=["1001"]
    )
    plugin.groups.remember("1001", group_name="魔兽交流群")
    plugin.groups.remember("napcat:GroupMessage:1002", group_name="活动群")
    plugin.groups.remember("napcat:GroupMessage:3003", group_name="没配任何功能的群")

    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_groups()))
    assert ok and plugin.refresh_calls == []
    by_umo = {r["umo"]: r for r in data["rows"]}
    assert by_umo["1001"]["flags"]["news_groups"] is True
    assert by_umo["1001"]["flags"]["reset_groups"] is True
    assert by_umo["1001"]["count"] == 2
    assert by_umo["napcat:GroupMessage:3003"]["count"] == 0
    # summary 统计的是「配置里」的内容：只认 1001 / 1002，缓存里多出来的群不计入
    assert data["summary"]["groups"] == 2
    assert data["summary"]["links"] == 3
    # 群名 + 群号都能取到（面板显示用）
    assert by_umo["1001"]["label"] == "魔兽交流群（1001）"
    assert by_umo["1001"]["group_id"] == "1001"
    # 有功能的行排在前面
    assert data["rows"][0]["umo"] == "1001"

    with_request(FakeRequest(query={"refresh": "1"}))
    ok, data, _ = unwrap(run(ctrl.get_groups()))
    assert ok and data["refreshed"] == 4 and plugin.refresh_calls == [True]


def test_save_groups_writes_all_lists():
    plugin, ctrl, _ = make_case(news_groups=["1001"])
    plugin.groups.remember("1001", group_name="魔兽交流群")
    plugin.groups.remember("napcat:GroupMessage:1002", group_name="活动群")
    rows = [
        {
            "umo": "1001",
            "flags": {"news_groups": True, "reset_groups": False, "pet_push_groups": True},
        },
        {
            "umo": "napcat:GroupMessage:1002",
            "flags": {"news_groups": True, "festival_push_groups": True},
        },
    ]
    with_request(FakeRequest(body={"rows": rows}, method="POST"))
    ok, data, msg = unwrap(run(ctrl.save_groups()))
    assert ok
    assert plugin.config["news_groups"] == ["1001", "napcat:GroupMessage:1002"]
    assert plugin.config["pet_push_groups"] == ["1001"]
    assert plugin.config["festival_push_groups"] == ["napcat:GroupMessage:1002"]
    assert plugin.config["reset_groups"] == []
    assert plugin.config.save_count == 1
    changes = {c["key"]: c for c in data["changes"]}
    assert [c["umo"] for c in changes["news_groups"]["added"]] == ["napcat:GroupMessage:1002"]
    assert [c["umo"] for c in changes["pet_push_groups"]["added"]] == ["1001"]
    assert "festival_push_groups" in changes
    assert "已保存" in msg


def test_save_groups_validation_and_diff():
    plugin, ctrl, _ = make_case(news_groups=["1001", "1002"])
    with_request(FakeRequest(body={"rows": "x"}, method="POST"))
    ok, _, msg = unwrap(run(ctrl.save_groups()))
    assert not ok and "rows" in msg

    too_many = [
        {"umo": str(i), "flags": {"news_groups": True}}
        for i in range(wm.MAX_UMOS_PER_LIST + 1)
    ]
    with_request(FakeRequest(body={"rows": too_many}, method="POST"))
    ok, _, msg = unwrap(run(ctrl.save_groups()))
    assert not ok and "最多" in msg
    assert plugin.config.save_count == 0  # 没落盘

    # 正常保存：移除 1002（前端会把没勾选的行也提交上来）
    with_request(
        FakeRequest(
            body={
                "rows": [
                    {"umo": "1001", "flags": {"news_groups": True}},
                    {"umo": "1002", "flags": {"news_groups": False}},
                ]
            },
            method="POST",
        )
    )
    ok, data, _ = unwrap(run(ctrl.save_groups()))
    assert ok
    changes = {c["key"]: c for c in data["changes"]}
    assert [c["umo"] for c in changes["news_groups"]["removed"]] == ["1002"]


# ---------------------------------------------------------------------------
# 平台（实例 id vs 适配器类型名）与整理
# ---------------------------------------------------------------------------

# 现场真实平台：OneBot 实例 id=napcat（类型 aiocqhttp），QQ 官方实例 id=default_102737249
LIVE_INSTS = [
    FakePlatformInst("napcat", "aiocqhttp"),
    FakePlatformInst("default_102737249", "qq_official"),
]
OPEN_A = "default_102737249:GroupMessage:00EDF05CAE59A4BFD64122A1825A5073"


def test_groups_rows_keep_official_open_id_and_platform_info():
    """回归：官方机器人（qq_official）的群 openid 必须带勾选显示，且标出平台。"""
    plugin, ctrl, _ = make_case(
        platform_insts=LIVE_INSTS,
        news_groups=[OPEN_A, "napcat:GroupMessage:723978808"],
        reset_groups=[OPEN_A],
        punish_notify_groups=["aiocqhttp:GroupMessage:723978808"],
        markdown_groups=["1001"],
    )
    plugin.groups.remember("napcat:GroupMessage:723978808", group_name="集合石插件_开心快乐版")
    plugin.groups.remember("1001", group_name="魔兽交流群")
    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_groups()))
    assert ok
    by_umo = {r["umo"]: r for r in data["rows"]}
    # 官方群：勾选如实显示（以前整行退化成缓存行，看起来「都没勾选」）
    assert by_umo[OPEN_A]["flags"]["news_groups"] is True
    assert by_umo[OPEN_A]["flags"]["reset_groups"] is True
    assert by_umo[OPEN_A]["count"] == 2
    assert by_umo[OPEN_A]["platform_state"] == "id"
    assert by_umo[OPEN_A]["reachable"] is True
    assert by_umo[OPEN_A]["platform_text"] == "default_102737249"
    assert by_umo[OPEN_A]["platform_type"] == "qq_official"
    # 同一群号的「类型名写法」与「实例 id 写法」是两行，各自标明会走哪个实例
    dead = by_umo["aiocqhttp:GroupMessage:723978808"]
    live = by_umo["napcat:GroupMessage:723978808"]
    assert dead["platform_state"] == "type" and dead["reachable"] is True
    assert dead["platform_text"] == "aiocqhttp → napcat"
    assert live["platform_state"] == "id" and live["platform_text"] == "napcat"
    # 裸群号：说明会补到哪个实例上
    assert by_umo["1001"]["platform_state"] == "bare"
    assert by_umo["1001"]["platform_text"] == "裸群号 → napcat"
    # 统计 + 定时任务的「N 个群」都要算上官方群
    assert data["summary"]["groups"] == 4
    assert data["summary"]["per_key"]["news_groups"] == 2
    assert {i["id"] for i in data["instances"]} == {"napcat", "default_102737249"}
    assert [i["id"] for i in data["instances"] if i["bare_id"]] == ["napcat"]
    plats = {p["platform"]: p for p in data["platforms"]}
    assert plats["default_102737249"]["count"] == 1
    assert plats["aiocqhttp"]["state"] == "type"
    assert data["dead"] == []
    assert [d["group_id"] for d in data["duplicates"]] == ["723978808"]


def test_groups_marks_unreachable_platform():
    _, ctrl, _ = make_case(platform_insts=LIVE_INSTS, news_groups=["old_bot:GroupMessage:555"])
    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_groups()))
    assert ok
    row = data["rows"][0]
    assert row["platform_state"] == "unknown"
    assert row["reachable"] is False
    assert row["platform_text"] == "old_bot（实例不存在）"
    assert data["dead"] == [
        {"umo": "old_bot:GroupMessage:555", "platform": "old_bot", "label": "群 555"}
    ]


def test_save_groups_keeps_targets_the_panel_did_not_submit():
    """前端没提交上来的目标不能被一次「保存」静默删掉（现场曾整批丢过）。"""
    plugin, ctrl, _ = make_case(
        platform_insts=LIVE_INSTS,
        news_groups=[OPEN_A, "napcat:GroupMessage:723978808"],
    )
    with_request(
        FakeRequest(
            body={
                "rows": [
                    {"umo": "napcat:GroupMessage:723978808", "flags": {"news_groups": True}}
                ]
            },
            method="POST",
        )
    )
    ok, data, msg = unwrap(run(ctrl.save_groups()))
    assert ok
    assert plugin.config["news_groups"] == ["napcat:GroupMessage:723978808", OPEN_A]
    assert data["kept"] == [OPEN_A]
    assert "保留了 1 条" in msg

    # 用户真的取消勾选（行提交了但没勾）→ 该删就删
    with_request(
        FakeRequest(
            body={
                "rows": [
                    {"umo": "napcat:GroupMessage:723978808", "flags": {"news_groups": True}},
                    {"umo": OPEN_A, "flags": {"news_groups": False}},
                ]
            },
            method="POST",
        )
    )
    ok, data, _ = unwrap(run(ctrl.save_groups()))
    assert ok
    assert plugin.config["news_groups"] == ["napcat:GroupMessage:723978808"]
    assert data["kept"] == []


def test_dedupe_groups_rewrites_and_merges():
    plugin, ctrl, _ = make_case(
        platform_insts=LIVE_INSTS,
        news_groups=["napcat:GroupMessage:723978808", OPEN_A],
        punish_notify_groups=["aiocqhttp:GroupMessage:723978808", OPEN_A],
        markdown_groups=[
            "aiocqhttp:GroupMessage:723978808",
            "napcat:GroupMessage:723978808",
        ],
        reset_groups=["old_bot:GroupMessage:555"],
    )
    with_request(FakeRequest(body={}, method="POST"))
    ok, data, msg = unwrap(run(ctrl.dedupe_groups()))
    assert ok
    # 写法换掉了，勾选没变（官方群仍在处罚通报里）
    assert plugin.config["punish_notify_groups"] == ["napcat:GroupMessage:723978808", OPEN_A]
    assert plugin.config["markdown_groups"] == ["napcat:GroupMessage:723978808"]
    assert plugin.config["news_groups"] == ["napcat:GroupMessage:723978808", OPEN_A]
    assert plugin.config["reset_groups"] == ["old_bot:GroupMessage:555"]  # 救不了的留着
    assert plugin.config.save_count == 1
    assert set(data["changed"]) == {"punish_notify_groups", "markdown_groups"}
    actions = [r["action"] for r in data["report"]]
    assert "type" in actions and "merge" in actions and "unknown" in actions
    assert [u["umo"] for u in data["unreachable"]] == ["old_bot:GroupMessage:555"]
    assert "改写" in msg and "合并" in msg and "实例不存在" in msg

    # 整理过了再点一次：不写盘
    with_request(FakeRequest(body={}, method="POST"))
    ok, data, msg = unwrap(run(ctrl.dedupe_groups()))
    assert ok and data["changed"] == [] and "没有需要整理" in msg
    assert plugin.config.save_count == 1

    # 配置不可用 → 返回错误而不是抛异常
    ok2, _, msg2 = unwrap(run(page_mod.WowPageController(None, None).dedupe_groups()))
    assert not ok2 and "配置" in msg2



def test_rename_group_sets_and_clears_note():
    """官方平台的群拿不到群名，只能手填备注（面板 ✎ 按钮）。"""
    plugin, ctrl, _ = make_case(platform_insts=LIVE_INSTS, news_groups=[OPEN_A])
    with_request(FakeRequest(body={"umo": OPEN_A, "name": "公熊猫粉丝团"}, method="POST"))
    ok, data, msg = unwrap(run(ctrl.rename_group()))
    assert ok
    assert plugin.groups.name_of(OPEN_A) == "公熊猫粉丝团"
    assert plugin.groups.get(OPEN_A)["source"] == "manual"
    assert data["label"] == "公熊猫粉丝团（00EDF05CAE59A4BFD64122A1825A5073）"
    assert "已保存" in msg

    # 平台后来报来的名字不许覆盖手填备注
    plugin.groups.remember(OPEN_A, group_name="平台改名", source="api")
    assert plugin.groups.name_of(OPEN_A) == "公熊猫粉丝团"

    # 面板行上能读到备注名（行首显示的就是它）
    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_groups()))
    assert {r["umo"]: r for r in data["rows"]}[OPEN_A]["group_name"] == "公熊猫粉丝团"

    # 清空备注
    with_request(FakeRequest(body={"umo": OPEN_A, "name": ""}, method="POST"))
    ok, data, msg = unwrap(run(ctrl.rename_group()))
    assert ok and "已清空" in msg
    # 参数校验
    with_request(FakeRequest(body={"umo": "坏的", "name": "x"}, method="POST"))
    ok, _, msg = unwrap(run(ctrl.rename_group()))
    assert not ok and "umo" in msg
    with_request(FakeRequest(body={"umo": OPEN_A, "name": "x" * 41}, method="POST"))
    ok, _, msg = unwrap(run(ctrl.rename_group()))
    assert not ok and "40" in msg
    # 群名缓存不可用（插件没起来）→ 报错而不是抛异常
    ok2, _, msg2 = unwrap(run(page_mod.WowPageController(None, None).rename_group()))
    assert not ok2 and "群名" in msg2


# ---------------------------------------------------------------------------
# 标量设置
# ---------------------------------------------------------------------------


def test_save_settings_ok_and_validation():
    plugin, ctrl, _ = make_case(reset_time="06:50", festival_push_time="07:05", weekly_report_day=3)
    with_request(
        FakeRequest(
            body={
                "reset_time": "7:30",  # 容忍不补零，保存时归一
                "festival_push_time": "08:00",
                "weekly_report_day": 5,
                "markdown_group_mode": "whitelist",
            },
            method="POST",
        )
    )
    ok, data, msg = unwrap(run(ctrl.save_settings()))
    assert ok
    assert plugin.config["reset_time"] == "07:30"
    assert plugin.config["festival_push_time"] == "08:00"
    assert plugin.config["weekly_report_day"] == 5
    assert plugin.config["markdown_group_mode"] == "whitelist"
    assert data["weekly_report_day"] == 5 and "已保存" in msg
    assert plugin.config.save_count == 1

    for body, needle in (
        ({"reset_time": "25:00"}, "HH:MM"),
        ({"festival_push_time": "8点"}, "HH:MM"),
        ({"weekly_report_day": 9}, "1-7"),
        ({"weekly_report_day": "x"}, "1-7"),
        ({"markdown_group_mode": "nope"}, "Markdown"),
    ):
        with_request(FakeRequest(body=body, method="POST"))
        ok, _, msg = unwrap(run(ctrl.save_settings()))
        assert not ok and needle in msg, (body, msg)


def test_save_settings_keeps_unsent_fields():
    plugin, ctrl, _ = make_case(
        reset_time="06:50", festival_push_time="07:05", weekly_report_day=3,
        markdown_group_mode="all",
    )
    with_request(FakeRequest(body={"markdown_group_mode": "blacklist"}, method="POST"))
    ok, data, _ = unwrap(run(ctrl.save_settings()))
    assert ok
    assert plugin.config["reset_time"] == "06:50"
    assert plugin.config["festival_push_time"] == "07:05"
    assert plugin.config["weekly_report_day"] == 3
    assert data["markdown_group_mode"] == "blacklist"


# ---------------------------------------------------------------------------
# 状态与数据
# ---------------------------------------------------------------------------


def test_status_schedule_and_settings():
    plugin, ctrl, _ = make_case(
        reset_groups=["1001"], news_groups=["1001"], punish_auto_fetch=True
    )
    plugin._last_news_check = time.time() - 60  # 1 分钟前查过 → 还有 4 分钟
    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_status()))
    assert ok
    rows = {r["key"]: r for r in data["schedule"]["rows"]}
    assert rows["reset"]["enabled"] is True
    assert rows["news"]["enabled"] is True
    assert 200 <= rows["news"]["remaining_sec"] <= 300
    assert rows["news"]["last_text"] not in ("", "插件启动后还没跑过")
    assert rows["punish_fetch"]["enabled"] is True
    assert rows["punish_fetch"]["last_text"] == "插件启动后还没跑过"
    assert data["running"] is True
    assert data["settings"]["weekly_report_day"] == 3
    assert "now_text" in data["schedule"]


def test_prices_info_reads_file():
    plugin, ctrl, data_dir = make_case()
    path = os.path.join(data_dir, "prices.json")
    day0 = 1577808000
    newest = 2459
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "realm": "白银之手",
                "scanned_at": 1790319432,
                "day0": day0,
                "newest_day": newest,
                "items": [{"i": 1, "n": "测试物品", "p": 100}],
            },
            fh,
            ensure_ascii=False,
        )
    info = ctrl._prices_info()
    assert info["exists"] is True
    assert info["items"] == 1 and info["realm"] == "白银之手"
    assert info["scanned_text"] != "从未"
    assert info["newest_text"] == "2026-09-25"
    assert isinstance(info["stale_days"], int) and info["stale_days"] >= 0
    assert info["size"] > 0

    # 文件不存在 / 内容坏掉都要能兜住
    os.unlink(path)
    assert ctrl._prices_info()["exists"] is False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ 不是 json")
    info = ctrl._prices_info()
    assert info["exists"] is True and info["items"] == 0

    # 没有数据目录（store 未初始化）也不炸
    ctrl2 = page_mod.WowPageController(None, types.SimpleNamespace(config={}))
    assert ctrl2._prices_info()["exists"] is False


def test_data_endpoint_inventory():
    plugin, ctrl, data_dir = make_case()
    os.makedirs(os.path.join(data_dir, "punish"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "cache"), exist_ok=True)
    with open(os.path.join(data_dir, "punish", "2026-09-25.xlsx"), "wb") as fh:
        fh.write(b"x" * 128)
    with open(os.path.join(data_dir, "cache", "a.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")

    with_request(FakeRequest())
    ok, data, _ = unwrap(run(ctrl.get_data()))
    assert ok
    assert data["punish"]["count"] == 1
    assert data["punish"]["files"][0]["name"] == "2026-09-25.xlsx"
    assert data["cache"]["files"] == 1 and data["cache"]["bytes"] == 2
    # store 未初始化时榜单/开箱要显示「不可用」而不是抛异常
    assert data["board"]["available"] is False
    assert data["gacha"]["available"] is False
    assert data["data_dir"] == data_dir


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
