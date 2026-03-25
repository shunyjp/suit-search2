"""PayPay Flea Market (paypayfleamarket.yahoo.co.jp) connector.

Responsibilities (site-specific layer only):
1. Extract structured data via __NEXT_DATA__ (embedded JSON).
2. Fall back to CSS selectors for image_urls.

Primary data path:
    window.__NEXT_DATA__
      .props.initialState.itemsState.items.item

Key field mapping:
    title        → title_text
    description  → description_text / all_text  (plain text; may be English)
    price        → price_text  ("即決 XXXX円" — PayPay フリマは固定価格のみ)
    status       → status_text  ("OPEN" → active, "SOLD" / isPurchased → sold)
    images[].url → image_urls
    categoryList → category_text
    brand.name   → brand_text
    condition.text → specs_text
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, PageSignals

logger = logging.getLogger(__name__)

_CSS_IMAGE_SEL = "img[src*='auctions.c.yimg.jp'], img[src*='flea.c.yimg.jp']"
_CSS_TITLE_SEL = "h1"


def _apply_next_data_paypay(signals: dict, item: dict) -> None:
    """Populate signals dict from PayPay Flea Market __NEXT_DATA__ item object.

    item = props.initialState.itemsState.items.item
    """
    # Title
    signals["title_text"] = item.get("title", "")

    # Description: plain text (some sellers write in English)
    desc = item.get("description", "")
    if desc:
        # Strip any residual HTML tags just in case
        soup = BeautifulSoup(desc, "html.parser")
        signals["description_text"] = soup.get_text(separator="\n").strip()
    signals["all_text"] = signals["description_text"]

    # Price: PayPay フリマ is a fixed-price marketplace → treat as buy_now
    price = int(item.get("price") or 0)
    if price > 0:
        signals["price_text"] = f"即決 {price:,}円"

    # Status: "OPEN" → active, "SOLD" / isPurchased → sold
    status = str(item.get("status", "")).upper()
    is_purchased = bool(item.get("isPurchased", False))
    if is_purchased or status in ("SOLD", "CLOSED", "CLOSE"):
        signals["status_text"] = "終了"
    elif status == "OPEN":
        signals["status_text"] = "出品中"
    else:
        signals["status_text"] = status

    # Images
    images = item.get("images", [])
    signals["image_urls"] = [
        img["url"] for img in images if isinstance(img, dict) and img.get("url")
    ]

    # Category breadcrumb
    category_list = item.get("categoryList", [])
    if category_list:
        signals["category_text"] = " ".join(
            c.get("name", "") for c in category_list if c.get("name")
        )

    # Brand
    brand = item.get("brand") or {}
    if isinstance(brand, dict):
        signals["brand_text"] = brand.get("name", "")

    # Specs / condition
    condition = item.get("condition") or {}
    if isinstance(condition, dict) and condition.get("text"):
        signals["specs_text"] = f"商品の状態: {condition['text']}"


class PayPayFleaMarketConnector(BaseConnector):
    site = "paypay_flea_market"

    def __init__(self, headless: bool = True, wait_ms: int = 2_000) -> None:
        self.headless = headless
        self.wait_ms = wait_ms

    async def fetch_page_signals(self, url: str) -> PageSignals:
        """Fetch a PayPay Flea Market item page and return PageSignals."""
        from app.fetchers.browser import browser_context
        from app.fetchers.rendered_fetcher import _safe_attr, _safe_text
        from playwright.async_api import TimeoutError as PWTimeoutError

        logger.info("Fetching PayPay Flea Market page: %s", url)

        signals: dict = {
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

        async with browser_context(headless=self.headless) as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(self.wait_ms)

                next_data = await page.evaluate("""
                    () => {
                        const el = document.getElementById('__NEXT_DATA__');
                        return el ? JSON.parse(el.textContent) : null;
                    }
                """)

                if next_data:
                    try:
                        item = (next_data["props"]["initialState"]
                                ["itemsState"]["items"]["item"])
                        _apply_next_data_paypay(signals, item)
                    except (KeyError, TypeError) as exc:
                        logger.warning("PayPay __NEXT_DATA__ parse failed: %s", exc)

                # Fallback CSS selectors
                if not signals["image_urls"]:
                    signals["image_urls"] = await _safe_attr(page, _CSS_IMAGE_SEL, "src")
                if not signals["title_text"]:
                    signals["title_text"] = await _safe_text(page, _CSS_TITLE_SEL)

            except PWTimeoutError:
                logger.warning("Timeout fetching %s", url)
            except Exception as exc:
                logger.error("Error fetching %s: %s", url, exc)
            finally:
                await page.close()

        return PageSignals(**{k: v for k, v in signals.items() if k in PageSignals.model_fields})
