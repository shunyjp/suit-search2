"""Yahoo! Auctions connector.

Responsibilities (site-specific layer only):
1. Build search URLs for Yahoo Auctions.
2. Extract structured data via __NEXT_DATA__ (embedded JSON) for reliable parsing.
3. Fall back to CSS selectors for image_urls and category_text.

Primary data source: window.__NEXT_DATA__.props.pageProps.initialState.item.detail.item
  - title, descriptionHtml (full description with size/material), price, bidorbuy,
    status (open/close), leftTime, chargeForShipping, conditionName

CSS selectors (Yahoo ships hashed class names so only stable patterns are used):
  - image_urls: img[src*='auctions.c.yimg.jp']
  - category_text: [class*='gv-Breadcrumb']

Search:
  Uses Yahoo Japan Auction Search API (https://developer.yahoo.co.jp/webapi/auctions/).
  Requires YAHOO_AUCTION_APP_ID environment variable.
  Register at: https://e.developer.yahoo.co.jp/register
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, PageSignals

logger = logging.getLogger(__name__)

# CSS selectors used only for fields not available in __NEXT_DATA__
_CSS_IMAGE_SEL = "img[src*='auctions.c.yimg.jp']"
_CSS_CATEGORY_SEL = "[class*='gv-Breadcrumb']"
_CSS_TITLE_SEL = "h1"  # fallback if __NEXT_DATA__ unavailable

# ---------------------------------------------------------------------------
# Search URL builder
# ---------------------------------------------------------------------------

BASE_SEARCH_URL = "https://auctions.yahoo.co.jp/search/search"

# Yahoo Auction Search API (AuctionWebService) – blocked for new app registrations (403).
# Kept as constant for reference; search() uses Shopping API instead.
_AUCTION_API_URL = "https://auctions.yahooapis.jp/AuctionWebService/V2/json/search"

# Yahoo Shopping API – used for search() (returns used items, condition=used)
_SHOPPING_API_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"

# Category for men's fashion on Yahoo Auctions (suits appear under this category)
MENSWEAR_CATEGORY = "23176"  # メンズファッション > スーツ


def build_search_url(
    query: str,
    category: str | None = MENSWEAR_CATEGORY,
    min_price: int | None = None,
    max_price: int | None = 30_000,
    page: int = 1,
    sort: str = "new",
) -> str:
    """Build a Yahoo Auctions search URL.

    Args:
        sort: "new" (新着順, default) | "score" (関連度順) | "price_asc" | "price_desc"
    """
    _SORT_MAP = {
        "new":        ("new", "d"),
        "score":      ("score", "d"),
        "price_asc":  ("cbids", "a"),
        "price_desc": ("cbids", "d"),
    }
    s1, o1 = _SORT_MAP.get(sort, ("new", "d"))

    params: dict[str, str | int] = {
        "p": query,
        "b": (page - 1) * 50 + 1,
        "n": 50,
        "s1": s1,
        "o1": o1,
    }
    if category:
        params["auccat"] = category
    if min_price is not None:
        params["min"] = min_price
    if max_price is not None:
        params["max"] = max_price

    return f"{BASE_SEARCH_URL}?{urlencode(params)}"


def build_item_url(item_id: str) -> str:
    """Build a direct item URL from its Yahoo Auctions item ID."""
    return f"https://auctions.yahoo.co.jp/jp/auction/{item_id}"


# ---------------------------------------------------------------------------
# PageSignals post-processing
# ---------------------------------------------------------------------------

# Price patterns for the price bucket
_BUY_NOW_INLINE = re.compile(r"即決[：:\s]*([0-9,]+)\s*円")
_CURRENT_INLINE = re.compile(r"現在[：:\s]*([0-9,]+)\s*円")


# Item URL patterns on Yahoo Auctions search results
# Yahoo changed the item URL format: page.auctions.yahoo.co.jp → auctions.yahoo.co.jp
_ITEM_URL_RE = re.compile(
    r"https?://(?:page\.)?auctions\.yahoo\.co\.jp/(?:jp/)?auction/[a-zA-Z0-9]+"
)
_ITEM_ID_RE = re.compile(r"/auction/([a-zA-Z0-9]+)")


def _extract_item_urls(text: str) -> list[str]:
    """Extract unique item URLs from page text / HTML."""
    urls = _ITEM_URL_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        # Normalise: strip query params
        base = url.split("?")[0]
        if base not in seen:
            seen.add(base)
            result.append(base)
    return result


def _extract_item_urls_from_html(html: str) -> list[str]:
    """Extract unique Yahoo Auctions item URLs from raw HTML.

    Uses BeautifulSoup to find all <a href="..."> elements and filters
    for the Yahoo Auctions item URL pattern (/auction/{id} path only).
    Non-item URLs (search pages, category pages, seller pages, etc.) are excluded.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[str] = []
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if _ITEM_URL_RE.search(href):
            base = href.split("?")[0]
            if base not in seen:
                seen.add(base)
                result.append(base)
    return result


