"""Offline browser regression tests for the WOW panel.

Development-only dependency: pip install playwright; playwright install chromium.
Run: python tests/test_wow_panel_ui.py
WOW_PANEL_BROWSER can point to an existing Chromium executable.
WOW_PANEL_SCREENSHOTS optionally enables light/dark/mobile PNG captures.
The mocked bridge never contacts AstrBot or modifies live configuration.
"""
from pathlib import Path
import mimetypes
import os
import unittest
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / "pages" / "wow-panel"
BRIDGE = r"""
const clone = value => JSON.parse(JSON.stringify(value));
const keys = ['news_groups','reset_groups','weekly_report_groups','wowboard_whitelist','punish_notify_groups','pet_push_groups','festival_push_groups','markdown_groups'];
const labels = ['魔兽新闻','重置提醒','周报','wowboard 指令','处罚名单','宠物世界任务','节日通告','Markdown 名单'];
const columns = keys.map((key, i) => ({key, label: labels[i], hint: labels[i]}));
const names = ['艾泽拉斯远征军', '周四开荒小分队', '翡翠梦境'];
let rows = names.map((name, i) => ({umo: 'napcat:GroupMessage:' + (10001+i), group_id: String(10001+i), group_name: name, label: name, count: i === 2 ? 0 : 2,
  platform_text: 'napcat', platform_state: 'instance', reachable: true,
  flags: Object.fromEntries(keys.map((key,j) => [key, i < 2 && j < 2]))}));
let settings = {reset_time:'06:50', festival_push_time:'07:05', weekly_report_day:3, markdown_group_mode:'all'};
const tasks = ['魔兽新闻','重置提醒','周报','宠物世界任务'].map((name,i) => ({name, enabled:i<3, when:i===0?'每 5 分钟检查':'每周四 06:50', next_text:'2026-10-08 06:50:00', last_text:'2026-10-01 06:50:02', groups:2, note:'按群订阅名单推送'}));
window.mock = {posts:[], failGet:false, failSave:false, delay:0};
window.AstrBotPluginPage = {
 ready: () => window.failReady ? Promise.reject(new Error('模拟桥接就绪失败')) : Promise.resolve(),
 apiGet: async path => {
  await new Promise(resolve => setTimeout(resolve, (window.mock.delays || {})[path] || window.mock.delay));
  if (window.mock.failGet) throw new Error('模拟接口不可用');
  let data;
  if (path === 'page/meta') data = {columns};
  if (path === 'page/groups') data = {rows, columns, summary:{groups:2,links:4}, instances:[{id:'napcat',label:'napcat'}], platforms:[{platform:'napcat',count:2,state:'instance'}],dead:[],duplicates:[]};
  if (path === 'page/status') data = {running:true, summary:{groups:2,links:4}, schedule:{rows:tasks}, settings,
    modifiers:{weekdays:Array.from({length:7},(_,i)=>({value:i+1,label:'周' +(i+1)})),markdown_modes:[{value:'all',label:'所有会话'},{value:'whitelist',label:'仅名单内的群'}]},
    prices:{exists:true, items:31407, realm:'贫瘠之地', stale_days:1, newest_text:'2026-09-30 23:40'}};
  if (path === 'page/data') data = {prices:{exists:true,items:31407,realm:'贫瘠之地',newest_text:'2026-09-30 23:40'},board:{available:true,roster:42},gacha:{available:true,players:128},punish:{count:3},cache:{files:26,bytes:10485760},data_dir:'/AstrBot/data/plugin_data/astrbot_plugin_wow'};
  if(window.mock.empty && path === 'page/groups') data = {...data, rows:[], summary:{}, instances:[]};
  if(window.mock.hostile && path === 'page/data') data.prices.realm = '<img src=x onerror=alert(1)>';
  return {status:'ok',data:clone(data)};
 },
 apiPost: async (path,body) => {
  window.mock.posts.push({path,body:clone(body)});
  if (window.mock.failSave) throw new Error('模拟保存失败');
  if(path === 'page/groups/save') rows = rows.map(row => {const saved=body.rows.find(r=>r.umo===row.umo); return {...row,flags:saved.flags,count:Object.values(saved.flags).filter(Boolean).length};});
  if(path === 'page/settings/save') settings = {...settings,...body};
  if(path === 'page/groups/rename') rows.forEach(row => {if(row.umo===body.umo) row.group_name=body.name;});
  return {status:'ok', data:{changes:[],name:body.name,label:body.name}};
 }
};
"""


class PanelBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        options = {"headless": True}
        if os.environ.get("WOW_PANEL_BROWSER"):
            options["executable_path"] = os.environ["WOW_PANEL_BROWSER"]
        cls.browser = cls.pw.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1080})
        self.context.route("http://wow.test/**", self.serve)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto("http://wow.test/index.html")
        expect(self.page.locator("#connectionText")).to_have_text("面板已连接")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def serve(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("bridge-sdk.js"):
            route.fulfill(body=BRIDGE, content_type="text/javascript; charset=utf-8")
            return
        file = ROOT / path.lstrip("/")
        if file.is_file() and file.parent == ROOT:
            route.fulfill(body=file.read_bytes(), content_type=(mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8")
        else:
            route.fulfill(status=404, body="not found")

    def view(self, key):
        self.page.locator(f'.nav-item[data-go="{key}"]').click()
        expect(self.page.locator(f"#view-{key}")).to_be_visible()
        self.assertEqual(self.page.locator(".view:visible").count(), 1)

    def test_overview_and_filter_alignment(self):
        p = self.page
        p.set_viewport_size({"width": 1700, "height": 1100})
        boxes = p.locator('.stat').evaluate_all("ns=>ns.map(n=>({label:n.querySelector('.l').getBoundingClientRect().top,value:n.querySelector('.n').getBoundingClientRect().top}))")
        self.assertEqual(len(boxes), 6)
        for box in boxes:
            self.assertAlmostEqual(box['label'], boxes[0]['label'], delta=1)
            self.assertAlmostEqual(box['value'], boxes[0]['value'], delta=1)
        self.view('groups')
        controls = [p.locator(s).bounding_box() for s in ['#searchBox', '#hideEmptyLbl', '#btnRefreshGroups']]
        centers = [r['y'] + r['height']/2 for r in controls]
        self.assertLess(max(centers)-min(centers), 2)

    def test_theme_toggle_persists_and_follows_host(self):
        root = self.page.locator("html")
        expect(root).to_have_attribute("data-theme", "light")
        self.page.locator("#btnTheme").click()
        expect(root).to_have_attribute("data-theme", "dark")
        self.page.reload()
        expect(root).to_have_attribute("data-theme", "dark")
        self.view("appearance")
        self.page.locator("#prefTheme").select_option("follow")
        expect(root).to_have_attribute("data-theme", "light")
        self.page.evaluate("document.documentElement.dataset.theme = 'dark'")
        expect(root).to_have_attribute("data-theme", "dark")
        self.page.locator("#btnTheme").click()
        expect(root).to_have_attribute("data-theme", "light")
        self.page.locator("#prefAccent").select_option("blue")
        self.page.locator("#prefCompact").check()
        self.page.locator("#prefMotion").uncheck()
        expect(root).to_have_attribute("data-accent", "blue")
        expect(root).to_have_attribute("data-compact", "true")
        expect(root).to_have_attribute("data-motion", "false")

    def test_filter_keeps_edits_and_saves_hidden_rows(self):
        self.view("groups")
        first = self.page.locator('#matrixBody input[data-key="news_groups"]').first
        first.uncheck()
        self.page.locator("#searchBox").fill("周四")
        self.page.locator("#searchBox").fill("")
        expect(first).not_to_be_checked()
        self.view("settings")
        self.page.locator("#cfgResetTime").fill("08:30")
        self.view("groups")
        self.page.locator("#btnSaveGroups").click()
        expect(self.page.locator("#btnSaveGroups")).to_have_text("保存群名单")
        saved = self.page.evaluate("window.mock.posts[0]")
        self.assertEqual(len(saved["body"]["rows"]), 3)
        self.assertFalse(saved["body"]["rows"][0]["flags"]["news_groups"])
        self.view("settings")
        expect(self.page.locator("#cfgResetTime")).to_have_value("08:30")
        self.page.locator("#btnSaveSettings").click()
        expect(self.page.locator("#draftNotice")).to_be_hidden()

    def test_clear_all_affects_filtered_groups_and_modal_keyboard(self):
        self.view("groups")
        self.page.locator("#searchBox").fill("周四")
        self.page.locator("#btnClearAll").click()
        expect(self.page.locator("#modalOk")).to_be_focused()
        self.page.keyboard.press("Shift+Tab")
        expect(self.page.locator("#modalCancel")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#modalMask")).to_be_hidden()
        self.page.locator("#btnClearAll").click()
        self.page.locator("#modalOk").click()
        self.page.locator("#btnSaveGroups").click()
        expect(self.page.locator("#btnSaveGroups")).to_have_text("保存群名单")
        rows = self.page.evaluate("window.mock.posts[0].body.rows")
        self.assertTrue(all(not any(row["flags"].values()) for row in rows))

    def test_refresh_warns_and_failure_is_recoverable(self):
        self.view("settings")
        self.page.locator("#cfgResetTime").fill("08:30")
        self.page.locator("#btnReload").click()
        self.page.locator("#modalCancel").click()
        expect(self.page.locator("#cfgResetTime")).to_have_value("08:30")
        self.page.locator("#btnReload").click()
        self.page.locator("#modalOk").click()
        expect(self.page.locator("#cfgResetTime")).to_have_value("06:50")
        expect(self.page.locator("#draftNotice")).to_be_hidden()
        self.page.evaluate("window.mock.failGet = true")
        self.page.locator("#btnReload").click()
        expect(self.page.locator("#loadError")).to_be_visible()
        expect(self.page.locator("#btnReload")).to_be_enabled()
        self.page.evaluate("window.mock.failGet = false")
        self.page.locator("#btnReload").click()
        expect(self.page.locator("#loadError")).to_be_hidden()

    def test_save_failure_preserves_draft_and_toast(self):
        self.view("groups")
        self.page.locator('#matrixBody input[data-key="news_groups"]').first.uncheck()
        self.page.evaluate("window.mock.failSave = true")
        self.page.locator("#btnSaveGroups").click()
        expect(self.page.locator("#toast")).to_be_visible()
        expect(self.page.locator("#toast")).to_have_class("toast show err")
        expect(self.page.locator("#draftNotice")).to_be_visible()
        expect(self.page.locator("#btnSaveGroups")).to_be_enabled()

    def test_mobile_layout_and_visual_captures(self):
        capture = os.environ.get("WOW_PANEL_SCREENSHOTS")
        if capture:
            Path(capture).mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(Path(capture) / "wow-light.png"), full_page=True)
            self.page.locator("#btnTheme").click()
            self.page.wait_for_timeout(250)  # Let theme color transitions finish.
            self.page.screenshot(path=str(Path(capture) / "wow-dark.png"), full_page=True)
            self.page.locator("#btnTheme").click()
        for width in (390, 768, 1440):
            self.page.set_viewport_size({"width": width, "height": 900})
            for key in ("overview", "groups", "schedule", "data", "appearance", "settings"):
                self.view(key)
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, key))
                if capture and width == 390 and key in ("overview", "groups"):
                    self.page.screenshot(path=str(Path(capture) / f"wow-mobile-{key}.png"), full_page=True)

    def test_request_lock_covers_newly_rendered_checkboxes(self):
        self.view("groups")
        self.page.evaluate("window.mock.delays = {'page/status': 500}")
        self.page.locator("#btnReload").click()
        expect(self.page.locator("#btnReload")).to_be_disabled()
        expect(self.page.locator('#matrixBody input[data-key="news_groups"]').first).to_be_disabled()
        expect(self.page.locator("#btnReload")).to_be_enabled()
        expect(self.page.locator('#matrixBody input[data-key="news_groups"]').first).to_be_enabled()

    def test_bridge_rejection_can_be_retried(self):
        self.context.add_init_script("window.failReady = true")
        self.page.reload()
        expect(self.page.locator("#loadError")).to_contain_text("桥接就绪失败")
        self.view("groups")
        expect(self.page.locator("#btnSaveGroups")).to_be_disabled()
        self.page.evaluate("window.failReady = false")
        self.page.locator("#btnReload").click()
        expect(self.page.locator("#connectionText")).to_have_text("面板已连接")
        expect(self.page.locator("#btnSaveGroups")).to_be_enabled()

    def test_empty_state_and_untrusted_realm_are_safe(self):
        self.page.evaluate("window.mock.empty = true; window.mock.hostile = true")
        self.page.locator("#btnReload").click()
        self.view("groups")
        expect(self.page.locator("#matrixBody")).to_contain_text("还没有群")
        self.view("data")
        expect(self.page.locator("#dataList")).to_contain_text("<img src=x onerror=alert(1)>")
        self.assertEqual(self.page.locator("#dataList img").count(), 0)

    def test_deep_links_and_theme_query(self):
        self.page.goto("http://wow.test/index.html?theme=dark#settings")
        expect(self.page.locator("#connectionText")).to_have_text("面板已连接")
        expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(self.page.locator("#view-settings")).to_be_visible()
        self.page.evaluate("location.hash = 'not-a-view'")
        expect(self.page.locator("#view-overview")).to_be_visible()

    def test_storage_denied_does_not_break_theme_or_data(self):
        self.page.evaluate("() => { Storage.prototype.setItem = function() { throw new Error('blocked'); }; }")
        self.page.locator("#btnTheme").click()
        expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
        self.view("appearance")
        expect(self.page.locator("#prefHint")).to_contain_text("本次打开")
        self.assertEqual(self.page.locator("#stats .stat").count(), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
