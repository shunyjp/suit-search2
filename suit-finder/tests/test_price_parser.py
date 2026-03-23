"""Unit tests for price_parser."""

from __future__ import annotations

import pytest

from app.connectors.base import EvidenceBlock, PageSignals, ParserInput
from app.parsers.price_parser import parse_price


def _make_input(price_text: str = "", description: str = "", all_text: str = "") -> ParserInput:
    blocks: list[EvidenceBlock] = []
    if price_text:
        blocks.append(EvidenceBlock(source="price", text=price_text, confidence=1.0))
    if description:
        blocks.append(EvidenceBlock(source="description", text=description, confidence=0.85))
    if all_text:
        blocks.append(EvidenceBlock(source="all_text", text=all_text, confidence=0.6))
    signals = PageSignals(url="https://example.com", price_text=price_text, all_text=all_text)
    return ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)


class TestPriceParserAuction:
    def test_auction_with_buy_now(self):
        inp = _make_input(price_text="現在 8,500円\n即決 15,000円")
        out = parse_price(inp)
        assert out.listing_type == "auction"
        assert out.current_price_jpy == 8500
        assert out.buy_now_price_jpy == 15000
        assert out.confidence >= 0.8

    def test_auction_without_buy_now(self):
        inp = _make_input(price_text="現在 5,000円\nオークション")
        out = parse_price(inp)
        assert out.listing_type == "auction"
        assert out.current_price_jpy == 5000
        assert out.buy_now_price_jpy is None
        assert "buy_now_price_jpy" in out.unknown_fields

    def test_buy_now_only(self):
        inp = _make_input(price_text="即決 20,000円")
        out = parse_price(inp)
        assert out.listing_type == "buy_now_only"
        assert out.buy_now_price_jpy == 20000

    def test_shipping_included(self):
        inp = _make_input(price_text="現在 8,000円\n即決 15,000円\n送料込み")
        out = parse_price(inp)
        assert out.shipping_included is True
        assert out.shipping_price_jpy == 0

    def test_shipping_separate(self):
        inp = _make_input(price_text="現在 8,000円\n即決 15,000円\n送料 520円")
        out = parse_price(inp)
        assert out.shipping_price_jpy == 520

    def test_no_price_info(self):
        inp = _make_input(price_text="")
        out = parse_price(inp)
        assert out.current_price_jpy is None
        assert out.confidence < 0.5
        assert "current_price_jpy" in out.unknown_fields

    def test_full_width_digits(self):
        # Full-width price digits (NFKC normalised before parsing)
        inp = _make_input(price_text="現在 １５，０００円\n即決 ２５，０００円")
        out = parse_price(inp)
        # Full-width digits are normalised via NFKC
        assert out.current_price_jpy == 15000
        assert out.buy_now_price_jpy == 25000

    def test_fixed_price_listing(self):
        inp = _make_input(description="販売価格：18,000円")
        out = parse_price(inp)
        assert out.listing_type == "fixed_price"
        assert out.current_price_jpy == 18000

    def test_evidence_from_description_fallback(self):
        inp = _make_input(description="現在 3,000円\n即決 10,000円")
        out = parse_price(inp)
        assert out.buy_now_price_jpy == 10000


class TestPriceParserEdgeCases:
    def test_comma_separated_price(self):
        inp = _make_input(price_text="現在 1,234,567円")
        out = parse_price(inp)
        assert out.current_price_jpy == 1234567

    def test_unknown_fields_listed(self):
        inp = _make_input(price_text="現在 5,000円")
        out = parse_price(inp)
        assert "buy_now_price_jpy" in out.unknown_fields
        assert "shipping_price_jpy" in out.unknown_fields
