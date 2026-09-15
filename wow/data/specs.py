# -*- coding: utf-8 -*-
"""内置数据表：BIS 专精别名解析（bloodmallet class/spec 标记）。"""

SPEC_TOKEN_BY_EN = {
    "frost": ("death_knight", "frost", "冰霜"),
    "frostdk": ("death_knight", "frost", "冰霜"),
    "unholy": ("death_knight", "unholy", "邪恶"),
    "unholydk": ("death_knight", "unholy", "邪恶"),
    "blood": ("death_knight", "blood", "灵血"),
    "blooddk": ("death_knight", "blood", "灵血"),
    "dk": ("death_knight", "frost", "冰霜"),
    "fire": ("mage", "fire", "火法"),
    "frostmage": ("mage", "frost", "冰法"),
    "arcane": ("mage", "arcane", "奥法"),
    "destruction": ("warlock", "destruction", "毁灭术"),
    "affliction": ("warlock", "affliction", "痛苦术"),
    "demonology": ("warlock", "demonology", "恶魔术"),
    "marksmanship": ("hunter", "marksmanship", "射击"),
    "survival": ("hunter", "survival", "生存"),
    "beastmastery": ("hunter", "beast_mastery", "兽王"),
    "outlaw": ("rogue", "outlaw", "狂徒"),
    "subtlety": ("rogue", "subtlety", "敏锐"),
    "assassination": ("rogue", "assassination", "刺杀"),
    "shadow": ("priest", "shadow", "暗影"),
    "retribution": ("paladin", "retribution", "惩戒"),
    "arms": ("warrior", "arms", "武器战"),
    "fury": ("warrior", "fury", "狂暴"),
    "protection": ("warrior", "protection", "防护"),
    "windwalker": ("monk", "windwalker", "踏风"),
    "havoc": ("demon_hunter", "havoc", "浩劫"),
    "devourer": ("demon_hunter", "devourer", "噬灭"),
    "balance": ("druid", "balance", "平衡"),
    "feral": ("druid", "feral", "野性"),
    "elemental": ("shaman", "elemental", "元素"),
    "ele": ("shaman", "elemental", "元素"),
    "enhancement": ("shaman", "enhancement", "增强"),
    "devastation": ("evoker", "devastation", "湮灭"),
    "augmentation": ("evoker", "augmentation", "增辉"),
    "preservation": ("evoker", "preservation", "恩护"),
}

