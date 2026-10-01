(function () {
  "use strict";


  function byId(id) { return document.getElementById(id); }

  var toastTimer = null;
  function toast(msg, isErr) {
    var el = byId("toast");
    el.textContent = String(msg || "");
    el.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.className = "toast"; }, 3200);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // 面板跑在 AstrBot 仪表盘的 iframe 里，浏览器会屏蔽 window.prompt/confirm，
  // 所以用页内弹窗替代（否则「编辑备注」点了没反应）。
  function _modal(opts) {
    return new Promise(function (resolve) {
      var mask = byId("modalMask");
      var input = byId("modalInput");
      byId("modalTitle").textContent = opts.title || "";
      byId("modalMsg").textContent = opts.message || "";
      input.hidden = !opts.prompt;
      if (opts.prompt) { input.value = opts.value || ""; }
      var previousFocus = document.activeElement;
      mask.hidden = false;
      byId("modalOk").focus();
      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); done(opts.prompt ? null : false); }
        if (e.key === "Tab") {
          var first = opts.prompt ? input : byId("modalOk");
          var last = byId("modalCancel");
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
      mask.addEventListener("keydown", onKey);
      if (opts.prompt) { input.focus(); input.select(); }
      function done(val) {
        mask.hidden = true;
        mask.removeEventListener("keydown", onKey);
        if (previousFocus && previousFocus.focus) previousFocus.focus();
        byId("modalOk").onclick = null;
        byId("modalCancel").onclick = null;
        input.onkeydown = null;
        resolve(val);
      }
      byId("modalOk").onclick = function () { done(opts.prompt ? input.value : true); };
      byId("modalCancel").onclick = function () { done(opts.prompt ? null : false); };
      input.onkeydown = function (e) {
        if (e.key === "Enter") { e.preventDefault(); done(input.value); }
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(null); }
      };
    });
  }
  function promptModal(title, message, value) {
    return _modal({ prompt: true, title: title, message: message, value: value || "" });
  }
  function confirmModal(message, title) {
    return _modal({ prompt: false, title: title || "确认", message: message });
  }

  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
    if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
    return n + " B";
  }

  // 后端统一返回 {status, message, data}；status 不是 ok 就抛出 message。
  function unwrap(resp) {
    if (resp && typeof resp === "object" && "status" in resp) {
      if (String(resp.status).toLowerCase() !== "ok") {
        throw new Error(resp.message || "请求失败");
      }
      return resp.data || {};
    }
    return resp || {};
  }

  var _bridgeReady = null;
  function waitForBridge(timeoutMs) {
    if (_bridgeReady) return _bridgeReady;
    _bridgeReady = new Promise(function (resolve, reject) {
      var pollTimer;
      var expired = false;
      var timeout = setTimeout(function () {
        expired = true;
        clearTimeout(pollTimer);
        reject(new Error("面板桥接不可用，请在 AstrBot WebUI 里打开本页面"));
      }, timeoutMs || 8000);
      function finish(error, bridge) {
        if (expired) return;
        clearTimeout(timeout);
        if (error) reject(error);
        else resolve(bridge);
      }
      (function poll() {
        var bridge = window.AstrBotPluginPage;
        if (!bridge) { pollTimer = setTimeout(poll, 32); return; }
        Promise.resolve().then(function () {
          if (typeof bridge.ready === "function") return bridge.ready();
        }).then(function () { finish(null, bridge); }, function (err) { finish(err); });
      })();
    }).catch(function (err) {
      _bridgeReady = null;
      throw err;
    });
    return _bridgeReady;
  }

  function apiGet(path, params) {
    return waitForBridge().then(function (bridge) {
      return bridge.apiGet(path, params || {}).then(unwrap);
    });
  }

  function apiPost(path, body) {
    return waitForBridge().then(function (bridge) {
      return bridge.apiPost(path, body || {}).then(unwrap);
    });
  }

  function fail(err) { toast((err && err.message) || "操作失败", true); }

  // Local appearance preferences never touch plugin configuration.
  var prefs = { theme: "follow", accent: "gold", compact: false, motion: true };
  var followTheme = "light";
  var themeObserver;
  var dirty = { groups: false, settings: false };
  var busy = false;
  var loaded = false;
  var views = {
    overview: ["指挥总览", "COMMAND CENTER", "今天的艾泽拉斯，尽在掌握。"],
    groups: ["群订阅", "COMMUNITY NETWORK", "一个矩阵，管理所有群与功能的连接。"],
    schedule: ["定时任务", "AUTOMATION", "每一次提醒，都在正确的时间抵达。"],
    data: ["数据资产", "DATA ARCHIVE", "物价、榜单与缓存，井然有序。"],
    appearance: ["界面外观", "PERSONALIZATION", "晨曦或暗夜，选择让你舒适的工作空间。"],
    settings: ["插件设置", "CONFIGURATION", "调整推送节奏，让工具箱按你的方式运行。"]
  };

  function showView() {
    var key = location.hash.slice(1);
    if (!Object.prototype.hasOwnProperty.call(views, key)) key = "overview";
    document.querySelectorAll(".view").forEach(function (el) { el.hidden = el.id !== "view-" + key; });
    document.querySelectorAll(".nav-item").forEach(function (el) {
      var active = el.dataset.go === key;
      el.classList.toggle("is-active", active);
      if (active) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
      el.setAttribute("title", views[el.dataset.go][0]);
      el.setAttribute("aria-label", views[el.dataset.go][0]);
    });
    byId("viewTitle").textContent = byId("breadcrumbTitle").textContent = views[key][0];
    byId("viewEyebrow").textContent = views[key][1];
    byId("viewSubtitle").textContent = views[key][2];
  }

  function applyPrefs() {
    var root = document.documentElement;
    if (themeObserver) themeObserver.disconnect();
    var theme = prefs.theme === "follow" ? followTheme : prefs.theme;
    root.dataset.theme = theme;
    root.dataset.accent = prefs.accent;
    root.dataset.compact = String(prefs.compact);
    root.dataset.motion = String(prefs.motion);
    byId("prefTheme").value = prefs.theme;
    byId("prefAccent").value = prefs.accent;
    byId("prefCompact").checked = prefs.compact;
    byId("prefMotion").checked = prefs.motion;
    byId("btnTheme").textContent = theme === "dark" ? "☀ 浅色" : "☾ 深色";
    byId("btnTheme").setAttribute("aria-label", theme === "dark" ? "切换为浅色主题" : "切换为深色主题");
    if (themeObserver) themeObserver.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
  }

  function savePrefs() {
    applyPrefs();
    try {
      localStorage.setItem("wowPanelAppearance", JSON.stringify(prefs));
      byId("prefHint").textContent = "外观已保存到当前浏览器。";
    } catch (e) { byId("prefHint").textContent = "浏览器限制了存储，外观仅在本次打开时有效。"; }
  }

  function initTheme() {
    var params = new URLSearchParams(location.search);
    var theme = params.get("theme") || document.documentElement.dataset.theme;
    if (theme !== "dark" && theme !== "light") {
      var isDark = params.get("isDark");
      try { if (isDark === null) isDark = localStorage.getItem("astrbot_plugin_theme_is_dark"); } catch (e) { /* light default */ }
      theme = isDark === "true" ? "dark" : "light";
    }
    followTheme = theme;
    try {
      var saved = JSON.parse(localStorage.getItem("wowPanelAppearance") || "{}");
      if (["follow", "light", "dark"].indexOf(saved.theme) >= 0) prefs.theme = saved.theme;
      if (["gold", "blue", "green"].indexOf(saved.accent) >= 0) prefs.accent = saved.accent;
      if (typeof saved.compact === "boolean") prefs.compact = saved.compact;
      if (typeof saved.motion === "boolean") prefs.motion = saved.motion;
    } catch (e) { /* Invalid or unavailable storage must not prevent startup. */ }
    themeObserver = new MutationObserver(function () {
      var hostTheme = document.documentElement.dataset.theme;
      if (hostTheme === "dark" || hostTheme === "light") followTheme = hostTheme;
      applyPrefs();
    });
    applyPrefs();
    window.addEventListener("storage", function (e) {
      if (e.key === "astrbot_plugin_theme_is_dark") {
        followTheme = e.newValue === "true" ? "dark" : "light";
        applyPrefs();
      }
    });
  }

  function markDirty(key, value) {
    dirty[key] = value;
    byId("draftNotice").hidden = !dirty.groups && !dirty.settings;
    byId("btnSaveGroups").textContent = dirty.groups ? "保存群名单 · 未保存" : "保存群名单";
    byId("btnSaveSettings").textContent = dirty.settings ? "保存设置 · 未保存" : "保存设置";
  }

  // Lock all server-backed edits during requests to avoid losing edits to late responses.
  function updateLocks() {
    ["view-groups", "view-settings"].forEach(function (id) {
      byId(id).setAttribute("aria-busy", String(busy));
      byId(id).querySelectorAll("input, select, button").forEach(function (el) { el.disabled = busy || !loaded; });
    });
    byId("btnReload").disabled = busy;
    byId("btnReload").textContent = busy ? "同步中…" : "↻ 同步数据";
  }

  function operation(action) {
    if (busy) return Promise.resolve();
    busy = true;
    updateLocks();
    return Promise.resolve().then(action).catch(fail).finally(function () {
      busy = false;
      updateLocks();
    });
  }

  function protectDrafts(keys, action) {
    if (busy) return;
    if (!keys.some(function (key) { return dirty[key]; })) return operation(action);
    return confirmModal("此操作会重新读取服务器数据并覆盖未保存的修改。确定放弃这些草稿吗？", "有未保存的修改").then(function (ok) {
      if (!ok) return;
      return operation(function () {
        return Promise.resolve(action()).then(function () {
          keys.forEach(function (key) { markDirty(key, false); });
        });
      });
    });
  }

  function refreshPanel() {
    return loadAll().then(function () {
      renderSettings();
      loaded = true;
      byId("loadError").hidden = true;
      byId("connectionText").textContent = "面板已连接";
      byId("connectionDot").classList.remove("error");
      byId("lastSync").textContent = "同步于 " + new Date().toLocaleTimeString("zh-CN", { hour12: false });
    }).catch(function (err) {
      byId("loadError").hidden = false;
      byId("loadError").textContent = "同步未完成：" + (err.message || "请求失败") + "。请点击「同步数据」重试。";
      byId("connectionText").textContent = "连接异常";
      byId("connectionDot").classList.add("error");
      throw err;
    });
  }

  function renderOverview() {
    var tasks = (state.schedule.rows || []).filter(function (row) { return row.enabled; });
    byId("taskRadar").innerHTML = tasks.slice(0, 3).map(function (row) {
      return '<div class="radar-row"><div><strong>' + esc(row.name) + '</strong><small>' + esc(row.when || "按配置执行") + '</small></div><span class="hint">' + esc(row.next_text || "等待下一次触发") + '</span></div>';
    }).join("") || '<p class="empty">暂无已启用的定时任务</p>';
    var issues = state.dead.length + state.duplicates.length;
    byId("healthTag").textContent = issues ? issues + " 项待检查" : "未发现异常写法";
    byId("healthTag").className = "tag" + (issues ? " warn" : "");
    byId("healthSummary").innerHTML = '<div><strong>' + state.instances.length + '</strong> 个平台实例已加载</div><p>' +
      (issues ? '检测到 ' + state.dead.length + ' 条失效写法、' + state.duplicates.length + ' 组重复目标，请在群订阅中检查。' : '未检测到失效平台写法或重复目标。实际推送结果仍取决于平台权限与连接状态。') + '</p>';
  }

  var state = {
    meta: {},
    status: {},
    rows: [],        // [{umo,label,group_id,group_name,count,flags:{key:bool},platform_*}]
    columns: [],     // [{key,label,hint}]
    summary: {},
    schedule: { rows: [] },
    settings: {},
    data: {},
    instances: [],   // 已加载平台实例 [{id,type,label,bare_id}]
    platforms: [],   // 配置里每个平台段几个群 [{platform,count,state}]
    dead: [],        // 平台实例不存在的写法
    duplicates: []   // 同一群号的多种写法
  };

  // ---------- 渲染：状态卡 ----------

  function renderStatus() {
    var st = state.status || {};
    var sum = st.summary || {};
    var sched = (st.schedule && st.schedule.rows) || [];
    var enabledTasks = sched.filter(function (r) { return r.enabled; }).length;
    var prices = st.prices || {};
    var pill = byId("runPill");
    pill.textContent = st.running ? "定时任务运行中" : "定时任务未启动";
    pill.className = "pill" + (st.running ? "" : " warn");

    var priceText = prices.exists
      ? (prices.items || 0) + " 条" +
        (prices.stale_days != null
          ? "（" + (prices.stale_days > 7 ? "⚠ " : "") + prices.stale_days + " 天前）"
          : "")
      : "未导入";
    byId("stats").innerHTML = [
      ['<div class="stat"><div class="n">', sum.groups || 0, '</div><div class="l">已配置群</div></div>'],
      ['<div class="stat"><div class="n">', sum.links || 0, '</div><div class="l">名单条目</div></div>'],
      ['<div class="stat"><div class="n">', enabledTasks, ' / ', sched.length, '</div><div class="l">启用中的任务</div></div>'],
      ['<div class="stat"><div class="n">', esc(priceText), '</div><div class="l">物价表</div></div>'],
      ['<div class="stat"><div class="n">', esc(prices.realm || "—"), '</div><div class="l">物价服务器</div></div>'],
      ['<div class="stat"><div class="n">', esc(prices.newest_text || "—"), '</div><div class="l">拍卖数据截止</div></div>']
    ].map(function (p) { return p.join(""); }).join("");
  }

  // ---------- 渲染：矩阵 ----------

  function renderMatrixHead() {
    var html = '<th class="grp">群</th><th>群号</th><th class="plat">平台</th>';
    state.columns.forEach(function (col) {
      html += '<th class="rot" title="' + esc(col.hint) + '">' + esc(col.label) +
        '<span class="col-hint">' + esc(col.key) + "</span></th>";
    });
    html += '<th style="width:60px">合计</th>';
    byId("matrixHead").innerHTML = html;
  }

  // 平台列：说清这条订阅走哪个实例（官方 openid / napcat 数字群号一眼可分）
  function platformCell(row) {
    var st = row.platform_state || "";
    var cls = st === "unknown" || st === "plain" ? " bad" : (st === "type" ? " fix" : "");
    var mark = st === "unknown" || st === "plain" ? "⚠ " : "";
    var title = "完整 umo：" + String(row.umo == null ? "" : row.umo);
    if (st === "unknown") {
      title += "\n这个平台实例当前没加载，推送会静默失败";
    } else if (st === "plain") {
      title += "\n裸群号且没探到可用平台实例，推送会静默失败";
    } else if (st === "type") {
      title += "\n写的是适配器类型名，插件会自动改写成实例 id 发出";
    }
    if (row.platform_type) {
      title += "\n适配器类型：" + row.platform_type;
    }
    return '<td class="plat' + cls + '" title="' + esc(title) + '">' +
      mark + esc(row.platform_text || "—") + "</td>";
  }

  function renderMatrix() {
    var kw = (byId("searchBox").value || "").trim().toLowerCase();
    var hideEmpty = !!(byId("hideEmpty") && byId("hideEmpty").checked);
    var rows = state.rows.filter(function (r) {
      // 搜索时一律参与匹配（方便找到没启用功能的群去勾选）；不搜索时才按开关隐藏空群
      if (!kw && hideEmpty && !(r.count > 0)) return false;
      if (!kw) return true;
      return (String(r.label) + " " + (r.group_name || "") + " " + (r.group_id || "") + " " +
        (r.platform_text || ""))
        .toLowerCase().indexOf(kw) >= 0;
    });
    byId("matrixCount").textContent = "显示 " + rows.length + " / " + state.rows.length + " 个群";
    var tb = byId("matrixBody");
    if (!rows.length) {
      var msg;
      if (!state.rows.length) {
        msg = "还没有群：点「刷新群列表」拉取机器人所在的群，或先在群里说句话";
      } else if (kw) {
        msg = "没有匹配的群";
      } else {
        msg = "这些群都没启用功能，已被「只看已启用功能的群」隐藏（取消勾选可看全部）";
      }
      tb.innerHTML = '<tr><td colspan="' + (state.columns.length + 4) +
        '" class="empty">' + msg + "</td></tr>";
      return;
    }
    tb.innerHTML = rows.map(function (row) {
      var cells = state.columns.map(function (col) {
        return '<td><input type="checkbox" data-umo="' + esc(row.umo) +
          '" data-key="' + esc(col.key) + '" aria-label="' + esc((row.group_name || row.group_id || row.umo) + " · " + col.label) + '"' +
          (row.flags[col.key] ? " checked" : "") + "></td>";
      }).join("");
      var trCls = (row.count ? "on" : "") + (row.reachable === false ? " dead" : "");
      return '<tr class="' + trCls.trim() + '">' +
        '<td class="grp" title="' + esc(row.label || row.umo) + '">' +
          '<button class="link" data-rename="' + esc(row.umo) + '" ' +
            'title="起个备注名（官方平台的群没有群名）">✎</button> ' +
          esc(row.group_name || "（无群名）") +
          (row.group_name ? "" : ' <span class="tag warn">无群名</span>') + "</td>" +
        '<td>' + esc(row.group_id || "—") + "</td>" +
        platformCell(row) +
        cells +
        '<td class="count">' + (row.count || 0) + "</td></tr>";
    }).join("");
    updateLocks();
  }

  // 诊断区：坏写法 + 同群号多写法（官方/napcat 的 id 不同，不会被误当重复）
  function renderDiag() {
    var lines = [];
    var insts = state.instances || [];
    if (insts.length) {
      lines.push("已加载平台：" + insts.map(function (i) {
        return "<code>" + esc(i.label) + "</code>" + (i.bare_id ? "（裸群号默认补到这里）" : "");
      }).join("、"));
    }
    var dead = state.dead || [];
    if (dead.length) {
      lines.push("⚠ " + dead.length + " 条写法指向不存在的平台实例（发不出去）：" +
        dead.map(function (d) { return "<code>" + esc(d.umo) + "</code>"; }).join("、"));
    }
    var dup = state.duplicates || [];
    if (dup.length) {
      lines.push("同一群号有多种写法（整理按钮只合并「类型名 → 实例 id」那种；" +
        "不同真实平台上的同号群请手动确认）：" +
        dup.map(function (d) {
          return esc(d.group_id) + " → " + d.umos.map(function (u) {
            return "<code>" + esc(u) + "</code>";
          }).join(" ／ ");
        }).join("；"));
    }
    byId("diagBox").innerHTML = lines.join("<br>");
  }

  // ---------- 渲染：定时任务 ----------

  function renderSchedule() {
    var rows = (state.schedule && state.schedule.rows) || [];
    var tb = byId("schedBody");
    if (!rows.length) {
      tb.innerHTML = '<tr><td colspan="6" class="empty">没有定时任务</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(function (r) {
      var when = esc(r.when || "");
      if (r.interval_sec && r.remaining_sec) {
        when += '<span class="col-hint">还有 ' + Math.round(r.remaining_sec / 60) + " 分钟</span>";
      }
      return "<tr>" +
        "<td><b>" + esc(r.name) + "</b></td>" +
        '<td><span class="tag' + (r.enabled ? "" : " off") + '">' +
          (r.enabled ? "开" : "关") + "</span></td>" +
        "<td>" + when + (r.groups ? '<span class="col-hint">' + r.groups + " 个群</span>" : "") + "</td>" +
        "<td>" + esc(r.next_text || "—") + "</td>" +
        "<td>" + esc(r.last_text || "—") + "</td>" +
        '<td><span class="hint">' + esc(r.note || "") + "</span></td>" +
        "</tr>";
    }).join("");
  }

  // ---------- 渲染：设置与数据 ----------

  function renderSettings() {
    var st = state.settings || {};
    var mods = (state.status && state.status.modifiers) || {};
    byId("cfgResetTime").value = st.reset_time || "";
    byId("cfgFestivalTime").value = st.festival_push_time || "";
    var days = mods.weekdays || [];
    byId("cfgWeeklyDay").innerHTML = days.map(function (d) {
      return '<option value="' + d.value + '">' + esc(d.label) + "</option>";
    }).join("");
    byId("cfgWeeklyDay").value = String(st.weekly_report_day || 3);
    var modes = mods.markdown_modes || [];
    byId("cfgMarkdownMode").innerHTML = modes.map(function (m) {
      return '<option value="' + esc(m.value) + '">' + esc(m.label) + "</option>";
    }).join("");
    byId("cfgMarkdownMode").value = st.markdown_group_mode || "all";
    var strip = st.markdown_strip_platforms || [];
    byId("mdNote").textContent = strip.length
      ? "当前强制剥 MD 的平台：" + strip.join("、") + "（在插件配置页改）"
      : "没有强制剥 MD 的平台；Markdown 总开关在插件配置页。";
  }

  function renderData() {
    var d = state.data || {};
    var items = [];
    var prices = d.prices || {};
    items.push('<div class="list-item"><span class="nm">物价表：' +
      (prices.exists
        ? prices.items + " 条 ｜ 服务器 " + esc(prices.realm || "?") +
          " ｜ 数据截止 " + (prices.newest_text || "?") +
          " ｜ 文件 " + (prices.mtime_text || "?") +
          (prices.stale_days != null && prices.stale_days > 7
            ? ' <span class="tag warn">已 ' + prices.stale_days + " 天没更新</span>"
            : "")
        : "还没导入（本机跑 tools/sync_prices.py 上传）") + "</span></div>");
    var board = d.board || {};
    items.push('<div class="list-item"><span class="nm">榜单名单：' +
      (board.available ? board.roster + " 个角色" : "（数据库未打开）") +
      (board.size ? " ｜ " + fmtBytes(board.size) : "") + "</span></div>");
    var gacha = d.gacha || {};
    items.push('<div class="list-item"><span class="nm">开箱积分：' +
      (gacha.available ? gacha.players + " 个玩家" : "（数据库未打开）") +
      (gacha.size ? " ｜ " + fmtBytes(gacha.size) : "") + "</span></div>");
    var punish = d.punish || {};
    items.push('<div class="list-item"><span class="nm">处罚名单：' +
      (punish.count || 0) + " 个文件" +
      (punish.files && punish.files.length
        ? "（最新 " + esc(punish.files[0].name) + " · " +
          esc(punish.files[0].modified_text) + "）"
        : "") + "</span></div>");
    var cache = d.cache || {};
    items.push('<div class="list-item"><span class="nm">缓存目录：' +
      (cache.files || 0) + " 个文件 ｜ " + fmtBytes(cache.bytes || 0) + "</span></div>");
    items.push('<div class="list-item"><span class="nm">数据目录：' +
      esc(d.data_dir || "—") + "</span></div>");
    byId("dataList").innerHTML = items.join("");
  }

  // ---------- 数据加载 ----------

  function loadMeta() {
    return apiGet("page/meta").then(function (d) {
      state.meta = d || {};
      state.columns = d.columns || [];
      renderMatrixHead();
    });
  }

  function loadGroups(refresh) {
    return apiGet("page/groups", refresh ? { refresh: "1" } : {}).then(function (d) {
      state.rows = d.rows || [];
      state.columns = d.columns || state.columns;
      state.summary = d.summary || {};
      state.instances = d.instances || [];
      state.platforms = d.platforms || [];
      state.dead = d.dead || [];
      state.duplicates = d.duplicates || [];
      renderMatrixHead();
      renderMatrix();
      renderDiag();
      renderOverview();
      byId("platHint").textContent = (state.platforms || []).length
        ? "已配置 " + (state.summary.groups || 0) + " 个群：" +
          state.platforms.map(function (p) {
            var bad = p.state === "unknown" || p.state === "plain";
            return p.platform + " " + p.count + " 个" + (bad ? " ⚠" : "");
          }).join("、")
        : "";
      byId("saveHint").textContent = d.refreshed
        ? "群列表已刷新（" + d.refreshed + " 个群有更新）"
        : "";
      if (refresh) {
        toast("群列表已刷新：共 " + state.rows.length + " 个群，其中 " +
          (d.named || 0) + " 个有名称");
      }
    });
  }

  function loadStatus() {
    return apiGet("page/status").then(function (d) {
      state.status = d || {};
      state.schedule = d.schedule || { rows: [] };
      state.settings = d.settings || {};
      renderStatus();
      renderSchedule();
      if (!dirty.settings) renderSettings();
      renderOverview();
    });
  }

  function loadData() {
    return apiGet("page/data").then(function (d) {
      state.data = d || {};
      renderData();
    });
  }

  function settleRequests(requests) {
    // Do not unlock on the first rejection: another response may still rebuild an editor.
    return Promise.allSettled(requests).then(function (results) {
      var rejected = results.find(function (result) { return result.status === "rejected"; });
      if (rejected) throw rejected.reason;
    });
  }

  function loadAll() {
    return settleRequests([loadMeta(), loadStatus(), loadGroups(false), loadData()]).then(renderOverview);
  }

  // ---------- 保存 ----------

  function collectRows() {
    // 直接读 DOM：勾选状态是唯一真相，避免 state 与界面不同步
    var boxes = byId("matrixBody").querySelectorAll('input[type="checkbox"][data-key]');
    var byUmo = {};
    Array.prototype.forEach.call(boxes, function (box) {
      var umo = box.getAttribute("data-umo");
      var key = box.getAttribute("data-key");
      if (!byUmo[umo]) {
        byUmo[umo] = { umo: umo, flags: {} };
      }
      byUmo[umo].flags[key] = box.checked;
    });
    // 没渲染到的行（被搜索过滤掉的）也要带上，否则保存会丢配置
    state.rows.forEach(function (row) {
      if (byUmo[row.umo]) {
        return;
      }
      var flags = {};
      state.columns.forEach(function (col) { flags[col.key] = !!row.flags[col.key]; });
      byUmo[row.umo] = { umo: row.umo, flags: flags };
    });
    return Object.keys(byUmo).map(function (k) { return byUmo[k]; });
  }

  function saveGroups() {
    var btn = byId("btnSaveGroups");
    btn.disabled = true;
    byId("saveHint").textContent = "保存中…";
    return apiPost("page/groups/save", { rows: collectRows() }).then(function (d) {
      var changes = d.changes || [];
      var detail = changes.map(function (c) {
        var parts = [];
        if (c.added.length) { parts.push("+" + c.added.length); }
        if (c.removed.length) { parts.push("-" + c.removed.length); }
        return c.label + " " + parts.join("/");
      }).join("；");
      toast(detail ? "已保存：" + detail : "已保存（没有变化）");
      markDirty("groups", false);
      return settleRequests([loadGroups(false), loadStatus()]);
    }).catch(fail).then(function () {
      btn.disabled = false;
      byId("saveHint").textContent = "";
    });
  }

  function saveSettings() {
    var btn = byId("btnSaveSettings");
    btn.disabled = true;
    byId("cfgHint").textContent = "保存中…";
    return apiPost("page/settings/save", {
      reset_time: byId("cfgResetTime").value.trim(),
      festival_push_time: byId("cfgFestivalTime").value.trim(),
      weekly_report_day: byId("cfgWeeklyDay").value,
      markdown_group_mode: byId("cfgMarkdownMode").value
    }).then(function () {
      markDirty("settings", false);
      toast("设置已保存");
      return loadStatus();
    }).catch(fail).then(function () {
      btn.disabled = false;
      byId("cfgHint").textContent = "";
    });
  }

  function clearAll() {
    confirmModal("把所有列的勾选都取消？（还要点「保存群名单」才生效）", "全部取消").then(function (ok) {
      if (!ok) return;
      state.rows.forEach(function (row) {
        state.columns.forEach(function (col) { row.flags[col.key] = false; });
        row.count = 0;
      });
      markDirty("groups", true);
      renderMatrix();
      toast("已全部取消，记得点「保存群名单」");
    });
  }

  function dedupeGroups() {
    return confirmModal(
      "把「适配器类型名」（aiocqhttp / qq_official 这类）换成真实平台实例 id，\n" +
      "并合并同一平台同一群号的重复写法？\n只改写法，不改勾选（每个群在哪些名单里完全不变）。",
      "整理写法"
    ).then(function (ok) {
      if (!ok) return;
      var btn = byId("btnDedupe");
      btn.disabled = true;
      return apiPost("page/groups/dedupe", {}).then(function (d) {
        var report = d.report || [];
        var rewritten = report.filter(function (r) {
          return r.action === "type" || r.action === "bare";
        }).length;
        var merged = report.filter(function (r) { return r.action === "merge"; }).length;
        var stuck = (d.unreachable || []).length;
        var parts = [];
        if (rewritten) parts.push("改写 " + rewritten + " 处");
        if (merged) parts.push("合并 " + merged + " 处");
        if (stuck) parts.push(stuck + " 处平台实例不存在（需手动改）");
        toast(parts.length ? "已整理：" + parts.join("，") : "没有需要整理的地方");
        return loadGroups(false);
      }).catch(fail).then(function () {
        btn.disabled = false;
      });
    });
  }

  function renameGroup(umo) {
    var row = null;
    state.rows.forEach(function (r) { if (r.umo === umo) row = r; });
    return promptModal(
      "会话备注名",
      "给这个会话起个备注名（只影响面板显示，方便认出官方平台的 openid 群）。留空 = 清掉备注。",
      row ? (row.group_name || "") : ""
    ).then(function (name) {
      if (name === null) return;
      return apiPost("page/groups/rename", { umo: umo, name: String(name).trim() })
        .then(function (d) {
          toast(d.name ? "备注已保存：" + d.label : "备注已清空");
          return loadGroups(false);
        })
        .catch(fail);
    });
  }

  // ---------- 绑定 & 启动 ----------

  function bind() {
    document.querySelectorAll("[data-go]").forEach(function (el) {
      el.addEventListener("click", function () { location.hash = el.dataset.go; });
    });
    window.addEventListener("hashchange", showView);
    showView();
    byId("btnTheme").addEventListener("click", function () {
      prefs.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      savePrefs();
    });
    ["prefTheme", "prefAccent", "prefCompact", "prefMotion"].forEach(function (id) {
      byId(id).addEventListener("change", function () {
        prefs = { theme: byId("prefTheme").value, accent: byId("prefAccent").value,
          compact: byId("prefCompact").checked, motion: byId("prefMotion").checked };
        savePrefs();
      });
    });
    byId("btnResetAppearance").addEventListener("click", function () {
      prefs = { theme: "follow", accent: "gold", compact: false, motion: true };
      savePrefs();
    });
    byId("view-settings").addEventListener("input", function () { markDirty("settings", true); });
    byId("view-settings").addEventListener("change", function () { markDirty("settings", true); });
    window.addEventListener("beforeunload", function (e) {
      if (!dirty.groups && !dirty.settings) return;
      e.preventDefault();
      e.returnValue = "";
    });
    byId("btnReload").addEventListener("click", function () {
      protectDrafts(["groups", "settings"], refreshPanel);
    });
    byId("searchBox").addEventListener("input", renderMatrix);
    // 「只看已启用功能的群」开关：记住选择（iframe 里 localStorage 可能不可用，包一层）
    try {
      var savedHide = localStorage.getItem("wowHideEmpty");
      if (savedHide !== null) { byId("hideEmpty").checked = savedHide === "1"; }
    } catch (e) { /* ignore */ }
    byId("hideEmpty").addEventListener("change", function () {
      try { localStorage.setItem("wowHideEmpty", this.checked ? "1" : "0"); } catch (e) { /* ignore */ }
      renderMatrix();
    });
    byId("btnRefreshGroups").addEventListener("click", function () {
      protectDrafts(["groups"], function () { return loadGroups(true); });
    });
    byId("btnSaveGroups").addEventListener("click", function () { operation(saveGroups); });
    byId("btnDedupe").addEventListener("click", function () {
      if (dirty.groups) { toast("请先保存群名单，再整理写法。", true); return; }
      operation(dedupeGroups);
    });
    byId("btnSaveSettings").addEventListener("click", function () { operation(saveSettings); });
    byId("btnClearAll").addEventListener("click", clearAll);
    byId("matrixBody").addEventListener("click", function (e) {
      var target = e.target;
      if (!target || !target.closest) return;
      var btn = target.closest("[data-rename]");
      if (!btn) return;
      e.preventDefault();
      if (dirty.groups) { toast("请先保存群名单，再编辑备注。", true); return; }
      operation(function () { return renameGroup(btn.getAttribute("data-rename")); });
    });
    byId("matrixBody").addEventListener("change", function (e) {
      var box = e.target;
      if (!box || box.type !== "checkbox") return;
      state.rows.forEach(function (row) {
        if (row.umo !== box.dataset.umo) return;
        row.flags[box.dataset.key] = box.checked;
        row.count = state.columns.filter(function (col) { return row.flags[col.key]; }).length;
      });
      markDirty("groups", true);
      var tr = box.closest("tr");
      if (!tr) return;
      var count = tr.querySelectorAll('input[type="checkbox"][data-key]:checked').length;
      var cell = tr.querySelector("td.count");
      if (cell) { cell.textContent = String(count); }
      // 别把「平台实例不存在」的 dead 标记一起冲掉
      tr.className = ((count ? "on" : "") + (tr.className.indexOf("dead") >= 0 ? " dead" : "")).trim();
    });
  }

  initTheme();
  bind();
  byId("matrixBody").innerHTML = '<tr><td colspan="12" class="empty">正在连接面板…</td></tr>';
  operation(refreshPanel);
})();
