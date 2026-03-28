"""Search job – collect item URLs from one or more sources.

Supports:
- Single connector, single page
- Single connector, multiple pages (up to max_pages)
- Both Yahoo Auctions and Yahoo Shopping in one call

Deduplicates URLs across pages and sources before returning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.connectors.base import BaseConnector
from app.connectors.yahoo_auctions import YahooAuctionsConnector
from app.connectors.yahoo_shopping import YahooShoppingConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    query: str
    sources: list[str]
    item_urls: list[str]
    page_count: int
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_pages(
    connector: BaseConnector,
    query: str,
    max_price: int,
    max_pages: int,
) -> tuple[list[str], list[str]]:
    """Collect item URLs across multiple pages from one connector.

    Returns (urls, errors).
    """
    seen: set[str] = set()
    urls: list[str] = []
    errors: list[str] = []

    for page in range(1, max_pages + 1):
        try:
            page_urls = await connector.search(query, max_price=max_price, page=page)
        except Exception as exc:
            msg = f"{connector.site} page {page} failed: {exc}"
            logger.warning(msg)
            errors.append(msg)
            break

        new_urls = [u for u in page_urls if u not in seen]
        seen.update(new_urls)
        urls.extend(new_urls)

        logger.info("%s page %d: %d new URLs (total %d)", connector.site, page, len(new_urls), len(urls))

        # If the page returned fewer results than expected, we've reached the end
        if not page_urls:
            logger.info("%s: no results on page %d, stopping", connector.site, page)
            break

    return urls, errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_search_job(
    query: str,
    sources: list[str] | None = None,
    max_price: int = 30_000,
    max_pages: int = 3,
    headless: bool = True,
) -> SearchResult:
    """Collect item URLs from search results.

    Args:
        query:      Search keyword(s).
        sources:    List of source names to search. Defaults to both connectors.
                    Accepted values: "yahoo_auctions", "yahoo_shopping".
        max_price:  Upper price limit in JPY.
        max_pages:  Maximum number of result pages to fetch per source.
        headless:   Run browser in headless mode.

    Returns:
        SearchResult with deduplicated item_urls across all sources/pages.
    """
    if sources is None:
        sources = ["yahoo_auctions", "yahoo_shopping"]

    connector_map: dict[str, BaseConnector] = {
        "yahoo_auctions": YahooAuctionsConnector(headless=headless),
        "yahoo_shopping": YahooShoppingConnector(headless=headless),
    }

    all_urls: list[str] = []
    all_errors: list[str] = []
    seen: set[str] = set()
    active_sources: list[str] = []

    for source in sources:
        connector = connector_map.get(source)
        if connector is None:
            all_errors.append(f"Unknown source: {source}")
            logger.warning("Unknown source: %s", source)
            continue

        active_sources.append(source)
        page_urls, errors = await _collect_pages(connector, query, max_price, max_pages)
        all_errors.extend(errors)

        for url in page_urls:
            if url not in seen:
                seen.add(url)
                all_urls.append(url)

    logger.info(
        "Search complete: query=%r sources=%s pages=%d urls=%d",
        query, active_sources, max_pages, len(all_urls),
    )

    return SearchResult(
        query=query,
        sources=active_sources,
        item_urls=all_urls,
        page_count=max_pages,
        errors=all_errors,
    )
