"""Unit tests for material_parser."""

from __future__ import annotations

import pytest

from app.connectors.base import EvidenceBlock, PageSignals, ParserInput
from app.parsers.material_parser import parse_material


def _make_input(*texts: str, source: str = "description") -> ParserInput:
    blocks = [EvidenceBlock(source=source, text=t, confidence=0.85) for t in texts]
    signals = PageSignals(url="https://example.com")
    return ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)


class TestMaterialParserOuter:
    def test_wool_100(self):
        out = parse_material(_make_input("表地：ウール100%"))
        assert len(out.outer_fibers) == 1
        assert out.outer_fibers[0]["fiber"] == "wool"
        assert out.outer_fibers[0]["percentage"] == 100

    def test_single_fiber_infers_100(self):
        out = parse_material(_make_input("ウール"))
        assert out.outer_fibers[0]["percentage"] == 100

    def test_mohair_wool_mix(self):
        out = parse_material(_make_input("表地：モヘア60% ウール40%"))
        fibers = {f["fiber"]: f["percentage"] for f in out.outer_fibers}
        assert fibers["mohair"] == 60
        assert fibers["wool"] == 40

    def test_polyester_detected(self):
        out = parse_material(_make_input("ポリエステル100%"))
        assert out.outer_fibers[0]["fiber"] == "polyester"

    def test_no_material_unknown(self):
        out = parse_material(_make_input("美品のスーツです"))
        assert "outer_fibers" in out.unknown_fields
        assert len(out.warnings) > 0

    def test_outer_lining_split(self):
        out = parse_material(_make_input("表地：ウール100%\n裏地：ポリエステル100%"))
        assert out.outer_fibers[0]["fiber"] == "wool"
        assert out.lining_fibers[0]["fiber"] == "polyester"

    def test_lining_not_counted_as_outer(self):
        out = parse_material(_make_input("裏地：ポリエステル100%"))
        # outer_fibers should be empty (no outer info)
        assert "outer_fibers" in out.unknown_fields

    def test_confidence_nonzero_when_found(self):
        out = parse_material(_make_input("ウール100%"))
        assert out.confidence > 0.0

    def test_specs_priority_over_description(self):
        blocks = [
            EvidenceBlock(source="description", text="ウール80% ポリエステル20%", confidence=0.85),
            EvidenceBlock(source="specs", text="ウール100%", confidence=0.95),
        ]
        signals = PageSignals(url="https://example.com")
        inp = ParserInput(item_id="t", evidence_blocks=blocks, page_signals=signals)
        out = parse_material(inp)
        assert out.outer_fibers[0]["fiber"] == "wool"
        assert out.outer_fibers[0]["percentage"] == 100


class TestMaterialParserEdgeCases:
    def test_english_wool(self):
        out = parse_material(_make_input("Wool 100%"))
        assert out.outer_fibers[0]["fiber"] == "wool"

    def test_english_polyester(self):
        out = parse_material(_make_input("Polyester 100%"))
        assert out.outer_fibers[0]["fiber"] == "polyester"

    def test_percentage_colon_format(self):
        out = parse_material(_make_input("ウール：100%"))
        assert out.outer_fibers[0]["percentage"] == 100
