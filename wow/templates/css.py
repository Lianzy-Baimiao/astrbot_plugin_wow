# -*- coding: utf-8 -*-
"""html_render 公共工具：物品品质色。

注：各模板已自带 <style>，不再注入公共 CSS。
"""


def quality_color(q: int) -> str:
    return {0: "#9D9D9D", 1: "#FFFFFF", 2: "#1EFF00", 3: "#0070DD", 4: "#A335EE", 5: "#FF8000", 6: "#E268A8"}.get(q, "#FFFFFF")