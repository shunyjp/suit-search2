"""Batch routes – search + judge multiple listings in one call."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel


router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory job registry (single-process dev use)
# ---------------------------------------------------------------------------

_jobs: dict[str, "_Job"] = {}


class _Job:
    def __init__(self, job_id: str, target: int) -> None:
        self.job_id = job_id
        self.status = "running"       # running | done | error
        self.target = target          # 目標新規判定件数
        self.total_urls = 0           # 取得したURL総数
        self.newly_judged = 0         # 実際に判定した件数（crawled + status_rechecked）
        self.crawled = 0
        self.status_rechecked = 0
        self.skipped = 0
        self.errors = 0
        self.verdicts: dict[str, int] = {}
        self.error_msg: Optional[str] = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "target": self.target,
            "total_urls": self.total_urls,
            "processed": self.newly_judged + self.skipped + self.errors,
            "newly_judged": self.newly_judged,
            "crawled": self.crawled,
            "status_rechecked": self.status_rechecked,
            "skipped": self.skipped,
            "errors": self.errors,
            "verdicts": self.verdicts,
            "error_msg": self.error_msg,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class BatchSearchJudgeRequest(BaseModel):
    query: str = "メンズ スーツ セットアップ"
    source: str = "yahoo_auctions"        # "yahoo_auctions" | "yahoo_shopping" | "mercari"
    sort: str = "new"                     # "new" | "score" | "price_asc" | "price_desc"
    max_price: int = 30_000
    target_new: int = 50                  # 新規判定の目標件数
    max_pages: int = 10                   # 上限ページ数（無限ループ防止）
    headless: bool = True
    concurrency: int = 2                  # 同時クロール数（1–5）
    recrawl_after_days: int = 1           # この日数×24h より古い NO_MATCH を再判定（0=永続スキップ）


class EnqueueResponse(BaseModel):
    job_id: str
    message: str


# ---------------------------------------------------------------------------
# Background task implementation
# ---------------------------------------------------------------------------


async def _run_job(job: _Job, req: BatchSearchJudgeRequest) -> None:
    """ページを順に取得し、新規判定が target_new 件に達するまで繰り返す。

    3-phase design:
      Phase 1 – DB read   (db_lock でシリアル化、短時間)
      Phase 2 – Crawl     (crawl_sem で並列制限、長時間 I/O)
      Phase 3 – DB write  (db_lock でシリアル化、短時間)

    DB セッションをクロール中に保持しないため SQLite の書き込みロック競合が発生しない。
    """
    from app.connectors.yahoo_auctions import YahooAuctionsConnector
    from app.connectors.yahoo_shopping import YahooShoppingConnector
    from app.connectors.mercari import MercariConnector
    from app.storage.repository import ListingRepository, create_tables, get_session_factory
    from app.workflows.batch_crawl_job import (
        CrawlPhaseResult, decide_url_action, run_crawl_phase, save_crawl_phase,
    )

    # 並列度は 1–5 に制限
    concurrency = max(1, min(req.concurrency, 5))
    crawl_sem = asyncio.Semaphore(concurrency)   # クロール並列度
    db_lock   = asyncio.Lock()                   # DB アクセスをシリアル化
    lock      = asyncio.Lock()                   # ジョブカウンタ更新

    try:
        if req.source == "yahoo_shopping":
            connector = YahooShoppingConnector(headless=req.headless)
        elif req.source == "mercari":
            connector = MercariConnector(headless=req.headless)
        else:
            connector = YahooAuctionsConnector(headless=req.headless)

        await create_tables()
        factory = get_session_factory()

        seen_urls: set[str] = set()
        page = 1

        async def _process_url(url: str) -> None:
            """3フェーズで 1 URL を処理する。DB セッションをクロール中に保持しない。"""
            # ── Phase 1: DB read (シリアル) ──────────────────────────────
            try:
                async with db_lock:
                    async with factory() as session:
                        repo = ListingRepository(session)
                        record = await repo.get_by_url(url)
            except Exception as exc:
                logger.warning("DB read failed %s: %s", url, exc)
                async with lock:
                    job.errors += 1
                return

            action = decide_url_action(record, req.recrawl_after_days)
            if action == "skip":
                async with lock:
                    job.skipped += 1
                    logger.info(
                        "Job %s [%d/%d] skipped → %s",
                        job.job_id, job.newly_judged, req.target_new,
                        url,
                    )
                return

            # ── Phase 2: Crawl (並列, DB セッションなし) ─────────────────
            async with crawl_sem:
                try:
                    crawl_result: CrawlPhaseResult = await run_crawl_phase(
                        url, record, action, req.headless
                    )
                except Exception as exc:
                    logger.warning("Crawl phase failed %s: %s", url, exc)
                    async with lock:
                        job.errors += 1
                    return

            # ── Phase 3: DB write (シリアル) ──────────────────────────────
            try:
                async with db_lock:
                    async with factory() as session:
                        async with session.begin():
                            repo = ListingRepository(session)
                            fresh = await repo.get_by_url(url)
                            outcome = await save_crawl_phase(url, fresh, repo, crawl_result)
            except Exception as exc:
                logger.warning("DB write failed %s: %s", url, exc)
                async with lock:
                    job.errors += 1
                return

            # ── カウンタ更新 ───────────────────────────────────────────────
            async with lock:
                if outcome.action == "crawled":
                    job.crawled += 1
                    job.newly_judged += 1
                    if outcome.verdict:
                        job.verdicts[outcome.verdict] = (
                            job.verdicts.get(outcome.verdict, 0) + 1
                        )
                elif outcome.action == "status_rechecked":
                    job.status_rechecked += 1
                    job.newly_judged += 1
                else:
                    job.errors += 1

                logger.info(
                    "Job %s [%d/%d] %s → %s",
                    job.job_id, job.newly_judged, req.target_new,
                    outcome.action, outcome.verdict or "-",
                )

        while job.newly_judged < req.target_new and page <= req.max_pages:
            logger.info(
                "Job %s: page %d (newly_judged=%d / target=%d, concurrency=%d)",
                job.job_id, page, job.newly_judged, req.target_new, concurrency,
            )
            try:
                page_urls = await connector.search(
                    req.query, max_price=req.max_price, page=page, sort=req.sort
                )
            except Exception as exc:
                logger.warning("Search page %d failed: %s", page, exc)
                break

            if not page_urls:
                logger.info("No results on page %d, stopping", page)
                break

            new_urls = [u for u in page_urls if u not in seen_urls]
            seen_urls.update(new_urls)
            job.total_urls += len(new_urls)

            if not new_urls:
                page += 1
                continue

            # 目標未達分だけ並列処理（目標超過を最小化）
            remaining = req.target_new - job.newly_judged
            batch = new_urls[:remaining + concurrency]  # 少し多めに取って余裕を持たせる
            await asyncio.gather(*[_process_url(u) for u in batch])

            if job.newly_judged >= req.target_new:
                break
            page += 1

        job.status = "done"

    except Exception as exc:
        logger.exception("Job %s failed: %s", job.job_id, exc)
        job.status = "error"
        job.error_msg = str(exc)
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()


def _start_job_thread(job: _Job, req: BatchSearchJudgeRequest) -> None:
    """Run the async job in a dedicated thread with its own event loop.

    On Windows, uvicorn's SelectorEventLoop does not support subprocess
    transports (needed by Playwright). Running in a new thread with
    ProactorEventLoop (Windows default for new_event_loop) solves this.
    """
    def run() -> None:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_job(job, req))
        finally:
            loop.close()

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/enqueue", response_model=EnqueueResponse)
async def enqueue_batch(
    req: BatchSearchJudgeRequest,
    background_tasks: BackgroundTasks,
) -> EnqueueResponse:
    """Start a batch search-and-judge job in the background.

    Returns a job_id immediately. Poll GET /batch/jobs/{job_id} for status.
    """
    job_id = str(uuid.uuid4())
    job = _Job(job_id=job_id, target=req.target_new)
    _jobs[job_id] = job

    background_tasks.add_task(_start_job_thread, job, req)

    return EnqueueResponse(job_id=job_id, message="ジョブを開始しました")


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    """Poll a background batch job for progress and result."""
    job = _jobs.get(job_id)
    if job is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return job.to_dict()
