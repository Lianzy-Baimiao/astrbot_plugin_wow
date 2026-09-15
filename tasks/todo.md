# tasks/todo.md — v1.1.12：纯文本 MD 化（带开关/黑白名单）+ 天赋X兼容

- [x] 服务层 MD 化：wclfmt / reset / punish / punishfeed / kernel / misc(物价+地下堡)
- [x] main.py：HELP_TEXT、roster、新闻文本块 MD 化
- [x] 天赋兼容：T_TALENT_PREFIX 正则 + talent_prefix_cmd（7 用例验证）
- [x] MD 开关：markdown_output（总开关，默认开）
- [x] 群黑白名单：markdown_group_mode(all/whitelist/blacklist) + markdown_groups
- [x] strip_markdown 剥离器：**加粗**/`代码`/[链接](url)→文字：url；全角＊不动；单*不吃
- [x] 出口接线：11 处事件回复走 _md()；定时推送经 _send_text_to→_md_for_umo
- [x] _conf_schema.json 加 3 项配置；README 补说明
- [x] 验证：py_compile、strip 冒烟（天赋/处罚/帮助/边界）、判定矩阵 10 用例
- [x] 打包 _pack_wow.py 校验、发 Release v1.1.12

## Review
- Git：本地与远端历史分叉（远端 v1.1.11 是重做的提交），rebase 冲突后改为
  cherry-pick 到 origin/main 之上，metadata 冲突手选 v1.1.12。
- 设计：服务层只产 MD 一种格式；关闭开关时在 main.py 出口统一剥 MD，
  不往服务函数穿参、无双份分支。私聊随总开关，群聊受黑白名单控制。
