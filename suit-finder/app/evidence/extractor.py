"""Extract EvidenceBlocks from PageSignals.

Each text bucket in PageSignals becomes one or more EvidenceBlocks.
The extractor does NOT interpret meaning – it only segments and labels text.
"""

from __future__ import annotations

from app.connectors.base import EvidenceBlock, EvidencePackage, PageSignals
from app.normalizers.text import clean_text


def _make_block(source: str, text: str, block_type: str = "text",
                confidence: float = 1.0) -> EvidenceBlock:
    cleaned = clean_text(text)
    return EvidenceBlock(
        source=source,
        text=cleaned,
        block_type=block_type,
        confidence=confidence,
    )


def extract_evidence_blocks(signals: PageSignals) -> list[EvidenceBlock]:
    """Convert PageSignals → list[EvidenceBlock].

    Rules:
    - title_text   → high confidence (selectors are stable)
    - price_text   → high confidence
    - status_text  → high confidence
    - specs_text   → high confidence (structured table)
    - brand_text   → high confidence
    - category_text → medium confidence
    - description_text → medium (free text, may contain noise)
    - all_text     → low confidence fallback (may duplicate others)
    """
    blocks: list[EvidenceBlock] = []

    if signals.title_text.strip():
        blocks.append(_make_block("title", signals.title_text, "title", 1.0))

    if signals.price_text.strip():
        blocks.append(_make_block("price", signals.price_text, "price", 1.0))

    if signals.status_text.strip():
        blocks.append(_make_block("status", signals.status_text, "status", 1.0))

    if signals.specs_text.strip():
        blocks.append(_make_block("specs", signals.specs_text, "specs", 0.95))

    if signals.brand_text.strip():
        blocks.append(_make_block("brand", signals.brand_text, "brand", 0.95))

    if signals.category_text.strip():
        blocks.append(_make_block("category", signals.category_text, "category", 0.8))

    if signals.description_text.strip():
        # Split description into paragraph-sized blocks for better evidence granularity
        paras = [p.strip() for p in signals.description_text.split("\n") if p.strip()]
        for para in paras:
            cleaned = clean_text(para)
            if cleaned:
                blocks.append(EvidenceBlock(
                    source="description",
                    text=cleaned,
                    block_type="description",
                    confidence=0.85,
                ))

    # all_text is a fallback – mark lower confidence to avoid over-counting
    if signals.all_text.strip():
        blocks.append(_make_block("all_text", signals.all_text, "all_text", 0.6))

    return blocks


def build_evidence_package(
    url: str,
    signals: PageSignals,
    item_id: str | None = None,
    source_site: str = "yahoo_auctions",
) -> EvidencePackage:
    """Build a full EvidencePackage from a URL and its PageSignals."""
    blocks = extract_evidence_blocks(signals)
    pkg = EvidencePackage(
        url=url,
        source_site=source_site,
        page_signals=signals,
        evidence_blocks=blocks,
    )
    if item_id:
        pkg.item_id = item_id
    return pkg
