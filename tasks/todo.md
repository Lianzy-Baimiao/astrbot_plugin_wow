# tasks/todo.md — v1.1.16：宠物对战世界任务预警（重量级野兽）

- [x] 数据源验证：todayinwow.com /api/wqs（NA+legion，每日 15:00 UTC 批次，Active+end_timestamp）
- [x] 时区推算：美服批次北京 23:00 结束 → 国服次日 07:00–23:00 可做（16 小时窗口）
- [x] wow/data/petquests.py：58 任务中文名表 + 区域/奖励/阵营翻译（wowhead CN 重定向抓取）
- [x] wow/services/petwq.py：fetch_active_pets（10 分钟缓存）、cn_window、账本（petwq_bob_seen.json）、query_text、push_check
- [x] main.py：宠物 [详情] 指令、宠物推送 开/关/状态/测试（复用推送四件套）、定时器 16:05 检查、HELP_TEXT
- [x] _conf_schema.json：pet_push_groups；README 指令表+原理+配置说明
- [x] 测试：py_compile、AST 结构、正则 11 用例、窗口/解析/账本/翻译单测、实弹 query_text、模拟 BoB push_check、strip_markdown
- [x] 任务中文名 56/58 经 wowhead 验证（49057/49058 限流未取到，暂用通行译名，后续对表）
- [x] 打包 zip、git 提交推送、发 Release v1.1.16

## Review
- 数据源只认 Active + end_timestamp 的宠物任务；CN region 返回全空，确认必须走 NA 预测。
- 推送定时 16:05（非整点）：美服夏令时 15:00 UTC 重置 = 北京 23:00，16:05 时美服当天数据必然已刷新。
- 名表新任务回退英文原名，不影响功能。
- wowhead CN 抓名走重定向 URL slug，限流凶（约 15 连发后 403），间隔 6-10s + 多轮退避（60s~900s）可逐步拿全。
