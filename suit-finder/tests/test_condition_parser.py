"""Unit tests for condition_parser."""

from __future__ import annotations

import pytest

from app.connectors.base import EvidenceBlock, PageSignals, ParserInput
from app.parsers.condition_parser import parse_condition


def _make_input(*texts: str, source: str = "description") -> ParserInput:
    blocks = [EvidenceBlock(source=source, text=t, confidence=0.85) for t in texts]
    signals = PageSignals(url="https://example.com")
    return ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)


class TestGradeDetection:
    def test_grade_s(self):
        out = parse_condition(_make_input("未使用品です"))
        assert out.grade == "S"

    def test_grade_a_bisan(self):
        out = parse_condition(_make_input("美品です"))
        assert out.grade == "A"

    def test_grade_a_rank(self):
        out = parse_condition(_make_input("Aランク品"))
        assert out.grade == "A"

    def test_grade_b(self):
        out = parse_condition(_make_input("Bランク 使用感あり"))
        assert out.grade == "B"

    def test_grade_c(self):
        out = parse_condition(_make_input("Cランク 傷あり"))
        assert out.grade == "C"

    def test_grade_d(self):
        out = parse_condition(_make_input("難あり ジャンク品"))
        assert out.grade == "D"

    def test_unknown_grade(self):
        out = parse_condition(_make_input("スーツです"))
        assert out.grade is None
        assert "grade" in out.unknown_fields


class TestStainDetection:
    def test_stain_present(self):
        out = parse_condition(_make_input("汚れがあります"))
        assert out.has_stain is True

    def test_stain_absent(self):
        out = parse_condition(_make_input("汚れなし"))
        assert out.has_stain is False

    def test_stain_absent_verbose(self):
        out = parse_condition(_make_input("目立った汚れはありません"))
        assert out.has_stain is False

    def test_severe_stain_warning(self):
        out = parse_condition(_make_input("ひどい汚れがあります"))
        assert out.has_stain is True
        assert any("ひどい" in w for w in out.warnings)

    def test_stain_unknown(self):
        out = parse_condition(_make_input("スーツです"))
        assert out.has_stain is None
        assert "has_stain" in out.unknown_fields


class TestHoleDetection:
    def test_hole_present(self):
        out = parse_condition(_make_input("穴あり"))
        assert out.has_hole is True

    def test_hole_absent(self):
        out = parse_condition(_make_input("穴なし"))
        assert out.has_hole is False

    def test_tear_present(self):
        out = parse_condition(_make_input("破れあり"))
        assert out.has_hole is True

    def test_hole_unknown(self):
        out = parse_condition(_make_input("スーツです"))
        assert out.has_hole is None
        assert "has_hole" in out.unknown_fields


class TestConditionCombined:
    def test_good_condition(self):
        out = parse_condition(_make_input("美品 汚れなし 穴なし"))
        assert out.grade == "A"
        assert out.has_stain is False
        assert out.has_hole is False
        assert out.confidence > 0.0

    def test_bad_condition(self):
        out = parse_condition(_make_input("ひどい汚れ 穴あり"))
        assert out.has_stain is True
        assert out.has_hole is True
