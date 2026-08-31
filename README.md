# astrbot_plugin_wow

魔兽世界综合插件（AstrBot）。整合了 ZeroBot-Plugin 中 16 个魔兽相关插件的全部功能，统一为一个插件。

**所有指令都是裸词触发，`` 前缀可省略**（群里直接发 `词缀`、`BIS 火法`、`角色 阿尔萨斯 白银之手` 即可；带 `` 也一样能用）。
发 `魔兽帮助` 可列出全部指令。

> 开机 / 关机 / 电脑状态 已拆分为独立插件 **astrbot_plugin_songguo_power（松果电子开关机）**，不在本插件内。

作者：lianzy

## 功能与指令

| 原插件 | 指令 | 说明 |
|---|---|---|
| wcl | `wcl 角色名 服务器名` | WCL 大秘境战绩速查（Warcraft Logs GraphQL v2） |
| charinfo | `角色 角色名 服务器名` | 魔兽角色卡（装等/评分/排名/最近大秘境/团本进度/16 装备槽） |
| wowboard | `名单` `名单 添加 群友名 角色名 服务器` `名单 删除 编号` | 魔兽群名单管理 |
| wowboard | `榜单 [装等] [详情] [刷新]` | 群内分数/装等榜（RIO 主源 + WCL 回退） |
| wowboard | `周报` | 本周进步榜（对比上周快照） |
| wowboard | `查卡 <群友名或角色名>` | 名单角色资料卡（子串匹配） |
| wowguild | `公会 公会名 [服务器]` | 公会资料卡（团本进度/职业分布） |
| wowguild | `团本排行 [难度] [团本]` | 团本进度排行 TOP20 |
| bis | `饰品排行 <专精>` | bloodmallet 饰品排行（**单体+5目标双区块**，真实图标 + 多装等 DPS 曲线，基准 = 满级英雄 321 装等） |
| bis | `BIS <专精>`（别名 `bis`/`BIS推荐`/`装备推荐`） | BIS 推荐卡（饰品Top3/副属性/最佳种族，出图） |
| specrank | `强度榜 [aoe]` | 全职业专精强度榜 |
| mpaffix | `词缀` `下周词缀` | 本周/下周大秘境词缀（含重置倒计时） |
| blizzardnews | `魔兽新闻` `魔兽新闻改` `魔兽新闻状态` | 暴雪新闻（按群去重）；状态查看本群推送开关 |
| blizzardnews | `魔兽新闻推送 开/关/状态/测试` | 本群开启后**每 5 分钟检查**，有更新自动推送（开/关/测试需管理员） |
| wowcal | `日历 [关键词]` | 魔兽事件日历（wow.kernel.moe） |
| wowgacha | `开箱 [数量]` `红手榜 [数量]` | 开箱抽奖/红手积分榜 |
| wowquote | `BOSS语录 [BOSS名]` | 经典 BOSS 台词卡 |
| wowreset | `重置` `重置提醒 开/关/状态/测试` | 重置倒计时/周四自动推送 |
| dixiabao | `地下堡饰品` | 当日地下堡饰品 |
| wowinfo | `事件` `事件 <版本>` `<版本>事件` `徽章` `大米成功率 [层数]` `大米排行榜` | 版本事件/限时率/专精排行（条形图，数值中文化；排行榜含**输出/防御/治疗**三段，列出当前全部专精，不写死行数） |
| chishenme | `吃什么` `X天赋`（含 `鸟德天赋`/`DK天赋` 等 ~140 别名） `物价 a、b` `低保` | 娱乐与实用小工具 |
| ngajiexi | 群内发送 NGA 帖子链接 | 自动生成帖子卡片 |

## 安装

1. 将本目录复制到 AstrBot 的 `data/plugins/astrbot_plugin_wow`
2. 在 AstrBot WebUI 插件页启用并重载插件
3. 依赖自动安装：`httpx`、`openpyxl`、`playwright`（requirements.txt 声明，AstrBot 自动 pip 安装）
4. **魔兽新闻网页截图**：Playwright 浏览器组件（约 150MB）在**首次使用 `/魔兽新闻` 时自动后台下载**，无需任何手动操作；下载完成前自动回退为新闻卡片。

## 配置（WebUI 插件配置页）

