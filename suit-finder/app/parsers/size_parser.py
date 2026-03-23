"""Size parser – Phase 3 (priority fields).

Extracts garment measurements from evidence text using regex.
Does NOT use CSS selectors. Reads evidence_blocks only.

Priority fields:
  Jacket : shoulder_cm, chest_width_cm, sleeve_cm
  Pants  : waist_flat_cm | waist_circumference_cm, inseam_cm, hem_finish

All other fields are parsed if found but are non-blocking.
"""

from __future__ import annotations

import re
from typing import Optional

from app.connectors.base import (
    CategoricalValue,
    EvidenceBlock,
    JacketMeasurements,
    MeasurementValue,
    PantsMeasurements,
    ParserInput,
    SizeParserOutput,
)
from app.normalizers.measurements import is_plausible
from app.normalizers.text import normalize_japanese_text
from app.normalizers.units import parse_cm


# ---------------------------------------------------------------------------
# Measurement regex builders
# ---------------------------------------------------------------------------
# Pattern structure:
#   <label_variants> <separator?> <number> <unit?>
#
# After NFKC normalisation full-width digits → half-width.
# Colons unified to ':'.

_NUM = r"(\d{1,3}(?:\.\d{1,2})?)"      # capture group: the numeric value
_UNIT = r"(?:cm|CM|㎝|センチ)?"         # optional unit
_SEP = r"[\s：:・/＝=]*"               # label–value separator


def _pat(*labels: str) -> re.Pattern[str]:
    """Build pattern: (label1|label2|...) SEP NUM UNIT"""
    label_group = "|".join(re.escape(l) for l in labels)
    return re.compile(
        rf"(?:{label_group}){_SEP}{_NUM}\s*{_UNIT}",
        re.IGNORECASE,
    )


# ---------------------------------------------------------------------------
# Jacket patterns
# ---------------------------------------------------------------------------

PAT_SHOULDER = _pat("肩幅", "肩 幅", "ショルダー")
PAT_CHEST = _pat("身幅", "バスト", "胸囲", "胸幅")
PAT_LENGTH = _pat("着丈", "ジャケット丈", "身丈")
PAT_SLEEVE = _pat("袖丈", "袖 丈", "スリーブ")

# ---------------------------------------------------------------------------
# Pants patterns
# ---------------------------------------------------------------------------

PAT_WAIST_FLAT = _pat("ウエスト平置き", "ウェスト平置き", "腰幅", "ウエスト（平置き）",
                       "ウェスト（平置き）", "W平置き", "ウエスト 平置き",
                       "ウェスト 平置き")
PAT_WAIST_CIRC = _pat("ウエスト周り", "ウェスト周り", "ウエストぐるり", "ウェストぐるり",
                       "ウエスト（ぐるり）", "W周囲")
# Plain ウエスト – ambiguous (flat vs. circumference)
PAT_WAIST_PLAIN = _pat("ウエスト", "ウェスト", "W")
PAT_RISE = _pat("股上", "ライズ")
PAT_INSEAM = _pat("股下", "インシーム")
PAT_HEM_WIDTH = _pat("裾幅", "裾 幅", "裾巾")
PAT_THIGH = _pat("ワタリ", "渡り", "もも幅", "腿幅")
PAT_TOTAL_LEN = _pat("総丈", "全丈", "パンツ丈")

