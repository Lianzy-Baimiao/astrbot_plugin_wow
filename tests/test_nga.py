"""NGA transient-response regression tests: python tests/test_nga.py."""
import asyncio
import json
import logging
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "astrbot.api" not in sys.modules:
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("nga-test")
    sys.modules["astrbot"] = types.ModuleType("astrbot")
    sys.modules["astrbot.api"] = api

from wow.services import nga

URL = "https://ngabbs.com/read.php?tid=47664464&__output=8"
VALID = json.dumps({"encode": "GBK", "data": {
    "__T": {"subject": "test topic", "author": "tester"},
    "__R": {"0": {"lou": 0, "content": "test post"}},
}})


def response(body, status=200, content_type="text/javascript; charset=GBK"):
    return httpx.Response(status, content=body.encode("gbk"),
                          headers={"content-type": content_type}, request=httpx.Request("GET", URL))


class NgaTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, responses):
        client = types.SimpleNamespace(get=AsyncMock(side_effect=responses))
        with patch.object(nga, "get_client", return_value=client), patch.object(
            asyncio, "sleep", new_callable=AsyncMock
        ) as sleep:
            result = await nga.fetch_topic("47664464")
        return result, client, sleep

    async def test_transient_html_recovers_before_mirror(self):
        topic, client, sleep = await self.fetch([
            response("<html>captcha</html>", content_type="text/html"), response(VALID)
        ])
        self.assertEqual(topic["title"], "test topic")
        self.assertEqual(len(topic["posts"]), 1)
        self.assertEqual(client.get.await_count, 2)
        self.assertEqual(client.get.await_args_list[0].args, client.get.await_args_list[1].args)
        sleep.assert_awaited_once_with(0.5)

    async def test_html_with_encode_marker_is_not_accepted(self):
        topic, client, sleep = await self.fetch([
            response('<html>"encode" captcha</html>'), response(VALID)
        ])
        self.assertEqual(topic["title"], "test topic")
        self.assertEqual(client.get.await_count, 2)
        sleep.assert_awaited_once_with(0.5)

    async def test_normal_response_does_not_retry(self):
        _, client, sleep = await self.fetch([response(VALID)])
        self.assertEqual(client.get.await_count, 1)
        sleep.assert_not_awaited()

    async def test_missing_marker_retries_then_falls_back(self):
        _, client, sleep = await self.fetch([response('{}'), response('{}'), response(VALID)])
        self.assertEqual(client.get.await_count, 3)
        self.assertIn("bbs.nga.cn", client.get.await_args_list[2].args[0])
        sleep.assert_awaited_once_with(0.5)

    async def test_diagnostics_and_retry_limit(self):
        for body, kind in [("<html>captcha SECRET</html>", "verification_page"),
                           ("<html>upstream unavailable SECRET</html>", "html_page"),
                           ('{"data": "SECRET"', "incomplete_data")]:
            with self.subTest(kind=kind):
                client = types.SimpleNamespace(get=AsyncMock(return_value=response(body)))
                with patch.object(nga, "get_client", return_value=client), patch.object(
                    asyncio, "sleep", new_callable=AsyncMock
                ), patch.object(nga, "logger") as logger:
                    with self.assertRaises(RuntimeError):
                        await nga.fetch_topic("47664464")
                self.assertEqual(client.get.await_count, 4)
                diagnostics = [c for c in logger.warning.call_args_list if "response anomaly" in c.args[0]]
                self.assertEqual(len(diagnostics), 4)
                self.assertIn(kind, str(diagnostics))
                self.assertNotIn("SECRET", str(logger.warning.call_args_list))

    async def test_explicit_api_error_is_not_retried(self):
        client = types.SimpleNamespace(get=AsyncMock(return_value=response('{"error":{"0":"denied"}}')))
        with patch.object(nga, "get_client", return_value=client), patch.object(
            asyncio, "sleep", new_callable=AsyncMock
        ) as sleep:
            with self.assertRaisesRegex(RuntimeError, "denied"):
                await nga._fetch_raw(URL)
        self.assertEqual(client.get.await_count, 1)
        sleep.assert_not_awaited()

    async def test_http_error_preserved(self):
        client = types.SimpleNamespace(get=AsyncMock(return_value=response("unavailable", 503)))
        with patch.object(nga, "get_client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "503"):
                await nga._fetch_raw(URL)
        self.assertEqual(client.get.await_count, 1)


if __name__ == "__main__":
    unittest.main()

