"""Recheck job – re-run parser pipeline on a stored EvidencePackage.

Allows re-parsing without re-fetching from the web.
Useful when parser rules are updated.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.connectors.base import (
    DecisionOutput, EvidencePackage, MergedStructuredAttributes, ParserInput,
)
from app.evidence.cleaner import clean_blocks
from app.evidence.merger import merge_attributes
from app.parsers.condition_parser import parse_condition
from app.parsers.material_parser import parse_material
from app.parsers.price_parser import parse_price
from app.parsers.size_parser import parse_size
from app.parsers.status_parser import parse_status
from app.parsers.style_parser import parse_style
from app.rules.decision_engine import decide

logger = logging.getLogger(__name__)


@dataclass
class RecheckResult:
    item_id: str
    success: bool
    merged: Optional[MergedStructuredAttributes] = None
    decision: Optional[DecisionOutput] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


def run_recheck(package: EvidencePackage) -> RecheckResult:
    """Re-run the parser pipeline on an existing EvidencePackage.

    Does not re-fetch from the web. Returns RecheckResult.
    Exceptions are caught and returned as RecheckResult(success=False).
    """
    try:
        cleaned = clean_blocks(package.evidence_blocks)
        pi = ParserInput(
            item_id=package.item_id,
            evidence_blocks=cleaned,
            page_signals=package.page_signals,
        )
        size = parse_size(pi)
        price = parse_price(pi)
        status = parse_status(pi)
        material = parse_material(pi)
        style = parse_style(pi)
        condition = parse_condition(pi)

        merged = merge_attributes(
            item_id=package.item_id,
            size=size, price=price, status=status,
            material=material, style=style, condition=condition,
        )
        decision = decide(merged)

        warnings = (
            size.warnings + price.warnings + status.warnings
            + material.warnings + style.warnings + condition.warnings
        )
        logger.info("Recheck done: %s → %s (score=%.2f)", package.item_id, decision.verdict, decision.score)
        return RecheckResult(
            item_id=package.item_id,
            success=True,
            merged=merged,
            decision=decision,
            warnings=warnings,
        )
    except Exception as exc:
        logger.exception("Recheck failed: %s", package.item_id)
        return RecheckResult(item_id=package.item_id, success=False, error=str(exc))


async def run_recheck_job(item_id: str) -> None:
    """Async wrapper – placeholder for future DB-backed recheck."""
    logger.info("run_recheck_job called for item_id=%s (DB lookup not yet implemented)", item_id)
