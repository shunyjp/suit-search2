"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes_crawl import router as crawl_router
from app.api.routes_search import router as search_router
from app.api.routes_admin import router as admin_router
from app.api.routes_batch import router as batch_router
from app.api.routes_listings import router as listings_router
from app.fetchers.browser import close_browser

_STATIC_DIR = Path(__file__).parent.parent / "static"


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
app.include_router(batch_router, prefix="/batch", tags=["batch"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(listings_router, prefix="/listings", tags=["listings"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
