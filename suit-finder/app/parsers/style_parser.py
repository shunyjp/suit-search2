"""Style parser – Phase 4 implementation.

Detects jacket style features:
  - button_type  : "single" | "double"
  - button_count : 1 | 2 | 3 | 4 | ...
  - button_color : "gold" | "silver" | "black" | "navy" | ...

NG conditions (per judgement_rules):
  - double breasted
  - 1-button
  - gold / silver buttons
"""

from __future__ import annotations

import re
from typing import Optional

from app.connectors.base import CategoricalValue, EvidenceBlock, ParserInput, StyleParserOutput
from app.normalizers.text import normalize_japanese_text


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Single / Double breasted
# NOTE: negative lookbehind (?<!裾) prevents matching "裾ダブル" (double hem finish)
_DOUBLE = re.compile(
    r"(?<!裾)ダブル(?:ブレスト|スーツ|ジャケット)?|double\s*breasted|[Ww]ブレスト",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"シングル(?:ブレスト|スーツ|ジャケット)?|single\s*breasted|[Ss]ブレスト",
    re.IGNORECASE,
)

# Button count: "2ボタン", "2B", "三つボタン", "2つボタン"
_KANJI_NUM: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "ひとつ": 1, "ふたつ": 2, "みっつ": 3,
}

_BTN_COUNT_NUM = re.compile(r"(\d)\s*(?:ボタン|B\b|つボタン)")
_BTN_COUNT_KANJI = re.compile(r"([一二三四五ひとつふたつみっつ]+)\s*(?:ボタン|つボタン)")

# Button color
_GOLD_BTN = re.compile(r"金ボタン|ゴールド(?:ボタン)?|gold\s*button", re.IGNORECASE)
_SILVER_BTN = re.compile(r"銀ボタン|シルバー(?:ボタン)?|silver\s*button", re.IGNORECASE)
_BLACK_BTN = re.compile(r"黒ボタン|ブラック(?:ボタン)?|black\s*button", re.IGNORECASE)

_PRIORITY_SOURCES = ["specs", "title", "description", "all_text"]


def _ordered(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    order = {s: i for i, s in enumerate(_PRIORITY_SOURCES)}
    return sorted(blocks, key=lambda b: order.get(b.source, 99))


def _detect_button_count(text: str) -> Optional[int]:
    m = _BTN_COUNT_NUM.search(text)
    if m:
        return int(m.group(1))
    mk = _BTN_COUNT_KANJI.search(text)
    if mk:
        raw = mk.group(1)
        for kanji, val in _KANJI_NUM.items():
            if kanji in raw:
                return val
    return None


def _make_cat(value: str, evidence: str, source: str, conf: float) -> CategoricalValue:
    return CategoricalValue(
        value=value,
        confidence=round(conf * 0.9, 3),
        evidence=evidence,
        source=source,
    )


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_style(parser_input: ParserInput) -> StyleParserOutput:
    """Parse jacket style features from evidence blocks."""
    warnings: list[str] = []
    unknown_fields: list[str] = []

    button_type: Optional[CategoricalValue] = None
    button_count: Optional[int] = None
    button_count_source: Optional[str] = None
    button_count_conf: float = 0.0
    button_color: Optional[CategoricalValue] = None

    ordered = _ordered(parser_input.evidence_blocks)

    for block in ordered:
        text = normalize_japanese_text(block.text)
        conf = block.confidence

        # Button type
        if button_type is None:
            if _DOUBLE.search(text):
                m = _DOUBLE.search(text)
                button_type = _make_cat("double", m.group(0), block.source, conf)
            elif _SINGLE.search(text):
                m = _SINGLE.search(text)
                button_type = _make_cat("single", m.group(0), block.source, conf)

        # Button count
        if button_count is None:
            cnt = _detect_button_count(text)
            if cnt is not None:
                button_count = cnt
                button_count_source = block.source
                button_count_conf = conf

        # Button color
        if button_color is None:
            if _GOLD_BTN.search(text):
                m = _GOLD_BTN.search(text)
                button_color = _make_cat("gold", m.group(0), block.source, conf)
            elif _SILVER_BTN.search(text):
                m = _SILVER_BTN.search(text)
                button_color = _make_cat("silver", m.group(0), block.source, conf)
            elif _BLACK_BTN.search(text):
                m = _BLACK_BTN.search(text)
                button_color = _make_cat("black", m.group(0), block.source, conf)

    if button_type is None:
        unknown_fields.append("button_type")
    if button_count is None:
        unknown_fields.append("button_count")
    if button_color is None:
        unknown_fields.append("button_color")

    # Convert button_count to a CategoricalValue for consistent output
    btn_count_value: Optional[CategoricalValue] = None
    if button_count is not None:
        btn_count_value = CategoricalValue(
            value=str(button_count),
            confidence=round(button_count_conf * 0.9, 3),
            evidence=f"{button_count}ボタン",
            source=button_count_source or "unknown",
        )

    return StyleParserOutput(
        button_type=button_type.value if button_type else None,
        button_count=button_count,
        button_color=button_color.value if button_color else None,
        unknown_fields=unknown_fields,
        warnings=warnings,
        confidence=round(
            max(
                (button_type.confidence if button_type else 0.0),
                (btn_count_value.confidence if btn_count_value else 0.0),
            ),
            3,
        ),
    )
