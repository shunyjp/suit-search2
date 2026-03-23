"""Condition parser – Phase 4 implementation.

Detects item condition from evidence text:
  - grade      : "S" | "A" | "B" | "C" | "D" (ランク表記)
  - has_stain  : True / False / None
  - has_hole   : True / False / None

Blocking conditions (per judgement_rules):
  - has_stain = True (severe)
  - has_hole  = True
"""

from __future__ import annotations

import re
from typing import Optional

from app.connectors.base import ConditionParserOutput, EvidenceBlock, ParserInput
from app.normalizers.text import normalize_japanese_text


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Grade patterns
_GRADE_S = re.compile(r"[Ss]\s*ランク|未使用|新品同様|デッドストック", re.IGNORECASE)
_GRADE_A = re.compile(r"[Aa]\s*ランク|美品|良好|目立った.*なし", re.IGNORECASE)
_GRADE_B = re.compile(r"[Bb]\s*ランク|普通|やや使用感|多少.*あり", re.IGNORECASE)
_GRADE_C = re.compile(r"[Cc]\s*ランク|使用感.*あり|傷.*あり", re.IGNORECASE)
_GRADE_D = re.compile(r"[Dd]\s*ランク|ジャンク|難あり|訳あり", re.IGNORECASE)

# Stain patterns
_STAIN_PRESENT = re.compile(
    r"汚れ\s*(?:が|は|あり|有り|あります|ございます)|シミ\s*あり|ステイン",
    re.IGNORECASE,
)
_STAIN_ABSENT = re.compile(
    r"汚れ\s*(?:なし|無し|ございません|はありません|ありません)|シミ\s*なし"
    r"|目立った汚れ\s*(?:なし|無し|はありません|ありません)",
    re.IGNORECASE,
)
_SEVERE_STAIN = re.compile(
    r"ひどい汚れ|大きな汚れ|酷い汚れ|目立つ汚れ\s*(?:あり|有り)",
    re.IGNORECASE,
)

# Hole patterns
_HOLE_PRESENT = re.compile(
    r"穴\s*(?:あり|有り|あります|開き)|破れ\s*あり|ほつれ\s*あり",
    re.IGNORECASE,
)
_HOLE_ABSENT = re.compile(
    r"穴\s*(?:なし|無し|ありません|はありません)|破れ\s*なし",
    re.IGNORECASE,
)

_PRIORITY_SOURCES = ["description", "specs", "title", "all_text"]


def _ordered(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    order = {s: i for i, s in enumerate(_PRIORITY_SOURCES)}
    return sorted(blocks, key=lambda b: order.get(b.source, 99))


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_condition(parser_input: ParserInput) -> ConditionParserOutput:
    """Parse item condition from evidence blocks."""
    warnings: list[str] = []
    unknown_fields: list[str] = []

    grade: Optional[str] = None
    has_stain: Optional[bool] = None
    has_hole: Optional[bool] = None
    severe_stain = False
    confidence = 0.0

    ordered = _ordered(parser_input.evidence_blocks)

    for block in ordered:
        text = normalize_japanese_text(block.text)
        conf = block.confidence

        # Grade
        if grade is None:
            for label, pat in [("S", _GRADE_S), ("A", _GRADE_A), ("B", _GRADE_B),
                                ("C", _GRADE_C), ("D", _GRADE_D)]:
                if pat.search(text):
                    grade = label
                    confidence = max(confidence, conf * 0.85)
                    break

        # Stain – check absent before present to avoid false positives
        # e.g. "目立った汚れはありません" should match absent, not present
        if has_stain is None:
            if _STAIN_ABSENT.search(text):
                has_stain = False
                confidence = max(confidence, conf * 0.85)
            elif _SEVERE_STAIN.search(text):
                has_stain = True
                severe_stain = True
                warnings.append("ひどい汚れの記述あり")
                confidence = max(confidence, conf * 0.9)
            elif _STAIN_PRESENT.search(text):
                has_stain = True
                warnings.append("汚れの記述あり")
                confidence = max(confidence, conf * 0.9)

        # Hole
        if has_hole is None:
            if _HOLE_PRESENT.search(text):
                has_hole = True
                warnings.append("穴・破れの記述あり")
                confidence = max(confidence, conf * 0.9)
            elif _HOLE_ABSENT.search(text):
                has_hole = False
                confidence = max(confidence, conf * 0.85)

    if grade is None:
        unknown_fields.append("grade")
    if has_stain is None:
        unknown_fields.append("has_stain")
    if has_hole is None:
        unknown_fields.append("has_hole")

    return ConditionParserOutput(
        grade=grade,
        has_stain=has_stain,
        has_hole=has_hole,
        unknown_fields=unknown_fields,
        warnings=warnings,
        confidence=round(confidence, 3),
    )
