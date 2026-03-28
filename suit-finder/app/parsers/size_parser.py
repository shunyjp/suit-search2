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
# label–value separator: optional punctuation/約, optional modifier (直線で)/etc
# Note: normalize_japanese_text() converts full-width （）→ half-width ()
_SEP = r"[\s：:・/＝=約]*(?:\([^)]{1,6}\))?[\s：:・/＝=約]*"


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
PAT_CHEST_WIDTH = _pat("身幅", "胸幅")        # flat width (平置き幅)
PAT_CHEST_CIRC  = _pat("バスト", "胸囲")     # circumference – must be halved to get 身幅
PAT_LENGTH = _pat("着丈", "ジャケット丈", "身丈")
PAT_SLEEVE = _pat("袖丈", "袖 丈", "スリーブ")

# ---------------------------------------------------------------------------
# Pants patterns
# ---------------------------------------------------------------------------

PAT_WAIST_FLAT = _pat("ウエスト平置き", "ウェスト平置き", "腰幅", "ウエスト（平置き）",
                       "ウェスト（平置き）", "W平置き", "ウエスト 平置き",
                       "ウェスト 平置き")
PAT_WAIST_CIRC = _pat("ウエスト周り", "ウェスト周り", "ウエストぐるり", "ウェストぐるり",
                       "ウエスト（ぐるり）", "W周囲",
                       "ウエスト実寸", "ウェスト実寸")
# Plain ウエスト – ambiguous (flat vs. circumference)
PAT_WAIST_PLAIN = _pat("ウエスト", "ウェスト", "W")
PAT_RISE = _pat("股上", "ライズ")
PAT_INSEAM = _pat("股下", "インシーム")
PAT_HEM_WIDTH = _pat("裾幅", "裾 幅", "裾巾")
PAT_THIGH = _pat("ワタリ", "渡り", "渡り幅", "もも幅", "腿幅")
PAT_TOTAL_LEN = _pat("総丈", "全丈", "パンツ丈")

