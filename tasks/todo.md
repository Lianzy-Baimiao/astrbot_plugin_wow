# tasks/todo.md — v1.1.16~v1.1.18：宠物对战世界任务通报（重量级野兽）

- [x] 数据源验证：todayinwow.com /api/wqs（NA+legion，每日 15:00 UTC 批次，Active+end_timestamp）
- [x] wow/data/petquests.py：58 任务中文名表（56 经 wowhead 验证，49057/49058 暂用通行译名）+ 区域/奖励/阵营翻译
- [x] wow/services/petwq.py：fetch_data（10 分钟缓存 + 野兽 last-seen）、cn_window、账本（自动补记）、query_text、push_text
- [x] main.py：宠物 [详情]、宠物推送 开/关/状态/测试、定时器 16:05 通报、HELP_TEXT
- [x] v1.1.16 发布（4f85d40/1f8e0d5）
- [x] v1.1.17（3405620）：窗口改为「批次结束日当日 07:00 起」——**改错了**，用户纠正
- [x] **v1.1.18 模型定稿（用户确认）**：美服 16 点（北京 07:00）查到的当前批次 = 国服**下一天** 07:00
      才开始的批次。即国服比美服晚一批：批次美服结束后 8 小时、国服次日 07:00 重置才开始，
      窗口 = 批次结束日（北京）的次日 07:00 起 24h（v1.1.16 的起始日其实是对的，只是结束时刻写成了
      当天 23:00，应为第三日 07:00）。任何时刻查询都是预测：白天查 = 国服明天，夜里查 = 国服后天
- [ ] 待国服实机抽查验证：今日（窗口起始日）游戏内宠物任务应与推送列表一致

## v1.1.26 — 修复预告推送半成品批次（2026-09-18）
- [x] 根因：源站新批**逐条落库**，`push_text` 只判「非空」→ 13:00 只捞到 1 条就当完整推出去
- [x] 双判据（用户确认）：跨轮稳定（本轮与上一轮明日 quest_id 集合一致）+ 数量下限（明日数 ≥ 今日数），
      两条都满足才推；今日拉取失败时降级只靠稳定性
- [x] 新增 `_POLL_STATE = petwq_poll_snap.json` 快照，`day` 不匹配自动作废（跨天不误判）
- [x] main.py 轮询与 mark_pushed 时机不变；手动 query_text 不受影响
- [x] 离线模拟验证：1条→仍1条→补齐5条→同样5条 = None/None/None/PUSH；跨天作废、降级路径均正确
- [x] 发布 v1.1.26（3c5129b）
- [ ] 明早观察：12:00 起轮询日志应出现若干「明日批次未就绪」后再推送，且推送批次为 5 条

## v1.1.27 — 物价改用 Auctionator 本地库（2026-09-18）
- [x] 线上源评估：**两条都断**。暴雪官方 API 对 CN region 只开放 WoW Token 索引，拍卖行拿不到；
      bnade.com 已不是魔兽站点（改成建站公司页面），`/api/realms`、`/api/v2/items`、`/api/auctions` 全 404
- [x] 结论：只能读本机 `WTF/Account/*/SavedVariables/Auctionator.lua` 的 `AUCTIONATOR_PRICE_DATABASE`
- [x] 该库是 CBOR 序列化的（`__dbversion=8`，Auctionator 在 `PLAYER_LOGOUT` 用
      `C_EncodingUtil.SerializeCBOR` 写盘）→ `tools/export_prices.py` 内置极简 CBOR 解码器，
      **纯标准库、不加 cbor2 依赖**；Lua 字面量按 `\ddd` 十进制反转义
- [x] 物品名在导出时烤进 JSON（wago.tools zhCN ItemSparse 全量 175746 条，缓存 7 天），云端不联网
- [x] `wow/services/prices.py` 读 prices.json，按 mtime 缓存，文件一换自动重载；删掉旧的 xlsx 实现
- [x] 自动上传：`tools/upload_prices.py`（SFTP，先传 .tmp 再 rename 的原子写）+
      `tools/sync_prices.py` 一条命令串起导出→上传
- [x] 凭证不进仓库：命令行 > 环境变量 > `tools/deploy.json`（已 gitignore）> 交互输入，文件权限 0600
- [x] 实测：31407 条 / 2.16MB，价格新鲜到 2026-09-17；服务器插件真实代码路径查询通过
- [x] 修 bug①：工艺品质三档共享名字、ID 相邻且无装等，原按「名字+装等」归组把三档压成一条
      （全表 972 组受影响）→ 改按 itemID 归组，用 ①②③ 标档位
- [x] 修 bug②：itemID 去重前，只按装等分档的装备每行都挂了无意义的「①」
- [ ] 上传仍需手动跑 `sync_prices.py`（定时同步待定：要看游戏里多久扫一次拍卖行，扫之前同步等于白跑）
- [ ] 宠物 `p:` 键（964 条）未导出：按 speciesID 存，名字要另查 BattlePetSpecies 表

## Review
- 物价：国服拍卖数据**没有可用线上源**，这是整个方案只能走本地导出的根因。
- 数据只有「当前在玩的服务器」可靠：贫瘠之地那 1.7 万条是旧 schema 被惰性 CBOR 化的残留，
  一条最新价都没有，`pick_realm` 按「有无 m 字段」计分自动跳过这种。
- 新鲜度取决于玩家自己扫拍卖行且登出才写盘 → 回复头部固定带「数据截止」，
  单条超 7 天加 ⚠ 和日期，避免群友拿旧价当真。
- 部署踩到的坑：服务器曾是 v1.1.26 而本地仓库 v1.1.18（落后 9 个提交），
  当时按行 patch 而非整目录覆盖以保住服务器的欧服宠物逻辑；**正确做法是先 git pull 对齐**。
- 窗口公式三版演变：v1.1.16 end+1d@07:00~23:00（起始对、结束错）→ v1.1.17 end-16h~+8h（全错）
  → v1.1.18 end+1d@07:00 ~ +2d@07:00（用户模型定稿）
- 数据源只认 Active + end_timestamp；CN region 无数据，必须走 NA。
- EU/NA 实测同一天同一批；国服轮换偏移一天，按用户国服经验实现，游戏内抽查为准。
- wowhead CN 抓名走重定向 slug，约 15 连发后 403，间隔 6-10s + 多轮退避可拿全。
- 推送定时 16:05（用户指定）；此时拉到的批次 = 国服明天的，文案相对日（今天/明天/后天）动态生成。
