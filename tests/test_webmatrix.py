# -*- coding: utf-8 -*-
"""wow/webmatrix.py 单测：矩阵双向转换 / umo 清洗 / 定时任务下次触发（不依赖 astrbot）。

    python tests/test_webmatrix.py
全绿打印 OK。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wow import webmatrix as wm  # noqa: E402


# ---------------- 时间 ----------------


def test_parse_hhmm():
    assert wm.parse_hhmm("06:50") == (6, 50)
    assert wm.parse_hhmm(" 7:5 ") == (7, 5)
    assert wm.parse_hhmm("00:00") == (0, 0)
    assert wm.parse_hhmm("23:59") == (23, 59)
    # 非法值必须报不出来（不能像 reset_svc 那样静默回落）
    assert wm.parse_hhmm("24:00") is None
    assert wm.parse_hhmm("06:60") is None
    assert wm.parse_hhmm("6点50") is None
    assert wm.parse_hhmm("") is None
    assert wm.parse_hhmm(None) is None
    assert wm.parse_hhmm(650) is None


def test_format_hhmm():
    assert wm.format_hhmm(6, 50) == "06:50"
    assert wm.format_hhmm(7, 5) == "07:05"
    assert wm.format_hhmm(0, 0) == "00:00"


def test_next_daily():
    # 2026-09-26 是周六
    now = dt.datetime(2026, 9, 26, 10, 0)
    assert wm.next_daily(now, 12, 0) == dt.datetime(2026, 9, 26, 12, 0)
    assert wm.next_daily(now, 7, 5) == dt.datetime(2026, 9, 27, 7, 5)  # 今天已过 → 明天
    assert wm.next_daily(now, 10, 0) == dt.datetime(2026, 9, 27, 10, 0)  # 正好等于 → 顺延


def test_next_weekly():
    now = dt.datetime(2026, 9, 26, 10, 0)  # 周六
    # 周四（0=周一 → 3）
    assert wm.next_weekly(now, 3, 6, 50) == dt.datetime(2026, 10, 1, 6, 50)
    # 周三 20:00（本周三已过）
    assert wm.next_weekly(now, 2, 20, 0) == dt.datetime(2026, 9, 30, 20, 0)
    # 周六同一天但时间未到 → 今天
    assert wm.next_weekly(now, 5, 20, 0) == dt.datetime(2026, 9, 26, 20, 0)
    # 周六同一天且时间已到 → 下周六
    assert wm.next_weekly(now, 5, 9, 0) == dt.datetime(2026, 10, 3, 9, 0)


def test_humanize_delta():
    assert wm.humanize_delta(dt.timedelta(seconds=30)) == "30 秒后"
    assert wm.humanize_delta(dt.timedelta(minutes=5)) == "5 分钟后"
    assert wm.humanize_delta(dt.timedelta(hours=2)) == "2 小时后"
    assert wm.humanize_delta(dt.timedelta(hours=21, minutes=5)) == "21 小时 5 分钟后"
    assert wm.humanize_delta(dt.timedelta(days=4)) == "4 天后"
    assert wm.humanize_delta(dt.timedelta(seconds=0)) == "即将"
    assert wm.humanize_delta(dt.timedelta(seconds=-10)) == "即将"


# ---------------- umo 清洗 ----------------


def test_normalize_umo():
    assert wm.normalize_umo("339466990") == "339466990"
    assert wm.normalize_umo(339466990) == "339466990"
    assert wm.normalize_umo("napcat:GroupMessage:339466990") == "napcat:GroupMessage:339466990"
    assert wm.normalize_umo("  napcat:GroupMessage:339466990  ") == "napcat:GroupMessage:339466990"
    # 会话号不是纯数字也必须留下：QQ 官方机器人的群 id 是 32 位 openid，
    # 按 isdigit 过滤会把官方群整批丢掉（面板看不到勾选、保存还会删配置）。
    open_id = "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F"
    assert wm.normalize_umo(open_id) == open_id
    assert wm.normalize_umo("napcat:GroupMessage:abc") == "napcat:GroupMessage:abc"
    # Telegram 超群 id 是负数
    assert wm.normalize_umo("telegram:GroupMessage:-1001234567890") == (
        "telegram:GroupMessage:-1001234567890"
    )
    # 非法：段数不够、空段、空、含中文的裸值、会话号里有空格、超长
    assert wm.normalize_umo("napcat:339466990") == ""
    assert wm.normalize_umo("napcat:GroupMessage:") == ""
    assert wm.normalize_umo("::339466990") == ""
    assert wm.normalize_umo("napcat:GroupMessage:有中文") == ""
    assert wm.normalize_umo("napcat:GroupMessage:1 2") == ""
    assert wm.normalize_umo("") == ""
    assert wm.normalize_umo(None) == ""
    assert wm.normalize_umo("群号339") == ""
    assert wm.normalize_umo("9" * 201) == ""


def test_clean_umo_list():
    got = wm.clean_umo_list(["1001", "1001", "坏的", "napcat:GroupMessage:1002", ""])
    assert got == ["1001", "napcat:GroupMessage:1002"]
    assert wm.clean_umo_list(None) == []
    assert len(wm.clean_umo_list([str(i) for i in range(500)])) == wm.MAX_UMOS_PER_LIST


# ---------------- 平台写法：实例 id vs 适配器类型名 ----------------

# 现场（2026-09）真实平台：OneBot 的实例 id 是 napcat（适配器类型 aiocqhttp），
# QQ 官方机器人的实例 id 是 default_102737249（适配器类型 qq_official）。
INSTANCES = [("napcat", "aiocqhttp"), ("default_102737249", "qq_official")]


def test_split_umo_and_predicates():
    assert wm.split_umo("napcat:GroupMessage:1001") == ("napcat", "GroupMessage", "1001")
    assert wm.split_umo("1001") == ("", "", "1001")
    assert wm.split_umo("") == ("", "", "")
    assert wm.platform_of("napcat:GroupMessage:1001") == "napcat"
    assert wm.platform_of("1001") == ""
    assert wm.session_of("napcat:GroupMessage:1001") == "1001"
    assert wm.session_of("1001") == "1001"
    assert wm.is_bare("1001") is True
    assert wm.is_bare("napcat:GroupMessage:1001") is False
    assert wm.is_bare("") is False
    # 两段简写能拆出来，但归一化阶段仍然要求三段
    assert wm.split_umo("napcat:1001") == ("napcat", "1001", "")
    assert wm.normalize_umo("napcat:1001") == ""


def test_normalize_instances_and_alias_map():
    insts = wm.normalize_instances(
        [
            ("napcat", "aiocqhttp"),
            ["default_102737249", "qq_official"],
            {"id": "webchat", "type": "webchat"},  # id 与类型同名，不进取别名表
            ("napcat", "aiocqhttp"),  # 重复按 id 去重
            "",
            None,
        ]
    )
    assert insts == [
        ("napcat", "aiocqhttp"),
        ("default_102737249", "qq_official"),
        ("webchat", "webchat"),
    ]
    assert wm.platform_alias_map(insts) == {
        "aiocqhttp": "napcat",
        "qq_official": "default_102737249",
    }
    assert wm.platform_type_map(insts)["napcat"] == "aiocqhttp"
    assert wm.normalize_instances(None) == []


def test_resolve_platform():
    assert wm.resolve_platform("napcat", INSTANCES) == ("napcat", "id")
    # 适配器类型名——现场「aiocqhttp:」写法的坑：send_message 只认实例 id
    assert wm.resolve_platform("aiocqhttp", INSTANCES) == ("napcat", "type")
    assert wm.resolve_platform("qq_official", INSTANCES) == ("default_102737249", "type")
    assert wm.resolve_platform("old_bot", INSTANCES) == ("", "unknown")  # 旧实例名/拼错
    assert wm.resolve_platform("", INSTANCES) == ("", "bare")
    assert wm.resolve_platform("napcat", []) == ("", "unknown")  # 探不到平台不许瞎猜


def test_rewrite_umo():
    # 已经是实例 id → 原样
    assert wm.rewrite_umo("napcat:GroupMessage:723978808", INSTANCES, "napcat") == (
        "napcat:GroupMessage:723978808",
        "id",
    )
    # QQ 官方群的 openid 原样保留（不能补成 QQ 群号）
    open_id = "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F"
    assert wm.rewrite_umo(open_id, INSTANCES, "napcat") == (open_id, "id")
    # 类型名 → 实例 id
    assert wm.rewrite_umo("aiocqhttp:GroupMessage:723978808", INSTANCES, "napcat") == (
        "napcat:GroupMessage:723978808",
        "type",
    )
    assert wm.rewrite_umo("qq_official:GroupMessage:ABC123", INSTANCES, "napcat") == (
        "default_102737249:GroupMessage:ABC123",
        "type",
    )
    # 裸群号 → 补默认平台
    assert wm.rewrite_umo("1001", INSTANCES, "napcat") == ("napcat:GroupMessage:1001", "bare")
    # 拿不到默认平台 / 平台段认不出来 → 原样 + 状态说明
    assert wm.rewrite_umo("1001", INSTANCES, "") == ("1001", "plain")
    assert wm.rewrite_umo("telegram:GroupMessage:-100123", INSTANCES, "napcat") == (
        "telegram:GroupMessage:-100123",
        "unknown",
    )
    assert wm.rewrite_umo("", INSTANCES, "napcat") == ("", "")


def test_rewrite_umos_reports_and_merges():
    umos, report = wm.rewrite_umos(
        [
            "aiocqhttp:GroupMessage:723978808",
            "napcat:GroupMessage:723978808",  # 与上一条改写后撞车
            "1002",
            "napcat:GroupMessage:1002",  # 与上一条补全后撞车
        ],
        INSTANCES,
        "napcat",
    )
    assert umos == ["napcat:GroupMessage:723978808", "napcat:GroupMessage:1002"]
    actions = [(r["from"], r["action"]) for r in report]
    assert ("aiocqhttp:GroupMessage:723978808", "type") in actions
    assert ("napcat:GroupMessage:723978808", "merge") in actions
    assert ("1002", "bare") in actions
    assert ("napcat:GroupMessage:1002", "merge") in actions
    # 坏数据不进结果，但也不能把整批带崩
    assert wm.rewrite_umos(["", None, "坏值"], INSTANCES, "napcat") == ([], [])
    assert [r["action"] for r in wm.rewrite_umos(["old_bot:GroupMessage:5"], INSTANCES)[1]] == [
        "unknown"
    ]


def test_unreachable_and_platform_stats():
    lists = {
        "news_groups": [
            "napcat:GroupMessage:723978808",
            "old_bot:GroupMessage:555",  # 平台实例不存在
            "1001",  # 裸群号
            "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F",
        ],
        "pet_push_groups": ["napcat:GroupMessage:723978808"],
    }
    assert wm.all_umos(lists) == [
        "napcat:GroupMessage:723978808",
        "old_bot:GroupMessage:555",
        "1001",
        "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F",
    ]
    assert [item["umo"] for item in wm.unreachable_umos(wm.all_umos(lists), INSTANCES)] == [
        "old_bot:GroupMessage:555"
    ]
    stats = {item["platform"]: item for item in wm.platform_stats(lists, INSTANCES)}
    assert stats["napcat"] == {"platform": "napcat", "count": 1, "state": "id"}
    assert stats["default_102737249"]["state"] == "id"
    assert stats["old_bot"]["state"] == "unknown"
    assert stats[wm.BARE_LABEL] == {"platform": wm.BARE_LABEL, "count": 1, "state": "bare"}
    assert wm.platform_stats({}, INSTANCES) == []


def test_duplicate_targets_and_group_targets():
    lists = {
        "news_groups": ["napcat:GroupMessage:723978808"],
        "punish_notify_groups": ["aiocqhttp:GroupMessage:723978808"],
        "markdown_groups": [
            "aiocqhttp:GroupMessage:723978808",
            "napcat:GroupMessage:723978808",
        ],
        "reset_groups": ["napcat:GroupMessage:1001"],
    }
    assert wm.duplicate_targets(lists) == [
        {
            "group_id": "723978808",
            "umos": ["napcat:GroupMessage:723978808", "aiocqhttp:GroupMessage:723978808"],
        }
    ]
    assert wm.duplicate_targets({"news_groups": ["1001", "1002"]}) == []
    # 官方 openid 与 OneBot 数字群号是两个会话，不能被当成「同一个群写了两遍」
    mixed = wm.all_umos(
        {
            "news_groups": [
                "napcat:GroupMessage:723978808",
                "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F",
            ]
        }
    )
    assert len(wm.group_targets(mixed)) == 2
    # 同一个群号挂在两个**真实**平台上：报出来给人看，但不去自动合并
    two_plats = {"news_groups": ["napcat:GroupMessage:555", "webchat:GroupMessage:555"]}
    assert len(wm.duplicate_targets(two_plats)) == 1
    merged, _ = wm.normalize_lists(two_plats, INSTANCES + [("webchat", "webchat")], "napcat")
    assert merged["news_groups"] == ["napcat:GroupMessage:555", "webchat:GroupMessage:555"]
    assert wm.group_targets(["1001", "1001", "坏的"]) == [{"group_id": "1001", "umos": ["1001"]}]


def test_normalize_lists_fixes_dead_prefix_and_merges():
    """现场那套配置：同一群号写了 napcat / aiocqhttp 两种平台，整理后只剩一条且勾选不丢。"""
    open_gid = "default_102737249:GroupMessage:00EDF05CAE59A4BFD64122A1825A5073"
    lists = {
        "news_groups": [open_gid, "napcat:GroupMessage:723978808"],
        "punish_notify_groups": ["aiocqhttp:GroupMessage:723978808", open_gid],
        "markdown_groups": ["aiocqhttp:GroupMessage:723978808"],
        "reset_groups": ["old_bot:GroupMessage:555"],
    }
    cleaned, report = wm.normalize_lists(lists, INSTANCES, "napcat")
    assert cleaned["news_groups"] == [open_gid, "napcat:GroupMessage:723978808"]
    assert cleaned["punish_notify_groups"] == ["napcat:GroupMessage:723978808", open_gid]
    assert cleaned["markdown_groups"] == ["napcat:GroupMessage:723978808"]
    assert cleaned["reset_groups"] == ["old_bot:GroupMessage:555"]  # 救不了的原样留着
    by_key_action = {(r["key"], r["action"]) for r in report}
    assert ("punish_notify_groups", "type") in by_key_action
    assert ("markdown_groups", "type") in by_key_action
    assert ("reset_groups", "unknown") in by_key_action
    assert all("label" in r for r in report)
    # 官方群在处罚通报里没被删掉（只换了同群号的另一条写法）
    assert cleaned["punish_notify_groups"][1] == open_gid
    assert wm.normalize_lists({}, INSTANCES)[0]["news_groups"] == []


def test_matrix_roundtrip_keeps_official_open_id_groups():
    """回归：官方机器人的 openid 群曾被 normalize_umo 丢掉（勾选显示不出来、保存还会删掉）。"""
    open_a = "default_102737249:GroupMessage:00EDF05CAE59A4BFD64122A1825A5073"
    open_b = "default_102737249:GroupMessage:21E86DB833C12870E3287DF3C5704B5F"
    lists = {
        "news_groups": [open_a, "napcat:GroupMessage:723978808"],
        "pet_push_groups": [open_b],
    }
    rows = wm.matrix_from_lists(lists)
    by_umo = {row["umo"]: row for row in rows}
    assert set(by_umo) == {open_a, "napcat:GroupMessage:723978808", open_b}
    assert by_umo[open_a]["flags"]["news_groups"] is True
    assert by_umo[open_b]["flags"]["pet_push_groups"] is True
    assert by_umo[open_b]["flags"]["news_groups"] is False
    summary = wm.matrix_summary(lists)
    assert summary["groups"] == 3 and summary["links"] == 3
    # 面板原样保存回去，官方群不能丢
    saved = wm.lists_from_matrix(rows)
    assert saved["news_groups"] == [open_a, "napcat:GroupMessage:723978808"]
    assert saved["pet_push_groups"] == [open_b]
    # 定时任务表格里的「N 个群」也要算上官方群（原来显示 1 个，实际 2 个）
    sched = {r["key"]: r for r in wm.schedule_rows(lists, dt.datetime(2026, 9, 26, 10, 0))}
    assert sched["news"]["groups"] == 2
    assert sched["pet"]["groups"] == 1



# ---------------- 矩阵 ----------------


def test_matrix_roundtrip():
    lists = {
        "news_groups": ["1001", "napcat:GroupMessage:1002"],
        "reset_groups": ["1001"],
        "wowboard_whitelist": ["napcat:GroupMessage:1002", "1003"],
    }
    rows = wm.matrix_from_lists(lists)
    assert [r["umo"] for r in rows] == ["1001", "napcat:GroupMessage:1002", "1003"]
    first = rows[0]
    assert first["flags"]["news_groups"] is True and first["flags"]["reset_groups"] is True
    assert first["flags"]["weekly_report_groups"] is False
    assert set(first["flags"]) == set(wm.GROUP_LIST_KEYS)

    back = wm.lists_from_matrix(rows)
    for key in wm.GROUP_LIST_KEYS:
        assert back[key] == wm.clean_umo_list(lists.get(key, [])), key


def test_matrix_skips_bad_entries():
    rows = wm.matrix_from_lists(
        {
            "news_groups": ["1001", "坏的", "", None, "napcat:GroupMessage:1002"],
            "reset_groups": "不是列表",
            "不认识的键": ["1001"],
        }
    )
    assert [r["umo"] for r in rows] == ["1001", "napcat:GroupMessage:1002"]
    assert wm.matrix_from_lists(None) == []


def test_lists_from_matrix_validation():
    rows = [
        {"umo": "1001", "flags": {"news_groups": True, "reset_groups": False}},
        {"umo": "1002", "flags": {"news_groups": True, "不认识的键": True}},
        {"umo": "坏的", "flags": {"news_groups": True}},
        {"umo": "1003"},  # 没有 flags → 跳过
        "不是对象",
        {"umo": "napcat:GroupMessage:1002", "flags": {"reset_groups": True}},  # 同群第二行也要合进去
    ]
    out = wm.lists_from_matrix(rows)
    assert out["news_groups"] == ["1001", "1002"]
    assert out["reset_groups"] == ["napcat:GroupMessage:1002"]
    assert out["weekly_report_groups"] == []
    assert set(out) == set(wm.GROUP_LIST_KEYS)


def test_diff_and_summary():
    old = {"news_groups": ["1001", "1002"], "reset_groups": ["1001"]}
    new = {"news_groups": ["1001", "1003"], "reset_groups": ["1001", "1002"]}
    diff = wm.diff_lists(old, new)
    assert diff["news_groups"] == {"added": ["1003"], "removed": ["1002"]}
    assert diff["reset_groups"] == {"added": ["1002"], "removed": []}
    assert "weekly_report_groups" not in diff  # 没变的不出现
    assert wm.diff_lists(old, old) == {}

    summary = wm.matrix_summary(new)
    assert summary["per_key"]["news_groups"] == 2
    assert summary["groups"] == 3  # 1001/1002/1003
    assert summary["links"] == 4


# ---------------- 定时任务 ----------------


def test_schedule_rows_disabled_without_groups():
    now = dt.datetime(2026, 9, 26, 10, 0)  # 周六
    rows = {r["key"]: r for r in wm.schedule_rows({}, now)}
    assert set(rows) == {"reset", "festival", "weekly", "news", "pet", "punish_fetch"}
    for key in ("reset", "festival", "weekly", "news", "pet"):
        assert rows[key]["enabled"] is False, key
    assert rows["reset"]["next_text"] == "2026-10-01 06:50（4 天后）"
    assert rows["festival"]["next_text"] == "2026-09-27 07:05（21 小时 5 分钟后）"
    assert rows["weekly"]["next_text"] == "2026-09-30 20:00（4 天后）"
    assert rows["news"]["next_at"] is None and rows["news"]["interval_sec"] == 300
    assert rows["punish_fetch"]["enabled"] is False


def test_schedule_rows_enabled_and_settings():
    now = dt.datetime(2026, 9, 26, 10, 0)
    cfg = {
        "reset_groups": ["1001"],
        "reset_time": "07:30",
        "festival_push_groups": ["1001", "1002"],
        "festival_push_time": "08:00",
        "weekly_report_groups": ["1001"],
        "weekly_report_day": 1,  # 周一
        "pet_push_groups": ["1001"],
        "news_groups": ["1001"],
        "punish_auto_fetch": True,
        "punish_fetch_interval": 180,  # 会被钳到最小 300
    }
    rows = {r["key"]: r for r in wm.schedule_rows(cfg, now)}
    assert rows["reset"]["enabled"] is True
    assert rows["reset"]["when"] == "周四 07:30"
    assert rows["reset"]["next_text"] == "2026-10-01 07:30（4 天后）"
    assert rows["festival"]["groups"] == 2
    assert rows["festival"]["next_text"] == "2026-09-27 08:00（22 小时后）"
    assert rows["weekly"]["when"] == "周一 20:00"
    assert rows["weekly"]["next_text"] == "2026-09-28 20:00（2 天后）"
    assert rows["news"]["enabled"] is True
    assert rows["pet"]["next_text"] == "2026-09-26 12:00（2 小时后）"
    assert rows["punish_fetch"]["enabled"] is True
    assert rows["punish_fetch"]["interval_sec"] == 300
    assert rows["punish_fetch"]["when"] == "每 5 分钟检查"


def test_schedule_rows_tolerates_bad_scalar_config():
    now = dt.datetime(2026, 9, 26, 10, 0)
    cfg = {
        "reset_groups": ["1001"],
        "reset_time": "乱写",  # 回落默认 06:50
        "festival_push_time": None,
        "weekly_report_day": "abc",  # 回落默认 周三
        "punish_fetch_interval": "x",
    }
    rows = {r["key"]: r for r in wm.schedule_rows(cfg, now)}
    assert rows["reset"]["when"] == "周四 06:50"
    assert rows["reset"]["enabled"] is True
    assert rows["festival"]["when"] == "每天 07:05"
    assert rows["weekly"]["when"] == "周三 20:00"
    assert rows["punish_fetch"]["interval_sec"] == wm.DEFAULT_PUNISH_INTERVAL


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
