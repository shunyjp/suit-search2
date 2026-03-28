"""Playwright browser lifecycle management.

Each call to browser_context() creates its own Playwright + Browser instance
and tears it down on exit. This avoids event-loop affinity issues when
Playwright is used from background threads (batch job pattern on Windows).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import BrowserContext, async_playwright

logger = logging.getLogger(__name__)


async def close_browser() -> None:
    """No-op: kept for API compatibility (lifespan hook calls this)."""


@asynccontextmanager
async def browser_context(
    headless: bool = True,
    user_agent: str | None = None,
    locale: str = "ja-JP",
) -> AsyncGenerator[BrowserContext, None]:
    """Launch a browser, yield a fresh context, then shut everything down."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            kwargs: dict = {"locale": locale}
            if user_agent:
                kwargs["user_agent"] = user_agent
            ctx = await browser.new_context(**kwargs)
            try:
                yield ctx
            finally:
                await ctx.close()
        finally:
            await browser.close()
