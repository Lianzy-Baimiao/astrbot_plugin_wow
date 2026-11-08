"""输出屏蔽的发送边界回归：python tests/test_output_filter.py。"""

import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_wow_main as harness
from wow.output_filter import blocked_keyword, message_text

main = harness.wow_main
GROUP = "napcat:GroupMessage:1001"


class Chain:
    def __init__(self):
        self.chain = []

    def message(self, text):
        self.chain.append(types.SimpleNamespace(text=text))
        return self

    def url_image(self, url):
        self.chain.append(types.SimpleNamespace(url=url))
        return self

    file_image = url_image


def event(text="魔兽新闻"):
    ev = harness.make_event(text)
    ev.plain_result = lambda text: Chain().message(text)
    ev.image_result = lambda url: Chain().url_image(url)
    ev.get_platform_name = lambda: "napcat"
    return ev


async def collect(replies):
    return [reply async for reply in replies]


class OutputFilterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin, self.ctx, _ = harness.make_plugin()
        self.ctx.send_message = AsyncMock()
        self.plugin.html_render = AsyncMock(return_value="https://example.com/card.png")
        self.plugin._limited = lambda *args: True
        self.chain_patch = patch.object(sys.modules["astrbot.api.event"], "MessageChain", Chain, create=True)
        self.chain_patch.start()
        self.addCleanup(self.chain_patch.stop)

    def test_list_defaults_replacement_empty_and_literal_match(self):
        self.assertEqual(blocked_keyword({}, "无限可能"), "无限")
        self.assertIsNone(blocked_keyword({}, "普通攻略"))
        self.assertIsNone(blocked_keyword({"output_block_keywords": []}, "无限可能"))
        cfg = {"output_block_keywords": ["", "  ", " 广告 ", "a.b"]}
        self.assertEqual(blocked_keyword(cfg, "今日广告"), "广告")
        self.assertEqual(blocked_keyword(cfg, "a.b"), "a.b")
        self.assertIsNone(blocked_keyword(cfg, "无限 axb A.B"))
        self.assertIsNone(blocked_keyword({"output_block_keywords": [" "]}, "正常文本"))

    async def test_direct_push_uses_live_config(self):
        await self.plugin._send_text_to(GROUP, "无限可能")
        self.ctx.send_message.assert_not_awaited()
        self.plugin.config["output_block_keywords"] = ["广告"]
        await self.plugin._send_text_to(GROUP, "广告")
        self.ctx.send_message.assert_not_awaited()
        await self.plugin._send_text_to(GROUP, "无限可能")
        self.assertEqual(self.ctx.send_message.await_count, 1)
        self.plugin.config["output_block_keywords"] = []
        await self.plugin._send_text_to(GROUP, "广告")
        self.assertEqual(self.ctx.send_message.await_count, 2)

    async def test_panel_keywords_roundtrip_changes_output(self):
        ctrl = self.plugin.page
        ok, status, _ = harness.unwrap(await ctrl.get_status())
        self.assertTrue(ok)
        self.assertEqual(status["settings"]["output_block_keywords"], ["无限"])
        for values, expected in (([" 广告 ", "", "广告"], ["广告"]), ([], [])):
            with patch.object(ctrl, "_payload", AsyncMock(return_value={"output_block_keywords": values})):
                ok, data, _ = harness.unwrap(await ctrl.save_settings())
            self.assertTrue(ok)
            self.assertEqual(data["output_block_keywords"], expected)
            self.assertEqual(self.plugin.config["output_block_keywords"], expected)
            self.assertEqual(self.plugin._output_blocked("广告"), bool(expected))
            self.assertFalse(self.plugin._output_blocked("无限"))
        self.assertEqual(self.plugin.config.save_count, 2)
        with patch.object(ctrl, "_payload", AsyncMock(return_value={"reset_time": "07:30"})):
            self.assertTrue(harness.unwrap(await ctrl.save_settings())[0])
        self.assertEqual(self.plugin.config["output_block_keywords"], [])

    async def test_panel_invalid_keywords_and_save_failure_leave_config_unchanged(self):
        ctrl = self.plugin.page
        self.plugin.config["output_block_keywords"] = ["无限"]
        original = dict(self.plugin.config)
        for invalid in ("广告", None, [1], ["广告", False]):
            with patch.object(ctrl, "_payload", AsyncMock(return_value={"output_block_keywords": invalid})):
                self.assertFalse(harness.unwrap(await ctrl.save_settings())[0])
            self.assertEqual(self.plugin.config, original)
        with patch.object(ctrl, "_payload", AsyncMock(return_value={"output_block_keywords": []})), patch.object(
            self.plugin.config, "save_config", side_effect=OSError("disk full")
        ):
            self.assertFalse(harness.unwrap(await ctrl.save_settings())[0])
        self.assertEqual(self.plugin.config, original)

    async def test_plain_command_and_markdown_command(self):
        with patch.object(main.misc_svc, "what_to_eat", return_value="无限美食"):
            self.assertEqual(await collect(self.plugin.eat_cmd(event("吃什么"))), [])
        with patch.object(main.prices_svc, "query_price", AsyncMock(return_value="**无限**药水")):
            self.assertEqual(await collect(self.plugin.price_cmd(event("物价 药水"))), [])
        with patch.object(main.misc_svc, "what_to_eat", return_value="烤肉"):
            replies = await collect(self.plugin.eat_cmd(event("吃什么")))
            self.assertEqual(message_text(replies[0]), "烤肉")

    async def test_manual_news_title_or_description_blocks_all_parts_before_screenshot(self):
        screenshot = AsyncMock(return_value="https://example.com/shot.png")
        shot_module = types.SimpleNamespace(screenshot=screenshot)
        with patch.dict(sys.modules, {"wow.screenshot": shot_module}):
            for field in ("title", "description"):
                news = {"title": "正常新闻", "description": "普通内容", "url": "https://example.com/news"}
                news[field] = "无限可能"
                with patch.object(main.news_svc, "latest_news", AsyncMock(return_value=news)):
                    self.assertEqual(await self.plugin._send_news(event(), force=True), [])
                    self.assertEqual(main.news_svc.last_title("1001"), news["title"])
            screenshot.assert_not_awaited()
            self.plugin.html_render.assert_not_awaited()

    async def test_allowed_news_still_sends_text_and_image(self):
        news = {"title": "正常新闻", "description": "普通内容", "url": "https://example.com/news"}
        shot_module = types.SimpleNamespace(screenshot=AsyncMock(return_value="https://example.com/shot.png"))
        with patch.dict(sys.modules, {"wow.screenshot": shot_module}), patch.object(
            main.news_svc, "latest_news", AsyncMock(return_value=news)
        ):
            replies = await self.plugin._send_news(event(), force=True)
        self.assertEqual(len(replies), 2)
        self.assertIn("正常新闻", message_text(replies[0]))
        self.assertEqual(replies[1].chain[0].url, "https://example.com/shot.png")

    async def test_scheduled_news_skips_screenshot_and_keeps_deduplication(self):
        self.plugin.config["news_groups"] = [GROUP]
        news = {"title": "普通新闻", "description": "无限可能", "url": "https://example.com/news"}
        shot_module = types.SimpleNamespace(screenshot=AsyncMock(), clean_shots=Mock())
        with patch.dict(sys.modules, {"wow.screenshot": shot_module}), patch.object(
            main.news_svc, "latest_news", AsyncMock(return_value=news)
        ):
            await self.plugin._tick()
            self.assertEqual(main.news_svc.last_title(f"push:{GROUP}"), news["title"])
            self.assertIsNone(await main.news_svc.get_news(f"push:{GROUP}"))
        self.ctx.send_message.assert_not_awaited()
        shot_module.screenshot.assert_not_awaited()
        self.plugin.html_render.assert_not_awaited()

    async def test_card_and_nga_body_are_checked_before_rendering(self):
        with patch.object(main.misc_svc, "quote_card", return_value={"text": "无限可能"}):
            self.assertEqual(await collect(self.plugin.quote_cmd(event("BOSS语录"))), [])
        topic = {"title": "普通标题", "author": "玩家", "replies": 1, "forum": "综合",
                 "posts": [{"content": "无限可能", "author": "玩家"}]}
        with patch.object(main.nga_svc, "fetch_topic", AsyncMock(return_value=topic)):
            replies = await collect(self.plugin.on_nga_link(event("https://ngabbs.com/read.php?tid=123")))
        self.assertEqual(replies, [])
        self.plugin.html_render.assert_not_awaited()
        await self.plugin._send_img_to(GROUP, None)
        self.ctx.send_message.assert_not_awaited()

    async def test_normal_card_and_explicit_disable_still_render(self):
        with patch.object(main.misc_svc, "quote_card", return_value={"text": "无限可能"}):
            self.plugin.config["output_block_keywords"] = []
            replies = await collect(self.plugin.quote_cmd(event("BOSS语录")))
        self.assertEqual(len(replies), 1)
        self.plugin.html_render.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
