"""Listings routes – query stored items."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.storage.models import ListingRecord
from app.storage.repository import ListingRepository, create_tables, get_session_factory

router = APIRouter()


def _mv(size_dict: dict, *keys: str) -> Optional[float]:
    """MeasurementValue を安全に展開して float を返す。

    size_attrs は model_dump(mode='json') で保存されるため
    measurement フィールドは {"value": float, ...} の dict になっている。
    """
    obj: object = size_dict
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    if isinstance(obj, dict):
        val = obj.get("value")
        return float(val) if val is not None else None
    if isinstance(obj, (int, float)):
        return float(obj)
    return None


def _record_to_dict(r: ListingRecord) -> dict:
    signals = r.page_signals or {}
    price = r.price_attrs or {}
    status = r.status_attrs or {}
    style = r.style_attrs or {}
    size = r.size_attrs or {}
    decision = r.decision_json or {}

    image_urls = signals.get("image_urls") or []
    thumbnail = image_urls[0] if image_urls else None

    buy_now = price.get("buy_now_price_jpy")
    current = price.get("current_price_jpy")
    price_jpy = buy_now or current

    # source_site に応じたラベル
    _SITE_LABELS = {
        "yahoo_auctions":    "ヤフオク",
        "yahoo_shopping":    "Yahoo!ショッピング",
        "mercari":           "メルカリ",
        "paypay_flea_market": "PayPayフリマ",
    }

    return {
        "id": r.id,
        "url": r.url,
        "source_site": r.source_site,
        "source_label": _SITE_LABELS.get(r.source_site or "", "サイト"),
        "title": signals.get("title_text") or "",
        "price_jpy": price_jpy,
        "score": r.score,
        "verdict": r.verdict,
        "is_active": r.is_active,
        "needs_recheck": r.needs_recheck,
        "thumbnail": thumbnail,
        "normalized_status": status.get("normalized_status"),
        "button_count": style.get("button_count"),
        # MeasurementValue の .value だけを返す（[object Object] 防止）
        "jacket_shoulder_cm": _mv(size, "jacket", "shoulder_cm"),
        "jacket_chest_cm":    _mv(size, "jacket", "chest_width_cm"),
        "pants_waist_cm":     _mv(size, "pants", "waist_flat_cm"),
        "non_blocking_reasons": decision.get("non_blocking_reasons") or decision.get("reasons") or [],
        "blocking_reasons": decision.get("blocking_reasons") or [],
        "buy_now_price_jpy": price.get("buy_now_price_jpy"),
        "listing_type": price.get("listing_type"),
        "retrieved_at": r.retrieved_at.isoformat() if r.retrieved_at else None,
    }


@router.get("/stats")
async def listing_stats() -> dict:
    """Return verdict counts from the full DB (no LIMIT)."""
    await create_tables()
    factory = get_session_factory()
    async with factory() as session:
        repo = ListingRepository(session)
        counts = await repo.count_by_verdict()
    return {
        "MATCH":    counts.get("MATCH", 0),
        "REVIEW":   counts.get("REVIEW", 0),
        "NO_MATCH": counts.get("NO_MATCH", 0),
    }


@router.get("")
async def list_listings(
    verdict: Optional[str] = Query(None, description="MATCH | NO_MATCH | REVIEW"),
    active_only: bool = Query(False),
    limit: int = Query(200, le=500),
    sort: str = Query("score", description="score | recent"),
) -> list[dict]:
    """Return stored listings, optionally filtered by verdict."""
    await create_tables()
    factory = get_session_factory()
    async with factory() as session:
        repo = ListingRepository(session)
        if verdict:
            records = await repo.list_by_verdict(verdict, limit=limit, sort=sort)
        else:
            from sqlalchemy import select
            stmt = select(ListingRecord).order_by(ListingRecord.score.desc()).limit(limit)
            result = await session.execute(stmt)
            records = list(result.scalars())

    if active_only:
        records = [r for r in records if r.is_active]

    return [_record_to_dict(r) for r in records]


class NgRequest(BaseModel):
    reason: str = "手動NG"


@router.post("/{item_id}/ng")
async def mark_as_ng(item_id: str, body: NgRequest = NgRequest()) -> dict:
    """Manually mark a listing as NG (overrides current verdict)."""
    await create_tables()
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            repo = ListingRepository(session)
            record = await repo.get_by_id(item_id)
            if record is None:
                raise HTTPException(status_code=404, detail="商品が見つかりません")
            await repo.mark_as_ng(record, reason=body.reason)
    return {"ok": True, "id": item_id}
