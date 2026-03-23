"""Rendered page fetcher using Playwright.

Navigates to a URL with a real browser, waits for JS rendering,
and returns a dict of raw text content keyed by role.

NOTE: Selectors defined here are ONLY for extracting text buckets
(title, price, status, description, specs, brand, category, images).
Size and material data are NOT extracted via selectors.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Page, TimeoutError as PWTimeoutError

from app.fetchers.browser import browser_context

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_WAIT_MS = 2_000


async def _safe_text(page: Page, selector: str, timeout: int = 5_000) -> str:
    """Return inner text of selector, or empty string on failure."""
    try:
        el = await page.wait_for_selector(selector, timeout=timeout)
        if el:
            return (await el.inner_text()).strip()
    except (PWTimeoutError, Exception):
        pass
    return ""


async def _safe_attr(page: Page, selector: str, attr: str, timeout: int = 5_000) -> list[str]:
    """Return attribute values for all matching elements."""
    try:
        elements = await page.query_selector_all(selector)
        results: list[str] = []
        for el in elements:
            val = await el.get_attribute(attr)
            if val:
                results.append(val.strip())
        return results
    except Exception:
        return []


async def fetch_rendered(
    url: str,
    headless: bool = True,
    wait_ms: int = DEFAULT_WAIT_MS,
    selectors: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch a rendered page and return raw text signals.

    Args:
        url: Page URL to fetch.
        headless: Run browser headlessly.
        wait_ms: Extra wait time after page load (ms).
        selectors: Optional override of CSS selector map.

    Returns:
        Dict with keys matching PageSignals fields.
    """
    result: dict[str, Any] = {
        "url": url,
        "title_text": "",
        "price_text": "",
        "status_text": "",
        "description_text": "",
        "all_text": "",
        "specs_text": "",
        "brand_text": "",
        "category_text": "",
        "image_urls": [],
    }

    async with browser_context(headless=headless) as ctx:
        page = await ctx.new_page()
        try:
            await page.goto(url, timeout=DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(wait_ms)

            if selectors:
                # Use provided selectors
                for field, sel in selectors.items():
                    if field == "image_urls":
                        result[field] = await _safe_attr(page, sel, "src")
                    else:
                        result[field] = await _safe_text(page, sel)

            # Always capture full page text as fallback
            try:
                result["all_text"] = await page.inner_text("body")
            except Exception:
                result["all_text"] = ""

        except PWTimeoutError:
            logger.warning("Timeout fetching %s", url)
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
        finally:
            await page.close()

    return result
