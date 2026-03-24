"""Tests for LLM supplementation layer (merger, supplement orchestrator).

GeminiClient is mocked so tests run without google-generativeai installed
and without a real API key.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors.base import (
    JacketMeasurements,
    MaterialParserOutput,
    MeasurementValue,
    PageSignals,
    PantsMeasurements,
    ParserInput,
    SizeParserOutput,
    EvidenceBlock,
)
from app.llm.merger import LLM_CONF, merge_llm_material, merge_llm_size
from app.llm.prompts import build_material_prompt, build_size_prompt
from app.llm.supplement import _needs_llm, maybe_supplement


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _size_all_unknown() -> SizeParserOutput:
    return SizeParserOutput(
        jacket=JacketMeasurements(),
        pants=PantsMeasurements(),
        unknown_fields=[
            "jacket_shoulder_cm", "jacket_chest_width_cm",
            "jacket_sleeve_cm", "jacket_length_cm",
            "pants_inseam_cm", "pants_waist_flat_cm",
        ],
    )


def _size_mostly_known() -> SizeParserOutput:
    mv = MeasurementValue(value=44.0, unit="cm", confidence=0.9, evidence="肩幅44cm", source="specs")
    jacket = JacketMeasurements(shoulder_cm=mv, chest_width_cm=mv, sleeve_cm=mv)
    pants = PantsMeasurements(inseam_cm=mv)
    return SizeParserOutput(
        jacket=jacket,
        pants=pants,
        unknown_fields=["jacket_length_cm", "pants_waist_flat_cm"],
    )


def _material_empty() -> MaterialParserOutput:
    return MaterialParserOutput(unknown_fields=["outer_fibers"])


def _material_known() -> MaterialParserOutput:
    return MaterialParserOutput(
        outer_fibers=[{"fiber": "wool", "percentage": 100}],
        unknown_fields=[],
    )


def _parser_input(description: str = "ウール100%\n肩幅44cm") -> ParserInput:
    signals = PageSignals(
        url="https://example.com",
        description_text=description,
        specs_text="",
    )
    return ParserInput(
        item_id="test-id",
        evidence_blocks=[EvidenceBlock(source="description", text=description)],
        page_signals=signals,
    )


# ---------------------------------------------------------------------------
# merger: merge_llm_size
# ---------------------------------------------------------------------------

class TestMergeLlmSize:
    def test_fills_none_fields(self):
        size = _size_all_unknown()
        result = merge_llm_size(size, {
            "jacket_shoulder_cm": 44.0,
            "jacket_sleeve_cm": 62.0,
            "pants_inseam_cm": 75.0,
        })
        assert result.jacket.shoulder_cm is not None
        assert result.jacket.shoulder_cm.value == 44.0
        assert result.jacket.shoulder_cm.confidence == LLM_CONF
        assert result.jacket.shoulder_cm.source == "llm_gemini"
        assert result.jacket.sleeve_cm.value == 62.0
        assert result.pants.inseam_cm.value == 75.0

    def test_does_not_override_existing_value(self):
        mv = MeasurementValue(value=44.0, unit="cm", confidence=0.9, evidence="x", source="specs")
        jacket = JacketMeasurements(shoulder_cm=mv)
        size = SizeParserOutput(jacket=jacket, pants=PantsMeasurements(), unknown_fields=[])
        result = merge_llm_size(size, {"jacket_shoulder_cm": 99.0})
        assert result.jacket.shoulder_cm.value == 44.0  # original preserved

    def test_removes_filled_fields_from_unknown(self):
        size = _size_all_unknown()
        result = merge_llm_size(size, {"jacket_shoulder_cm": 44.0})
        assert "jacket_shoulder_cm" not in result.unknown_fields

    def test_null_values_ignored(self):
        size = _size_all_unknown()
        result = merge_llm_size(size, {"jacket_shoulder_cm": None})
        assert result.jacket.shoulder_cm is None

    def test_implausible_value_ignored(self):
        # 200cm shoulder is implausible
        size = _size_all_unknown()
        result = merge_llm_size(size, {"jacket_shoulder_cm": 200.0})
        assert result.jacket.shoulder_cm is None

    def test_invalid_type_ignored(self):
        size = _size_all_unknown()
        result = merge_llm_size(size, {"jacket_shoulder_cm": "not-a-number"})
        assert result.jacket.shoulder_cm is None

    def test_no_change_returns_original(self):
        size = _size_all_unknown()
        result = merge_llm_size(size, {})
        assert result is size  # same object if nothing changed

    def test_pants_waist_flat_filled(self):
        size = _size_all_unknown()
        result = merge_llm_size(size, {"pants_waist_flat_cm": 43.0})
        assert result.pants.waist_flat_cm is not None
        assert result.pants.waist_flat_cm.value == 43.0


# ---------------------------------------------------------------------------
# merger: merge_llm_material
# ---------------------------------------------------------------------------

class TestMergeLlmMaterial:
    def test_fills_empty_outer_fibers(self):
        mat = _material_empty()
        result = merge_llm_material(mat, {
            "outer_fibers": [{"fiber": "wool", "percentage": 100}],
            "lining_fibers": [{"fiber": "polyester", "percentage": 100}],
        })
        assert result.outer_fibers == [{"fiber": "wool", "percentage": 100}]
        assert result.lining_fibers == [{"fiber": "polyester", "percentage": 100}]
        assert "outer_fibers" not in result.unknown_fields

    def test_does_not_override_existing_outer(self):
        mat = _material_known()
        result = merge_llm_material(mat, {
            "outer_fibers": [{"fiber": "polyester", "percentage": 100}],
        })
        assert result.outer_fibers[0]["fiber"] == "wool"  # original preserved

    def test_empty_list_ignored(self):
        mat = _material_empty()
        result = merge_llm_material(mat, {"outer_fibers": []})
        assert result.outer_fibers == []  # empty list not applied

    def test_no_change_returns_original(self):
        mat = _material_known()
        result = merge_llm_material(mat, {})
        assert result is mat


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_size_prompt_contains_unknown_fields(self):
        prompt = build_size_prompt("肩幅44cm...", ["jacket_shoulder_cm", "pants_inseam_cm"])
        assert "jacket_shoulder_cm" in prompt
        assert "pants_inseam_cm" in prompt
        assert "44cm" in prompt

    def test_size_prompt_skips_unknown_field_keys(self):
        # Fields not in _SIZE_FIELD_LABELS are silently skipped
        prompt = build_size_prompt("text", ["unknown_mystery_field"])
        assert "unknown_mystery_field" not in prompt

    def test_material_prompt_contains_description(self):
        prompt = build_material_prompt("ウール90%モヘア10%")
        assert "ウール90%" in prompt
        assert "outer_fibers" in prompt
        assert "lining_fibers" in prompt


# ---------------------------------------------------------------------------
# supplement: _needs_llm
# ---------------------------------------------------------------------------

class TestNeedsLlm:
    def test_many_unknowns_triggers(self):
        assert _needs_llm(_size_all_unknown(), _material_known()) is True

    def test_empty_material_triggers(self):
        assert _needs_llm(_size_mostly_known(), _material_empty()) is True

    def test_no_trigger_when_all_known(self):
        assert _needs_llm(_size_mostly_known(), _material_known()) is False


# ---------------------------------------------------------------------------
# supplement: maybe_supplement
# ---------------------------------------------------------------------------

class TestMaybeSupplement:
    @pytest.mark.asyncio
    async def test_skips_when_not_needed(self):
        size = _size_mostly_known()
        material = _material_known()
        s2, m2 = await maybe_supplement(_parser_input(), size, material, client=None)
        assert s2 is size
        assert m2 is material

    @pytest.mark.asyncio
    async def test_skips_when_no_client_and_no_env(self):
        with patch("app.llm.supplement.client_from_env", return_value=None):
            size = _size_all_unknown()
            material = _material_empty()
            s2, m2 = await maybe_supplement(_parser_input(), size, material)
            assert s2 is size  # unchanged
            assert m2 is material

    @pytest.mark.asyncio
    async def test_skips_when_text_is_empty(self):
        client = MagicMock()
        client.generate_json = AsyncMock()
        signals = PageSignals(url="https://x.com", description_text="", specs_text="")
        pi = ParserInput(item_id="x", evidence_blocks=[], page_signals=signals)
        size = _size_all_unknown()
        material = _material_empty()
        s2, m2 = await maybe_supplement(pi, size, material, client=client)
        client.generate_json.assert_not_called()
        assert s2 is size

    @pytest.mark.asyncio
    async def test_fills_size_via_llm(self):
        client = MagicMock()
        client.generate_json = AsyncMock(return_value={
            "jacket_shoulder_cm": 44.0,
            "jacket_sleeve_cm": 62.0,
            "pants_inseam_cm": 75.0,
        })
        size = _size_all_unknown()
        material = _material_known()  # no material call needed
        s2, m2 = await maybe_supplement(_parser_input(), size, material, client=client)
        assert s2.jacket.shoulder_cm is not None
        assert s2.jacket.shoulder_cm.value == 44.0
        assert s2.pants.inseam_cm.value == 75.0
        assert m2 is material

    @pytest.mark.asyncio
    async def test_fills_material_via_llm(self):
        size_result = {"jacket_shoulder_cm": 44.0}
        mat_result = {
            "outer_fibers": [{"fiber": "wool", "percentage": 100}],
            "lining_fibers": [],
        }
        client = MagicMock()
        client.generate_json = AsyncMock(side_effect=[size_result, mat_result])
        size = _size_all_unknown()
        material = _material_empty()
        s2, m2 = await maybe_supplement(_parser_input(), size, material, client=client)
        assert m2.outer_fibers == [{"fiber": "wool", "percentage": 100}]

    @pytest.mark.asyncio
    async def test_gemini_failure_is_non_blocking(self):
        client = MagicMock()
        client.generate_json = AsyncMock(return_value=None)  # simulate failure
        size = _size_all_unknown()
        material = _material_empty()
        # Should not raise; returns originals
        s2, m2 = await maybe_supplement(_parser_input(), size, material, client=client)
        assert s2 is size
        assert m2 is material
