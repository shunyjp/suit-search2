"""Search routes – search listings by keyword (Phase 2+)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.connectors.yahoo_auctions import YahooAuctionsConnector, build_search_url

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = "メンズ スーツ セットアップ"
    max_price: int = 30_000
    page: int = 1


class SearchResponse(BaseModel):
    query: str
    search_url: str
    item_urls: list[str]


@router.post("/yahoo-auctions", response_model=SearchResponse)
async def search_yahoo_auctions(req: SearchRequest) -> SearchResponse:
    """Build and return a Yahoo Auctions search URL.

    Phase 2+: will also return individual item URLs.
    """
    connector = YahooAuctionsConnector()
    urls = await connector.search(req.query, max_price=req.max_price, page=req.page)
    search_url = build_search_url(req.query, max_price=req.max_price, page=req.page)
    return SearchResponse(
        query=req.query,
        search_url=search_url,
        item_urls=urls,
    )
