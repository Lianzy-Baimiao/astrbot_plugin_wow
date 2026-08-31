# -*- coding: utf-8 -*-
"""Playwright 网页截图（魔兽新闻原网页样式）。

浏览器组件由插件首次使用时自动下载（playwright install chromium），
无需用户手动安装任何系统软件。依赖在 requirements.txt 声明。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from .store import data_dir

logger = logging.getLogger("astrbot_plugin_wow.screenshot")

_ready: bool | None = None
_install_started = False


def _shot_dir() -> Path:
    d = data_dir() / "news_shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _shot_path(url: str) -> Path:
    return _shot_dir() / (hashlib.md5(url.encode()).hexdigest() + ".png")


def clean_shots(max_keep: int = 10, max_age: int = 7 * 86400) -> None:
    """清理历史新闻截图：最多保留最近 max_keep 条 + 7 天兜底。"""
    try:
        now = time.time()
        files = [f for f in _shot_dir().iterdir() if f.is_file()]
        if len(files) > max_keep:
            for f in sorted(files, key=lambda x: x.stat().st_mtime)[:-max_keep]:
                f.unlink(missing_ok=True)
        for f in _shot_dir().iterdir():
            if f.is_file() and now - f.stat().st_mtime > max_age:
                f.unlink(missing_ok=True)
    except OSError:
        pass


async def _probe() -> bool:
    """探测 Playwright chromium 是否可用（结果缓存）。"""
    global _ready
    if _ready is not None:
        return _ready
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            b = await pw.chromium.launch(args=["--no-sandbox"])
            await b.close()
            _ready = True
        except Exception as e:  # noqa: BLE001
            logger.warning("Playwright chromium 不可用: %s", e)
            _ready = False
        await pw.stop()
    except Exception as e:  # noqa: BLE001
        logger.warning("Playwright 未安装或不可用: %s", e)
        _ready = False
    return _ready


async def _run_install() -> None:
    """后台下载 Playwright chromium（约 150MB，一次性）。"""
    logger.info("开始自动下载 Playwright chromium 浏览器组件（约 150MB）…")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "playwright",
        "install",
        "chromium",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    global _ready
    _ready = None  # 重新探测
    if await _probe():
        logger.info("Playwright chromium 下载完成")
    else:
        logger.error("Playwright chromium 下载失败，新闻将回退为卡片模式")


def request_install() -> bool:
    """触发后台下载（幂等），返回是否已开始。"""
    global _install_started
    if _install_started:
        return False
    _install_started = True
    try:
        asyncio.get_event_loop().create_task(_run_install())
        return True
    except Exception:  # noqa: BLE001
        _install_started = False
        return False


async def screenshot(url: str, full_page: bool = True) -> str:
    """Playwright 截图网页，返回图片文件路径（按 URL 缓存：多群推送只截一次）。

    浏览器组件未就绪时自动触发后台下载并抛 RuntimeError('DOWNLOADING')，
    调用方应回退卡片模式并提示用户稍后自动生效。
    """
    cached = _shot_path(url)
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)
    if not await _probe():
        request_install()
        raise RuntimeError("DOWNLOADING")
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = None
    try:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 800, "height": 1200})
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception:  # noqa: BLE001
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)  # 等待页面渲染与字体加载
        img = str(cached)
        await page.screenshot(path=img, full_page=full_page)
        if not os.path.exists(img) or os.path.getsize(img) == 0:
            raise RuntimeError("截图文件为空")
        return img
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        await pw.stop()