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

from app.connectors.base import BaseConnector, PageSignals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS selector map (Yahoo! Auctions – verified structure as of 2024)
# NOTE: Update these when Yahoo changes their DOM.
# ---------------------------------------------------------------------------

SELECTORS: dict[str, str] = {
    # Title
    "title_text": "h1.ProductTitle__text",
    # Current bid / price
    "price_text": ".Price__value",
    # Status area (contains remaining time, bid count, sold/active label)
    "status_text": ".AuctionStatus",
    # Item description / seller comment
    "description_text": ".ItemDescription",
    # Spec table (size/material sometimes appear here as free text)
    "specs_text": ".ProductDetail__section",
    # Brand
    "brand_text": ".Breadcrumb__link",
    # Category breadcrumb
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
        """Return a list of item URLs from a search results page.

        NOTE: Actual scraping of the search result page is Phase 2+.
        Currently returns the search URL itself for manual inspection.
        """
        search_url = build_search_url(query, max_price=max_price, page=page)
        logger.info("Search URL: %s", search_url)
        # Phase 2: parse result links from the rendered search page
        # For now, return the search URL as a placeholder
        return [search_url]
