"""Repository layer for ListingRecord persistence.

Phase 1: Minimal CRUD operations.
Database URL is read from the DATABASE_URL environment variable.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.connectors.base import (
    DecisionOutput,
    EvidencePackage,
    MergedStructuredAttributes,
)
from app.storage.models import Base, ListingRecord

logger = logging.getLogger(__name__)


def _get_engine():
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./suitfinder.db")
    if db_url.startswith("sqlite"):
        # SQLite: wait up to 30 s for a write lock instead of immediately failing
        return create_async_engine(
            db_url,
            echo=False,
            connect_args={"timeout": 30},
        )
    return create_async_engine(db_url, echo=False, pool_pre_ping=True)


_engine = None
_session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = _get_engine()
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


async def create_tables() -> None:
    """Create all tables (dev only – use Alembic for production)."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class ListingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_from_evidence(
        self,
        package: EvidencePackage,
        merged: MergedStructuredAttributes,
        decision: DecisionOutput,
        needs_recheck: bool = False,
    ) -> ListingRecord:
        """Insert or update a ListingRecord from pipeline outputs."""
        stmt = select(ListingRecord).where(ListingRecord.url == package.url)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            record = ListingRecord(url=package.url, source_site=package.source_site)
            self.session.add(record)

        record.item_id = package.item_id
        record.page_signals = package.page_signals.model_dump(mode="json")
        record.evidence_blocks = [b.model_dump(mode="json") for b in package.evidence_blocks]
        record.size_attrs = merged.size.model_dump(mode="json")
        record.price_attrs = merged.price.model_dump(mode="json")
        record.status_attrs = merged.status.model_dump(mode="json")
        record.material_attrs = merged.material.model_dump(mode="json")
        record.style_attrs = merged.style.model_dump(mode="json")
        record.condition_attrs = merged.condition.model_dump(mode="json")
        record.verdict = decision.verdict
        record.score = decision.score
        record.decision_json = decision.model_dump(mode="json")
        record.needs_recheck = needs_recheck
        record.retrieved_at = package.retrieved_at

        await self.session.flush()
        return record

    async def get_by_url(self, url: str) -> Optional[ListingRecord]:
        stmt = select(ListingRecord).where(ListingRecord.url == url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_verdict(
        self,
        verdict: str,
        limit: int = 100,
        sort: str = "score",   # "score" | "recent"
    ) -> list[ListingRecord]:
        order = (
            ListingRecord.retrieved_at.desc()
            if sort == "recent"
            else ListingRecord.score.desc()
        )
        stmt = (
            select(ListingRecord)
            .where(ListingRecord.verdict == verdict)
            .order_by(order)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def count_by_verdict(self) -> dict[str, int]:
        """Return total record count grouped by verdict (no LIMIT)."""
        stmt = select(
            ListingRecord.verdict,
            func.count(ListingRecord.id).label("cnt"),
        ).group_by(ListingRecord.verdict)
        result = await self.session.execute(stmt)
        return {row.verdict: row.cnt for row in result if row.verdict}

    async def list_active_matches(self) -> list[ListingRecord]:
        """Return all MATCH records that are still active (for status recheck)."""
        stmt = (
            select(ListingRecord)
            .where(ListingRecord.verdict == "MATCH")
            .where(ListingRecord.is_active == True)  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def update_status(
        self,
        record: ListingRecord,
        is_active: bool,
        status_attrs: dict,
    ) -> None:
        """Update listing status after a recheck (no full re-parse)."""
        record.is_active = is_active
        record.status_attrs = status_attrs
        await self.session.flush()

    async def get_by_id(self, item_id: str) -> Optional[ListingRecord]:
        stmt = select(ListingRecord).where(ListingRecord.id == item_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_as_ng(self, record: ListingRecord, reason: str = "手動NG") -> None:
        """Manually override verdict to NO_MATCH and lock from future rechecks."""
        record.verdict = "NO_MATCH"
        record.needs_recheck = False
        # Append the manual reason to decision_json for audit trail
        decision = record.decision_json or {}
        blocking = decision.get("blocking_reasons", [])
        if reason not in blocking:
            blocking.insert(0, reason)
        decision["blocking_reasons"] = blocking
        decision["verdict"] = "NO_MATCH"
        record.decision_json = decision
        await self.session.flush()

    async def mark_as_ok(self, record: ListingRecord, reason: str = "手動OK") -> None:
        """Manually override verdict to MATCH (human approval)."""
        record.verdict = "MATCH"
        record.needs_recheck = False
        decision = record.decision_json or {}
        decision["blocking_reasons"] = []
        decision["verdict"] = "MATCH"
        decision["manual_override"] = reason
        record.decision_json = decision
        await self.session.flush()

    async def delete_by_date(self, date_str: str) -> int:
        """Delete records retrieved on the given date (YYYY-MM-DD, JST).

        Returns the number of deleted rows.
        """
        from datetime import timedelta
        from sqlalchemy import delete as sa_delete

        # JST は UTC+9 なので date_str の 00:00 JST = UTC-9h 前日15:00 UTC
        # ただし retrieved_at は UTC で保存されているため、±9h の UTC 範囲で絞る
        from datetime import datetime as dt
        jst_start = dt.fromisoformat(date_str + "T00:00:00").replace(
            tzinfo=timezone.utc
        ) - timedelta(hours=9)
        jst_end = jst_start + timedelta(days=1)

        stmt = sa_delete(ListingRecord).where(
            ListingRecord.retrieved_at >= jst_start,
            ListingRecord.retrieved_at < jst_end,
        )
        result = await self.session.execute(stmt)
        return result.rowcount
