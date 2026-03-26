"""SQLAlchemy ORM models for persistent storage.

Phase 1: Minimal schema to store EvidencePackage and DecisionOutput.
Migrations are managed via Alembic (see storage/migrations/).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ListingRecord(Base):
    """Stores one scraped listing and its parsed attributes."""

    __tablename__ = "listing_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    source_site: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(128), nullable=True, index=True)

    # Raw signals (JSON)
    page_signals: Mapped[dict] = mapped_column(JSON, nullable=True)
    evidence_blocks: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Parsed attributes (JSON)
    size_attrs: Mapped[dict] = mapped_column(JSON, nullable=True)
    price_attrs: Mapped[dict] = mapped_column(JSON, nullable=True)
    status_attrs: Mapped[dict] = mapped_column(JSON, nullable=True)
    material_attrs: Mapped[dict] = mapped_column(JSON, nullable=True)
    style_attrs: Mapped[dict] = mapped_column(JSON, nullable=True)
    condition_attrs: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Decision
    verdict: Mapped[str] = mapped_column(String(16), nullable=True, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=True)
    decision_json: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Meta
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
