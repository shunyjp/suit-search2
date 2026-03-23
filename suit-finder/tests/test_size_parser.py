"""Unit tests for size_parser."""

from __future__ import annotations

import pytest

from app.connectors.base import EvidenceBlock, PageSignals, ParserInput
from app.parsers.size_parser import parse_size


def _block(text: str, source: str = "description") -> EvidenceBlock:
    return EvidenceBlock(source=source, text=text, confidence=0.85)


def _make_input(*texts: str, source: str = "description") -> ParserInput:
    blocks = [_block(t, source) for t in texts]
    signals = PageSignals(url="https://example.com")
    return ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)


class TestJacketMeasurements:
    def test_shoulder(self):
        out = parse_size(_make_input("肩幅：44cm"))
        assert out.jacket.shoulder_cm is not None
        assert out.jacket.shoulder_cm.value == 44.0
        assert out.jacket.shoulder_cm.source == "description"

    def test_chest_width(self):
        out = parse_size(_make_input("身幅：52cm"))
        assert out.jacket.chest_width_cm is not None
        assert out.jacket.chest_width_cm.value == 52.0

    def test_length(self):
        out = parse_size(_make_input("着丈：73cm"))
        assert out.jacket.length_cm is not None
        assert out.jacket.length_cm.value == 73.0

    def test_sleeve(self):
        out = parse_size(_make_input("袖丈：62cm"))
        assert out.jacket.sleeve_cm is not None
        assert out.jacket.sleeve_cm.value == 62.0

    def test_all_jacket_in_one_block(self):
        out = parse_size(_make_input("肩幅：44cm 身幅：52cm 着丈：73cm 袖丈：62cm"))
        assert out.jacket.shoulder_cm.value == 44.0
        assert out.jacket.chest_width_cm.value == 52.0
        assert out.jacket.length_cm.value == 73.0
        assert out.jacket.sleeve_cm.value == 62.0

    def test_no_unit_suffix(self):
        """Numbers without cm suffix should still be parsed."""
        out = parse_size(_make_input("肩幅 44 身幅 52"))
        assert out.jacket.shoulder_cm is not None
        assert out.jacket.shoulder_cm.value == 44.0

    def test_full_width_colon_separator(self):
        out = parse_size(_make_input("肩幅：44cm"))
        assert out.jacket.shoulder_cm.value == 44.0

    def test_decimal_value(self):
        out = parse_size(_make_input("肩幅：44.5cm"))
        assert out.jacket.shoulder_cm.value == 44.5

    def test_unknown_when_absent(self):
        out = parse_size(_make_input("肩幅：44cm"))
        assert "jacket_chest_width_cm" in out.unknown_fields
        assert "jacket_sleeve_cm" in out.unknown_fields


class TestPantsMeasurements:
    def test_waist_flat_explicit(self):
        out = parse_size(_make_input("ウエスト平置き：43cm"))
        assert out.pants.waist_flat_cm is not None
        assert out.pants.waist_flat_cm.value == 43.0
        assert out.pants.waist_circumference_cm is None

    def test_waist_circumference_explicit(self):
        out = parse_size(_make_input("ウエスト周り：87cm"))
        assert out.pants.waist_circumference_cm is not None
        assert out.pants.waist_circumference_cm.value == 87.0
        assert out.pants.waist_flat_cm is None

    def test_waist_plain_small_treated_as_flat(self):
        out = parse_size(_make_input("ウエスト：43cm"))
        assert out.pants.waist_flat_cm is not None
        assert out.pants.waist_flat_cm.value == 43.0
        assert any("平置き" in w for w in out.warnings)

    def test_waist_plain_large_treated_as_circumference(self):
        out = parse_size(_make_input("ウエスト：86cm"))
        assert out.pants.waist_circumference_cm is not None
        assert out.pants.waist_circumference_cm.value == 86.0

    def test_inseam(self):
        out = parse_size(_make_input("股下：76cm"))
        assert out.pants.inseam_cm is not None
        assert out.pants.inseam_cm.value == 76.0

    def test_rise(self):
        out = parse_size(_make_input("股上：26cm"))
        assert out.pants.rise_cm is not None
        assert out.pants.rise_cm.value == 26.0

    def test_hem_width(self):
        out = parse_size(_make_input("裾幅：19cm"))
        assert out.pants.hem_width_cm is not None
        assert out.pants.hem_width_cm.value == 19.0

    def test_thigh(self):
        out = parse_size(_make_input("ワタリ：30cm"))
        assert out.pants.thigh_cm is not None
        assert out.pants.thigh_cm.value == 30.0

    def test_hem_finish_double(self):
        out = parse_size(_make_input("裾ダブル"))
        assert out.pants.hem_finish is not None
        assert out.pants.hem_finish.value == "double"

    def test_hem_finish_single(self):
        out = parse_size(_make_input("裾シングル"))
        assert out.pants.hem_finish is not None
        assert out.pants.hem_finish.value == "single"

    def test_hem_finish_unknown(self):
        out = parse_size(_make_input("股下：76cm"))
        assert out.pants.hem_finish is None
        assert "pants_hem_finish" in out.unknown_fields


class TestSizeParserConfidence:
    def test_all_required_found(self):
        out = parse_size(_make_input(
            "肩幅：44cm 身幅：52cm 袖丈：62cm 股下：76cm"
        ))
        assert out.confidence == 1.0

    def test_none_found(self):
        out = parse_size(_make_input("このスーツは美品です"))
        assert out.confidence == 0.0

    def test_partial(self):
        out = parse_size(_make_input("肩幅：44cm 身幅：52cm"))
        assert 0.0 < out.confidence < 1.0


class TestSizeParserSourcePriority:
    def test_specs_takes_priority_over_description(self):
        blocks = [
            EvidenceBlock(source="description", text="肩幅：44cm", confidence=0.85),
            EvidenceBlock(source="specs", text="肩幅：45cm", confidence=0.95),
        ]
        signals = PageSignals(url="https://example.com")
        inp = ParserInput(item_id="test", evidence_blocks=blocks, page_signals=signals)
        out = parse_size(inp)
        # specs has higher priority, so 45 should win
        assert out.jacket.shoulder_cm.value == 45.0
        assert out.jacket.shoulder_cm.source == "specs"


class TestSizeParserPlausibilityFilter:
    def test_implausible_shoulder_discarded(self):
        """Shoulder 200cm is out of range and should be rejected."""
        out = parse_size(_make_input("肩幅：200cm"))
        assert out.jacket.shoulder_cm is None
        assert len(out.warnings) > 0

    def test_implausible_inseam_discarded(self):
        out = parse_size(_make_input("股下：200cm"))
        assert out.pants.inseam_cm is None


class TestSizeParserFullSample:
    def test_full_description(self):
        text = (
            "肩幅：44cm\n身幅：52cm\n着丈：73cm\n袖丈：62cm\n"
            "ウエスト平置き：43cm\n股上：26cm\n股下：76cm\n"
            "裾幅：19cm\nワタリ：30cm\n裾ダブル"
        )
        out = parse_size(_make_input(text))
        assert out.jacket.shoulder_cm.value == 44.0
        assert out.jacket.chest_width_cm.value == 52.0
        assert out.jacket.sleeve_cm.value == 62.0
        assert out.pants.waist_flat_cm.value == 43.0
        assert out.pants.inseam_cm.value == 76.0
        assert out.pants.hem_finish.value == "double"
        assert out.confidence == 1.0
