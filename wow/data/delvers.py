# -*- coding: utf-8 -*-
"""内置数据表：地下堡每日饰品（5 天循环）。"""

ACCESSORIES = [
    {"name": "虚触碎片【DPS】", "days": [True, False, True, False, False]},
    {"name": "碎魂者的印记", "days": [False, False, True, False, True]},
    {"name": "朦胧的法力帷纱", "days": [False, True, False, False, True]},
    {"name": "自动化足球炸弹分发器", "days": [False, True, False, False, True]},
    {"name": "影卫的扭曲收获者", "days": [True, True, True, True, True]},
    {"name": "混乱虚空之门【坦克高输出饰品】", "days": [True, True, True, True, True]},
    {"name": "精华猎手的镜片【DPS敏智】", "days": [True, False, False, True, False]},
    {"name": "法力熔炉以太电池【治疗超模】", "days": [False, True, False, False, True]},
    {"name": "共生以太薄纱【坦克(盾)自回饰品】", "days": [True, False, False, True, False]},
    {"name": "心智溃解之祸", "days": [True, False, False, True, False]},
    {"name": "虚体精华吞噬者【DPS】", "days": [False, True, False, True, False]},
    {"name": "扭曲的法力之魂【治疗/坦克超模】", "days": [True, False, False, True, False]},
]

START_DATE = (2025, 8, 26)  # 周期"第一天"（UTC）


def day_number(dt) -> int:
    """计算当前处于 5 天周期的第几天（1-5）。"""
    import datetime as _dt
    start = _dt.datetime(START_DATE[0], START_DATE[1], START_DATE[2], tzinfo=_dt.timezone.utc)
    delta_days = (dt - start).days
    return delta_days % 5 + 1


def get_menu(dt=None) -> list[str]:
    import datetime as _dt
    if dt is None:
        dt = _dt.datetime.now(_dt.timezone.utc)
    idx = day_number(dt) - 1
    return [a["name"] for a in ACCESSORIES if a["days"][idx]]