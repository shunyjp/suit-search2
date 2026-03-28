"""Batch crawl job – process a list of URLs with skip/recheck logic.

For each URL the job decides:
  1. Not in DB             → full crawl + save
  2. MATCH, is_active      → status-only recheck (are they still listed?)
  3. needs_recheck=True    → full crawl (data was missing last time)
  4. real NG, no recheck   → skip

Usage:
    from app.workflows.batch_crawl_job import run_batch_crawl_job
    result = await run_batch_crawl_job(urls, headless=True)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import EvidencePackage, ParserInput, PageSignals
from app.evidence.cleaner import clean_blocks
from app.evidence.extractor import build_evidence_package
from app.parsers.status_parser import parse_status
from app.rules.reasons import classify_needs_recheck
from app.storage.models import ListingRecord
from app.storage.repository import ListingRepository, get_session_factory, create_tables
from app.workflows.crawl_job import run_crawl_job

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ItemOutcome:
    url: str
    action: str          # "crawled" | "status_rechecked" | "skipped" | "error"
    verdict: Optional[str] = None
    is_active: Optional[bool] = None
    needs_recheck: bool = False
    error: Optional[str] = None


@dataclass
class BatchCrawlResult:
    total: int
    crawled: int = 0
    status_rechecked: int = 0
    skipped: int = 0
    errors: int = 0
    outcomes: list[ItemOutcome] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        verdicts: dict[str, int] = {}
        for o in self.outcomes:
            if o.verdict:
                verdicts[o.verdict] = verdicts.get(o.verdict, 0) + 1
        return {
            "total": self.total,
            "crawled": self.crawled,
            "status_rechecked": self.status_rechecked,
            "skipped": self.skipped,
            "errors": self.errors,
            "verdicts": verdicts,
        }


# ---------------------------------------------------------------------------
# Status-only recheck
# ---------------------------------------------------------------------------


async def _recheck_status(
    url: str,
    record: ListingRecord,
    repo: ListingRepository,
    headless: bool,
) -> ItemOutcome:
    """Fetch the item page and update status (and price sanity check).

    In addition to checking whether the item is still active, also verifies
    that the buy-now price is still present.  If it has been removed by the
    seller the item no longer qualifies and is immediately downgraded to
    NO_MATCH so it no longer appears in the candidate list.
    """
    from app.connectors.yahoo_auctions import YahooAuctionsConnector
    from app.connectors.yahoo_shopping import YahooShoppingConnector
    from app.connectors.mercari import MercariConnector
    from app.parsers.price_parser import parse_price

    try:
        if "shopping.yahoo.co.jp" in url:
            connector = YahooShoppingConnector(headless=headless)
        elif "mercari.com" in url:
            connector = MercariConnector(headless=headless)
        else:
            connector = YahooAuctionsConnector(headless=headless)

        signals: PageSignals = await connector.fetch_page_signals(url)
        package = build_evidence_package(url=url, signals=signals)
        cleaned = clean_blocks(package.evidence_blocks)
        pi = ParserInput(
            item_id=record.item_id or package.item_id,
            evidence_blocks=cleaned,
            page_signals=signals,
        )
        status_out = parse_status(pi)
        is_active = status_out.normalized_status == "active"

        # ── Buy-now sanity check ──────────────────────────────────────────
        # If the record previously had a buy-now price but it has now been
        # removed, immediately downgrade to NO_MATCH (seller removed 即決).
        prev_buy_now = (record.price_attrs or {}).get("buy_now_price_jpy")
        if prev_buy_now is not None:
            price_out = parse_price(pi)
            if price_out.buy_now_price_jpy is None:
                reason = "即決価格が削除されました (ステータス再確認時に検出)"
                await repo.mark_as_ng(record, reason=reason)
                logger.info(
                    "Buy-now removed for %s – downgraded to NO_MATCH", url
                )
                return ItemOutcome(
                    url=url,
                    action="status_rechecked",
                    verdict="NO_MATCH",
                    is_active=is_active,
                )

        await repo.update_status(
            record=record,
            is_active=is_active,
            status_attrs=status_out.model_dump(mode="json"),
        )
        logger.info("Status recheck %s → active=%s", url, is_active)
        return ItemOutcome(
            url=url,
            action="status_rechecked",
            verdict=record.verdict,
            is_active=is_active,
        )
    except Exception as exc:
        logger.warning("Status recheck failed %s: %s", url, exc)
        return ItemOutcome(url=url, action="error", error=str(exc))


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------


async def run_batch_crawl_job(
    urls: list[str],
    headless: bool = True,
) -> BatchCrawlResult:
    """Process a list of item URLs with smart skip/recheck logic.

    Creates tables if they don't exist yet (SQLite auto-init).
    Each URL is processed inside its own DB transaction.
    """
    await create_tables()
    factory = get_session_factory()

    result = BatchCrawlResult(total=len(urls))

    for url in urls:
        async with factory() as session:
            async with session.begin():
                repo = ListingRepository(session)
                record = await repo.get_by_url(url)
                outcome = await _process_one(url, record, repo, headless)

        result.outcomes.append(outcome)
        if outcome.action == "crawled":
            result.crawled += 1
        elif outcome.action == "status_rechecked":
            result.status_rechecked += 1
        elif outcome.action == "skipped":
            result.skipped += 1
        else:
            result.errors += 1

        logger.info(
            "[%d/%d] %s → %s (verdict=%s)",
            len(result.outcomes), result.total, url,
            outcome.action, outcome.verdict or "-",
        )

    logger.info("Batch complete: %s", result.summary)
    return result


async def _process_one(
    url: str,
    record: Optional[ListingRecord],
    repo: ListingRepository,
    headless: bool,
    recrawl_after_days: int = 3,
) -> ItemOutcome:
    """Decide what to do with one URL and execute it.

    recrawl_after_days: NO_MATCH items older than this many days are re-crawled
                        regardless of needs_recheck, so parser improvements are
                        applied to previously-rejected listings.
    """
    from datetime import timedelta

    # ── Already in DB ────────────────────────────────────────────────────
    if record is not None:
        if record.verdict == "MATCH":
            # Still a candidate → just confirm it's still listed
            return await _recheck_status(url, record, repo, headless)

        if not record.needs_recheck:
            # Real NG: skip unless the record has expired
            if recrawl_after_days > 0:
                retrieved = record.retrieved_at
                if retrieved.tzinfo is None:
                    retrieved = retrieved.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - retrieved
                threshold_sec = recrawl_after_days * 86400.0
                expired = age.total_seconds() >= threshold_sec
            else:
                expired = False

            if not expired:
                logger.debug("Skipping real-NG item: %s", url)
                return ItemOutcome(
                    url=url, action="skipped",
                    verdict=record.verdict, is_active=record.is_active,
                )
            logger.info("Re-crawling expired NO_MATCH: %s", url)
            # Fall through to full crawl
        else:
            # needs_recheck=True → data was missing last time, try again
            logger.info("Re-crawling (needs_recheck): %s", url)

    # ── Full crawl ───────────────────────────────────────────────────────
    try:
        crawl = await run_crawl_job(url, headless=headless, save_db=False)
    except Exception as exc:
        return ItemOutcome(url=url, action="error", error=str(exc))

    if not crawl.success or crawl.package is None or crawl.decision is None:
        return ItemOutcome(url=url, action="error", error=crawl.error or "crawl failed")

    needs_recheck = classify_needs_recheck(
        crawl.decision.verdict,
        crawl.decision.blocking_reasons,
    )
    await repo.upsert_from_evidence(
        package=crawl.package,
        merged=crawl.merged,  # type: ignore[arg-type]
        decision=crawl.decision,
        needs_recheck=needs_recheck,
    )

    return ItemOutcome(
        url=url,
        action="crawled",
        verdict=crawl.decision.verdict,
        is_active=True,
        needs_recheck=needs_recheck,
    )


# ---------------------------------------------------------------------------
# 3-phase helpers for parallel batch processing
# ---------------------------------------------------------------------------


def decide_url_action(
    record: Optional[ListingRecord],
    recrawl_after_days: int = 3,
) -> str:
    """Return the action to take for a URL: 'skip' | 'status_recheck' | 'full_crawl'.

    Pure logic – no DB or network access.
    recrawl_after_days=0 → 常にスキップ（永続NG扱い）
    recrawl_after_days>0 → その日数×24時間より古い NO_MATCH を再判定
    """
    if record is None:
        return "full_crawl"
    if record.verdict == "MATCH":
        return "status_recheck"
    if not record.needs_recheck:
        if recrawl_after_days > 0:
            retrieved = record.retrieved_at
            if retrieved.tzinfo is None:
                retrieved = retrieved.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - retrieved
            # age.days は切り捨て整数なので total_seconds で比較
            threshold_sec = recrawl_after_days * 86400.0
            if age.total_seconds() < threshold_sec:
                return "skip"
        else:
            return "skip"
    return "full_crawl"


@dataclass
class CrawlPhaseResult:
    """Data produced by the crawl phase; ready to be persisted in Phase 3."""
    action: str                          # "crawled" | "status_rechecked" | "error"
    verdict: Optional[str] = None
    is_active: Optional[bool] = None
    error: Optional[str] = None
    # full-crawl fields
    package: object = None
    merged: object = None
    decision: object = None
    needs_recheck: bool = False
    # status-recheck fields
    downgrade_reason: Optional[str] = None   # set → call mark_as_ng
    status_attrs: Optional[dict] = None      # set → call update_status


async def run_crawl_phase(
    url: str,
    record: Optional[ListingRecord],
    action: str,
    headless: bool,
) -> CrawlPhaseResult:
    """Execute the network crawl for *action*.  No DB access whatsoever."""
    from app.connectors.yahoo_auctions import YahooAuctionsConnector
    from app.connectors.yahoo_shopping import YahooShoppingConnector
    from app.connectors.mercari import MercariConnector
    from app.parsers.price_parser import parse_price

    if action == "status_recheck":
        try:
            if "shopping.yahoo.co.jp" in url:
                connector = YahooShoppingConnector(headless=headless)
            elif "mercari.com" in url:
                connector = MercariConnector(headless=headless)
            else:
                connector = YahooAuctionsConnector(headless=headless)

            signals: PageSignals = await connector.fetch_page_signals(url)
            package = build_evidence_package(url=url, signals=signals)
            cleaned = clean_blocks(package.evidence_blocks)
            pi = ParserInput(
                item_id=(record.item_id if record else None) or package.item_id,
                evidence_blocks=cleaned,
                page_signals=signals,
            )
            status_out = parse_status(pi)
            is_active = status_out.normalized_status == "active"

            # Buy-now sanity check
            prev_buy_now = (record.price_attrs or {}).get("buy_now_price_jpy") if record else None
            if prev_buy_now is not None:
                price_out = parse_price(pi)
                if price_out.buy_now_price_jpy is None:
                    return CrawlPhaseResult(
                        action="status_rechecked",
                        verdict="NO_MATCH",
                        is_active=is_active,
                        downgrade_reason="即決価格が削除されました (ステータス再確認時に検出)",
                    )

            return CrawlPhaseResult(
                action="status_rechecked",
                verdict=record.verdict if record else None,
                is_active=is_active,
                status_attrs=status_out.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.warning("Status recheck crawl failed %s: %s", url, exc)
            return CrawlPhaseResult(action="error", error=str(exc))

    # full_crawl
    try:
        # save_db=False: DB write is handled by the caller (save_crawl_phase)
        # with proper needs_recheck and db_lock to avoid SQLite contention.
        crawl = await run_crawl_job(url, headless=headless, save_db=False)
    except Exception as exc:
        return CrawlPhaseResult(action="error", error=str(exc))

    if not crawl.success or crawl.package is None or crawl.decision is None:
        return CrawlPhaseResult(action="error", error=crawl.error or "crawl failed")

    needs_recheck = classify_needs_recheck(
        crawl.decision.verdict,
        crawl.decision.blocking_reasons,
    )
    return CrawlPhaseResult(
        action="crawled",
        verdict=crawl.decision.verdict,
        is_active=True,
        needs_recheck=needs_recheck,
        package=crawl.package,
        merged=crawl.merged,
        decision=crawl.decision,
    )


async def save_crawl_phase(
    url: str,
    record: Optional[ListingRecord],
    repo: ListingRepository,
    result: CrawlPhaseResult,
) -> ItemOutcome:
    """Persist *result* inside an already-open DB session/transaction."""
    if result.action == "error":
        return ItemOutcome(url=url, action="error", error=result.error)

    if result.action == "crawled":
        await repo.upsert_from_evidence(
            package=result.package,
            merged=result.merged,  # type: ignore[arg-type]
            decision=result.decision,
            needs_recheck=result.needs_recheck,
        )
        return ItemOutcome(
            url=url,
            action="crawled",
            verdict=result.verdict,
            is_active=True,
            needs_recheck=result.needs_recheck,
        )

    # status_rechecked
    if result.downgrade_reason is not None and record is not None:
        await repo.mark_as_ng(record, reason=result.downgrade_reason)
        logger.info("Buy-now removed for %s – downgraded to NO_MATCH", url)
    elif record is not None and result.status_attrs is not None:
        await repo.update_status(
            record=record,
            is_active=result.is_active,  # type: ignore[arg-type]
            status_attrs=result.status_attrs,
        )
        logger.info("Status recheck %s → active=%s", url, result.is_active)

    return ItemOutcome(
        url=url,
        action="status_rechecked",
        verdict=result.verdict,
        is_active=result.is_active,
    )
