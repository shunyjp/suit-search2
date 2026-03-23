"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.routes_crawl import router as crawl_router
from app.api.routes_search import router as search_router
from app.api.routes_admin import router as admin_router
from app.fetchers.browser import close_browser


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield  # startup (browser launched lazily)
    await close_browser()


app = FastAPI(
    title="Suit Finder API",
    description="中古メンズスーツ横断検索・候補判定システム",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(crawl_router, prefix="/crawl", tags=["crawl"])
app.include_router(search_router, prefix="/search", tags=["search"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