- `wcl_client_id` / `wcl_client_secret`：Warcraft Logs API 凭证（可选，也可放环境变量 `WCL_CLIENT_ID``WCL_CLIENT_SECRET` 或仓库根目录 `wcl_cred.json`）
- `default_realm`：公会查询默认服务器（默认影之哀伤）
- `news_groups` / `reset_groups` / `weekly_report_groups`：定时推送目标（unified_msg_origin，可通过群内发 `重置提醒 开` 自动记录本群）
- `reset_time`：重置提醒推送时间（默认 06:50，周四）
- `weekly_report_day`：周报推送日（1=周一…7=周日，默认周三 20:00）

## 数据存储

所有持久化数据存放在 `data/plugin_data/astrbot_plugin_wow/`：榜单名单/周报快照（board.db）、开箱积分（gacha.db）、日历缓存、新闻去重记录、物价表（`prices.xlsx`，将原 CustomDecode xlsx 命名为 prices.xlsx 放入）。

## 说明

- 图片均通过 AstrBot `html_render`（HTML+Jinja2）渲染，卡片版式对齐原 ZeroBot 插件绘制风格（深色底 #141519、金色 #FFC14D 头带、斑马纹榜单等，各插件专属布局）
- 物品/副本/团本名内置离线中文表（`wow/data/*_cn.json`，来源于 wago.tools zHCN），查询先命中表内、未命中再线上补齐；无网络时常用装备/副本/团本仍显示中文
- 网络请求使用 httpx 异步客户端
- **魔兽新闻截图**：Playwright 截新闻详情页（组件缺失自动后台下载）
- 数据源现状：bloodmallet 只对部分专精提供仿真数据，`BIS`/`饰品排行` 遇到没数据的专精会明确说明是数据源缺口（血锤官网标注的 missing MID2 profiles 专精：惩戒骑/武器战/狂暴战/浩劫DH/平衡德/野德/熊德/踏风/湮灭/增辉 等，等血锤补 profile 后自动恢复）；`强度榜` 页脚会标注本次跳过了几个专精
- `饰品排行`/`BIS` 基准装等 = 满级英雄（321），随血锤 simulated_steps 自动对齐
- `饰品排行`/`BIS` 兼容 QQ 官方指令菜单点选出来的带参数名格式：`饰品排行 专精 射击猎`、`BIS 专精：火法`、`饰品排行 <专精> 元素萨` 与原来的 `饰品排行 射击猎` 等价；只点菜单没填专精时回提示用法
- 已支持 Midnight(12.0) 恶魔猎手第三专精 **噬灭**（Devourer，中文名取自 wago.tools `ChrSpecialization` zhCN）：`大米排行榜`、`饰品排行 噬灭`、`强度榜`、`噬灭天赋` 均覆盖
- `大米排行榜` 按 mythicstats 的三段一起出图：**输出 27 / 防御 6 / 治疗 7**，共 40 个专精。三段量纲一致（都是 DPS），但名次与 Tier 都是段内相对，所以条长在段内归一化（各段第一 = 100%）；认不出的新专精按英文名照常显示并记日志，不再静默漏行

## AstrBot 使用要点（重要）

1. **指令触发**：全部指令用 `@filter.regex` 注册，**不受唤醒前缀限制** —— 群聊里裸词、`/` 前缀、`@机器人 + 指令` 三种都能触发。NGA 链接嗅探同样无需前缀（裸链接或夹在句中都行）。
   为避免把正常聊天当指令，带中文参数的指令要求分隔符（`角色 阿尔萨斯 白银之手` 有效，`角色扮演游戏真好玩` 不触发）；`<版本>事件`、`<专精>天赋` 只在认得出版本名/职业名时才响应。
2. **管理权限**：`名单 添加/删除`、`榜单 刷新`、`重置提醒 开/关/测试`、`魔兽新闻推送 开/关/测试` 需要管理员。AstrBot 的管理员 = WebUI 配置里的 `admins_id`（不是 QQ 群管理），用 `/sid` 拿到自己的 ID 后加进去。
3. **升级**：改版后请**先删除服务器上的整个 `astrbot_plugin_wow` 目录再解压新包**，不要增量覆盖（新旧文件混装会导致运行时 `has no attribute` 崩溃）。

## 灵感来源

本插件移植自 [ZeroBot-Plugin](https://github.com/FloatTech/ZeroBot-Plugin) 的以下插件目录：
`plugin/{wcl, wowinfo, wowguild, wowboard, bis, specrank, charinfo, mpaffix, blizzardnews, wowcal, wowgacha, wowquote, wowreset, dixiabao, ngajiexi, chishenme}` 以及 `internal/wclclient`。原项目采用 MIT 许可证。
`chishenme` 的开机/关机/电脑状态已拆到 `astrbot_plugin_songguo_power`。

## License

MIT