# Hem finish – categorical
PAT_HEM_DOUBLE = re.compile(r"裾\s*(?:ダブル|W|double)", re.IGNORECASE)
PAT_HEM_SINGLE = re.compile(r"裾\s*(?:シングル|S|single)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRIORITY_SOURCES = ["specs", "description", "title", "brand", "category", "all_text"]


def _ordered_blocks(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    order = {s: i for i, s in enumerate(_PRIORITY_SOURCES)}
    return sorted(blocks, key=lambda b: order.get(b.source, 99))


def _search_blocks(
    pattern: re.Pattern[str],
    blocks: list[EvidenceBlock],
) -> Optional[tuple[float, str, str, float]]:
    """Search blocks in priority order.

    Returns (value_cm, matched_text, source, block_confidence) or None.
    """
    for block in blocks:
        text = normalize_japanese_text(block.text)
        m = pattern.search(text)
        if m:
            raw_num = m.group(1)
            value = parse_cm(raw_num)
            if value is not None:
                return value, m.group(0), block.source, block.confidence
    return None


def _make_measurement(
    field: str,
    result: tuple[float, str, str, float] | None,
    warnings: list[str],
) -> Optional[MeasurementValue]:
    if result is None:
        return None
    value, evidence_text, source, block_conf = result
    ok, warn = is_plausible(field, value)
    if not ok:
        warnings.append(warn or f"{field} 値 {value} は妥当範囲外")
        return None  # Discard implausible value
    confidence = round(block_conf * 0.9, 3)
    return MeasurementValue(
        value=value,
        unit="cm",
        confidence=confidence,
        evidence=evidence_text,
        source=source,
    )


def _make_categorical(
    result: tuple[str, str, str, float] | None,
) -> Optional[CategoricalValue]:
    if result is None:
        return None
    value, evidence_text, source, block_conf = result
    return CategoricalValue(
        value=value,
        confidence=round(block_conf * 0.9, 3),
        evidence=evidence_text,
        source=source,
    )


def _detect_hem_finish(
    blocks: list[EvidenceBlock],
) -> Optional[tuple[str, str, str, float]]:
    for block in blocks:
        text = normalize_japanese_text(block.text)
        if PAT_HEM_DOUBLE.search(text):
            m = PAT_HEM_DOUBLE.search(text)
            return "double", m.group(0), block.source, block.confidence  # type: ignore[union-attr]
        if PAT_HEM_SINGLE.search(text):
            m = PAT_HEM_SINGLE.search(text)
            return "single", m.group(0), block.source, block.confidence  # type: ignore[union-attr]
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_size(parser_input: ParserInput) -> SizeParserOutput:
    """Parse size measurements from evidence blocks."""
    warnings: list[str] = []
    unknown_fields: list[str] = []

    ordered = _ordered_blocks(parser_input.evidence_blocks)

    # --- Jacket ---
    jacket = JacketMeasurements()

    r = _search_blocks(PAT_SHOULDER, ordered)
    jacket.shoulder_cm = _make_measurement("jacket_shoulder_cm", r, warnings)
    if jacket.shoulder_cm is None:
        unknown_fields.append("jacket_shoulder_cm")

    r = _search_blocks(PAT_CHEST, ordered)
    jacket.chest_width_cm = _make_measurement("jacket_chest_width_cm", r, warnings)
    if jacket.chest_width_cm is None:
        unknown_fields.append("jacket_chest_width_cm")

    r = _search_blocks(PAT_LENGTH, ordered)
    jacket.length_cm = _make_measurement("jacket_length_cm", r, warnings)
    if jacket.length_cm is None:
        unknown_fields.append("jacket_length_cm")

    r = _search_blocks(PAT_SLEEVE, ordered)
    jacket.sleeve_cm = _make_measurement("jacket_sleeve_cm", r, warnings)
    if jacket.sleeve_cm is None:
        unknown_fields.append("jacket_sleeve_cm")

    # --- Pants ---
    pants = PantsMeasurements()

    # Prefer explicit flat/circumference labels
    r_flat = _search_blocks(PAT_WAIST_FLAT, ordered)
    r_circ = _search_blocks(PAT_WAIST_CIRC, ordered)

    if r_flat:
        pants.waist_flat_cm = _make_measurement("pants_waist_flat_cm", r_flat, warnings)
    elif r_circ:
        pants.waist_circumference_cm = _make_measurement("pants_waist_circ_cm", r_circ, warnings)
    else:
        # Ambiguous plain ウエスト
        r_plain = _search_blocks(PAT_WAIST_PLAIN, ordered)
        if r_plain:
            value = r_plain[0]
            if value <= 60:
                # Likely flat measurement for men's trousers
                pants.waist_flat_cm = _make_measurement("pants_waist_flat_cm", r_plain, warnings)
                warnings.append(
                    f"ウエスト {value}cm: 平置きと仮定 (明示なし)"
                )
            else:
                pants.waist_circumference_cm = _make_measurement(
                    "pants_waist_circ_cm", r_plain, warnings
                )
                warnings.append(
                    f"ウエスト {value}cm: 周囲と仮定 (明示なし)"
                )
        else:
            unknown_fields.append("pants_waist_flat_cm")

    r = _search_blocks(PAT_RISE, ordered)
    pants.rise_cm = _make_measurement("pants_rise_cm", r, warnings)
    if pants.rise_cm is None:
        unknown_fields.append("pants_rise_cm")

    r = _search_blocks(PAT_INSEAM, ordered)
    pants.inseam_cm = _make_measurement("pants_inseam_cm", r, warnings)
    if pants.inseam_cm is None:
        unknown_fields.append("pants_inseam_cm")

    r = _search_blocks(PAT_HEM_WIDTH, ordered)
    pants.hem_width_cm = _make_measurement("pants_hem_width_cm", r, warnings)
    if pants.hem_width_cm is None:
        unknown_fields.append("pants_hem_width_cm")

    r = _search_blocks(PAT_THIGH, ordered)
    pants.thigh_cm = _make_measurement("pants_thigh_cm", r, warnings)
    if pants.thigh_cm is None:
        unknown_fields.append("pants_thigh_cm")

    r = _search_blocks(PAT_TOTAL_LEN, ordered)
    pants.total_length_cm = _make_measurement("pants_total_length_cm", r, warnings)
    if pants.total_length_cm is None:
        unknown_fields.append("pants_total_length_cm")

    # Hem finish (categorical)
    hem_result = _detect_hem_finish(ordered)
    pants.hem_finish = _make_categorical(hem_result)
    if pants.hem_finish is None:
        unknown_fields.append("pants_hem_finish")

    # --- Overall confidence ---
    required = [
        jacket.shoulder_cm,
        jacket.chest_width_cm,
        jacket.sleeve_cm,
        pants.inseam_cm,
    ]
    found = sum(1 for v in required if v is not None)
    confidence = round(found / len(required), 3)

    return SizeParserOutput(
        jacket=jacket,
        pants=pants,
        unknown_fields=unknown_fields,
        warnings=warnings,
        confidence=confidence,
    )
