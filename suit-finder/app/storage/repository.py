"""Repository layer for ListingRecord persistence.

Phase 1: Minimal CRUD operations.
Database URL is read from the DATABASE_URL environment variable.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.connectors.base import (
    DecisionOutput,
    EvidencePackage,
    MergedStructuredAttributes,
)
from app.storage.models import Base, ListingRecord

logger = logging.getLogger(__name__)


def _get_engine():
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/suitfinder")
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
        record.retrieved_at = package.retrieved_at

        await self.session.flush()
        return record

    async def get_by_url(self, url: str) -> Optional[ListingRecord]:
        stmt = select(ListingRecord).where(ListingRecord.url == url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_verdict(
        self, verdict: str, limit: int = 100
    ) -> list[ListingRecord]:
        stmt = (
            select(ListingRecord)
            .where(ListingRecord.verdict == verdict)
            .order_by(ListingRecord.score.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())
