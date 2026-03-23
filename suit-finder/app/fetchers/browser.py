"""Playwright browser lifecycle management.

Provides an async context manager that reuses a single browser instance
across multiple fetches in the same process.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)

logger = logging.getLogger(__name__)

_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_lock = asyncio.Lock()


async def get_browser(headless: bool = True) -> Browser:
    """Return (or lazily create) the shared Browser instance."""
    global _playwright, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            logger.info("Launching Playwright browser (headless=%s)", headless)
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=headless)
    return _browser


async def close_browser() -> None:
    """Gracefully close the shared browser and Playwright."""
    global _playwright, _browser
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


@asynccontextmanager
async def browser_context(
    headless: bool = True,
    user_agent: str | None = None,
    locale: str = "ja-JP",
) -> AsyncGenerator[BrowserContext, None]:
    """Yield a fresh BrowserContext, closing it on exit."""
    browser = await get_browser(headless=headless)
    kwargs: dict = {"locale": locale}
    if user_agent:
        kwargs["user_agent"] = user_agent
    ctx = await browser.new_context(**kwargs)
    try:
        yield ctx
    finally:
        await ctx.close()
