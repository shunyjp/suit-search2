"""Yahoo! Auctions connector.

Responsibilities (site-specific layer only):
1. Build search URLs for Yahoo Auctions.
2. Define the CSS selector map for text-bucket extraction.
3. Post-process raw fetcher output into PageSignals.

Selectors are limited to:
- title, price, buy-now price, status, description, specs, brand, category, images

Size / material data are NOT extracted via selectors here.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, PageSignals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS selector map (Yahoo! Auctions – verified structure as of 2024)
# NOTE: Update these when Yahoo changes their DOM.
# ---------------------------------------------------------------------------

SELECTORS: dict[str, str] = {
    # Title
    "title_text": "h1.ProductTitle__text",
    # Full price area – captures current bid AND buy-now price in one text bucket
    # (using .Price__value only gets the first match; .Price captures both)
    "price_text": ".Price",
    # Status area (contains remaining time, bid count, sold/active label)
    "status_text": ".AuctionStatus",
    # Item description / seller comment
    "description_text": ".ItemDescription",
    # Spec table (size/material sometimes appear here as free text)
    "specs_text": ".ProductDetail__section",
    # Brand – last Breadcrumb__link is usually the brand/item category
    # We'll capture the full Breadcrumb and parse brand from it
    "brand_text": ".Breadcrumb",
    # Category breadcrumb (same element – used as category context)
    "category_text": ".Breadcrumb",
    # Product images
    "image_urls": ".ProductImage__image",
}

# Fallback generic selectors (tried if primary fails)
_FALLBACK_SELECTORS: dict[str, str] = {
    "title_text": "h1",
    "price_text": "[class*='Price']",
    "description_text": "[class*='Description'], [class*='detail'], [class*='Detail']",
    "status_text": "[class*='Status'], [class*='Auction']",
}

# ---------------------------------------------------------------------------
# Search URL builder
# ---------------------------------------------------------------------------

BASE_SEARCH_URL = "https://auctions.yahoo.co.jp/search/search"

# Category for men's suits on Yahoo Auctions
MENSWEAR_CATEGORY = "2084228408"  # スーツ（メンズ）


def build_search_url(
    query: str,
    category: str | None = MENSWEAR_CATEGORY,
    min_price: int | None = None,
    max_price: int | None = 30_000,
    page: int = 1,
) -> str:
    """Build a Yahoo Auctions search URL."""
    params: dict[str, str | int] = {
        "p": query,
        "va": query,
        "tab_ex": "commerce",
        "fr": "auc_prop",
        "alocale": "0jp",
        "b": (page - 1) * 50 + 1,
        "n": 50,
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
    return f"https://page.auctions.yahoo.co.jp/jp/auction/{item_id}"


# ---------------------------------------------------------------------------
# PageSignals post-processing
# ---------------------------------------------------------------------------

# Price patterns for the price bucket
_BUY_NOW_INLINE = re.compile(r"即決[：:\s]*([0-9,]+)\s*円")
_CURRENT_INLINE = re.compile(r"現在[：:\s]*([0-9,]+)\s*円")


# Item URL patterns on Yahoo Auctions search results
_ITEM_URL_RE = re.compile(
    r"https?://page\.auctions\.yahoo\.co\.jp/jp/auction/[a-zA-Z0-9]+"
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
    for Yahoo Auctions item URL pattern.
    """
    soup = BeautifulSoup(html, "html.parser")
    _ITEM_URL_PATTERN = "page.auctions.yahoo.co.jp/jp/auction/"
    seen: set[str] = set()
    result: list[str] = []
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if _ITEM_URL_PATTERN in href:
            base = href.split("?")[0]
            if base not in seen:
                seen.add(base)
                result.append(base)
    return result


def _postprocess(raw: dict) -> dict:
    """Apply site-specific fixes to the raw fetch result.

    Yahoo Auctions sometimes merges current + buy-now into the same
    price element. This split ensures both are visible in price_text.
    """
    # Nothing special needed right now – raw is used as-is
    return raw


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class YahooAuctionsConnector(BaseConnector):
    site = "yahoo_auctions"

    def __init__(self, headless: bool = True, wait_ms: int = 2_000) -> None:
        self.headless = headless
        self.wait_ms = wait_ms

    async def fetch_page_signals(self, url: str) -> PageSignals:
        """Fetch a single Yahoo Auctions item page and return PageSignals."""
        from app.fetchers.rendered_fetcher import fetch_rendered  # lazy – requires playwright

        logger.info("Fetching Yahoo Auctions page: %s", url)
        raw = await fetch_rendered(
            url=url,
            headless=self.headless,
            wait_ms=self.wait_ms,
            selectors=SELECTORS,
        )
        raw = _postprocess(raw)
        return PageSignals(**{k: v for k, v in raw.items() if k in PageSignals.model_fields})

    async def search(  # type: ignore[override]
        self,
        query: str,
        max_price: int = 30_000,
        page: int = 1,
    ) -> list[str]:
        """Fetch search results page and return individual item URLs.

        Extracts anchor hrefs matching the Yahoo Auctions item URL pattern.
        Returns empty list on failure (non-blocking).
        """
        from app.fetchers.rendered_fetcher import fetch_rendered  # lazy

        search_url = build_search_url(query, max_price=max_price, page=page)
        logger.info("Searching: %s", search_url)

        try:
            raw = await fetch_rendered(
                url=search_url,
                headless=self.headless,
                wait_ms=self.wait_ms,
                selectors={},  # only need all_text for link extraction
            )
        except Exception as exc:
            logger.warning("Search fetch failed: %s", exc)
            return []

        # Extract item URLs from all_text via regex
        all_text = raw.get("all_text", "")
        item_urls = _extract_item_urls(all_text)
        logger.info("Found %d item URLs", len(item_urls))
        return item_urls