SPEC_ALIAS = {
    "冰dk": ("death_knight", "frost", "冰霜DK"),
    "冰霜dk": ("death_knight", "frost", "冰霜DK"),
    "冰死骑": ("death_knight", "frost", "冰霜DK"),
    "邪dk": ("death_knight", "unholy", "邪恶DK"),
    "邪恶dk": ("death_knight", "unholy", "邪恶DK"),
    "邪死骑": ("death_knight", "unholy", "邪恶DK"),
    "血dk": ("death_knight", "blood", "鲜血DK"),
    "鲜血dk": ("death_knight", "blood", "鲜血DK"),
    "死亡骑士": ("death_knight", "frost", "冰霜DK"),
    "火法": ("mage", "fire", "火法"),
    "冰法": ("mage", "frost", "冰法"),
    "奥法": ("mage", "arcane", "奥法"),
    "法师": ("mage", "fire", "火法"),
    "毁灭": ("warlock", "destruction", "毁灭术"),
    "毁灭术": ("warlock", "destruction", "毁灭术"),
    "痛苦": ("warlock", "affliction", "痛苦术"),
    "痛苦术": ("warlock", "affliction", "痛苦术"),
    "恶魔": ("warlock", "demonology", "恶魔术"),
    "恶魔术": ("warlock", "demonology", "恶魔术"),
    "术士": ("warlock", "destruction", "毁灭术"),
    "射击猎": ("hunter", "marksmanship", "射击猎"),
    "射击": ("hunter", "marksmanship", "射击猎"),
    "生存猎": ("hunter", "survival", "生存猎"),
    "生存": ("hunter", "survival", "生存猎"),
    "兽王猎": ("hunter", "beast_mastery", "兽王猎"),
    "兽王": ("hunter", "beast_mastery", "兽王猎"),
    "猎人": ("hunter", "marksmanship", "射击猎"),
    "狂徒": ("rogue", "outlaw", "狂徒"),
    "狂徒贼": ("rogue", "outlaw", "狂徒贼"),
    "敏锐": ("rogue", "subtlety", "敏锐"),
    "敏锐贼": ("rogue", "subtlety", "敏锐贼"),
    "刺杀": ("rogue", "assassination", "刺杀"),
    "刺杀贼": ("rogue", "assassination", "刺杀贼"),
    "潜行者": ("rogue", "outlaw", "狂徒"),
    "盗贼": ("rogue", "outlaw", "狂徒"),
    "贼": ("rogue", "outlaw", "狂徒"),
    "dz": ("rogue", "outlaw", "狂徒"),
    "暗牧": ("priest", "shadow", "暗牧"),
    "牧师": ("priest", "shadow", "暗牧"),
    "神牧": ("priest", "holy", "神牧"),
    "ms": ("priest", "shadow", "暗牧"),
    "惩戒": ("paladin", "retribution", "惩戒骑"),
    "惩戒骑": ("paladin", "retribution", "惩戒骑"),
    "圣骑士": ("paladin", "retribution", "惩戒骑"),
    "qs": ("paladin", "retribution", "惩戒骑"),
    "防骑": ("paladin", "protection", "防骑"),
    "防护骑": ("paladin", "protection", "防骑"),
    "奶骑": ("paladin", "holy", "奶骑"),
    "神圣骑": ("paladin", "holy", "奶骑"),
    "武器": ("warrior", "arms", "武器战"),
    "武器战": ("warrior", "arms", "武器战"),
    "狂暴": ("warrior", "fury", "狂暴战"),
    "狂暴战": ("warrior", "fury", "狂暴战"),
    "防战": ("warrior", "protection", "防战"),
    "战士": ("warrior", "fury", "狂暴战"),
    "zs": ("warrior", "fury", "狂暴战"),
    "踏风": ("monk", "windwalker", "踏风"),
    "武僧": ("monk", "windwalker", "踏风"),
    "ws": ("monk", "windwalker", "踏风"),
    "酒仙": ("monk", "brewmaster", "酒仙"),
    "织雾": ("monk", "mistweaver", "织雾"),
    "奶僧": ("monk", "mistweaver", "织雾"),
    "浩劫": ("demon_hunter", "havoc", "浩劫"),
    "恶魔猎手": ("demon_hunter", "havoc", "浩劫"),
    # Midnight(12.0) 恶魔猎手第三专精 Devourer，官方 zhCN 名「噬灭」
    "噬灭": ("demon_hunter", "devourer", "噬灭DH"),
    "噬灭dh": ("demon_hunter", "devourer", "噬灭DH"),
    "远程dh": ("demon_hunter", "devourer", "噬灭DH"),
    "复仇": ("demon_hunter", "vengeance", "复仇"),
    "复仇dh": ("demon_hunter", "vengeance", "复仇"),
    "dh": ("demon_hunter", "havoc", "浩劫"),
    "鸟德": ("druid", "balance", "平衡德"),
    "平衡": ("druid", "balance", "平衡德"),
    "野性": ("druid", "feral", "野性德"),
    "平衡德": ("druid", "balance", "平衡德"),
    "猫德": ("druid", "feral", "野性德"),
    "野德": ("druid", "feral", "野性德"),
    "熊德": ("druid", "guardian", "熊德"),
    "奶德": ("druid", "restoration", "奶德"),
    "德鲁伊": ("druid", "balance", "平衡德"),
    "xd": ("druid", "balance", "平衡德"),
    "元素": ("shaman", "elemental", "元素萨"),
    "元素萨": ("shaman", "elemental", "元素萨"),
    "增强": ("shaman", "enhancement", "增强萨"),
    "增强萨": ("shaman", "enhancement", "增强萨"),
    "恢复萨": ("shaman", "restoration", "恢复萨"),
    "奶萨": ("shaman", "restoration", "恢复萨"),
    "萨满": ("shaman", "elemental", "元素萨"),
    "sm": ("shaman", "elemental", "元素萨"),
    "火法": ("mage", "fire", "火法"),
    "冰法": ("mage", "frost", "冰法"),
    "奥法": ("mage", "arcane", "奥法"),
    "法师": ("mage", "fire", "火法"),
    "fs": ("mage", "fire", "火法"),
    "射击猎": ("hunter", "marksmanship", "射击猎"),
    "生存猎": ("hunter", "survival", "生存猎"),
    "兽王猎": ("hunter", "beast_mastery", "兽王猎"),
    "猎人": ("hunter", "marksmanship", "射击猎"),
    "lr": ("hunter", "marksmanship", "射击猎"),
    "毁灭": ("warlock", "destruction", "毁灭术"),
    "毁灭术": ("warlock", "destruction", "毁灭术"),
    "痛苦术": ("warlock", "affliction", "痛苦术"),
    "恶魔术": ("warlock", "demonology", "恶魔术"),
    "术士": ("warlock", "destruction", "毁灭术"),
    "ss": ("warlock", "destruction", "毁灭术"),
    "血dk": ("death_knight", "blood", "鲜血DK"),
    "鲜血dk": ("death_knight", "blood", "鲜血DK"),
    "冰dk": ("death_knight", "frost", "冰霜DK"),
    "冰霜dk": ("death_knight", "frost", "冰霜DK"),
    "邪dk": ("death_knight", "unholy", "邪恶DK"),
    "邪恶dk": ("death_knight", "unholy", "邪恶DK"),
    "死亡骑士": ("death_knight", "frost", "冰霜DK"),
    "dk": ("death_knight", "frost", "冰霜DK"),
    "湮灭": ("evoker", "devastation", "湮灭"),
    "增辉": ("evoker", "augmentation", "增辉"),
    "恩护": ("evoker", "preservation", "恩护"),
    "恩护龙": ("evoker", "preservation", "恩护"),
    "治疗龙": ("evoker", "preservation", "恩护"),
    "奶龙": ("evoker", "preservation", "恩护"),
    "龙人": ("evoker", "devastation", "湮灭"),
    "唤魔师": ("evoker", "devastation", "湮灭"),
    "戒律": ("priest", "discipline", "戒律"),
}

