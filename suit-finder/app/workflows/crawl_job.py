"""Crawl job – fetch one URL and run the full parser pipeline.

This is the main entry point for processing a single listing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.connectors.base import (
    DecisionOutput,
    EvidencePackage,
    MergedStructuredAttributes,
    ParserInput,
)
from app.connectors.yahoo_auctions import YahooAuctionsConnector
from app.evidence.cleaner import clean_blocks
from app.evidence.extractor import build_evidence_package
from app.evidence.merger import merge_attributes
from app.parsers.condition_parser import parse_condition
from app.parsers.material_parser import parse_material
from app.parsers.price_parser import parse_price
from app.parsers.size_parser import parse_size
from app.parsers.status_parser import parse_status
from app.parsers.style_parser import parse_style
from app.llm.supplement import maybe_supplement
from app.rules.decision_engine import decide

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    url: str
    success: bool
    package: Optional[EvidencePackage] = None
    merged: Optional[MergedStructuredAttributes] = None
    decision: Optional[DecisionOutput] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


async def run_crawl_job(url: str, headless: bool = True) -> CrawlResult:
    """Fetch a Yahoo Auctions listing and run the full pipeline.

    Steps:
    1. Fetch rendered page → PageSignals
    2. Extract → EvidencePackage
    3. Clean evidence blocks
    4. Run all parsers
    5. Merge attributes
    6. Decide verdict

    Exceptions are caught and returned as CrawlResult(success=False).
    """
    try:
        connector = YahooAuctionsConnector(headless=headless)
        signals = await connector.fetch_page_signals(url)

        package = build_evidence_package(url=url, signals=signals)
        package.evidence_blocks = clean_blocks(package.evidence_blocks)

        parser_input = ParserInput(
            item_id=package.item_id,
            evidence_blocks=package.evidence_blocks,
            page_signals=package.page_signals,
        )

        size = parse_size(parser_input)
        price = parse_price(parser_input)
        status = parse_status(parser_input)
        material = parse_material(parser_input)
        style = parse_style(parser_input)
        condition = parse_condition(parser_input)

        # LLM supplement: fill unknown fields if GEMINI_API_KEY is set
        size, material = await maybe_supplement(parser_input, size, material)

        merged = merge_attributes(
            item_id=package.item_id,
            size=size,
            price=price,
            status=status,
            material=material,
            style=style,
            condition=condition,
        )

        decision = decide(merged)

        all_warnings = (
            size.warnings + price.warnings + status.warnings
            + material.warnings + style.warnings + condition.warnings
        )

        logger.info(
            "Crawl complete: %s → verdict=%s score=%.2f",
            url, decision.verdict, decision.score,
        )
        return CrawlResult(
            url=url,
            success=True,
            package=package,
            merged=merged,
            decision=decision,
            warnings=all_warnings,
        )

    except Exception as exc:
        logger.exception("Crawl job failed for %s", url)
        return CrawlResult(url=url, success=False, error=str(exc))
