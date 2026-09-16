# -*- coding: utf-8 -*-
"""魔兽世界综合插件（AstrBot）：16 个 ZeroBot 魔兽插件整合。

灵感来源：ZeroBot-Plugin 的 plugin/{wcl,wowinfo,wowguild,wowboard,bis,specrank,
charinfo,mpaffix,blizzardnews,wowcal,wowgacha,wowquote,wowreset,dixiabao,
ngajiexi,chishenme,wowah}（https://github.com/FloatTech/ZeroBot-Plugin）

指令触发方式：全部用 @filter.regex。AstrBot 的 @filter.command 在群聊里必须带唤醒
前缀（默认 /）或 @机器人，而原版 ZeroBot 这些插件用的是 OnRegex/OnFullMatch/
OnPrefix/OnSuffix —— 裸词即可触发。regex 过滤器不受 wake_prefix 制约，且
waking_check 会先把 / 前缀剥掉，所以同一条正则「裸词」和「/前缀」两种输入都能吃。

开机/关机/电脑状态 已拆分为独立插件 astrbot_plugin_songguo_power（松果电子开关机）。
"""

import asyncio
import importlib.util as _ilu
import math
import re
import sys
import time
from pathlib import Path

# AstrBot 以 data.plugins.<name> 模块名加载 main.py，需显式将插件目录加入 sys.path。
# 兼容不同部署方式（直接解压到 data/plugins/、或插件被放到其它根目录）。
_PLUGIN_ROOT = Path(__file__).resolve().parent


def _ensure_plugin_on_path() -> Path:
    """把含 wow/ 子包的真实插件根目录加入 sys.path，返回该根目录。"""
    candidates: list[Path] = [_PLUGIN_ROOT]
    if _PLUGIN_ROOT.name != "astrbot_plugin_wow":
        candidates.append(_PLUGIN_ROOT.parent / "astrbot_plugin_wow")
    cwd = Path.cwd()
    candidates += [
        cwd / "data" / "plugins" / "astrbot_plugin_wow",
        cwd / "astrbot_plugin_wow",
    ]
    if sys.argv:
        candidates.append(
            Path(sys.argv[0]).resolve().parent / "data" / "plugins" / "astrbot_plugin_wow"
        )
    root = None
    for cand in candidates:
        if cand is None:
            continue
        cand = cand.resolve()
        if (cand / "wow" / "__init__.py").is_file():
            root = cand
            break
    if root is None:
        root = _PLUGIN_ROOT
    p = str(root)
    if p not in sys.path:
        sys.path.insert(0, p)
    return root


_PLUGIN_ROOT = _ensure_plugin_on_path()

if _ilu.find_spec("wow") is None:
    raise RuntimeError(
        "astrbot_plugin_wow 目录不完整：找不到 wow/ 子包。"
        "请删除服务器上的 astrbot_plugin_wow 整个文件夹，"
        "再重新解压完整 zip（必须包含 wow/、wow/templates/、wow/services/、wow/data/ 等子目录）后重启 AstrBot。"
    ) from None

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from wow.const import PLUGIN_NAME
from wow.net import close_client
from wow.services import affix as affix_svc
from wow.services import bis as bis_svc
from wow.services import board as board_svc
from wow.services import charinfo as charinfo_svc
from wow.services import gacha as gacha_svc
from wow.services import guild as guild_svc
from wow.services import misc as misc_svc
from wow.services import news as news_svc
from wow.services import nga as nga_svc
from wow.services import petwq as petwq_svc
from wow.services import punish as punish_svc
try:
    from wow.services import punishfeed as punishfeed_svc
except ImportError:  # 旧版部署缺 punishfeed 模块时不整插件挂掉（容错导入约定）
    punishfeed_svc = None
    logger.warning("未找到 wow.services.punishfeed，处罚名单自动抓取不可用")
from wow.services import reset as reset_svc
from wow.services import wclfmt
from wow.store import close_stores, set_data_dir
from wow.templates.css import quality_color
from wow.wcl import get_wcl_client

try:
    from wow.data.specs import strip_arg_label
except ImportError:  # 旧版 specs.py 与新 main.py 混装部署时不许闪崩（见 lessons 第 3 条）
    logger.warning(
        "wow/data/specs.py 是旧版（缺 strip_arg_label），"
        "「饰品排行 专精 射击猎」这类菜单参数名格式本次不可用；"
        "请删除整个 astrbot_plugin_wow 目录后重新解压完整 zip。"
    )

    def strip_arg_label(s: str) -> str:
        return (s or "").strip()

TEMPLATE_DIR = _PLUGIN_ROOT / "wow" / "templates"

# ---------------------------------------------------------------------------
# 触发式：与原版 ZeroBot 的 OnRegex / OnFullMatch / OnPrefix / OnSuffix 一一对应。
#
# 带中文参数的前缀指令统一要求分隔符 (?:[\s:：]+(.+))? —— 原版 OnPrefix 会把
# 「角色扮演游戏真好玩」也当成 角色 指令，免前缀触发后这种误触发会刷屏。
# BIS / 开箱 / 红手榜 / 大米成功率 保留原版的紧贴写法（BIS火法、开箱10 要能用）。
# ---------------------------------------------------------------------------

T_WCL = r"^[Ww][Cc][Ll](?:[\s:：]+(.+))?$"
T_CHARINFO = r"^角色(?:[\s:：]+(.+))?$"
T_AFFIX = r"^(?:词缀|本周词缀)$"
T_AFFIX_NEXT = r"^下周词缀$"
T_CALENDAR = r"^日历(?:[\s:：]+(.+))?$"
T_TRINKET_RANK = r"^饰品排行(?:[\s:：]+(.+))?$"
T_BIS = r"^(?:BIS推荐|bis推荐|装备推荐|BIS|bis)[\s]*[：:]?[\s]*(.*)$"
T_SPECRANK = r"^强度榜[\s]*([Aa][Oo][Ee])?[\s]*$"
T_GUILD = r"^公会(?:[\s:：]+(.+))?$"
T_RAID_RANK = r"^团本排行[\s:：]*(.*)$"
T_ROSTER = r"^名单$"
T_ROSTER_ADD = r"^名单[\s]*添加[\s:：]*(.*)$"
T_ROSTER_DEL = r"^名单[\s]*删除[\s:：]*(.*)$"
T_BOARD = r"^榜单((?:[\s]*(?:装等|详情|刷新))*)[\s]*$"
T_WEEKLY = r"^周报$"
T_WEEKLY_PUSH = r"^周报推送[\s:：]*(开|关|状态|测试)?$"
T_CHAR_CARD = r"^查卡(?:[\s:：]+(.+))?$"
T_NEWS_FORCE = r"^魔兽新闻$"
T_NEWS = r"^魔兽新闻改$"
T_NEWS_PUSH = r"^魔兽新闻推送[\s:：]*(开|关|状态|测试)?$"
T_NEWS_STATUS = r"^魔兽新闻状态$"
T_GACHA = r"^开箱[\s:：]*(\d*)$"
T_GACHA_RANK = r"^红手榜[\s:：]*(\d*)$"
T_QUOTE = r"^(?:BOSS语录|boss语录|语录)[\s:：]*(.*)$"
T_RESET = r"^重置$"
T_RESET_REMIND = r"^重置提醒[\s:：]*(开|关|状态|测试)?$"
T_DELVER = r"^地下堡饰品$"
T_EVENT = r"^事件$"
T_EVENT_ARG = r"^事件[\s:：]+(.+)$"
T_EVENT_SUFFIX = r"^(.+?)事件$"
T_BADGE = r"^徽章$"
T_MPLUS_RATE = r"^大米成功率[\s:：]*(\d*)$"
T_MPLUS_RANK = r"^大米排行榜$"
T_EAT = r"^吃什么$"
T_TALENT = r"^(.+?)天赋$"
T_TALENT_PREFIX = r"^天赋[\s:：]*(.*)$"
T_PRICE = r"^物价(?:[\s:：]+(.+))?$"
T_FORTUNE = r"^低保$"
T_PUNISH = r"^处罚(?:[\s:：]+(.+))?$"
T_PUNISH_SYNC = r"^处罚名单更新[\s:：]*(强制|重建)?$"
T_PUNISH_NOTIFY = r"^处罚通报推送[\s:：]*(开|关|状态|测试)?$"
T_PET = r"^宠物$"
T_PET_PUSH = r"^宠物推送[\s:：]*(开|关|状态|测试)?$"
T_HELP = r"^魔兽帮助$"

_RE_CACHE: dict[str, re.Pattern] = {}

