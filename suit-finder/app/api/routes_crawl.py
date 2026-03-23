"""Crawl routes – trigger fetch + parse pipeline for a single URL."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from app.workflows.crawl_job import CrawlResult, run_crawl_job

router = APIRouter()


class CrawlRequest(BaseModel):
    url: str
    headless: bool = True


class CrawlResponse(BaseModel):
    url: str
    success: bool
    item_id: str | None = None
    verdict: str | None = None
    score: float | None = None
    blocking_reasons: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []
    error: str | None = None


@router.post("/", response_model=CrawlResponse)
async def crawl_item(req: CrawlRequest) -> CrawlResponse:
    """Fetch a listing URL and run the full analysis pipeline."""
    result: CrawlResult = await run_crawl_job(req.url, headless=req.headless)

    if not result.success:
        return CrawlResponse(
            url=req.url,
            success=False,
            error=result.error,
        )

    assert result.package and result.decision
    return CrawlResponse(
        url=req.url,
        success=True,
        item_id=result.package.item_id,
        verdict=result.decision.verdict,
        score=result.decision.score,
        blocking_reasons=result.decision.blocking_reasons,
        reasons=result.decision.reasons,
        warnings=result.warnings,
    )
