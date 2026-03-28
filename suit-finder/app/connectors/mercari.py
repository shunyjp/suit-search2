"""Mercari Japan (jp.mercari.com) connector.

Responsibilities:
1. Build search URLs for Mercari Japan.
2. Extract structured data via __NEXT_DATA__ (embedded JSON) for reliable parsing.
3. Fall back to CSS selectors / full-page text when JSON is unavailable.

Primary data paths tried in order:
    __NEXT_DATA__.props.pageProps.item
    __NEXT_DATA__.props.pageProps.serverData.item

Key field mapping:
    name             → title_text
    description      → description_text / all_text
    price            → price_text  ("即決 XXXX円" — Mercari は固定価格のみ)
    status           → status_text  ("on_sale" → 出品中, "sold_out"/"trading" → 終了)
    photos[]         → image_urls
    categories[]     → category_text
    brand.name       → brand_text
    item_condition   → specs_text

Item URL:    https://jp.mercari.com/item/m{id}
Search URL:  https://jp.mercari.com/search?keyword=...&status=on_sale&price_max=N
             &sort=SORT_CREATED_TIME&order=ORDER_DESC
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, PageSignals

logger = logging.getLogger(__name__)

MERCARI_BASE = "https://jp.mercari.com"

# Item URL pattern (absolute and relative forms)
_ITEM_URL_RE = re.compile(r"https?://jp\.mercari\.com/item/(m\w+)")
_ITEM_PATH_RE = re.compile(r"^/item/(m\w+)$")

_SORT_MAP = {
    "new":        "SORT_CREATED_TIME",
    "score":      "SORT_SCORE",
    "price_asc":  "SORT_PRICE_ASC",
    "price_desc": "SORT_PRICE_DESC",
}


# ---------------------------------------------------------------------------
# Search URL builder
# ---------------------------------------------------------------------------

def build_search_url(
    query: str,
    max_price: int | None = 30_000,
    page: int = 1,
    sort: str = "new",
) -> str:
    """Build a Mercari Japan search URL.

    Args:
        sort: "new" (新着順) | "score" (関連度) | "price_asc" | "price_desc"
    """
    params: dict = {
        "keyword": query,
        "status": "on_sale",
        "sort": _SORT_MAP.get(sort, "SORT_CREATED_TIME"),
        "order": "ORDER_DESC",
    }
    if max_price is not None:
        params["price_max"] = max_price
    if page > 1:
        # Mercari uses cursor-based pagination via page_token
        params["page_token"] = f"v1:{page}"
    return f"{MERCARI_BASE}/search?{urlencode(params)}"


# ---------------------------------------------------------------------------
# URL extractor for search results
# ---------------------------------------------------------------------------

def _extract_item_urls_from_html(html: str) -> list[str]:
    """Extract unique Mercari item URLs from raw HTML.

    Handles both absolute (https://jp.mercari.com/item/mXXX) and
    relative (/item/mXXX) hrefs.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[str] = []
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        m_abs = _ITEM_URL_RE.search(href)
        m_rel = _ITEM_PATH_RE.match(href)
        if m_abs:
            item_url = f"{MERCARI_BASE}/item/{m_abs.group(1)}"
        elif m_rel:
            item_url = f"{MERCARI_BASE}/item/{m_rel.group(1)}"
        else:
            continue
        if item_url not in seen:
            seen.add(item_url)
            result.append(item_url)
    return result


# ---------------------------------------------------------------------------
# __NEXT_DATA__ mapper
# ---------------------------------------------------------------------------

def _apply_next_data_mercari(signals: dict, item: dict) -> None:
    """Populate signals dict from Mercari __NEXT_DATA__ item object."""
    # Title
    signals["title_text"] = item.get("name", "")

    # Description: strip any embedded HTML tags just in case
    desc = item.get("description", "")
    if desc:
        soup = BeautifulSoup(desc, "html.parser")
        signals["description_text"] = soup.get_text(separator="\n").strip()
    signals["all_text"] = signals["description_text"]

    # Price: Mercari is a fixed-price marketplace → always 即決
    price = int(item.get("price") or 0)
    if price > 0:
        shipping = item.get("shipping_payer") or {}
        shipping_name = shipping.get("name", "") if isinstance(shipping, dict) else ""
        shipping_incl = "出品者" in shipping_name or "込み" in shipping_name
        signals["price_text"] = f"即決 {price:,}円" + ("\n送料込み" if shipping_incl else "")

    # Status
    status = str(item.get("status", "")).lower()
    if status == "on_sale":
        signals["status_text"] = "出品中"
    elif status in ("sold_out", "trading", "stop"):
        signals["status_text"] = "終了"
    else:
        signals["status_text"] = status

    # Images – Mercari stores them as photos[].image_urls dict or as thumbnails[]
    photos = item.get("photos") or item.get("thumbnails") or []
    urls: list[str] = []
    for p in photos:
        if isinstance(p, dict):
            img = p.get("image_urls") or {}
            if isinstance(img, dict):
                u = img.get("large") or img.get("medium") or img.get("small") or ""
                if u:
                    urls.append(u)
            elif isinstance(img, str) and img:
                urls.append(img)
        elif isinstance(p, str) and p:
            urls.append(p)
    signals["image_urls"] = urls

    # Category breadcrumb: try both categories[] and item_category{}
    categories = item.get("categories") or []
    if categories:
        signals["category_text"] = " > ".join(
            c.get("name", "") for c in categories
            if isinstance(c, dict) and c.get("name")
        )
    else:
        cat = item.get("item_category") or {}
        if isinstance(cat, dict):
            parts: list[str] = []
            parent = cat.get("parent")
            if isinstance(parent, dict) and parent.get("name"):
                parts.append(parent["name"])
            if cat.get("name"):
                parts.append(cat["name"])
            signals["category_text"] = " > ".join(parts)

    # Brand
    brand = item.get("brand") or {}
    if isinstance(brand, dict) and brand.get("name"):
        signals["brand_text"] = brand["name"]

    # Condition → specs_text (helps condition_parser and material_parser)
    cond = item.get("item_condition") or item.get("condition") or {}
    if isinstance(cond, dict) and cond.get("name"):
        signals["specs_text"] = f"商品の状態: {cond['name']}"


def _try_extract_item(next_data: dict) -> dict | None:
    """Walk __NEXT_DATA__ and return the first plausible item object."""
    page_props = next_data.get("props", {}).get("pageProps", {})
    # Direct item key
    for key in ("item",):
        candidate = page_props.get(key)
        if isinstance(candidate, dict) and candidate.get("id"):
            return candidate
    # Nested under serverData
    server = page_props.get("serverData") or {}
    if isinstance(server, dict):
        candidate = server.get("item")
        if isinstance(candidate, dict) and candidate.get("id"):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class MercariConnector(BaseConnector):
    site = "mercari"

    def __init__(self, headless: bool = True, wait_ms: int = 3_000) -> None:
        self.headless = headless
        self.wait_ms = wait_ms

    async def fetch_page_signals(self, url: str) -> PageSignals:
        """Fetch a Mercari item page and return PageSignals.

        Primary source: __NEXT_DATA__ embedded JSON.
        CSS fallbacks: h1, [data-testid='name'], sold indicator.
        """
        from app.fetchers.browser import browser_context
        from app.fetchers.rendered_fetcher import _safe_attr, _safe_text
        from playwright.async_api import TimeoutError as PWTimeoutError

        logger.info("Fetching Mercari page: %s", url)

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

                # ── Try __NEXT_DATA__ ────────────────────────────────────
                next_data = await page.evaluate("""
                    () => {
                        const el = document.getElementById('__NEXT_DATA__');
                        return el ? JSON.parse(el.textContent) : null;
                    }
                """)
                if next_data:
                    item = _try_extract_item(next_data)
                    if item:
                        try:
                            _apply_next_data_mercari(signals, item)
                        except Exception as exc:
                            logger.warning("Mercari __NEXT_DATA__ parse error: %s", exc)

                # ── CSS / JS fallbacks ───────────────────────────────────
                if not signals["title_text"]:
                    signals["title_text"] = (
                        await _safe_text(page, "h1")
                        or await _safe_text(page, "[data-testid='name']")
                    )
                if not signals["image_urls"]:
                    # Mercari CDN uses static.mercdn.net
                    signals["image_urls"] = await _safe_attr(
                        page, "img[src*='mercdn.net']", "src"
                    )
                # Status: if __NEXT_DATA__ didn't provide it, inspect DOM
                if not signals["status_text"]:
                    body_text = await page.inner_text("body")
                    if "売り切れ" in body_text or "SOLD OUT" in body_text.upper():
                        signals["status_text"] = "終了"
                    else:
                        signals["status_text"] = "出品中"
                # Fallback full-page text for all_text
                if not signals["all_text"]:
                    try:
                        signals["all_text"] = await page.inner_text("body")
                    except Exception:
                        pass

            except PWTimeoutError:
                logger.warning("Timeout fetching Mercari %s", url)
            except Exception as exc:
                logger.error("Error fetching Mercari %s: %s", url, exc)
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
        """Fetch Mercari search results and return item URLs.

        Returns empty list on failure (non-blocking).
        """
        from app.fetchers.rendered_fetcher import fetch_page_html

        search_url = build_search_url(query, max_price=max_price, page=page, sort=sort)
        logger.info("Mercari search: %s", search_url)

        try:
            html = await fetch_page_html(
                url=search_url,
                headless=self.headless,
                wait_ms=self.wait_ms,
                wait_until="networkidle",
            )
        except Exception as exc:
            logger.warning("Mercari search failed: %s", exc)
            return []

        urls = _extract_item_urls_from_html(html)
        logger.info("Mercari: found %d item URLs on page %d", len(urls), page)
        return urls