def _apply_next_data(signals: dict, item: dict) -> None:
    """Populate signals dict from Yahoo __NEXT_DATA__ item object.

    item = props.pageProps.initialState.item.detail.item
    """
    # Title
    signals["title_text"] = item.get("title", "")

    # Description: HTML → plain text (contains sizes, materials, condition)
    desc_html = item.get("descriptionHtml") or item.get("description") or ""
    if desc_html:
        soup = BeautifulSoup(desc_html, "html.parser")
        signals["description_text"] = soup.get_text(separator="\n").strip()

    # Use description as all_text so all parsers see it
    signals["all_text"] = signals["description_text"]

    # Price text: format for price parser
    price = int(item.get("price") or 0)
    bidorbuy = int(item.get("bidorbuy") or 0)
    bids = int(item.get("bids") or 0)
    charge = item.get("chargeForShipping", "")

    parts: list[str] = []
    if bidorbuy > 0:
        parts.append(f"即決 {bidorbuy:,}円")
    if price > 0 and (bids > 0 or bidorbuy == 0):
        # Show current price when there are bids or there is no buy-now
        parts.append(f"現在 {price:,}円")
    if charge == "seller":
        parts.append("送料込み")
    signals["price_text"] = "\n".join(parts)

    # Status text: format for status parser
    status = item.get("status", "")
    left_sec = float(item.get("leftTime") or 0)
    if status == "open":
        if left_sec < 3600:
            signals["status_text"] = f"残り{int(left_sec / 60)}分"
        elif left_sec < 86400:
            signals["status_text"] = f"残り{int(left_sec / 3600)}時間"
        else:
            signals["status_text"] = f"残り{int(left_sec / 86400)}日"
    elif status == "close":
        signals["status_text"] = "終了"
    else:
        signals["status_text"] = status

    # Specs: condition label
    condition = item.get("conditionName", "")
    if condition:
        signals["specs_text"] = f"商品の状態: {condition}"


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class YahooAuctionsConnector(BaseConnector):
    site = "yahoo_auctions"

    def __init__(self, headless: bool = True, wait_ms: int = 2_000) -> None:
        self.headless = headless
        self.wait_ms = wait_ms

    async def fetch_page_signals(self, url: str) -> PageSignals:
        """Fetch a Yahoo Auctions item page and return PageSignals.

        Primary data source: __NEXT_DATA__ embedded JSON (reliable, structured).
        CSS selectors used only for image_urls and category_text.
        """
        from app.fetchers.browser import browser_context
        from app.fetchers.rendered_fetcher import _safe_attr, _safe_text
        from playwright.async_api import TimeoutError as PWTimeoutError

        logger.info("Fetching Yahoo Auctions page: %s", url)

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

                # Extract __NEXT_DATA__ for structured item fields
                next_data = await page.evaluate("""
                    () => {
                        const el = document.getElementById('__NEXT_DATA__');
                        return el ? JSON.parse(el.textContent) : null;
                    }
                """)
                if next_data:
                    try:
                        item = (next_data["props"]["pageProps"]
                                ["initialState"]["item"]["detail"]["item"])
                        _apply_next_data(signals, item)
                    except (KeyError, TypeError) as exc:
                        logger.warning("__NEXT_DATA__ parse failed: %s", exc)

                # CSS selectors for fields not in __NEXT_DATA__
                signals["image_urls"] = await _safe_attr(page, _CSS_IMAGE_SEL, "src")
                if not signals["category_text"]:
                    signals["category_text"] = await _safe_text(page, _CSS_CATEGORY_SEL)
                if not signals["title_text"]:
                    signals["title_text"] = await _safe_text(page, _CSS_TITLE_SEL)

            except PWTimeoutError:
                logger.warning("Timeout fetching %s", url)
            except Exception as exc:
                logger.error("Error fetching %s: %s", url, exc)
            finally:
                await page.close()

        return PageSignals(**{k: v for k, v in signals.items() if k in PageSignals.model_fields})

    async def search(  # type: ignore[override]
        self,
        query: str,
        max_price: int = 30_000,
        page: int = 1,
        sort: str = "new",
    ) -> list[str]:
        """Fetch search results page and return individual item URLs.

        Extracts anchor hrefs matching the Yahoo Auctions item URL pattern.
        Returns empty list on failure (non-blocking).
        """
        from app.fetchers.rendered_fetcher import fetch_page_html  # lazy

        search_url = build_search_url(query, max_price=max_price, page=page, sort=sort)
        logger.info("Searching: %s", search_url)

        try:
            html = await fetch_page_html(
                url=search_url,
                headless=self.headless,
                wait_ms=self.wait_ms,
            )
        except Exception as exc:
            logger.warning("Search fetch failed: %s", exc)
            return []

        item_urls = _extract_item_urls_from_html(html)
        logger.info("Found %d item URLs", len(item_urls))
        return item_urls
