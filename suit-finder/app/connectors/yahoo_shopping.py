"""Yahoo Shopping connector (store.shopping.yahoo.co.jp).

Handles used-item listings from Yahoo Shopping stores, primarily ZOZO Used.
Uses httpx (no browser needed – pages are server-side rendered).

Primary data path:
    __NEXT_DATA__
      .dehydratedState.queries[0].state.data.itemData.item

Key fields:
    item.name          → title_text
    item.freeSpace1    → description_text / all_text (contains measurements)
    item.information   → additional description (fallback)
    item.price         → price_text
    item.condition     → specs_text
    item.images[].url  → image_urls
"""

from __future__ import annotations

import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, PageSignals

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}


def _strip_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator="\n").strip()


def _apply_next_data_shopping(signals: dict, item: dict) -> None:
    """Populate signals from Yahoo Shopping __NEXT_DATA__ item object."""
    # Title
    signals["title_text"] = item.get("name") or item.get("title") or ""

    # Description: freeSpace1 contains measurements, information has specs
    parts: list[str] = []
    for key in ("freeSpace1", "freeSpace2", "information"):
        val = item.get(key) or ""
        if val:
            parts.append(_strip_html(val) if "<" in val else val)

    # Include structured specs in description for parser
    spec_fields = {
        "brandName": "ブランド",
        "colorName": "カラー",
        "sizeName": "サイズ",
        "materialDescription": "素材",
    }
    for field, label in spec_fields.items():
        val = item.get(field) or ""
        if val:
            parts.append(f"{label}: {val}")

    signals["description_text"] = "\n".join(parts)
    signals["all_text"] = signals["description_text"]

    # Price: Yahoo Shopping is fixed price
    price_info = item.get("price") or {}
    if isinstance(price_info, dict):
        price = int(price_info.get("value") or price_info.get("selling") or 0)
    else:
        price = int(price_info or 0)
    if price > 0:
        signals["price_text"] = f"即決 {price:,}円"

    # Status: assume active (sold-out items are typically removed)
    availability = item.get("availability") or item.get("inStock")
    if availability is False or str(availability).lower() in ("false", "0", "outofstock"):
        signals["status_text"] = "終了"
    else:
        signals["status_text"] = "出品中"

    # Images
    images = item.get("images") or []
    if isinstance(images, list):
        signals["image_urls"] = [
            img["url"] for img in images if isinstance(img, dict) and img.get("url")
        ]

    # Category
    cat_list = item.get("categoryPath") or item.get("sellerCategoryPathList") or []
    if isinstance(cat_list, list):
        signals["category_text"] = " ".join(
            c.get("name", "") if isinstance(c, dict) else str(c)
            for c in cat_list
        )

    # Brand
    brand = item.get("brandName") or (item.get("brand") or {}).get("name") or ""
    signals["brand_text"] = brand

    # Condition / specs
    cond = item.get("condition") or item.get("usedCondition") or ""
    if isinstance(cond, dict):
        cond = cond.get("label") or cond.get("text") or ""
    if cond:
        signals["specs_text"] = f"商品の状態: {cond}"


def _extract_next_data_item(html: str) -> dict | None:
    """Extract item dict from __NEXT_DATA__ in the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None
    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return None

    # Primary path: dehydratedState.queries[*].state.data.itemData.item
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
        for q in queries:
            item = (q.get("state", {})
                     .get("data", {})
                     .get("itemData", {})
                     .get("item"))
            if item:
                return item
    except (KeyError, TypeError):
        pass

    # Fallback paths
    try:
        return data["props"]["pageProps"]["itemData"]["item"]
    except (KeyError, TypeError):
        pass

    return None


class YahooShoppingConnector(BaseConnector):
    site = "yahoo_shopping"

    def __init__(self, headless: bool = True, wait_ms: int = 2_000) -> None:
        self.headless = headless
        self.wait_ms = wait_ms

    async def fetch_page_signals(self, url: str) -> PageSignals:
        """Fetch a Yahoo Shopping item page (httpx, no browser needed)."""
        logger.info("Fetching Yahoo Shopping page: %s", url)

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

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                timeout=20.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

            item = _extract_next_data_item(html)
            if item:
                _apply_next_data_shopping(signals, item)
                logger.info("Yahoo Shopping __NEXT_DATA__ parsed OK for %s", url)
            else:
                # Fallback: extract text from page body
                logger.warning("Yahoo Shopping __NEXT_DATA__ not found for %s, falling back to HTML", url)
                soup = BeautifulSoup(html, "html.parser")
                title_tag = soup.find("h1")
                if title_tag:
                    signals["title_text"] = title_tag.get_text().strip()
                body_text = soup.get_text(separator="\n")
                signals["all_text"] = body_text
                signals["description_text"] = body_text

                # Images: product images from item-shopping.c.yimg.jp
                img_tags = soup.find_all("img", src=re.compile(r"item-shopping\.c\.yimg\.jp"))
                signals["image_urls"] = [t["src"] for t in img_tags if t.get("src")]

        except httpx.HTTPStatusError as exc:
            logger.error("HTTP error fetching %s: %s", url, exc)
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)

        return PageSignals(**{k: v for k, v in signals.items() if k in PageSignals.model_fields})