HELP_TEXT = """魔兽世界插件指令（前缀 / 可省略）
**—— 角色 / 战绩 ——**
角色 <角色名> <服务器>      角色卡
wcl <角色名> <服务器>       WCL 战绩
**—— 大秘境 ——**
词缀 / 本周词缀 / 下周词缀
大米成功率 [层数]           限时率（默认 10 层）
大米排行榜                  赛季专精排行（输出/防御/治疗）
重置                        重置倒计时 + 本周词缀
重置提醒 开/关/状态/测试     开/关/测试需管理员
**—— 装备 / 强度 ——**
BIS <专精>                  饰品Top3 + 副属性 + 种族
饰品排行 <专精>             Top15 饰品
强度榜 [aoe]                专精强度榜
地下堡饰品                  当日可获取饰品
<专精>天赋 / 天赋<专精>      如：火法天赋 / 鸟德天赋 / 天赋火法
**—— 公会 / 群榜 ——**
公会 <公会名> [服务器]
团本排行 [难度] [团本]
名单 / 名单 添加 <群友名> <角色名> <服务器> / 名单 删除 <编号>
榜单 [装等] [详情] [刷新]    刷新需管理员
周报 / 查卡 <群友名或角色名>
周报推送 开/关/状态/测试     开/关/测试需管理员
**—— 资讯 / 娱乐 ——**
魔兽新闻 / 魔兽新闻改
魔兽新闻推送 开/关/状态/测试   每5分钟检查，有更新自动推送本群（开/关/测试需管理员）
日历 [关键词] / 事件 / <版本>事件
开箱 [数量] / 红手榜 [数量]
语录 [BOSS名] / 吃什么 / 低保 / 物价 <物品1、物品2>
处罚 <角色名> [服务器]        查询官方处罚名单（按赛季列出）
处罚名单更新 [强制]           抓取新名单；「强制」忽略已收录记录重抓（需管理员）
处罚通报推送 开/关/状态/测试  收录到新名单自动通报本群（开/关/测试需管理员）
**—— 宠物对战 ——**
宠物                         国服宠物对战世界任务（今天 + 明天，附上次野兽时间）
宠物推送 开/关/状态/测试      中午起轮询预告明日批次（有重量级野兽加预警；开/关/测试需管理员）
NGA 帖子链接直接发出来即可自动解析"""


