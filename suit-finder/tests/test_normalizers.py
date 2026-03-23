"""Unit tests for normalizer utilities."""

from __future__ import annotations

import pytest

from app.normalizers.text import clean_text, normalize_japanese_text, to_half_width
from app.normalizers.units import parse_cm, parse_jpy
from app.normalizers.materials import normalize_material
from app.normalizers.measurements import is_plausible


class TestTextNormalizer:
    def test_full_width_digits(self):
        assert to_half_width("１２３") == "123"

    def test_full_width_alphabet(self):
        assert to_half_width("ＣＭ") == "CM"

    def test_normalize_whitespace(self):
        result = normalize_japanese_text("　hello　　world　")
        assert result == "hello world"

    def test_clean_html_tags(self):
        result = clean_text("<b>肩幅</b>：44cm")
        assert "肩幅" in result
        assert "<b>" not in result

    def test_full_width_colon_normalized(self):
        result = clean_text("肩幅：44cm")
        assert "：" not in result
        assert ":" in result


class TestUnitsNormalizer:
    def test_parse_cm_with_unit(self):
        assert parse_cm("44cm") == 44.0
        assert parse_cm("44.5cm") == 44.5
        assert parse_cm("44CM") == 44.0
        assert parse_cm("44㎝") == 44.0

    def test_parse_cm_without_unit(self):
        assert parse_cm("44") == 44.0

    def test_parse_cm_with_spaces(self):
        assert parse_cm("44 cm") == 44.0

    def test_parse_cm_none_on_no_number(self):
        assert parse_cm("なし") is None

    def test_parse_jpy_comma(self):
        assert parse_jpy("15,000円") == 15000

    def test_parse_jpy_no_comma(self):
        assert parse_jpy("8500円") == 8500

    def test_parse_jpy_with_spaces(self):
        assert parse_jpy("  1,234,567 円  ") == 1234567

    def test_parse_jpy_none_on_no_number(self):
        assert parse_jpy("価格なし") is None


class TestMaterialNormalizer:
    def test_japanese_wool(self):
        assert normalize_material("ウール") == "wool"

    def test_japanese_polyester(self):
        assert normalize_material("ポリエステル") == "polyester"

    def test_english_mohair(self):
        assert normalize_material("mohair") == "mohair"

    def test_unknown_returns_lowercased(self):
        assert normalize_material("未知素材") == "未知素材"


class TestMeasurementBounds:
    def test_plausible_shoulder(self):
        ok, warn = is_plausible("jacket_shoulder_cm", 44.0)
        assert ok is True
        assert warn is None

    def test_implausible_shoulder_too_large(self):
        ok, warn = is_plausible("jacket_shoulder_cm", 100.0)
        assert ok is False
        assert warn is not None

    def test_implausible_inseam_too_small(self):
        ok, warn = is_plausible("pants_inseam_cm", 20.0)
        assert ok is False

    def test_unknown_field_always_plausible(self):
        ok, warn = is_plausible("nonexistent_field", 999.0)
        assert ok is True
