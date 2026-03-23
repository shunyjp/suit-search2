"""Unit tests for status_parser."""

from __future__ import annotations

import pytest

from app.connectors.base import EvidenceBlock, PageSignals, ParserInput
from app.parsers.status_parser import parse_status


def _make_input(status_text: str = "", description: str = "", all_text: str = "") -> ParserInput:
    blocks: list[EvidenceBlock] = []
    if status_text:
        blocks.append(EvidenceBlock(source="status", text=status_text, confidence=1.0))
    if description:
        blocks.append(EvidenceBlock(source="description", text=description, confidence=0.85))
    if all_text:
        blocks.append(EvidenceBlock(source="all_text", text=all_text, confidence=0.6))
    signals = PageSignals(url="https://example.com", status_text=status_text)
    return ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)


class TestStatusParserActive:
    def test_active_explicit(self):
        out = parse_status(_make_input(status_text="出品中"))
        assert out.normalized_status == "active"
        assert out.confidence >= 0.85

    def test_active_in_sale(self):
        out = parse_status(_make_input(status_text="販売中"))
        assert out.normalized_status == "active"

    def test_active_remaining_time(self):
        out = parse_status(_make_input(status_text="残り 2日 3時間"))
        assert out.normalized_status == "active"


class TestStatusParserSold:
    def test_sold(self):
        out = parse_status(_make_input(status_text="落札済み"))
        assert out.normalized_status == "sold"
        assert out.confidence >= 0.9

    def test_sold_out(self):
        out = parse_status(_make_input(status_text="売り切れ"))
        assert out.normalized_status == "sold"

    def test_purchased(self):
        out = parse_status(_make_input(status_text="購入済み"))
        assert out.normalized_status == "sold"


class TestStatusParserEnded:
    def test_ended(self):
        out = parse_status(_make_input(status_text="オークション終了"))
        assert out.normalized_status == "ended"

    def test_ended_simple(self):
        out = parse_status(_make_input(status_text="終了"))
        assert out.normalized_status == "ended"


class TestStatusParserUnknown:
    def test_empty(self):
        out = parse_status(_make_input(status_text=""))
        assert out.normalized_status == "unknown"
        assert out.confidence < 0.5
        assert len(out.warnings) > 0

    def test_fallback_to_description(self):
        out = parse_status(_make_input(description="残り 5時間で終了します"))
        assert out.normalized_status == "active"

    def test_sold_keyword_in_all_text(self):
        out = parse_status(_make_input(all_text="この商品は落札済みです"))
        assert out.normalized_status == "sold"
