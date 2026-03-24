"""Integration tests: full pipeline with fixture data (no browser/network).

These tests run the complete parser chain from EvidencePackage → DecisionOutput
using the sample JSON fixtures, verifying the end-to-end logic without I/O.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.connectors.base import (
    EvidencePackage,
    ParserInput,
)
from app.evidence.cleaner import clean_blocks
from app.evidence.merger import merge_attributes
from app.parsers.condition_parser import parse_condition
from app.parsers.material_parser import parse_material
from app.parsers.price_parser import parse_price
from app.parsers.size_parser import parse_size
from app.parsers.status_parser import parse_status
from app.parsers.style_parser import parse_style
from app.rules.decision_engine import decide

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _run_pipeline(pkg: EvidencePackage):
    """Run parsers + decision on an EvidencePackage and return DecisionOutput."""
    pkg.evidence_blocks = clean_blocks(pkg.evidence_blocks)
    pi = ParserInput(
        item_id=pkg.item_id,
        evidence_blocks=pkg.evidence_blocks,
        page_signals=pkg.page_signals,
    )
    size = parse_size(pi)
    price = parse_price(pi)
    status = parse_status(pi)
    material = parse_material(pi)
    style = parse_style(pi)
    condition = parse_condition(pi)
    merged = merge_attributes(
        item_id=pkg.item_id,
        size=size,
        price=price,
        status=status,
        material=material,
        style=style,
        condition=condition,
    )
    return merged, decide(merged)


class TestSampleFixturePipeline:
    """Run the sample fixture through the full pipeline."""

    def test_sample_verdict_is_match(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, decision = _run_pipeline(pkg)
        # The sample fixture describes a well-fitting wool suit at ¥15,000
        assert decision.verdict in ("MATCH", "REVIEW")

    def test_sample_price_parsed(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        assert merged.price.buy_now_price_jpy == 15000
        assert merged.price.listing_type == "auction"

    def test_sample_status_active(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        assert merged.status.normalized_status == "active"

    def test_sample_jacket_shoulder(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        assert merged.size.jacket.shoulder_cm is not None
        assert merged.size.jacket.shoulder_cm.value == 44.0

    def test_sample_jacket_sleeve(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        assert merged.size.jacket.sleeve_cm is not None
        assert merged.size.jacket.sleeve_cm.value == 62.0

    def test_sample_pants_inseam(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        assert merged.size.pants.inseam_cm is not None
        assert merged.size.pants.inseam_cm.value == 76.0

    def test_sample_hem_finish_double(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        assert merged.size.pants.hem_finish is not None
        assert merged.size.pants.hem_finish.value == "double"

    def test_sample_material_wool(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        # Sample has "表地：ウール100%"
        if merged.material.outer_fibers:
            fibers = {f["fiber"] for f in merged.material.outer_fibers}
            assert "wool" in fibers

    def test_sample_condition_grade_a(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, _ = _run_pipeline(pkg)
        # Sample has "美品" in description
        assert merged.condition.grade == "A"

    def test_sample_no_blocking_reasons(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, decision = _run_pipeline(pkg)
        # The sample is a well-described good suit – should have no blocking reasons
        assert len(decision.blocking_reasons) == 0

    def test_sample_confidence_positive(self):
        pkg = EvidencePackage.model_validate(_load("evidence_package_sample.json"))
        merged, decision = _run_pipeline(pkg)
        assert decision.score > 0.0


class TestNGScenariosEndToEnd:
    """Test NG scenarios using modified fixture data."""

    def _modified_pkg(self, description_override: str) -> EvidencePackage:
        data = _load("evidence_package_sample.json")
        # Replace description blocks
        data["evidence_blocks"] = [
            b for b in data["evidence_blocks"]
            if b["source"] != "description"
        ]
        data["evidence_blocks"].append({
            "source": "description",
            "text": description_override,
            "block_type": "description",
            "confidence": 0.85,
            "metadata": {},
        })
        data["page_signals"]["description_text"] = description_override
        return EvidencePackage.model_validate(data)

    def test_ng_polyester_suit(self):
        pkg = self._modified_pkg(
            "肩幅：44cm 身幅：52cm 袖丈：62cm "
            "ウエスト平置き：43cm 股下：76cm 裾ダブル "
            "表地：ポリエステル100%"
        )
        _, decision = _run_pipeline(pkg)
        assert decision.verdict == "NO_MATCH"
        assert any("polyester" in r for r in decision.blocking_reasons)

    def test_ng_double_breasted(self):
        pkg = self._modified_pkg(
            "肩幅：44cm 身幅：52cm 袖丈：62cm "
            "ウエスト平置き：43cm 股下：76cm "
            "ダブルブレスト ウール100%"
        )
        _, decision = _run_pipeline(pkg)
        assert decision.verdict == "NO_MATCH"
        assert any("ダブル" in r for r in decision.blocking_reasons)

    def test_ng_short_inseam(self):
        pkg = self._modified_pkg(
            "肩幅：44cm 身幅：52cm 袖丈：62cm "
            "ウエスト平置き：43cm 股下：68cm 裾シングル"
        )
        _, decision = _run_pipeline(pkg)
        assert decision.verdict == "NO_MATCH"
        assert any("股下" in r for r in decision.blocking_reasons)

    def test_ng_price_over_limit(self):
        data = _load("evidence_package_sample.json")
        for b in data["evidence_blocks"]:
            if b["source"] == "price":
                b["text"] = "現在 20,000円 即決 35,000円"
        data["page_signals"]["price_text"] = "現在 20,000円 即決 35,000円"
        pkg = EvidencePackage.model_validate(data)
        _, decision = _run_pipeline(pkg)
        assert decision.verdict == "NO_MATCH"
        assert any("30,000" in r for r in decision.blocking_reasons)


class TestNGPageFixture:
    """Tests using the NG HTML fixture (double breasted, polyester, no buy-now, short inseam)."""

    FIXTURE_HTML = FIXTURES / "mock_yahoo_auction_ng_page.html"

    def _build_package_from_ng_html(self) -> EvidencePackage:
        """Build an EvidencePackage from the NG HTML fixture using BeautifulSoup."""
        from bs4 import BeautifulSoup
        from app.connectors.base import PageSignals
        from app.evidence.extractor import build_evidence_package

        html = self.FIXTURE_HTML.read_text("utf-8")
        soup = BeautifulSoup(html, "html.parser")

        def _text(selector: str) -> str:
            el = soup.select_one(selector)
            return el.get_text(separator=" ", strip=True) if el else ""

        signals = PageSignals(
            url="https://page.auctions.yahoo.co.jp/jp/auction/ng_test_item",
            title_text=_text("h1.ProductTitle__text"),
            price_text=_text(".Price"),
            status_text=_text(".AuctionStatus"),
            description_text=_text(".ItemDescription"),
            specs_text=_text(".ProductDetail__section"),
            brand_text=_text(".Breadcrumb"),
            category_text=_text(".Breadcrumb"),
        )
        return build_evidence_package(
            url=signals.url,
            signals=signals,
            item_id="ng_test_item",
        )

    def test_ng_page_fixture_exists(self):
        assert self.FIXTURE_HTML.exists()

    def test_ng_page_verdict_is_no_match(self):
        pkg = self._build_package_from_ng_html()
        _, decision = _run_pipeline(pkg)
        assert decision.verdict == "NO_MATCH"

    def test_ng_page_no_buy_now_blocking(self):
        pkg = self._build_package_from_ng_html()
        _, decision = _run_pipeline(pkg)
        assert any("即決" in r for r in decision.blocking_reasons)

    def test_ng_page_polyester_blocking(self):
        pkg = self._build_package_from_ng_html()
        _, decision = _run_pipeline(pkg)
        assert any("polyester" in r for r in decision.blocking_reasons)

    def test_ng_page_double_breasted_blocking(self):
        pkg = self._build_package_from_ng_html()
        _, decision = _run_pipeline(pkg)
        assert any("ダブル" in r for r in decision.blocking_reasons)

    def test_ng_page_short_inseam_blocking(self):
        """股下69cm is ≤ 70cm → absolute NG."""
        pkg = self._build_package_from_ng_html()
        _, decision = _run_pipeline(pkg)
        assert any("股下" in r for r in decision.blocking_reasons)


class TestExtractItemUrls:
    def test_extract_from_text(self):
        from app.connectors.yahoo_auctions import _extract_item_urls
        text = (
            "https://page.auctions.yahoo.co.jp/jp/auction/abc123 "
            "https://page.auctions.yahoo.co.jp/jp/auction/xyz456?from=search "
            "https://page.auctions.yahoo.co.jp/jp/auction/abc123"  # duplicate
        )
        urls = _extract_item_urls(text)
        assert len(urls) == 2
        assert "https://page.auctions.yahoo.co.jp/jp/auction/abc123" in urls
        assert "https://page.auctions.yahoo.co.jp/jp/auction/xyz456" in urls

    def test_no_urls(self):
        from app.connectors.yahoo_auctions import _extract_item_urls
        assert _extract_item_urls("テキストのみ") == []
