"""Unit tests for evidence extractor and cleaner."""

from __future__ import annotations

import pytest

from app.connectors.base import PageSignals
from app.evidence.cleaner import clean_blocks, deduplicate, is_noise
from app.evidence.extractor import build_evidence_package, extract_evidence_blocks
from app.connectors.base import EvidenceBlock


def _signals(**kwargs) -> PageSignals:
    defaults = dict(
        url="https://example.com",
        title_text="",
        price_text="",
        status_text="",
        description_text="",
        all_text="",
    )
    defaults.update(kwargs)
    return PageSignals(**defaults)


class TestExtractEvidenceBlocks:
    def test_title_block_created(self):
        s = _signals(title_text="テストスーツ")
        blocks = extract_evidence_blocks(s)
        title_blocks = [b for b in blocks if b.source == "title"]
        assert len(title_blocks) == 1
        assert title_blocks[0].confidence == 1.0

    def test_price_block_created(self):
        s = _signals(price_text="現在 5,000円")
        blocks = extract_evidence_blocks(s)
        price_blocks = [b for b in blocks if b.source == "price"]
        assert len(price_blocks) == 1

    def test_description_split_by_lines(self):
        s = _signals(description_text="行1\n行2\n行3")
        blocks = extract_evidence_blocks(s)
        desc_blocks = [b for b in blocks if b.source == "description"]
        assert len(desc_blocks) == 3

    def test_empty_fields_skipped(self):
        s = _signals()  # all empty
        blocks = extract_evidence_blocks(s)
        assert blocks == []

    def test_all_text_lower_confidence(self):
        s = _signals(all_text="全体テキスト")
        blocks = extract_evidence_blocks(s)
        all_text_blocks = [b for b in blocks if b.source == "all_text"]
        assert all(b.confidence < 0.8 for b in all_text_blocks)

    def test_text_cleaned(self):
        """Full-width digits should be normalised."""
        s = _signals(title_text="サイズ４６　ジャケット")
        blocks = extract_evidence_blocks(s)
        assert blocks[0].text == "サイズ46 ジャケット"


class TestEvidenceCleaner:
    def test_noise_short_text(self):
        b = EvidenceBlock(source="all_text", text="ab", confidence=0.5)
        assert is_noise(b) is True

    def test_noise_pure_number(self):
        b = EvidenceBlock(source="all_text", text="12345", confidence=0.5)
        assert is_noise(b) is True

    def test_not_noise_normal_text(self):
        b = EvidenceBlock(source="description", text="肩幅：44cm", confidence=0.85)
        assert is_noise(b) is False

    def test_deduplicate_keeps_higher_confidence(self):
        b1 = EvidenceBlock(source="description", text="同じ文", confidence=0.6)
        b2 = EvidenceBlock(source="specs", text="同じ文", confidence=0.95)
        result = deduplicate([b1, b2])
        assert len(result) == 1
        # b2 appears second but has higher confidence; deduplicate keeps b2
        assert result[0].confidence == 0.95

    def test_clean_blocks_removes_noise(self):
        blocks = [
            EvidenceBlock(source="all_text", text="x", confidence=0.5),
            EvidenceBlock(source="description", text="肩幅：44cm", confidence=0.85),
        ]
        result = clean_blocks(blocks)
        assert len(result) == 1
        assert result[0].text == "肩幅：44cm"


class TestBuildEvidencePackage:
    def test_builds_package(self):
        s = _signals(title_text="テスト", description_text="肩幅：44cm")
        pkg = build_evidence_package(url="https://example.com", signals=s)
        assert pkg.url == "https://example.com"
        assert len(pkg.evidence_blocks) >= 2

    def test_item_id_override(self):
        s = _signals(title_text="テスト")
        pkg = build_evidence_package(
            url="https://example.com", signals=s, item_id="custom_id_001"
        )
        assert pkg.item_id == "custom_id_001"
