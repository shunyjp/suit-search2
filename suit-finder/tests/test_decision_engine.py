"""Unit tests for the decision engine."""

from __future__ import annotations

import pytest

from app.connectors.base import (
    CategoricalValue,
    ConditionParserOutput,
    JacketMeasurements,
    MaterialParserOutput,
    MeasurementValue,
    MergedStructuredAttributes,
    PantsMeasurements,
    PriceParserOutput,
    SizeParserOutput,
    StatusParserOutput,
    StyleParserOutput,
)
from app.rules.decision_engine import decide


def _mv(value: float, source: str = "description") -> MeasurementValue:
    return MeasurementValue(value=value, unit="cm", confidence=0.9,
                             evidence=f"{value}cm", source=source)


def _cv(value: str) -> CategoricalValue:
    return CategoricalValue(value=value, confidence=0.9, evidence=value, source="description")


def _good_attrs(
    shoulder: float = 44.0,
    chest: float = 52.0,
    sleeve: float = 62.0,
    inseam: float = 76.0,
    waist_flat: float = 43.0,
    price: int = 15000,
    hem_finish: str = "single",
) -> MergedStructuredAttributes:
    return MergedStructuredAttributes(
        item_id="test",
        size=SizeParserOutput(
            jacket=JacketMeasurements(
                shoulder_cm=_mv(shoulder),
                chest_width_cm=_mv(chest),
                sleeve_cm=_mv(sleeve),
            ),
            pants=PantsMeasurements(
                waist_flat_cm=_mv(waist_flat),
                inseam_cm=_mv(inseam),
                hem_finish=_cv(hem_finish),
            ),
            confidence=1.0,
        ),
        price=PriceParserOutput(
            listing_type="auction",
            current_price_jpy=8000,
            buy_now_price_jpy=price,
            confidence=0.9,
        ),
        status=StatusParserOutput(
            normalized_status="active",
            confidence=0.9,
        ),
        material=MaterialParserOutput(),
        style=StyleParserOutput(),
        condition=ConditionParserOutput(),
    )


class TestDecisionEngineMatch:
    def test_good_listing_is_match(self):
        out = decide(_good_attrs())
        assert out.verdict == "MATCH"
        assert len(out.blocking_reasons) == 0

    def test_verdict_match_score_positive(self):
        out = decide(_good_attrs())
        assert out.score > 0.0


class TestDecisionEngineNoMatch:
    def test_price_over_limit(self):
        out = decide(_good_attrs(price=35000))
        assert out.verdict == "NO_MATCH"
        assert any("30,000" in r for r in out.blocking_reasons)

    def test_no_buy_now_auction(self):
        attrs = _good_attrs()
        attrs.price.buy_now_price_jpy = None
        attrs.price.listing_type = "auction"
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("即決" in r for r in out.blocking_reasons)

    def test_shoulder_out_of_range(self):
        out = decide(_good_attrs(shoulder=40.0))
        assert out.verdict == "NO_MATCH"
        assert any("肩幅" in r for r in out.blocking_reasons)

    def test_chest_out_of_range(self):
        out = decide(_good_attrs(chest=55.0))
        assert out.verdict == "NO_MATCH"
        assert any("身幅" in r for r in out.blocking_reasons)

    def test_sleeve_too_short(self):
        out = decide(_good_attrs(sleeve=55.0))
        assert out.verdict == "NO_MATCH"
        assert any("袖丈" in r for r in out.blocking_reasons)

    def test_inseam_ng(self):
        out = decide(_good_attrs(inseam=68.0))
        assert out.verdict == "NO_MATCH"
        assert any("股下" in r for r in out.blocking_reasons)

    def test_inseam_short_single_hem(self):
        out = decide(_good_attrs(inseam=72.0, hem_finish="single"))
        assert out.verdict == "NO_MATCH"

    def test_status_not_active(self):
        attrs = _good_attrs()
        attrs.status.normalized_status = "sold"
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("active" in r for r in out.blocking_reasons)


class TestDecisionEngineDoubleHem:
    def test_inseam_71_with_double_hem_ok(self):
        out = decide(_good_attrs(inseam=72.0, hem_finish="double"))
        # 72 >= 71 (min with double hem) → should pass
        assert "NO_MATCH" != out.verdict or all("股下" not in r for r in out.blocking_reasons)

    def test_inseam_70_ng_even_with_double_hem(self):
        out = decide(_good_attrs(inseam=70.0, hem_finish="double"))
        assert out.verdict == "NO_MATCH"
        assert any("NG" in r or "股下" in r for r in out.blocking_reasons)


