"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.connectors.base import (
    EvidenceBlock,
    EvidencePackage,
    PageSignals,
    ParserInput,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def evidence_package_sample() -> EvidencePackage:
    data = load_fixture("evidence_package_sample.json")
    return EvidencePackage.model_validate(data)


@pytest.fixture
def sample_parser_input(evidence_package_sample: EvidencePackage) -> ParserInput:
    pkg = evidence_package_sample
    return ParserInput(
        item_id=pkg.item_id,
        evidence_blocks=pkg.evidence_blocks,
        page_signals=pkg.page_signals,
    )


@pytest.fixture
def minimal_page_signals() -> PageSignals:
    return PageSignals(
        url="https://page.auctions.yahoo.co.jp/jp/auction/test001",
        title_text="テスト スーツ サイズ46",
        price_text="現在 5,000円\n即決 12,000円",
        status_text="出品中",
        description_text=(
            "肩幅：44cm\n身幅：52cm\n着丈：73cm\n袖丈：62cm\n"
            "ウエスト平置き：43cm\n股上：26cm\n股下：76cm\n"
            "裾幅：19cm\nワタリ：30cm\n裾ダブル"
        ),
        all_text="",
    )
