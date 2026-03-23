"""Unit tests for style_parser."""

from __future__ import annotations

import pytest

from app.connectors.base import EvidenceBlock, PageSignals, ParserInput
from app.parsers.style_parser import parse_style


def _make_input(*texts: str, source: str = "description") -> ParserInput:
    blocks = [EvidenceBlock(source=source, text=t, confidence=0.85) for t in texts]
    signals = PageSignals(url="https://example.com")
    return ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)


class TestButtonType:
    def test_single_breasted(self):
        out = parse_style(_make_input("シングルブレストスーツ"))
        assert out.button_type == "single"

    def test_double_breasted(self):
        out = parse_style(_make_input("ダブルブレストスーツ"))
        assert out.button_type == "double"

    def test_single_short(self):
        out = parse_style(_make_input("シングルジャケット"))
        assert out.button_type == "single"

    def test_double_short(self):
        out = parse_style(_make_input("ダブルジャケット"))
        assert out.button_type == "double"

    def test_unknown_when_absent(self):
        out = parse_style(_make_input("スーツです"))
        assert out.button_type is None
        assert "button_type" in out.unknown_fields


class TestButtonCount:
    def test_2_button(self):
        out = parse_style(_make_input("2ボタンスーツ"))
        assert out.button_count == 2

    def test_3_button(self):
        out = parse_style(_make_input("3ボタンジャケット"))
        assert out.button_count == 3

    def test_1_button(self):
        out = parse_style(_make_input("1ボタン"))
        assert out.button_count == 1

    def test_kanji_2_button(self):
        out = parse_style(_make_input("二ボタン"))
        assert out.button_count == 2

    def test_kanji_3_button(self):
        out = parse_style(_make_input("三つボタン"))
        assert out.button_count == 3

    def test_2b_abbreviation(self):
        out = parse_style(_make_input("2B シングル"))
        assert out.button_count == 2

    def test_unknown_when_absent(self):
        out = parse_style(_make_input("スーツです"))
        assert out.button_count is None
        assert "button_count" in out.unknown_fields


class TestButtonColor:
    def test_gold_button(self):
        out = parse_style(_make_input("金ボタンのジャケット"))
        assert out.button_color == "gold"

    def test_silver_button(self):
        out = parse_style(_make_input("銀ボタン付き"))
        assert out.button_color == "silver"

    def test_black_button(self):
        out = parse_style(_make_input("黒ボタン"))
        assert out.button_color == "black"

    def test_unknown_when_absent(self):
        out = parse_style(_make_input("2ボタンスーツ"))
        assert out.button_color is None
        assert "button_color" in out.unknown_fields


class TestStyleCombined:
    def test_full_description(self):
        out = parse_style(_make_input("シングルブレスト 2ボタン 黒ボタン スーツ"))
        assert out.button_type == "single"
        assert out.button_count == 2
        assert out.button_color == "black"

    def test_ng_combination_detected(self):
        out = parse_style(_make_input("ダブルブレスト 金ボタン 2ボタン"))
        assert out.button_type == "double"
        assert out.button_color == "gold"