SPEC_SUGGESTION = "冰DK 邪DK 火法 冰法 元素萨 惩戒骑 狂徒 浩劫 狂暴战"

SPEC_DISPLAY_NAME = {
    "death_knight/frost": "冰霜DK",
    "death_knight/unholy": "邪恶DK",
    "death_knight/blood": "鲜血DK",
    "mage/fire": "火法",
    "mage/frost": "冰法",
    "mage/arcane": "奥法",
    "warlock/destruction": "毁灭术",
    "warlock/affliction": "痛苦术",
    "warlock/demonology": "恶魔术",
    "hunter/marksmanship": "射击猎",
    "hunter/survival": "生存猎",
    "hunter/beast_mastery": "兽王猎",
    "rogue/outlaw": "狂徒",
    "rogue/subtlety": "敏锐",
    "rogue/assassination": "刺杀",
    "priest/shadow": "暗牧",
    "priest/discipline": "戒律牧",
    "paladin/retribution": "惩戒骑",
    "warrior/arms": "武器战",
    "warrior/fury": "狂暴战",
    "warrior/protection": "防战",
    "paladin/protection": "防骑",
    "paladin/holy": "奶骑",
    "monk/windwalker": "踏风",
    "monk/brewmaster": "酒仙",
    "monk/mistweaver": "织雾",
    "demon_hunter/havoc": "浩劫",
    "demon_hunter/devourer": "噬灭DH",
    "demon_hunter/vengeance": "复仇",
    "druid/balance": "平衡德",
    "druid/feral": "野性德",
    "druid/guardian": "熊德",
    "druid/restoration": "奶德",
    "shaman/elemental": "元素萨",
    "shaman/enhancement": "增强萨",
    "shaman/restoration": "恢复萨",
    "priest/holy": "神牧",
    "evoker/devastation": "湮灭",
    "evoker/augmentation": "增辉",
    "evoker/preservation": "恩护",
}

# bloodmallet 不提供仿真数据的治疗专精
UNSUPPORTED_SPECS = {
    "evoker/preservation": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
    "priest/discipline": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
    "priest/holy": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
    "paladin/holy": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
    "monk/mistweaver": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
    "druid/restoration": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
    "shaman/restoration": "当前数据源 bloodmallet 暂不提供治疗专精的仿真数据",
}


# QQ 官方指令菜单点选出来的指令会把参数名一起带上，例如
# 「饰品排行 专精 射击猎」/「BIS 专精：火法」/「饰品排行 <专精> 元素萨」，
# 这些参数名和占位括号都不是专精名的一部分，解析前先剥掉。
ARG_LABELS = ("专精", "职业", "spec", "class")
_LABEL_SEPS = " \t:：=＝、,，"
_BRACKETS = "<>《》【】[]（）()「」"


def strip_arg_label(s: str) -> str:
    """剥掉参数名标签（可连写多个）与紧随的分隔符/占位括号。

    只剩标签没有值时（用户只点了菜单没填专精）返回空串，交给调用方提示用法。
    """
    out = (s or "").strip().strip(_BRACKETS).strip()
    while out:
        low = out.lower()
        for lab in ARG_LABELS:
            if low.startswith(lab):
                out = out[len(lab):].strip(_BRACKETS).strip(_LABEL_SEPS).strip()
                break
        else:
            break
    return out


def resolve_spec(s: str) -> tuple[str, str, bool]:
    """将用户输入的中文/缩写专精名解析为 bloodmallet 的 class/spec。"""
    s = strip_arg_label(s).lower().replace(" ", "").replace("：", ":")
    if s in SPEC_ALIAS:
        return SPEC_ALIAS[s][0], SPEC_ALIAS[s][1], True
    if s in SPEC_TOKEN_BY_EN:
        return SPEC_TOKEN_BY_EN[s][0], SPEC_TOKEN_BY_EN[s][1], True
    return "", "", False