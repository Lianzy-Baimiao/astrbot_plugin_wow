# tasks/todo.md — 纯文本 MD 化 + 天赋X兼容

- [x] wclfmt.format_profile MD 化
- [x] reset.remind_text MD 化
- [x] punish.format_hits MD 化（保留 safe_name ＊保护，冒烟确认 36 条截断分支 + 全角＊）
- [x] punishfeed.report_text MD 化
- [x] kernel.fetch_event_card MD 化
- [x] misc.query_price / delver_menu MD 化
- [x] main.py：HELP_TEXT 分区标题加粗、roster_cmd 标题加粗、新闻文本块标签加粗（两处）
- [x] main.py：新增 T_TALENT_PREFIX 正则 + talent_prefix_cmd handler
- [x] README.md 补「天赋X」兼容说明
- [x] 语法检查 + 冒烟验证
- [x] 提交（不加 AI 署名尾注）

## Review

改动文件：main.py、wow/services/{wclfmt,reset,punish,punishfeed,misc}.py、wow/kernel.py、README.md。

MD 化（仍走 plain_result，只改字符串内容，客户端自行按 MD 渲染）：
- wcl：标题/角色名/属性行标签加粗，地城分项分数用 `` ` `` 包住
- 重置：标题 + 距重置/本周词缀/低保 标签加粗（定时推送同步受益）
- 处罚：汇总行加粗，赛季组头 `**赛季**`，记录 `- ` 列表；safe_name 全角＊保护保留并冒烟验证
- 处罚名单更新战报：标题加粗 + `- ` 列表
- 事件：头部加粗，tab 分隔改 `- **标题**：详情`
- 物价：标题加粗 + `- ` 列表 + 价格反引号
- 地下堡饰品：标题加粗 + `- ` 列表
- 帮助：5 个分区标题加粗
- 名单：标题加粗
- 新闻文本块（手动查询 + 定时推送）：标签加粗

天赋兼容：`T_TALENT_PREFIX = r"^天赋[\s:：]*(.*)$"`（紧贴/空格/冒号均认），
handler 与 talent_cmd 同逻辑，`is_talent_key` 不认识就静默放过（裸词「天赋」、
「天赋垃圾词」均验证不触发）。首版正则要求分隔符导致「天赋火法」不命中，
已改为分隔符可选并用 7 个边界用例验证。

验证：py_compile 全过；wcl（中文表命中）、punish（36 条截断 + ＊保护）、
punishfeed、delver、remind_text（真实网络）、天赋正则 7 用例全部 OK。

刻意不改：吃什么/低保（单行）、各单行错误与限流消息、2~3 行用法提示、
已是 MD 的天赋输出与「**强制**」tip、出图指令。
