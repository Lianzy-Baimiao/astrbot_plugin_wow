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

## v1.1.30 — 角色卡评分标注来源 + 分专精分数（2026-09-19）
- [x] 发布 v1.1.30（d69b6c1）
- [x] 起因：神之宣告〈烈焰峰〉角色卡 2069 vs wcl 卡 3151.11，用户质疑分数对不上
- [x] 排查结论（重要，非插件 bug）：WCL 与 raider.io **单局算分完全同源**（5 本 +15 的单局分逐位一致），
      分歧全在档案归属——该角色同名同服有两条 raider.io 记录（删号/腾名后新角色占用旧名）：
      旧档案 ID 8729964（邪DK，8 月末 M+ 2920、8/8H），活体档案 308739256（血DK，2069、5/8M）。
      WCL 按「名字+服务器」记账跨身份累积 8 本成绩 → 3151.11；raider.io 活体档案只有新身份
      9 月起的 5 本 → 2068.7。缺的 3 本（ToSF+10、Vale+12、Voidscar+12）在旧身份名下
- [x] wcl 卡「评分」→「WCL评分」，角色卡面板「大秘境评分」→「大秘境评分（Raider.IO）」，消除两套数字歧义
- [x] charinfo.py：CLASS_SPEC_ORDER 表 + spec_scores（raider.io 返回里的 spec_0..3 原本被丢弃）
- [x] charinfo.html：评分面板新增「专精」chip 行（只显 >0），总分/角色条/单局分改一位小数
- [x] main.py：_CLIP_CHARINFO 同步专精行高度（实测 dk 1562/est 1566、双修武僧 1625/est 1626，均覆盖）
- [x] spec_N 下标顺序实测：按**游戏天赋界面顺序**而非专精 ID 升序——武僧 spec_1=织雾（3 个酒仙+织雾
      双修样本一致）、德鲁伊 spec_3=恢复、DK spec_2=邪恶；全部 13 职业表按此口径
- [x] 渲染冒烟：Jinja2 本地渲染 + playwright 截图目检（单专精 DK / 双修武僧两张卡）
- [ ] 全 handler 桩冒烟 + 真实 t2i 端点出图（下轮部署前跑一遍即可）

### 补充：转移前成绩整合（用户确认根因为转子战网，同日）
- [x] raider.io 无按 ID 取旧档案的公开接口（`id=`/`characterId=` 均 400），整合源用 WCL：
      按「名字+服务器」记账跨身份留存，单局算分与 raider.io 同源（已实测逐位一致）
- [x] charinfo.py：fetch_char 增拉 mythic_plus_best_runs（逐本最佳，合计≈官方 all）；
      _integrate_transfer_history 逐本取两边较高者，extra_count≥1 且总分>官方+1 才生效
- [x] 角色卡大数字显示整合分，注明「总评分 · 含转移前 N 本（Raider.IO 当前档案 xxx）」；
      角色/专精明细与排名仍用官方档案（排名语义只属于活体档案）
- [x] main.py：charinfo_cmd 传 self._wcl；估算器整合行 +18（实测 est 1584 vs 实际 1562）
- [x] 三路径实测：DK+凭证 整合 3151.2/转移前 3 本；无转移武僧 None；无凭证 None
### 补充2：整合覆盖整个评分面板（用户实测反馈，同日）
- [x] 用户实测发现整合只替换了总分，专精行/角色条仍是活体档案数据 → 已全线切整合口径：
      角色条 = max(raider.io 角色分, WCL allStars 按角色归并)；专精行 = max(spec_N, allStars)
- [x] 专精行改为全专精展示（0 分灰显 ci-spec-zero），鲜血 0 不再隐藏，卡片自解释归属
- [x] 归属实证：每条战绩原始字段 spec=Unholy(id 252, role dps)、tank=0 → 2068.7 是邪恶的，
      不是鲜血（官网横幅只是「当前专精+总分」并排展示，非归属）；WCL 转移前另有鲜血 331.2
- [x] run 对象的 spec.ordinal 就是 spec_N 下标官方定义（Unholy=2 与映射表吻合）
- [x] 重新打包校验通过（失败项 0），_smoke 归档 v1.1.30
### 补充3：整合改为纯 raider.io 双档案合并（用户否决 WCL 方案，同日）
- [x] 用户明确：整合对象是两条 raider.io 档案，不是 WCL 数据 → 撤掉 charinfo 的 WCL 依赖
- [x] 发现站内内部接口（浏览器抓包）：`/api/characters/cn/{realm}/{名字}-{旧ID}?season=...`
      可取冻结旧档案全量数据；`mythicPlusScores` 有 all/dps/healer/tank/spec_0..3 五套
      逐本 runs（zoneId+score），两档案同构 → 逐 zoneId 取较高者合并，全部 raider.io 口径
- [x] 旧档案 ID 无法自动发现（search 只索引在玩角色、persona_id 均 0、两档案 JSON 无互引）
      → 命令支持 `角色 名字 服务器 [旧档案ID或raider.io链接]`；整合一次写入 char_links.json，
      之后普通查询自动带上（实测：第二次普通查询自动整合生效）
- [x] 归属澄清：2068.7 是邪恶的（每条战绩 spec=Unholy/role=dps，tank=0），鲜血是当前专精
      但本赛季无成绩；旧档案另有血DK 347.7（spec_0），比 WCL allStars 显示的 331.2 更准
- [x] 合并结果（神之宣告）：总分 3155.7（旧档案含 ToSF +11=336.5，WCL 口径 3151.2 少算了它）、
      输出 3155.7、坦克 347.7、专精 鲜血 347.7/冰霜 0/邪恶 3155.7
- [x] spec_N 下标顺序再获官方佐证：内部接口 spec_0=鲜血/坦克、spec_2=邪恶，与 CLASS_SPEC_ORDER 一致
- [x] 重新打包校验通过，_smoke 归档
### 补充4：旧档案自动发现（用户提供 /cn/search 线索，同日）
- [x] 用户发现 raider.io/cn/search 高级搜索能同时搜出 2 条档案 → 自动发现有解
- [x] 抓包定位接口：/api/search-advanced?type=character&name[0][contains]=名&limit=100&offset=0
      返回含冻结旧档案（名字带 -旧ID 后缀，如 神之宣告-8729964）
- [x] charinfo.py：_search_same_name_records（同服+精确名/后缀名过滤，30 分钟缓存）；
      普通查询即自动发现旧档案并整合，手动带 旧档案ID/链接 仍作为补充
- [x] 防误并护栏：旧档案职业与活体不同则跳过（名字被他人复用的场景）
- [x] 实测：普通查询自动出整合卡 3155.7；无旧档案角色不受影响；打包校验通过
