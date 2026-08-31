# -*- coding: utf-8 -*-
"""异步网络请求封装（httpx）。"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .const import HTTP_TIMEOUT, UA

logger = logging.getLogger("astrbot_plugin_wow")

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """获取全局异步客户端（惰性创建）。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(HTTP_TIMEOUT),
            headers={"User-Agent": UA},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def fetch_text(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
    encoding: str | None = None,
) -> str:
    """GET 文本，带重试（最多 2 次）。"""
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = await get_client().get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            if encoding:
                resp.encoding = encoding
            return resp.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                await asyncio.sleep(0.5)
    raise last_err  # type: ignore[misc]


async def fetch_json(
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> dict | list:
    """GET JSON，带重试。"""
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = await get_client().get(url, headers=headers, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                await asyncio.sleep(0.5)
    raise last_err  # type: ignore[misc]


async def fetch_bytes(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> bytes:
    """GET 二进制（图片等）。"""
    resp = await get_client().get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content


async def post_json(
    url: str,
    *,
    json_body: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
    auth: tuple[str, str] | None = None,
) -> dict | list:
    """POST，返回 JSON。"""
    resp = await get_client().post(
        url, json=json_body, data=data, headers=headers, timeout=timeout, auth=auth
    )
    resp.raise_for_status()
    return resp.json()