# Hem finish – categorical
PAT_HEM_DOUBLE = re.compile(r"裾\s*(?:ダブル|W|double)", re.IGNORECASE)
PAT_HEM_SINGLE = re.compile(r"裾\s*(?:シングル|S|single)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Multi-size table handling
# ---------------------------------------------------------------------------

# Canonical size aliases: lowercase key → canonical label
_SIZE_ALIASES: dict[str, str] = {
    "5xl": "5XL", "5xo": "5XL", "5l": "5XL",
    "4xl": "4XL", "4xo": "4XL", "4l": "4XL",
    "3xl": "3XL", "3xo": "3XL", "3l": "3XL",
    "xxl": "2XL", "2xl": "2XL", "2xo": "2XL", "2l": "2XL", "ll": "2XL",
    "xl":  "XL",
    "l":   "L",
    "m":   "M",
    "s":   "S",
    "xs":  "XS",
}

# Check in longest-first order to avoid "L" matching inside "XL" etc.
_DETECT_ORDER = ["5XL", "4XL", "3XL", "2XL", "XXL", "LL", "XL", "XS", "S", "M", "L"]


def _canon_size(label: str) -> Optional[str]:
    """Normalize a raw size token to its canonical label."""
    return _SIZE_ALIASES.get(label.lower().replace(" ", "").replace("\u3000", ""))


def _detect_target_size(text: str) -> Optional[str]:
    """Return the primary size label found in *text* (title or similar).

    Tries each canonical size in longest-first order so that '3XL' is found
    before 'L' and 'XL' is found before 'L'.
    """
    upper = text.upper()
    for size in _DETECT_ORDER:
        # Must not be part of a longer alphanumeric run
        pat = re.compile(
            rf"(?<![A-Z0-9]){re.escape(size)}(?![A-Z0-9])",
            re.IGNORECASE,
        )
        if pat.search(upper):
            return size
    return None


# Matches rows like: 【 Mサイズ 】   or  【3XLサイズ】  or  [XL]
# Group 1 = raw size token, Group 2 = rest of line until next bracket / newline
_SIZE_TABLE_ROW_RE = re.compile(
    r"[【\[][\s\u3000]*([\dA-Za-z]+)[\s\u3000]*(?:サイズ|SIZE)?[\s\u3000]*[】\]]([^\n【\[]+)",
)


def _extract_size_table(text: str) -> dict[str, str]:
    """Return {canonical_size: row_text} for every row found in a size table."""
    rows: dict[str, str] = {}
    for m in _SIZE_TABLE_ROW_RE.finditer(text):
        raw = m.group(1).strip()
        canon = _canon_size(raw)
        if canon:
            rows[canon] = m.group(2).strip()
    return rows


def _filter_blocks_to_size(
    blocks: list[EvidenceBlock],
    target_size: str,
) -> Optional[list[EvidenceBlock]]:
    """Return a version of *blocks* where multi-size table blocks are reduced
    to only the row matching *target_size*.

    Returns **None** when no size table is found (caller uses originals).
    Each non-table block is kept as-is.
    """
    filtered: list[EvidenceBlock] = []
    table_found = False

    for block in blocks:
        text = normalize_japanese_text(block.text)
        rows = _extract_size_table(text)
        if len(rows) >= 2:          # ≥2 rows → it's a size table
            table_found = True
            if target_size in rows:
                filtered.append(
                    EvidenceBlock(
                        source=block.source,
                        text=rows[target_size],
                        confidence=block.confidence,
                        metadata={"size_row_selected": target_size},
                    )
                )
            # Rows for other sizes are dropped intentionally
        else:
            filtered.append(block)  # not a table – keep verbatim

    return filtered if table_found else None


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
    """Parse size measurements from evidence blocks.

    When the description contains a multi-size table (several size rows like
    【 Mサイズ 】…  【3XLサイズ】…), the function identifies which size the
    listing is sold as (from the title first, then the description) and uses
    only that row for measurement extraction.  This prevents the first row
    (e.g. M) from being used when the item is actually 3XL.
    """
    warnings: list[str] = []
    unknown_fields: list[str] = []

    # ── Step 1: Detect which size this listing is for ─────────────────────
    target_size: Optional[str] = None

    # Title is the most reliable source for the sold size
    for block in parser_input.evidence_blocks:
        if block.source == "title":
            target_size = _detect_target_size(normalize_japanese_text(block.text))
            break

    # Fallback: scan description / all_text for an explicit size mention
    if target_size is None:
        for block in parser_input.evidence_blocks:
            if block.source in ("description", "all_text"):
                target_size = _detect_target_size(normalize_japanese_text(block.text))
                if target_size:
                    break

    # ── Step 2: Narrow multi-size table to the target row ─────────────────
    evidence_blocks = parser_input.evidence_blocks
    if target_size:
        filtered = _filter_blocks_to_size(evidence_blocks, target_size)
        if filtered is not None:
            evidence_blocks = filtered
            warnings.append(
                f"サイズ表を検出: '{target_size}' 行のみを使用して判定しました"
            )

    ordered = _ordered_blocks(evidence_blocks)

    # --- Jacket ---
    jacket = JacketMeasurements()

    r = _search_blocks(PAT_SHOULDER, ordered)
    jacket.shoulder_cm = _make_measurement("jacket_shoulder_cm", r, warnings)
    if jacket.shoulder_cm is None:
        unknown_fields.append("jacket_shoulder_cm")

    r = _search_blocks(PAT_CHEST_WIDTH, ordered)
    if r is None:
        # Try circumference keyword: divide by 2 to get flat chest width
        r_circ = _search_blocks(PAT_CHEST_CIRC, ordered)
        if r_circ is not None:
            val, ev_text, source, conf = r_circ
            r = (round(val / 2, 1), f"{ev_text} (胸囲→身幅 ÷2)", source, conf)
            warnings.append(f"胸囲 {val}cm → 身幅 {val/2:.1f}cm に換算して判定")
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
