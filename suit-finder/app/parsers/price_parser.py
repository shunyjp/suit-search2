"""Price parser – Phase 2.

Extracts from evidence_blocks:
- listing_type  : "auction" | "fixed_price" | "buy_now_only"
- current_price_jpy
- buy_now_price_jpy
- shipping_price_jpy
- shipping_included
"""

from __future__ import annotations

import re
from typing import Optional

from app.connectors.base import (
    EvidenceBlock,
    ParserInput,
    PriceParserOutput,
)
from app.normalizers.text import normalize_japanese_text
from app.normalizers.units import parse_jpy


# ---------------------------------------------------------------------------
# Regex patterns (all applied after NFKC normalisation)
# ---------------------------------------------------------------------------

# 現在価格: "現在 1,234円" / "現在価格1,234円"
_CURRENT_PRICE = re.compile(
    r"現在\s*(?:価格|入札額|価格)?[：:\s]*([0-9,，]+)\s*円",
    re.IGNORECASE,
)

# 即決価格: "即決 15,000円" / "即決価格：15,000円"
_BUY_NOW = re.compile(
    r"即決\s*(?:価格)?[：:\s]*([0-9,，]+)\s*円",
    re.IGNORECASE,
)

# 落札価格 (closed auctions)
_WINNING_PRICE = re.compile(
    r"落札(?:価格|金額)?[：:\s]*([0-9,，]+)\s*円",
    re.IGNORECASE,
)

# 送料: "送料 520円" / "送料込み" / "送料無料"
_SHIPPING_PRICE = re.compile(
    r"送料\s*([0-9,，]+)\s*円",
    re.IGNORECASE,
)
_SHIPPING_FREE = re.compile(r"送料\s*(?:無料|込み|込)", re.IGNORECASE)

# Fixed price listing (フリマ style) – "販売価格" or lone "¥XX,XXX"
_FIXED_PRICE = re.compile(
    r"(?:販売価格|定価|金額)[：:\s]*([0-9,，]+)\s*円",
    re.IGNORECASE,
)

# Generic number+円 fallback
_GENERIC_PRICE = re.compile(r"([0-9,，]{3,})\s*円")

# "オークション" keyword indicates auction listing
_AUCTION_KEYWORD = re.compile(r"オークション|入札", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return normalize_japanese_text(text).replace("，", ",")


def _first_match_jpy(pattern: re.Pattern[str], text: str) -> Optional[int]:
    m = pattern.search(text)
    if m:
        return parse_jpy(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_price(parser_input: ParserInput) -> PriceParserOutput:
    """Parse price information from evidence blocks.

    Strategy:
    1. Prefer 'price' source blocks (highest confidence).
    2. Fall back to 'description' and 'all_text'.
    3. Detect listing_type from keywords (即決, オークション).
    """
    output = PriceParserOutput()
    evidence_texts: list[str] = []
    warnings: list[str] = []

    # Ordered by priority: price > specs > description > all_text
    priority = ["price", "specs", "description", "all_text"]

    def _sources_ordered(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
        order = {s: i for i, s in enumerate(priority)}
        return sorted(blocks, key=lambda b: order.get(b.source, 99))

    ordered = _sources_ordered(parser_input.evidence_blocks)
    full_text = "\n".join(_clean(b.text) for b in ordered)

    # --- current price ---
    current = _first_match_jpy(_CURRENT_PRICE, full_text)
    if current is None:
        current = _first_match_jpy(_WINNING_PRICE, full_text)
    output.current_price_jpy = current
    if current is not None:
        evidence_texts.append(f"現在価格: {current}円")

    # --- buy now price ---
    buy_now = _first_match_jpy(_BUY_NOW, full_text)
    output.buy_now_price_jpy = buy_now
    if buy_now is not None:
        evidence_texts.append(f"即決: {buy_now}円")

    # --- fixed price fallback ---
    fixed = _first_match_jpy(_FIXED_PRICE, full_text)

    # --- shipping ---
    shipping = _first_match_jpy(_SHIPPING_PRICE, full_text)
    output.shipping_price_jpy = shipping
    if _SHIPPING_FREE.search(full_text):
        output.shipping_included = True
        output.shipping_price_jpy = 0
        evidence_texts.append("送料込み")
    elif shipping is not None:
        evidence_texts.append(f"送料: {shipping}円")

    # --- listing_type detection ---
    has_auction_kw = bool(_AUCTION_KEYWORD.search(full_text))
    if buy_now is not None and current is not None:
        output.listing_type = "auction"
    elif buy_now is not None and current is None:
        output.listing_type = "buy_now_only"
    elif fixed is not None:
        output.listing_type = "fixed_price"
        if output.current_price_jpy is None:
            output.current_price_jpy = fixed
            output.buy_now_price_jpy = fixed
            evidence_texts.append(f"販売価格: {fixed}円")
    elif has_auction_kw and current is not None:
        output.listing_type = "auction"
    elif current is not None:
        output.listing_type = "auction"
    else:
        output.listing_type = None
        warnings.append("listing_type を特定できませんでした")

    # --- confidence ---
    if output.current_price_jpy is not None or output.buy_now_price_jpy is not None:
        output.confidence = 0.9
    else:
        output.confidence = 0.3

    # --- unknown_fields ---
    unknown: list[str] = []
    if output.listing_type is None:
        unknown.append("listing_type")
    if output.current_price_jpy is None:
        unknown.append("current_price_jpy")
    if output.buy_now_price_jpy is None:
        unknown.append("buy_now_price_jpy")
    if output.shipping_price_jpy is None and not output.shipping_included:
        unknown.append("shipping_price_jpy")

    output.unknown_fields = unknown
    output.warnings = warnings
    output.evidence = evidence_texts
    return output