# ---------------------------------------------------------------------------
# Markdown 输出开关（markdown_output / markdown_group_mode + 黑白名单）
#
# 服务层统一产 Markdown（唯一格式，避免双份分支）；关闭时在 main.py 出口
# 把 MD 语法剥成纯文本：**加粗** -> 加粗、`代码` -> 代码、[文字](url) -> 文字：url。
# 处罚名单的脱敏名已是全角＊，不会被这里的 ** 规则误伤。
# ---------------------------------------------------------------------------
_MD_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_MD_CODE = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def strip_markdown(text: str) -> str:
    """把本插件产出的 MD 语法剥成纯文本（信息不丢）。

    链接 `[文字](url)` → `文字：url`；标签本身就是 URL 时只留一份（链接标签用 URL
    写法时，剥完不应出现 `url：url` 重复）。
    """

    def _link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return label if label == url else f"{label}：{url}"

    text = _MD_LINK.sub(_link, text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_CODE.sub(r"\1", text)
    return text


def _clip(w: int, h: float, slack: int = 28) -> dict:
    """clip 构造：高度宁多勿少（多出部分与卡面同色）。"""
    return {"x": 0, "y": 0, "width": w, "height": int(h) + slack}


# 各模板物理尺寸估算（与 HTML/CSS 版式一一对应；估算值只影响出图裁剪，宁大勿小）
def _CLIP_CHARINFO(d: dict) -> dict:
    # 与 charinfo.html 版式逐项对应（2026-08-26 版模板）：
    # 面板 = head 56（padding 18+14 + 标题 20px*1.2） + divider 1 + 内容 + 底 padding 18
    bars = sum(1 for v in (d.get("score_dps", 0), d.get("score_healer", 0), d.get("score_tank", 0)) if v > 0)
    ranks = len(d.get("rank_rows") or [])
    if d.get("has_mp"):
        score_h = 56 + 1 + 72  # score-line：padding-top 18 + 54px 总分
        if bars:
            score_h += 10 + bars * 34  # bars：margin-top 20，行 24 + gap 10
        if ranks:
            score_h += 14 + ranks * 26  # rank：margin-top 14，行 padding 8 + 15px*1.2
        score_h += 18
    else:
        score_h = 56 + 1 + 43 + 18  # 空态：padding 18+6 + 16px 文本
    runs = d.get("runs") or []
    if runs:
        runs_h = 56 + 1 + len(runs) * 34 + 18  # 行：padding 12 + 内容 21.6
    else:
        runs_h = 0
    raids = d.get("raids") or []
    if raids:
        raids_h = 56 + 1 + len(raids) * 34 + 18
    else:
        raids_h = 56 + 1 + 43 + 18
    slots = d.get("slots") or []
    gear_h = 56 + 1 + math.ceil(len(slots) / 2) * 46 + 18  # 双列，行高 46
    # 头部 200 + 面板间 margin 18 + gear 面板 margin-bottom 18 + footer 70（margin 18+border 1+padding 34+文本 17）
    total = 200 + 18 + score_h + 18 + runs_h + 18 + raids_h + 18 + gear_h + 18 + 70
    return _clip(940, total)


def _CLIP_BOARD(d: dict) -> dict:
    # 榜单：band 120 + 行 52 + rows padding 6 + foot 32
    return _clip(680, 120 + len(d.get("rows") or []) * 52 + 38)


def _CLIP_WEEKLY(d: dict) -> dict:
    return _clip(900, 120 + len(d.get("rows") or []) * 54 + 52)


def _CLIP_BOARD_CHAR(d: dict) -> dict:
    return _clip(900, 240)


def _CLIP_GUILD(d: dict) -> dict:
    raids = d.get("raids") or []
    cls_rows = len(d.get("class_dist") or {})
    raid_h = 50 + (90 if not raids else len(raids) * 66 + 12)
    cls_h = 50 + (90 if not cls_rows else cls_rows * 36 + 12)
    return _clip(900, 150 + 18 + raid_h + 18 + cls_h + 52)


def _CLIP_GUILD_RANK(d: dict) -> dict:
    return _clip(900, 120 + len(d.get("rows") or []) * 50 + 52)


def _CLIP_SPECRANK(d: dict) -> dict:
    return _clip(900, 128 + len(d.get("rows") or []) * 40 + 56)


def _CLIP_TRINKETS(d: dict) -> dict:
    # 双区块饰品卡：头部 96 + 每区块（块头 58 + 表头 42 + 行 64）+ foot 40
    st_n = len((d.get("st") or {}).get("trinkets") or [])
    aoe_n = len((d.get("aoe5") or {}).get("trinkets") or [])
    h = 96 + (58 + 42 + st_n * 64) + (58 + 42 + aoe_n * 64) + 40
    return _clip(860, h)


def _CLIP_BIS(d: dict) -> dict:
    # h-title 68 + h-sub 28 + 各段（sec 52 + 行 32）+ foot 50 + root padding 16
    h = 68 + 28 + 52 + max(len(d.get("trinkets") or []), 1) * 32
    if d.get("secondary"):
        h += 52 + 32
    if d.get("race"):
        h += 52 + 32
    return _clip(900, h + 66)


def _CLIP_CALENDAR(d: dict) -> dict:
    return _clip(900, 96 + len(d.get("rows") or []) * 58 + 50)


def _CLIP_AFFIX(d: dict) -> dict:
    card = d.get("card") or {}
    h = 110 + 16
    for a in card.get("affixes") or []:
        desc_lines = WowPlugin._measure_wrap_lines(a.get("desc", ""), 550, 15)
        h += 64 + desc_lines * 20 + 14
    return _clip(720, h + 30)


def _CLIP_NEWS(d: dict) -> dict:
    # 与 news.html（深色版）版式逐项对应：
    # brand 57 + banner(图200/无图140) + article(24+标题行*40.6+分隔线33)
    # + desc(行*30.4+33) + link 60.8 + foot 32.2 + page padding 12
    # t2i 端点固定输出 800x720：内容不足 720 时底部会出现同色空带，需按内容裁剪
    news = d.get("news") or {}
    title_lines = WowPlugin._measure_wrap_lines(news.get("title", ""), 734, 28)
    h = 57 + (200 if news.get("image_url") else 140)
    if news.get("image_url"):
        h += 24 + title_lines * 40.6 + 33
    if news.get("description"):
        desc_lines = WowPlugin._measure_wrap_lines(news.get("description", ""), 734, 16)
        h += desc_lines * 30.4 + 33
    if news.get("url"):
        h += 60.8
    h += 32.2 + 12
    return _clip(800, min(h, 720))


def _CLIP_NGA(d: dict) -> dict:
    # 与 nga.html（深色版）版式逐项对应：
    # 头区 forum(30+20) + title(8+行*42) + meta(8+20)
    # 楼层 margin22 + padding32 + 头26 + body margin10 + 行*27 + 图 margin12+高 + border2
    # 页脚 margin16+10+1+17 + root padding-bottom 10
    posts = d.get("posts") or []
    title_lines = WowPlugin._measure_wrap_lines(d.get("title", ""), 784, 30)
    h = 50 + 8 + title_lines * 42 + 28
    for p in posts:
        body_lines = WowPlugin._measure_wrap_lines(p.get("content", ""), 752, 16)
        img_h = len(p.get("images") or []) * 860
        h += 22 + 32 + 26 + 10 + body_lines * 27 + img_h + 2
    h += 16 + 28 + 10
    return _clip(832, h)


def _CLIP_GACHA(d: dict) -> dict:
    return _clip(880, 96 + len(d.get("rows") or []) * 46 + 45)


def _CLIP_GACHA_RANK(d: dict) -> dict:
    return _clip(880, 96 + len(d.get("rows") or []) * 46 + 45)


def _CLIP_QUOTE(d: dict) -> dict:
    return _clip(880, 420)


def _CLIP_MPLUS_RATE(d: dict) -> dict:
    n = len(d.get("rows") or [])
    return _clip(1500, max(420, 218 + 58 + n * 56 + 40))


def _CLIP_MPLUS_RANK(d: dict) -> dict:
    groups = d.get("groups") or []
    n = sum(len(g.get("rows") or []) for g in groups)
    # 条形榜单：band 104 + 每段（组头 margin12+18+padding6+border1 与 rows padding6）48 + 行 62 + foot 60
    # 端点会把多要的高度收敛回内容高，所以这里宁多勿少（少了会切掉页脚）
    return _clip(700, 104 + len(groups) * 48 + n * 62 + 60)


_CLIP_ESTIMATORS = {
    "charinfo.html": _CLIP_CHARINFO,
    "board.html": _CLIP_BOARD,
    "weekly.html": _CLIP_WEEKLY,
    "board_char.html": _CLIP_BOARD_CHAR,
    "guild.html": _CLIP_GUILD,
    "guild_rank.html": _CLIP_GUILD_RANK,
    "specrank.html": _CLIP_SPECRANK,
    "trinkets.html": _CLIP_TRINKETS,
    "bis.html": _CLIP_BIS,
    "calendar.html": _CLIP_CALENDAR,
    "affix.html": _CLIP_AFFIX,
    "news.html": _CLIP_NEWS,
    "nga.html": _CLIP_NGA,
    "gacha.html": _CLIP_GACHA,
    "gacha_rank.html": _CLIP_GACHA_RANK,
    "quote.html": _CLIP_QUOTE,
    "mplus_rate.html": _CLIP_MPLUS_RATE,
    "mplus_rank.html": _CLIP_MPLUS_RANK,
}


class _RateLimit:
    """简单限流器（按 key）。"""

    def __init__(self, interval: float):
        self.interval = interval
        self._last: dict[str, float] = {}

    def ok(self, key: str) -> bool:
        now = time.time()
        if now - self._last.get(key, 0) >= self.interval:
            self._last[key] = now
            return True
        return False


class WowPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        plugin_data = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        set_data_dir(plugin_data)
        wcl_client = get_wcl_client(
            str(config.get("wcl_client_id", "")),
            str(config.get("wcl_client_secret", "")),
        )
        self._wcl = wcl_client
        self._limits = {k: _RateLimit(v) for k, v in {
            "default": 5, "heavy": 10, "light": 2,
        }.items()}
        self._scheduler_task: asyncio.Task | None = None
        self._last_news_check: float = 0
        self._last_punish_check: float = 0
        self._fired: set[tuple] = set()
        logger.info(
            "魔兽世界插件初始化完成 | 插件根目录：%s | 模板目录存在：%s | 数据目录：%s",
            _PLUGIN_ROOT, TEMPLATE_DIR.is_dir(), plugin_data,
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _cap(pattern: str, event: AstrMessageEvent) -> str:
        """取触发正则的第一个捕获组。

        RegexFilter 用的是 event.get_message_str().strip()（唤醒前缀已被剥掉），
        这里保持一致，所以别名/大小写都不需要单独处理。
        """
        rx = _RE_CACHE.get(pattern)
        if rx is None:
            rx = _RE_CACHE[pattern] = re.compile(pattern)
        m = rx.match(event.message_str.strip())
        if not m or not m.groups():
            return ""
        return (m.group(1) or "").strip()

    def _punish_dir(self) -> Path:
        """名单目录：配置优先，留空用 plugin_data/punish。查询与自动抓取共用。"""
        from wow.store import data_dir
        cfg = str(self.config.get("punish_xlsx_dir", "") or "").strip()
        base = Path(cfg) if cfg else data_dir() / "punish"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _limited(self, kind: str, key: str) -> bool:
        return self._limits[kind].ok(key)

    # ---- wowboard 指令白名单 ------------------------------------------
    # wowboard_whitelist 留空 = 不限制；填了umo/群号 = 只放行名单内的群（私聊放行）。
    # 未授权的群静默跳过（「名单」「周报」是裸词，回提示会误伤正常聊天）。
    def wowboard_allowed(self, event: AstrMessageEvent) -> bool:
        groups = self._norm_umo_list("wowboard_whitelist")
        if not groups:
            return True
        if not self._group_id(event):  # 私聊放行
            return True
        return self._umo(event) in groups

    # ---- Markdown 输出开关 -------------------------------------------
    # markdown_output：总开关（默认开）
    # markdown_group_mode：all=所有会话 / whitelist=仅白名单群 / blacklist=黑名单群除外
    # 名单填 unified_msg_origin 或裸群号均可（走 _norm_umo 归一，私聊不受名单影响、随总开关）
    def md_enabled(self, event: AstrMessageEvent) -> bool:
        if not bool(self.config.get("markdown_output", True)):
            return False
        mode = str(self.config.get("markdown_group_mode", "all") or "all").strip().lower()
        if mode == "all":
            return True
        gid = self._group_id(event)
        if not gid:  # 私聊：没有群维度，随总开关
            return True
        groups = self._norm_umo_list("markdown_groups")
        umo = self._umo(event)
        # 名单里存的是归一化 umo，与当前会话比对即可
        if mode == "whitelist":
            return umo in groups
        if mode == "blacklist":
            return umo not in groups
        return True

    def _md(self, event: AstrMessageEvent, text: str):
        """MD 开关出口：开启原样发（客户端渲染），关闭剥成纯文本。"""
        return event.plain_result(text if self.md_enabled(event) else strip_markdown(text))

    def _group_key(self, event: AstrMessageEvent) -> str:
        try:
            return f"{event.get_platform_name()}:{event.get_session_id()}"
        except Exception:  # noqa: BLE001
            return event.unified_msg_origin

    @staticmethod
    def _measure_wrap_lines(
        text: str, content_px: float, font_px: float, ascii_ratio: float = 0.55
    ) -> int:
        """按整页 CSS 像素估算折行后的总行数。

        CJK 一字≈font_px 宽，ASCII/数字≈font_px*ascii_ratio 宽（更贴近实际渲染）。
        """
        if not text:
            return 0
        lines = 0
        for para in str(text).split("\n"):
            w = 0.0
            for ch in para:
                w += font_px if ord(ch) > 127 else font_px * ascii_ratio
            lines += max(1, math.ceil(w / content_px))
        return lines

    def _clip_for(self, tmpl_name: str, data: dict) -> dict | None:
        """估算每张卡的物理尺寸，构造 t2i 端点需要的 clip（精确出图，消除黑/白边与空白）。

        t2i 端点视口固定 800x720：比 800 宽的卡会被截断、窄卡两侧会露出页面底色。
        用 clip 按卡宽+估算内容高裁剪，即可得到与卡片等大的图片。
        高度估算宁多勿少：多出的部分是卡面同色，肉眼不可见；少了会切掉内容。
        """
        est = _CLIP_ESTIMATORS.get(tmpl_name)
        if est is None:
            return None
        try:
            return est(data)
        except Exception as e:  # noqa: BLE001
            logger.warning("%s 尺寸估算失败，本次不裁剪（可能出现黑边）：%s", tmpl_name, e)
            return None

    async def _render(self, tmpl_name: str, data: dict) -> str:
        tmpl_path = TEMPLATE_DIR / tmpl_name
        if not tmpl_path.is_file():
            raise RuntimeError(
                f"模板缺失：{tmpl_path}。插件目录不完整，请删除 data/plugins/astrbot_plugin_wow"
                " 后重新解压完整 zip（需包含 wow/templates/ 子目录）并重启 AstrBot"
            )
        tmpl = tmpl_path.read_text(encoding="utf-8")
        # t2i 端点视口固定 800x720：用 clip 精确裁出卡片大小，消除黑/白边与大片空白
        options: dict = {"type": "png"}
        clip = self._clip_for(tmpl_name, data)
        if clip:
            options["clip"] = clip
        return await self.html_render(tmpl, data, options=options)

    def _umo(self, event: AstrMessageEvent) -> str:
        return event.unified_msg_origin

    @staticmethod
    def _group_id(event: AstrMessageEvent) -> str:
        try:
            return str(event.message_obj.group_id or "")
        except Exception:  # noqa: BLE001
            return ""

    # ---- 推送目标归一化 -------------------------------------------------
    # 配置项 news_groups / reset_groups / weekly_report_groups 允许两种写法：
    #   1. 完整 unified_msg_origin（群内发「重置提醒 开」时自动记录的就是这种）
    #   2. 裸群号（用户手填最常见）
    # context.send_message() 只认 unified_msg_origin（platform:MessageType:session_id），
    # 裸群号必须补全，否则定时推送会静默失败。

    _GROUP_MSG_TYPE = "GroupMessage"

    def _platform_names(self) -> list[str]:
        """当前已加载的平台名。取不到就返回空列表，由调用方回落默认值。"""
        mgr_paths = (
            lambda: self.context.platform_manager.platform_insts,
            lambda: self.context.get_platform_insts(),
        )
        for get in mgr_paths:
            try:
                insts = get()
            except Exception:  # noqa: BLE001
                continue
            names = []
            for p in insts or []:
                try:
                    names.append(str(p.meta().name))
                except Exception:  # noqa: BLE001
                    continue
            if names:
                return names
        return []

    def _norm_umo(self, entry) -> str:
        """把配置里的一项推送目标归一化成 unified_msg_origin。"""
        s = str(entry or "").strip()
        if not s:
            return ""
        if ":" in s:  # 已经是完整 umo
            return s
        plats = self._platform_names()
        # 裸群号是 OneBot（aiocqhttp）风格，优先挂到它上面；否则用首个已加载平台
        if "aiocqhttp" in plats:
            plat = "aiocqhttp"
        elif plats:
            plat = plats[0]
        else:
            plat = "aiocqhttp"
        return f"{plat}:{self._GROUP_MSG_TYPE}:{s}"

    def _norm_umo_list(self, key: str) -> list[str]:
        """读取推送目标配置并归一化、去重（保持配置顺序）。"""
        out: list[str] = []
        for raw in list(self.config.get(key, []) or []):
            umo = self._norm_umo(raw)
            if not umo:
                continue
            if umo != str(raw).strip():
                logger.debug("%s：群号 %s 已补全为 %s", key, raw, umo)
            if umo not in out:
                out.append(umo)
        return out

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        """AstrBot 的管理员 = 全局 admins_id 名单（对应原版 SuperUser/Admin）。"""
        return event.is_admin()

    def _md_for_umo(self, umo: str, text: str) -> str:
        """定时推送版的 MD 出口：按推送目标群的黑白名单决定是否剥 MD。"""
        if not bool(self.config.get("markdown_output", True)):
            return strip_markdown(text)
        mode = str(self.config.get("markdown_group_mode", "all") or "all").strip().lower()
        if mode == "all":
            return text
        groups = self._norm_umo_list("markdown_groups")
        if mode == "whitelist" and umo not in groups:
            return strip_markdown(text)
        if mode == "blacklist" and umo in groups:
            return strip_markdown(text)
        return text

    async def _send_text_to(self, umo: str, text: str) -> None:
        from astrbot.api.event import MessageChain
        await self.context.send_message(umo, MessageChain().message(self._md_for_umo(umo, text)))

    async def _send_img_to(self, umo: str, url: str) -> None:
        from astrbot.api.event import MessageChain
        chain = MessageChain()
        if url.startswith(("http://", "https://")):
            chain.url_image(url)
        else:
            chain.file_image(url)
        await self.context.send_message(umo, chain)

    # ---- 推送开关四件套（开/关/状态/测试）共用实现 --------------------
    # 新闻 / 重置提醒 / 周报 / 处罚通报四组推送命令共用同一套开关逻辑，
    # 差异只在文案（on/off/usage）与状态、测试的实现（status_fn / test_fn）。
    async def _push_toggle_cmd(
        self, event: AstrMessageEvent, arg: str, cfg_key: str, usage: str,
        on_msg: str, off_msg: str, status_fn=None, test_fn=None,
    ):
        """status_fn(on: bool) -> str；test_fn(event) -> list[结果]，无则提示不支持测试。"""
        if not self._group_id(event):
            yield event.plain_result("该命令仅支持在群聊中使用")
            return
        groups = self._norm_umo_list(cfg_key)  # 顺带把裸群号归一成 umo
        umo = self._umo(event)
        if arg == "开":
            if not self._is_admin(event):
                yield event.plain_result("需要管理员权限")
                return
            if umo not in groups:
                groups.append(umo)
            self.config[cfg_key] = groups
            self.config.save_config()
            yield event.plain_result(on_msg)
        elif arg == "关":
            if not self._is_admin(event):
                yield event.plain_result("需要管理员权限")
                return
            self.config[cfg_key] = [g for g in groups if g != umo]
            self.config.save_config()
            yield event.plain_result(off_msg)
        elif arg == "状态":
            on = umo in groups
            yield event.plain_result(status_fn(on) if status_fn else ("已开启" if on else "已关闭"))
        elif arg == "测试":
            if not self._is_admin(event):
                yield event.plain_result("需要管理员权限")
                return
            if test_fn is None:
                yield event.plain_result("该推送暂不支持测试")
                return
            for r in await test_fn(event):
                yield r
        else:
            yield event.plain_result(f"用法：{usage} 开 / 关 / 状态 / 测试")

    # ------------------------------------------------------------------
    # 帮助
    # ------------------------------------------------------------------

    @filter.regex(T_HELP)
    async def help_cmd(self, event: AstrMessageEvent):
        '''魔兽帮助：列出全部指令'''
        yield self._md(event, HELP_TEXT)

    # ------------------------------------------------------------------
    # wcl（WCL 战绩速查）
    # ------------------------------------------------------------------

    @filter.regex(T_WCL)
    async def wcl_cmd(self, event: AstrMessageEvent):
        '''WCL 战绩速查：wcl 角色名 服务器名'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        parts = self._cap(T_WCL, event).split()
        if not parts:
            yield event.plain_result("用法：wcl 角色名 服务器名\n例如：wcl 阿尔萨斯 白银之手")
            return
        if len(parts) < 2:
            yield event.plain_result("请指定服务器名，例如：wcl 阿尔萨斯 白银之手")
            return
        name, realm = parts[0], " ".join(parts[1:])
        try:
            profile = await asyncio.wait_for(
                self._wcl.fetch_character(name, realm, force_update=True), timeout=90
            )
            yield self._md(event, wclfmt.format_profile(profile))
        except asyncio.TimeoutError:
            yield event.plain_result("查询 Warcraft Logs 超时，请稍后再试")
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"查询 Warcraft Logs 失败：{e}")

    # ------------------------------------------------------------------
    # 角色卡（charinfo）
    # ------------------------------------------------------------------

    @filter.regex(T_CHARINFO)
    async def charinfo_cmd(self, event: AstrMessageEvent):
        '''魔兽角色卡：角色 角色名 服务器名'''
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        parts = self._cap(T_CHARINFO, event).split()
        if len(parts) < 2:
            yield event.plain_result("用法：角色 角色名 服务器名\n例：角色 阿尔萨斯 影之哀伤")
            return
        try:
            data = await asyncio.wait_for(
                charinfo_svc.build_char_card(parts[0], " ".join(parts[1:])), timeout=60
            )
            for s in data["slots"]:
                s["color"] = quality_color(s["quality"])
            url = await self._render("charinfo.html", data)
            yield event.image_result(url)
        except asyncio.TimeoutError:
            yield event.plain_result("查询超时（Raider.IO / wago.tools 响应太慢），请稍后再试")
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"查询失败：{e}")

    # ------------------------------------------------------------------
    # 词缀（mpaffix）
    # ------------------------------------------------------------------

    @filter.regex(T_AFFIX)
    async def affix_cmd(self, event: AstrMessageEvent):
        '''本周词缀'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            data = await affix_svc.build_affix_data()
            url = await self._render("affix.html", {"card": data["current"], "period_end": data.get("period_end")})
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"查询失败：{e}")

    @filter.regex(T_AFFIX_NEXT)
    async def next_affix_cmd(self, event: AstrMessageEvent):
        '''下周词缀'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            data = await affix_svc.build_affix_data()
            if not data.get("next"):
                yield event.plain_result("暂无法推算下周词缀")
                return
            url = await self._render("affix.html", {"card": data["next"], "period_end": data.get("period_end")})
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"查询失败：{e}")

    # ------------------------------------------------------------------
    # 日历（wowcal）
    # ------------------------------------------------------------------

    @filter.regex(T_CALENDAR)
    async def calendar_cmd(self, event: AstrMessageEvent):
        '''魔兽事件日历：日历 [关键词]'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        from wow.kernel import fetch_schedule
        try:
            data = await fetch_schedule()
            keyword = self._cap(T_CALENDAR, event)
            if keyword:
                rows = [
                    r for r in data["rows"]
                    if keyword in r["name"] or keyword in r["detail"]
                ]
                if not rows:
                    yield event.plain_result(f"没有找到与「{keyword}」相关的事件")
                    return
            else:
                rows = data["rows"]
            url = await self._render("calendar.html", {
                "expansion": data.get("expansion", ""),
                "generated": data.get("generated", ""),
                "rows": rows,
            })
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"日历获取失败：{e}")

    # ------------------------------------------------------------------
    # BIS / 强度榜
    # ------------------------------------------------------------------

    @filter.regex(T_TRINKET_RANK)
    async def trinket_rank_cmd(self, event: AstrMessageEvent):
        '''饰品排行 <专精>，如：饰品排行 冰DK'''
        if not self._limited("heavy", f"{event.get_sender_id()}"):
            yield event.plain_result("BIS 查询冷却中，请稍后再试（同一用户约 10 秒一次）")
            return
        spec = strip_arg_label(self._cap(T_TRINKET_RANK, event))
        if not spec:
            yield event.plain_result("用法：饰品排行 <专精>\n例：饰品排行 冰DK / 火法 / 狂暴战\n（也支持菜单格式：饰品排行 专精 射击猎）")
            return
        try:
            data = await bis_svc.build_trinket_rank(spec)
            url = await self._render("trinkets.html", data)
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(str(e))

    @filter.regex(T_BIS)
    async def bis_cmd(self, event: AstrMessageEvent):
        '''BIS 推荐 <专精>：饰品Top3 + 副属性 + 种族（出图，与原版一致）'''
        if not self._limited("heavy", f"{event.get_sender_id()}"):
            yield event.plain_result("BIS 查询冷却中，请稍后再试（同一用户约 10 秒一次）")
            return
        spec = strip_arg_label(self._cap(T_BIS, event))
        if not spec:
            yield event.plain_result("用法：BIS <专精>\n例：BIS 元素萨 / BIS 火法")
            return
        try:
            data = await bis_svc.build_bis(spec)
            url = await self._render("bis.html", data)
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(str(e))

    @filter.regex(T_SPECRANK)
    async def specrank_cmd(self, event: AstrMessageEvent):
        '''专精强度榜：强度榜 [aoe]'''
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        aoe = bool(self._cap(T_SPECRANK, event))
        try:
            rows, skipped, is_aoe = await bis_svc.build_spec_rank(aoe)
            url = await self._render("specrank.html", {
                "rows": rows, "skipped": skipped, "aoe": is_aoe,
            })
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            if aoe:
                yield event.plain_result(
                    "bloodmallet 当前未提供多目标（AoE）仿真数据，请改用「强度榜」看单体木桩。"
                )
                return
            yield event.plain_result(f"强度榜获取失败：{e}")

    # ------------------------------------------------------------------
    # 公会 / 团本排行（wowguild）
    # ------------------------------------------------------------------

    @filter.regex(T_GUILD)
    async def guild_cmd(self, event: AstrMessageEvent):
        '''公会资料：公会 公会名 [服务器]'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        parts = self._cap(T_GUILD, event).split()
        if not parts:
            yield event.plain_result("用法：公会 公会名 [服务器]\n例：公会 某某公会 影之哀伤")
            return
        name = parts[0]
        realm = " ".join(parts[1:]) or str(self.config.get("default_realm", "影之哀伤"))
        try:
            data = await guild_svc.fetch_guild_card(name, realm)
            url = await self._render("guild.html", data)
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(str(e))

    @filter.regex(T_RAID_RANK)
    async def raid_rank_cmd(self, event: AstrMessageEvent):
        '''团本排行 [难度] [团本]'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        args = self._cap(T_RAID_RANK, event)
        difficulty = None
        raid = None
        for token in args.split():
            if not difficulty and token in guild_svc.DIFFICULTY_MAP:
                difficulty = token
            elif not raid:
                raid = token
        try:
            data = await guild_svc.fetch_rank_card(difficulty, raid)
            url = await self._render("guild_rank.html", data)
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(str(e))

    # ------------------------------------------------------------------
    # 榜单 / 名单 / 周报 / 查卡（wowboard）
    # ------------------------------------------------------------------

    @filter.regex(T_ROSTER)
    async def roster_cmd(self, event: AstrMessageEvent):
        '''名单：查看预设名单'''
        if not self.wowboard_allowed(event):
            return
        roster = board_svc.get_board_store().list_roster()
        if not roster:
            yield event.plain_result("名单为空，请使用「名单 添加 <群友名> <角色名> <服务器>」添加")
            return
        lines = [f"**名单（{len(roster)} 人）**"]
        lines.extend(f"{r['id']}. {r['nickname']}（{r['char_name']}〈{r['realm']}〉）" for r in roster)
        yield self._md(event, "\n".join(lines))

    @filter.regex(T_ROSTER_ADD)
    async def roster_add_cmd(self, event: AstrMessageEvent):
        '''名单 添加 <群友名> <角色名> <服务器>（需管理员）'''
        if not self.wowboard_allowed(event):
            return
        if not self._is_admin(event):
            yield event.plain_result("需要管理员权限（AstrBot 全局管理员，可用 /sid 获取 ID 后添加）")
            return
        parts = self._cap(T_ROSTER_ADD, event).split()
        if len(parts) < 3:
            yield event.plain_result("用法：名单 添加 <群友名> <角色名> <服务器>")
            return
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("操作太频繁，请稍后再试")
            return
        row_id, ok = board_svc.get_board_store().add_roster(parts[0], parts[1], " ".join(parts[2:]))
        if ok:
            yield event.plain_result(f"已添加：{parts[0]}（{parts[1]}〈{' '.join(parts[2:])}〉，编号 {row_id}）")
        else:
            yield event.plain_result("该成员已存在")

    @filter.regex(T_ROSTER_DEL)
    async def roster_del_cmd(self, event: AstrMessageEvent):
        '''名单 删除 <编号>（需管理员）'''
        if not self.wowboard_allowed(event):
            return
        if not self._is_admin(event):
            yield event.plain_result("需要管理员权限（AstrBot 全局管理员，可用 /sid 获取 ID 后添加）")
            return
        parts = self._cap(T_ROSTER_DEL, event).split()
        if not parts or not parts[0].isdigit():
            yield event.plain_result("用法：名单 删除 <编号>")
            return
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("操作太频繁，请稍后再试")
            return
        if board_svc.get_board_store().delete_roster(int(parts[0])):
            yield event.plain_result(f"已删除编号 {parts[0]}")
        else:
            yield event.plain_result(f"编号 {parts[0]} 不存在")

    @filter.regex(T_BOARD)
    async def board_cmd(self, event: AstrMessageEvent):
        '''榜单 [装等] [详情] [刷新]（刷新需管理员）'''
        if not self.wowboard_allowed(event):
            return
        flags = self._cap(T_BOARD, event)
        mode = "ilvl" if "装等" in flags else "score"
        detail = "详情" in flags
        refresh = "刷新" in flags
        if refresh and not self._is_admin(event):
            yield event.plain_result("「榜单 刷新」需要管理员权限（会重新请求 Raider.IO）")
            return
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        if refresh:
            yield event.plain_result("正在请求 Raider.IO 更新，请稍候…")
        try:
            rows, err = await board_svc.build_board_data(refresh=refresh)
            if not rows:
                yield event.plain_result(err or "榜单为空")
                return
            display = rows
            hidden = 0
            if mode == "score":
                visible = [r for r in display if (r.get("score", 0) or 0) > 0]
                hidden = len(display) - len(visible)
                display = visible
            url = await self._render("board.html", {
                "rows": display, "mode": mode, "detail": detail, "hidden": hidden or None,
            })
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"榜单获取失败：{e}")

    @filter.regex(T_WEEKLY)
    async def weekly_cmd(self, event: AstrMessageEvent):
        '''周报：本周进步榜'''
        if not self.wowboard_allowed(event):
            return
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            report = await board_svc.build_weekly_report()
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"周报获取失败：{e}")
            return
        if not report:
            yield event.plain_result("名单为空，请先使用「名单 添加 <群友名> <角色名> <服务器>」添加")
            return
        url = await self._render("weekly.html", {"rows": report})
        yield event.image_result(url)

    def _next_weekly_time(self) -> str:
        """下次周报推送时刻（weekly_report_day 1=周一…7=周日，固定 20:00）。"""
        import datetime as dt
        try:
            wday = int(self.config.get("weekly_report_day", 3) or 3)
        except (TypeError, ValueError):
            wday = 3
        wday = min(7, max(1, wday))
        now = dt.datetime.now()
        days = (wday - 1 - now.weekday()) % 7
        t = (now + dt.timedelta(days=days)).replace(hour=20, minute=0, second=0, microsecond=0)
        if t <= now:
            t += dt.timedelta(days=7)
        return t.strftime("%m-%d（周" + "一二三四五六日"[wday - 1] + "）%H:%M")

    @filter.regex(T_WEEKLY_PUSH)
    async def weekly_push_cmd(self, event: AstrMessageEvent):
        '''周报推送 开/关/状态/测试：本群开启后每周推送本周进步榜（开/关/测试需管理员）'''
        def status(on: bool) -> str:
            return (f"本群周报推送：{'已开启' if on else '已关闭'}\n"
                    f"下次推送：{self._next_weekly_time()}")
        async for r in self._push_toggle_cmd(
            event, self._cap(T_WEEKLY_PUSH, event), "weekly_report_groups", "周报推送",
            on_msg=f"已开启本群周报推送（{self._next_weekly_time()} 起生效，每周自动推送）",
            off_msg="已关闭本群周报推送",
            status_fn=status,
            test_fn=lambda ev: self._weekly_test(ev),
        ):
            yield r

    async def _weekly_test(self, event: AstrMessageEvent) -> list:
        # 测试 = 当场生成一份周报（wowboard 数据，受白名单约束）
        if not self.wowboard_allowed(event):
            return [event.plain_result("本群不在 wowboard 白名单内，无法生成周报")]
        out = []
        try:
            report = await board_svc.build_weekly_report()
            if not report:
                out.append(event.plain_result("名单为空，请先使用「名单 添加 <群友名> <角色名> <服务器>」添加"))
                return out
            url = await self._render("weekly.html", {"rows": report})
            out.append(event.image_result(url))
        except Exception as e:  # noqa: BLE001
            out.append(event.plain_result(f"周报获取失败：{e}"))
        return out

    @filter.regex(T_CHAR_CARD)
    async def char_card_cmd(self, event: AstrMessageEvent):
        '''查卡 <群友名或角色名>'''
        if not self.wowboard_allowed(event):
            return
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        nick = self._cap(T_CHAR_CARD, event)
        if not nick:
            yield event.plain_result("用法：查卡 <群友名或角色名>")
            return
        try:
            prof = await board_svc.fetch_char_card(nick)
            from wow.data.names import realm_cn
            prof["realm_cn"] = realm_cn(prof.get("realm", prof.get("realm_cn", "")))
            url = await self._render("board_char.html", prof)
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(str(e))

    # ------------------------------------------------------------------
    # 新闻（blizzardnews）
    # ------------------------------------------------------------------

    @filter.regex(T_NEWS_FORCE)
    async def news_force_cmd(self, event: AstrMessageEvent):
        '''魔兽新闻：强制返回最新新闻'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        for r in await self._send_news(event, force=True):
            yield r

    @filter.regex(T_NEWS)
    async def news_cmd(self, event: AstrMessageEvent):
        '''魔兽新闻改：有更新才返回'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        for r in await self._send_news(event, force=False):
            yield r

    @filter.regex(T_NEWS_PUSH)
    async def news_push_cmd(self, event: AstrMessageEvent):
        '''魔兽新闻推送 开/关/状态/测试：本群开启后每 5 分钟检查，有更新自动推送卡片图+链接（开/关/测试需管理员）'''
        async for r in self._push_toggle_cmd(
            event, self._cap(T_NEWS_PUSH, event), "news_groups", "魔兽新闻推送",
            on_msg="已开启本群魔兽新闻自动推送（每 5 分钟检查一次，有更新实时推送）",
            off_msg="已关闭本群魔兽新闻自动推送",
            status_fn=lambda on: (
                f"本群魔兽新闻推送：{'已开启（每 5 分钟检查）' if on else '已关闭'}\n"
                "开启后由机器人自动推送，无需手动查询"
            ),
            test_fn=lambda ev: self._send_news(ev, force=True),
        ):
            yield r

    @filter.regex(T_NEWS_STATUS)
    async def news_status_cmd(self, event: AstrMessageEvent):
        '''魔兽新闻状态：本群推送开关'''
        if not self._group_id(event):
            yield event.plain_result("该命令仅支持在群聊中使用")
            return
        groups = list(self.config.get("news_groups", []) or [])
        umo = self._umo(event)
        on = umo in groups
        yield event.plain_result(
            f"本群魔兽新闻推送：{'已开启（每 5 分钟检查，有更新自动推送）' if on else '已关闭'}\n"
            "开关指令：魔兽新闻推送 开 / 关"
        )

    async def _send_news(self, event: AstrMessageEvent, force: bool) -> list:
        # 去重键按会话而不是笼统的 "private"，否则一个人看过就把所有私聊都压掉了
        key = self._group_id(event) or f"session:{event.unified_msg_origin}"
        results = []
        try:
            news = await news_svc.get_news(str(key), force=force)
            if not news:
                if force:
                    results.append(event.plain_result("暂时没有新闻"))
                return results
            # 与原 ZeroBot blizzardnews 一致的文本块（MD：标签加粗、地址为可点击链接。
            # 链接标签直接用 URL：QQ 官方 Bot 渲染成可点击链接；普通群若被
            # markdown_killer 之类剥掉语法，剩下的标签恰好就是完整 URL，不丢地址）
            url = news.get("url", "")
            link = f"[{url}]({url})" if url else "暂无"
            text = (
                f"**最新魔兽新闻**\n**标题**: {news['title']}\n"
                f"**描述**: {news.get('description', '')}\n"
                f"**地址**: {link}"
            )
            results.append(self._md(event, text))
            # 优先 Playwright 截真实网页（原版样式）；组件未就绪/失败时回退卡片
            shot = None
            if news.get("url"):
                try:
                    from wow.screenshot import screenshot
                    shot = await screenshot(news["url"])
                except RuntimeError as e:
                    if str(e) == "DOWNLOADING":
                        results.append(event.plain_result("首次使用正在后台下载网页截图组件（约 150MB），下载完成后自动生效"))
                    else:
                        logger.warning("网页截图失败，改用新闻卡片: %s", e)
                except Exception as e:  # noqa: BLE001
                    logger.warning("网页截图失败，改用新闻卡片: %s", e)
            if shot:
                results.append(event.image_result(shot))
            else:
                url = await self._render("news.html", {"news": news})
                results.append(event.image_result(url))
        except Exception as e:  # noqa: BLE001
            logger.warning("新闻获取失败: %s", e)
            if force:
                results.append(event.plain_result(f"新闻获取失败：{e}"))
        return results

    # ------------------------------------------------------------------
    # 开箱 / 红手榜（wowgacha）
    # ------------------------------------------------------------------

    @filter.regex(T_GACHA)
    async def gacha_cmd(self, event: AstrMessageEvent):
        '''开箱 [数量]：随机抽装备'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("开箱太频繁，请稍后再试")
            return
        gid = self._group_id(event)
        if not gid:
            yield event.plain_result("开箱只能在群里玩哦")
            return
        arg = self._cap(T_GACHA, event)
        n = max(1, min(100, int(arg))) if arg.isdigit() else 1
        result = gacha_svc.open_boxes(n)
        nick = event.get_sender_name() or str(event.get_sender_id())
        gacha_svc.add_score(gid, str(event.get_sender_id()), result["total"], nick)
        url = await self._render("gacha.html", {
            "nick": nick, "rows": result["rows"], "total": result["total"],
        })
        yield event.image_result(url)

    @filter.regex(T_GACHA_RANK)
    async def gacha_rank_cmd(self, event: AstrMessageEvent):
        '''红手榜 [数量]：本群红手积分排行'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        gid = self._group_id(event)
        if not gid:
            yield event.plain_result("红手榜只能在群里查看哦")
            return
        arg = self._cap(T_GACHA_RANK, event)
        top_n = max(1, min(50, int(arg))) if arg.isdigit() else 10
        rows = gacha_svc.rank_top(gid, top_n)
        if not rows:
            yield event.plain_result("本群还没有人开过箱，快试试「开箱」吧")
            return
        url = await self._render("gacha_rank.html", {"rows": rows})
        yield event.image_result(url)

    # ------------------------------------------------------------------
    # 语录（wowquote）
    # ------------------------------------------------------------------

    @filter.regex(T_QUOTE)
    async def quote_cmd(self, event: AstrMessageEvent):
        '''BOSS语录 [BOSS名]：随机一条魔兽台词'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        q = misc_svc.quote_card(self._cap(T_QUOTE, event))
        url = await self._render("quote.html", {"q": q})
        yield event.image_result(url)

    # ------------------------------------------------------------------
    # 重置提醒（wowreset）
    # ------------------------------------------------------------------

    @filter.regex(T_RESET)
    async def reset_cmd(self, event: AstrMessageEvent):
        '''重置：查询重置倒计时与本周词缀'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            yield self._md(event, await reset_svc.remind_text())
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"查询失败：{e}")

    @filter.regex(T_RESET_REMIND)
    async def reset_remind_cmd(self, event: AstrMessageEvent):
        '''重置提醒 开/关/状态/测试（开/关/测试需管理员）'''
        def status(on: bool) -> str:
            next_t = reset_svc.next_push_time(str(self.config.get("reset_time", "06:50")))
            return (f"本群重置提醒推送：{'已开启' if on else '已关闭'}\n"
                    f"下次推送：{next_t.strftime('%m-%d %H:%M')}")
        async for r in self._push_toggle_cmd(
            event, self._cap(T_RESET_REMIND, event), "reset_groups", "重置提醒",
            on_msg="已开启本群重置推送",
            off_msg="已关闭本群重置推送",
            status_fn=status,
            test_fn=lambda ev: self._reset_test(ev),
        ):
            yield r

    async def _reset_test(self, event: AstrMessageEvent) -> list:
        return [self._md(event, await reset_svc.remind_text())]

    # ------------------------------------------------------------------
    # 地下堡（dixiabao）
    # ------------------------------------------------------------------

    @filter.regex(T_DELVER)
    async def delver_cmd(self, event: AstrMessageEvent):
        '''地下堡饰品：当日可获取饰品'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        yield self._md(event, misc_svc.delver_menu())

    # ------------------------------------------------------------------
    # 事件 / 徽章 / 大米成功率 / 大米排行榜（wowinfo）
    # ------------------------------------------------------------------

    @filter.regex(T_EVENT)
    async def event_cmd(self, event: AstrMessageEvent):
        '''事件：当前版本事件'''
        async for r in self._event_card(event, 1):
            yield r

    @filter.regex(T_EVENT_ARG)
    async def event_arg_cmd(self, event: AstrMessageEvent):
        '''事件 <版本>：指定版本事件'''
        key = self._cap(T_EVENT_ARG, event)
        from wow.kernel import is_card_key, translate_card_id
        if not is_card_key(key):
            yield event.plain_result("未知版本：" + key + "\n可用：地心之战 / 巨龙时代 / 暗影国度 / 争霸艾泽拉斯 / 军团再临 / 德拉诺")
            return
        async for r in self._event_card(event, int(translate_card_id(key))):
            yield r

    @filter.regex(T_EVENT_SUFFIX)
    async def event_suffix_cmd(self, event: AstrMessageEvent):
        '''X事件：地心之战事件 / 巨龙时代事件 ...'''
        key = self._cap(T_EVENT_SUFFIX, event)
        from wow.kernel import is_card_key, translate_card_id
        # 免前缀触发：不是已知版本名就当普通聊天，静默放过（否则「这是什么事件」也会触发）
        if not is_card_key(key):
            return
        async for r in self._event_card(event, int(translate_card_id(key))):
            yield r

    async def _event_card(self, event: AstrMessageEvent, index: int):
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        from wow.kernel import fetch_event_card
        try:
            yield self._md(event, await fetch_event_card(index))
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"获取失败：{e}")

    @filter.regex(T_BADGE)
    async def badge_cmd(self, event: AstrMessageEvent):
        '''徽章：还没开发'''
        yield event.plain_result("还没开发")

    @filter.regex(T_MPLUS_RATE)
    async def mplus_rate_cmd(self, event: AstrMessageEvent):
        '''大米成功率 [层数]：当前周限时率（出图，默认 10 层）'''
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        arg = self._cap(T_MPLUS_RATE, event)
        level = max(1, min(40, int(arg))) if arg.isdigit() else 10
        try:
            from wow.bestkeystone import current_period, ontime_rate
            rows = await ontime_rate(level)
            if not rows:
                yield event.plain_result("加载失败啦，极大概率是网络访问问题")
                return
            url = await self._render("mplus_rate.html", {
                "period": current_period(), "level": level, "rows": rows,
            })
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"加载失败啦，极大概率是网络访问问题（{e}）")

    @filter.regex(T_MPLUS_RANK)
    async def mplus_rank_cmd(self, event: AstrMessageEvent):
        '''大米排行榜：当前赛季 输出/防御/治疗 三段排行（出图）'''
        if not self._limited("heavy", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            from wow import mythicstats
            # 不硬截行数：原版 rankSize=26 是当年只有 26 个输出专精，
            # Midnight 加了噬灭DH 之后写死 26 会漏行。
            fetch_groups = getattr(mythicstats, "fetch_role_ranks", None)
            if fetch_groups is not None:
                groups = await fetch_groups()
            else:  # 旧版 mythicstats.py 混装部署：退化成只有输出段
                rows = await mythicstats.fetch_dps_rank()
                groups = [{"role": "damage", "label": "输出", "rows": rows}] if rows else []
            if not groups:
                yield event.plain_result("加载失败啦，极大概率是网络访问问题")
                return
            url = await self._render(
                "mplus_rank.html", {"title": "大秘境专精排行榜", "groups": groups}
            )
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"加载失败啦，极大概率是网络访问问题（{e}）")

    # ------------------------------------------------------------------
    # 吃什么 / 天赋 / 物价 / 低保（chishenme）
    # ------------------------------------------------------------------

    @filter.regex(T_EAT)
    async def eat_cmd(self, event: AstrMessageEvent):
        '''吃什么：按时段推荐'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        yield event.plain_result(misc_svc.what_to_eat())

    @filter.regex(T_TALENT)
    async def talent_cmd(self, event: AstrMessageEvent):
        '''X天赋：火法天赋 / 鸟德天赋 / DK天赋 ...'''
        key = self._cap(T_TALENT, event)
        # 免前缀触发：认不出职业/专精就当普通聊天，静默放过
        if not misc_svc.is_talent_key(key):
            return
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            yield event.plain_result(await misc_svc.talent_info(key))
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"天赋获取失败：{e}")

    @filter.regex(T_TALENT_PREFIX)
    async def talent_prefix_cmd(self, event: AstrMessageEvent):
        '''天赋X：天赋火法 / 天赋 DK ...（与 X天赋 等价的兼容写法）'''
        key = self._cap(T_TALENT_PREFIX, event)
        # 免前缀触发：认不出职业/专精（含裸词「天赋」）就当普通聊天，静默放过
        if not misc_svc.is_talent_key(key):
            return
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            yield event.plain_result(await misc_svc.talent_info(key))
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"天赋获取失败：{e}")

    @filter.regex(T_PRICE)
    async def price_cmd(self, event: AstrMessageEvent):
        '''物价 物品1、物品2：查询本地物价表'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        raw = self._cap(T_PRICE, event).replace("，", "、")
        items = [i for i in raw.split("、") if i.strip()]
        if not items:
            yield event.plain_result("用法：物价 丰饶药水、xxx")
            return
        try:
            yield self._md(event, await misc_svc.query_price(items))
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"物价查询失败：{e}")

    @filter.regex(T_FORTUNE)
    async def fortune_cmd(self, event: AstrMessageEvent):
        '''低保：每日低保运势'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        yield event.plain_result(misc_svc.daily_fortune(str(event.get_sender_id())))

    @filter.regex(T_PUNISH)
    async def punish_cmd(self, event: AstrMessageEvent):
        '''处罚 <角色名> [服务器]：查询处罚名单 xlsx'''
        if not self._limited("light", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        arg = self._cap(T_PUNISH, event)
        parts = arg.split()
        if not parts:
            yield event.plain_result(
                "用法：处罚 <角色名> [服务器]\n"
                "例：处罚 张三丰 / 处罚 张三丰 白银之手\n"
                "名单是脱敏名（一个＊代表一个字），也可直接按＊查：处罚 张＊丰"
            )
            return
        name, realm = parts[0], None
        if len(parts) > 1:
            realm = " ".join(parts[1:])
        try:
            base = self._punish_dir()
            # 首轮要读 38 万行 xlsx（约 10s），走线程避免卡住整个事件循环；
            # 旧版 punish 模块没有 query_async，退回同步版（见容错导入约定）
            q = getattr(punish_svc, "query_async", None)
            hits = await q(base, name, realm) if q else punish_svc.query(base, name, realm)
        except Exception as e:  # noqa: BLE001
            logger.warning("处罚名单查询失败: %s", e)
            yield event.plain_result(f"处罚名单查询失败：{e}")
            return
        if not hits:
            where = f"·{realm}" if realm else ""
            safe = getattr(punish_svc, "safe_name", lambda s: s)
            yield event.plain_result(f"「{safe(name)}{where}」不在处罚名单里，清白。")
            return
        yield self._md(event, punish_svc.format_hits(name, realm, hits))

    @filter.regex(T_PUNISH_SYNC)
    async def punish_sync_cmd(self, event: AstrMessageEvent):
        '''处罚名单更新 [强制]：扫官网处罚公告收录新名单；带「强制」则忽略记录全量重抓（管理员）'''
        if not event.is_admin():
            yield event.plain_result("仅管理员可手动更新处罚名单")
            return
        if punishfeed_svc is None:
            yield event.plain_result("当前部署缺少 punishfeed 模块，无法自动抓取")
            return
        force = bool(self._cap(T_PUNISH_SYNC, event))
        tip = "正在**强制**重抓官网处罚公告（忽略已收录记录）……" if force else \
            "正在扫描官网处罚公告……"
        yield event.plain_result(tip + "大名单解析较慢，请稍候")
        try:
            done = await punishfeed_svc.sync_once(self._punish_dir(), force=force)
        except TypeError:  # 旧版 punishfeed 无 force 参数（容错导入约定）
            done = await punishfeed_svc.sync_once(self._punish_dir())
        except Exception as e:  # noqa: BLE001
            logger.warning("处罚名单手动更新失败: %s", e)
            yield event.plain_result(f"抓取失败：{e}")
            return
        if not done:
            yield event.plain_result(
                "没有发现新名单，本地已是最新。\n"
                "若确认官网有名单却没收录，发「处罚名单更新 强制」忽略已收录记录重抓一遍。"
            )
            return
        yield self._md(event, punishfeed_svc.report_text(done))

    @filter.regex(T_PUNISH_NOTIFY)
    async def punish_notify_cmd(self, event: AstrMessageEvent):
        '''处罚通报推送 开/关/状态/测试：本群开启后收录到新处罚名单自动通报（开/关/测试需管理员）'''
        def status(on: bool) -> str:
            auto = bool(self.config.get("punish_auto_fetch", False))
            try:
                interval = max(300, int(self.config.get("punish_fetch_interval", 3600) or 3600))
            except (TypeError, ValueError):
                interval = 3600
            lines = [f"本群新处罚名单通报：{'已开启' if on else '已关闭'}"]
            lines.append(f"自动抓取：{'已开启' if auto else '已关闭'}（检查间隔 {interval} 秒）")
            if not auto:
                lines.append("提示：自动抓取默认关闭，需在 WebUI 开启 punish_auto_fetch 才会自动收录并通报")
            return "\n".join(lines)
        async for r in self._push_toggle_cmd(
            event, self._cap(T_PUNISH_NOTIFY, event), "punish_notify_groups", "处罚通报推送",
            on_msg="已开启本群新处罚名单通报（收录到新名单后自动推送）",
            off_msg="已关闭本群新处罚名单通报",
            status_fn=status,
            test_fn=lambda ev: self._punish_notify_test(ev),
        ):
            yield r

    async def _punish_notify_test(self, event: AstrMessageEvent) -> list:
        text = (
            "**[测试]** 处罚通报推送链路验证 —— 收到这条说明本群可以收到新处罚名单通报。\n"
            "正式通报在收录到新名单时自动发送；手动抓取可发「处罚名单更新」。"
        )
        return [self._md(event, text)]

    # ------------------------------------------------------------------
    # 宠物对战世界任务（重量级野兽预警）
    # ------------------------------------------------------------------

    @filter.regex(T_PET)
    async def pet_cmd(self, event: AstrMessageEvent):
        '''宠物：国服宠物对战世界任务（今天 + 明天，欧服数据源）'''
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("查询太频繁，请稍后再试")
            return
        try:
            yield self._md(event, await petwq_svc.query_text())
        except Exception as e:  # noqa: BLE001
            yield event.plain_result(f"查询失败：{e}")

    @filter.regex(T_PET_PUSH)
    async def pet_push_cmd(self, event: AstrMessageEvent):
        '''宠物推送 开/关/状态/测试：12:00 起每 5 分钟轮询欧服切批，拿到明日批次即推（有重量级野兽加预警；开/关/测试需管理员）'''
        def status(on: bool) -> str:
            return (f"本群宠物任务通报：{'已开启' if on else '已关闭'}\n"
                    "12:00 起每 5 分钟检查欧服切批，拿到国服明天 07:00 开始的批次即推"
                    "（附今天批次与上次野兽出现时间），有重量级野兽时加预警横幅")
        async for r in self._push_toggle_cmd(
            event, self._cap(T_PET_PUSH, event), "pet_push_groups", "宠物推送",
            on_msg="已开启本群宠物任务通报（中午起轮询，拿到明天批次即推；有重量级野兽加预警）",
            off_msg="已关闭本群宠物任务通报",
            status_fn=status,
            test_fn=lambda ev: self._pet_test(ev),
        ):
            yield r

    async def _pet_test(self, event: AstrMessageEvent) -> list:
        # 测试 = 当场跑一次完整查询（与定时推送同一份文案口径）
        try:
            text = await petwq_svc.push_text()
            if text is None:
                return [event.plain_result("暂时拉不到宠物任务数据（todayinwow.com），请稍后再试")]
            return [self._md(event, "**[测试]**\n" + text)]
        except Exception as e:  # noqa: BLE001
            return [event.plain_result(f"查询失败：{e}")]

    # ------------------------------------------------------------------
    # NGA 帖子（ngajiexi）
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_nga_link(self, event: AstrMessageEvent):
        '''嗅探 NGA 帖子链接并生成卡片（无需指令前缀，裸链接/句中链接均可触发）'''
        m = getattr(nga_svc, "match_link", None)
        if m is None:
            # 兜底：旧版 nga 模块（无 match_link）时退回 extract_tid，避免混合部署闪崩
            tid = nga_svc.extract_tid(event.message_str)
            if not tid:
                return
            domain, tid = "ngabbs.com", tid
        else:
            got = m(event.message_str)
            if not got:
                return
            domain, tid = got
        if not self._limited("default", self._group_key(event)):
            yield event.plain_result("解析太频繁，请稍后再试")
            return
        prefix = nga_svc.convert_line(domain, tid)
        try:
            topic = await nga_svc.fetch_topic(tid)
            header = nga_svc.header_text(topic["title"], topic["author"], topic["replies"], tid)
            url = await self._render("nga.html", {
                "forum": topic["forum"], "title": topic["title"], "replies": topic["replies"],
                "posts": topic["posts"],
            })
            yield self._md(event, prefix + header)
            yield event.image_result(url)
        except Exception as e:  # noqa: BLE001
            logger.warning("NGA 解析失败: %s", e)
            yield event.plain_result(f"{prefix}ERROR: {e}")

    # ------------------------------------------------------------------
    # 定时任务
    # ------------------------------------------------------------------

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._scheduler())

    async def _scheduler(self):
        while True:
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                logger.warning("定时任务异常: %s", e)
            await asyncio.sleep(30)

    def _fire_once(self, tag: str, now) -> bool:
        """30 秒一跳会在同一分钟命中两次，用 (日, 时, 分) 去重，避免推送发两遍。"""
        key = (tag, now.tm_yday, now.tm_hour, now.tm_min)
        if key in self._fired:
            return False
        self._fired.add(key)
        if len(self._fired) > 64:
            self._fired = {k for k in self._fired if k[1] == now.tm_yday}
        return True

    async def _tick(self):
        now = time.localtime()
        cfg = self.config

        # 重置提醒（周四 HH:MM）
        reset_groups = self._norm_umo_list("reset_groups")  # 归一：裸群号自动补全 umo
        if reset_groups and now.tm_wday == 3:
            h, m = reset_svc.parse_reset_time(str(cfg.get("reset_time", "06:50")))
            if now.tm_hour == h and now.tm_min == m and self._fire_once("reset", now):
                try:
                    text = await reset_svc.remind_text()
                    for umo in reset_groups:
                        try:
                            await self._send_text_to(umo, text)
                        except Exception as e:  # noqa: BLE001
                            logger.warning("重置推送失败 %s: %s", umo, e)
                except Exception as e:  # noqa: BLE001
                    logger.warning("重置提醒生成失败: %s", e)

        # 周报（weekly_report_day，1=周一 ... 7=周日，20:00）
        weekly_groups = self._norm_umo_list("weekly_report_groups")  # 归一：裸群号自动补全 umo
        try:
            wday = int(cfg.get("weekly_report_day", 3) or 3)
        except (TypeError, ValueError):
            wday = 3
        wday = min(7, max(1, wday))
        if (weekly_groups and now.tm_wday == wday - 1 and now.tm_hour == 20
                and now.tm_min == 0 and self._fire_once("weekly", now)):
            try:
                report = await board_svc.build_weekly_report()
                if report:
                    url = await self._render("weekly.html", {"rows": report})
                    for umo in weekly_groups:
                        try:
                            await self._send_img_to(umo, url)
                        except Exception as e:  # noqa: BLE001
                            logger.warning("周报推送失败 %s: %s", umo, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("周报生成失败: %s", e)

        # 宠物对战世界任务预告（欧服数据源，北京 12:00 切批）
        # 源站放出新批有延迟（实测 12:20 仍未见到新批），所以 12:00 起每 5 分钟
        # 轮询一次：拿到「国服明天 07:00 开始的批次」就推，当天只推一次（跨重启去重）。
        pet_groups = self._norm_umo_list("pet_push_groups")  # 归一：裸群号自动补全 umo
        if (pet_groups and now.tm_hour >= 12 and now.tm_min % 5 == 0
                and self._fire_once("petpoll", now)
                and petwq_svc.pushed_day() != petwq_svc.today_str()):
            text = None
            try:
                text = await petwq_svc.push_text(require_tomorrow=True)
            except Exception as e:  # noqa: BLE001
                logger.warning("宠物任务通报生成失败: %s", e)
            if text:
                for umo in pet_groups:
                    try:
                        await self._send_text_to(umo, text)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("宠物任务通报推送失败 %s: %s", umo, e)
                petwq_svc.mark_pushed(petwq_svc.today_str())
                logger.info("宠物任务预告已推送（国服明天批次）")
            else:
                logger.info("宠物任务预告：源站尚未放出明日批次，5 分钟后再试")

        # 处罚名单自动抓取（先于新闻块：新闻块内有 return，放后面会被跳过）
        if punishfeed_svc is not None and bool(cfg.get("punish_auto_fetch", False)):
            interval = max(300, int(cfg.get("punish_fetch_interval", 3600) or 3600))
            if time.time() - self._last_punish_check > interval:
                self._last_punish_check = time.time()
                try:
                    done = await punishfeed_svc.sync_once(self._punish_dir())
                except Exception as e:  # noqa: BLE001
                    logger.warning("处罚名单自动抓取失败: %s", e)
                    done = []
                if done:
                    text = punishfeed_svc.report_text(done)
                    for umo in self._norm_umo_list("punish_notify_groups"):
                        try:
                            await self._send_text_to(umo, text)
                        except Exception as e:  # noqa: BLE001
                            logger.warning("处罚名单通报失败 %s: %s", umo, e)

        # 新闻（每 5 分钟检查一次，有更新实时推送：网页截图 + 可点链接）
        news_groups = self._norm_umo_list("news_groups")  # 归一化：裸群号自动补全 umo
        if news_groups and time.time() - self._last_news_check > 300:
            self._last_news_check = time.time()
            # 先收集需要推送的群（get_news 按群去重），统一只截一次图
            targets = []
            news_item = None
            for umo in news_groups:
                try:
                    news = await news_svc.get_news(f"push:{umo}", force=False)
                    if news:
                        news_item = news
                        targets.append(umo)
                except Exception as e:  # noqa: BLE001
                    logger.warning("新闻检查失败 %s: %s", umo, e)
            if not targets or news_item is None:
                return
            shot = None
            card_url = None
            if news_item.get("url"):
                try:
                    from wow.screenshot import screenshot, clean_shots
                    shot = await screenshot(news_item["url"])  # 缓存复用：多群只截一次
                except RuntimeError as e:
                    if str(e) == "DOWNLOADING":
                        logger.info("新闻截图组件首次下载中，本次推送回退卡片")
                    else:
                        logger.warning("定时新闻网页截图失败，改用卡片: %s", e)
                except Exception as e:  # noqa: BLE001
                    logger.warning("定时新闻网页截图失败，改用卡片: %s", e)
                if shot is None:
                    card_url = await self._render("news.html", {"news": news_item})
            else:
                card_url = await self._render("news.html", {"news": news_item})
            _url = news_item.get("url", "")
            _link = f"[{_url}]({_url})" if _url else "暂无"
            text = f"**最新魔兽新闻**\n**标题**: {news_item['title']}\n**地址**: {_link}"
            for umo in targets:
                try:
                    if shot:
                        await self._send_img_to(umo, shot)
                    elif card_url:
                        await self._send_img_to(umo, card_url)
                    if news_item.get("url"):
                        await self._send_text_to(umo, text)
                except Exception as e:  # noqa: BLE001
                    logger.warning("新闻推送失败 %s: %s", umo, e)
            try:
                from wow.screenshot import clean_shots
                clean_shots()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------

    async def terminate(self):
        if self._scheduler_task:
            self._scheduler_task.cancel()
        await close_client()
        close_stores()