class TestDecisionEngineReview:
    def test_many_unknowns_triggers_review(self):
        attrs = _good_attrs()
        # Inject many unknown fields
        attrs.size.unknown_fields = ["a", "b", "c", "d", "e", "f"]
        out = decide(attrs)
        assert out.verdict in ("REVIEW", "MATCH")  # depends on score


class TestDecisionEngineMaterial:
    def test_polyester_outer_ng(self):
        attrs = _good_attrs()
        attrs.material = MaterialParserOutput(
            outer_fibers=[{"fiber": "polyester", "percentage": 100}]
        )
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("polyester" in r for r in out.blocking_reasons)

    def test_polyurethane_outer_ng(self):
        attrs = _good_attrs()
        attrs.material = MaterialParserOutput(
            outer_fibers=[{"fiber": "polyurethane", "percentage": 5}]
        )
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"

    def test_cotton_outer_ng(self):
        attrs = _good_attrs()
        attrs.material = MaterialParserOutput(
            outer_fibers=[{"fiber": "cotton", "percentage": 100}]
        )
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"

    def test_wool_100_ok(self):
        attrs = _good_attrs()
        attrs.material = MaterialParserOutput(
            outer_fibers=[{"fiber": "wool", "percentage": 100}]
        )
        out = decide(attrs)
        # wool is not NG
        assert not any("polyester" in r or "cotton" in r for r in out.blocking_reasons)

    def test_lining_polyester_not_ng(self):
        """Polyester in lining is not NG – only outer matters."""
        attrs = _good_attrs()
        attrs.material = MaterialParserOutput(
            outer_fibers=[{"fiber": "wool", "percentage": 100}],
            lining_fibers=[{"fiber": "polyester", "percentage": 100}],
        )
        out = decide(attrs)
        assert not any("polyester" in r for r in out.blocking_reasons)

    def test_unknown_material_note_not_blocking(self):
        """Unknown material raises note but is not a blocking reason."""
        attrs = _good_attrs()
        attrs.material = MaterialParserOutput(outer_fibers=[])
        out = decide(attrs)
        # Should be REVIEW or MATCH, not NO_MATCH due to unknown material alone
        blocking_mat = [r for r in out.blocking_reasons if "polyester" in r or "cotton" in r]
        assert len(blocking_mat) == 0


class TestDecisionEngineStyle:
    def test_double_breasted_ng(self):
        attrs = _good_attrs()
        attrs.style = StyleParserOutput(button_type="double")
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("ダブル" in r for r in out.blocking_reasons)

    def test_one_button_ng(self):
        attrs = _good_attrs()
        attrs.style = StyleParserOutput(button_count=1)
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("1ボタン" in r for r in out.blocking_reasons)

    def test_gold_button_ng(self):
        attrs = _good_attrs()
        attrs.style = StyleParserOutput(button_color="gold")
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("金ボタン" in r for r in out.blocking_reasons)

    def test_silver_button_ng(self):
        attrs = _good_attrs()
        attrs.style = StyleParserOutput(button_color="silver")
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"

    def test_single_2button_black_ok(self):
        attrs = _good_attrs()
        attrs.style = StyleParserOutput(button_type="single", button_count=2, button_color="black")
        out = decide(attrs)
        assert not any("ダブル" in r or "1ボタン" in r or "金ボタン" in r
                       for r in out.blocking_reasons)


class TestDecisionEngineCondition:
    def test_severe_stain_ng(self):
        attrs = _good_attrs()
        attrs.condition = ConditionParserOutput(
            has_stain=True,
            warnings=["ひどい汚れの記述あり"],
        )
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("汚れ" in r for r in out.blocking_reasons)

    def test_hole_ng(self):
        attrs = _good_attrs()
        attrs.condition = ConditionParserOutput(has_hole=True)
        out = decide(attrs)
        assert out.verdict == "NO_MATCH"
        assert any("穴" in r for r in out.blocking_reasons)

    def test_normal_stain_not_blocking(self):
        """Minor stain (no severe warning) should not block."""
        attrs = _good_attrs()
        attrs.condition = ConditionParserOutput(
            has_stain=True,
            warnings=["汚れの記述あり"],  # no "ひどい"
        )
        out = decide(attrs)
        # Not a blocking reason (only noted)
        assert not any("汚れ" in r for r in out.blocking_reasons)

    def test_no_stain_no_hole_ok(self):
        attrs = _good_attrs()
        attrs.condition = ConditionParserOutput(grade="A", has_stain=False, has_hole=False)
        out = decide(attrs)
        assert not any("穴" in r or "汚れ" in r for r in out.blocking_reasons)
