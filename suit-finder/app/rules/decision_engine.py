"""Decision engine – Phase 3 minimum skeleton.

Applies user-defined rules to MergedStructuredAttributes and returns
a DecisionOutput (MATCH / REVIEW / NO_MATCH).

Full implementation (material, style, condition rules) is Phase 4.
"""

from __future__ import annotations

from app.connectors.base import DecisionOutput, MergedStructuredAttributes
from app.rules import scoring, reasons as rsn


# ---------------------------------------------------------------------------
# User-defined thresholds (move to judgement_rules.yaml in Phase 4)
# ---------------------------------------------------------------------------

MAX_PRICE_JPY = 30_000

JACKET_SHOULDER_MIN = 43.0
JACKET_SHOULDER_MAX = 45.0
JACKET_CHEST_MIN = 51.0
JACKET_CHEST_MAX = 53.0
JACKET_SLEEVE_MIN = 60.0
JACKET_SLEEVE_MAX = 64.0

PANTS_WAIST_FLAT_MIN = 42.0
PANTS_WAIST_FLAT_MAX = 45.0
PANTS_WAIST_CIRC_MIN = 84.0
PANTS_WAIST_CIRC_MAX = 90.0
PANTS_INSEAM_MIN = 74.0              # without double hem
PANTS_INSEAM_MIN_DOUBLE = 71.0      # with double hem
PANTS_INSEAM_NG = 70.0
PANTS_HEM_WIDTH_MIN = 18.0
PANTS_THIGH_MIN = 29.0


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------

def _check_price(attrs: MergedStructuredAttributes) -> tuple[list[str], list[str]]:
    """Returns (blocking_reasons, reasons)."""
    blocking: list[str] = []
    notes: list[str] = []
    p = attrs.price

    if p.listing_type == "auction" and p.buy_now_price_jpy is None:
        blocking.append(rsn.NO_BUY_NOW)

    effective_price = p.buy_now_price_jpy or p.current_price_jpy
    if effective_price is not None and effective_price > MAX_PRICE_JPY:
        blocking.append(rsn.price_over(effective_price, MAX_PRICE_JPY))
    elif effective_price is None:
        blocking.append(rsn.NO_PRICE)

    return blocking, notes


def _check_status(attrs: MergedStructuredAttributes) -> list[str]:
    blocking: list[str] = []
    s = attrs.status
    if s.normalized_status != "active":
        blocking.append(rsn.not_active(s.normalized_status or "unknown"))
    return blocking


def _check_jacket_size(attrs: MergedStructuredAttributes) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    notes: list[str] = []
    j = attrs.size.jacket

    if j.shoulder_cm is not None:
        v = j.shoulder_cm.value
        if not (JACKET_SHOULDER_MIN <= v <= JACKET_SHOULDER_MAX):
            blocking.append(rsn.out_of_range("肩幅", v, JACKET_SHOULDER_MIN, JACKET_SHOULDER_MAX))
    else:
        notes.append(rsn.UNKNOWN_SHOULDER)

    if j.chest_width_cm is not None:
        v = j.chest_width_cm.value
        if not (JACKET_CHEST_MIN <= v <= JACKET_CHEST_MAX):
            blocking.append(rsn.out_of_range("身幅", v, JACKET_CHEST_MIN, JACKET_CHEST_MAX))
    else:
        notes.append(rsn.UNKNOWN_CHEST)

    if j.sleeve_cm is not None:
        v = j.sleeve_cm.value
        if v < JACKET_SLEEVE_MIN:
            blocking.append(rsn.out_of_range("袖丈", v, JACKET_SLEEVE_MIN, JACKET_SLEEVE_MAX))
        elif v > JACKET_SLEEVE_MAX:
            notes.append(rsn.out_of_range("袖丈", v, JACKET_SLEEVE_MIN, JACKET_SLEEVE_MAX))
    else:
        notes.append(rsn.UNKNOWN_SLEEVE)

    return blocking, notes


def _check_pants_size(attrs: MergedStructuredAttributes) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    notes: list[str] = []
    pts = attrs.size.pants

    # Waist
    if pts.waist_flat_cm is not None:
        v = pts.waist_flat_cm.value
        if not (PANTS_WAIST_FLAT_MIN <= v <= PANTS_WAIST_FLAT_MAX):
            notes.append(rsn.out_of_range("ウエスト平置き", v, PANTS_WAIST_FLAT_MIN, PANTS_WAIST_FLAT_MAX))
    elif pts.waist_circumference_cm is not None:
        v = pts.waist_circumference_cm.value
        if not (PANTS_WAIST_CIRC_MIN <= v <= PANTS_WAIST_CIRC_MAX):
            notes.append(rsn.out_of_range("ウエスト周り", v, PANTS_WAIST_CIRC_MIN, PANTS_WAIST_CIRC_MAX))
    else:
        notes.append(rsn.UNKNOWN_WAIST)

    # Inseam
    if pts.inseam_cm is not None:
        v = pts.inseam_cm.value
        hem = pts.hem_finish.value if pts.hem_finish else None
        min_inseam = PANTS_INSEAM_MIN_DOUBLE if hem == "double" else PANTS_INSEAM_MIN
        if v <= PANTS_INSEAM_NG:
            blocking.append(rsn.inseam_ng(v))
        elif v < min_inseam:
            blocking.append(rsn.inseam_short(v, min_inseam, hem == "double"))
    else:
        notes.append(rsn.UNKNOWN_INSEAM)

    # Hem width
    if pts.hem_width_cm is not None:
        v = pts.hem_width_cm.value
        if v < PANTS_HEM_WIDTH_MIN:
            blocking.append(rsn.out_of_range("裾幅", v, PANTS_HEM_WIDTH_MIN, 99))

    # Thigh
    if pts.thigh_cm is not None:
        v = pts.thigh_cm.value
        if v < PANTS_THIGH_MIN:
            blocking.append(rsn.out_of_range("ワタリ", v, PANTS_THIGH_MIN, 99))

    return blocking, notes


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def decide(attrs: MergedStructuredAttributes) -> DecisionOutput:
    """Apply rules and return a DecisionOutput."""
    all_blocking: list[str] = []
    all_notes: list[str] = []

    b, n = _check_price(attrs)
    all_blocking.extend(b)
    all_notes.extend(n)

    b = _check_status(attrs)
    all_blocking.extend(b)

    b, n = _check_jacket_size(attrs)
    all_blocking.extend(b)
    all_notes.extend(n)

    b, n = _check_pants_size(attrs)
    all_blocking.extend(b)
    all_notes.extend(n)

    # material / style / condition checks – Phase 4
    # all_blocking.extend(_check_material(attrs))
    # all_blocking.extend(_check_style(attrs))
    # all_blocking.extend(_check_condition(attrs))

    # Determine unknown count – if many unknowns → REVIEW
    unknown_count = (
        len(attrs.size.unknown_fields)
        + len(attrs.material.unknown_fields)
        + len(attrs.style.unknown_fields)
        + len(attrs.condition.unknown_fields)
    )
    many_unknowns = unknown_count >= 6

    score = scoring.compute_score(attrs, all_blocking, all_notes)

    if all_blocking:
        verdict = "NO_MATCH"
    elif many_unknowns or score < 0.5:
        verdict = "REVIEW"
    else:
        verdict = "MATCH"

    return DecisionOutput(
        item_id=attrs.item_id,
        verdict=verdict,
        score=score,
        reasons=all_notes,
        blocking_reasons=all_blocking,
        needs_llm_review=len(attrs.size.unknown_fields) > 3,
        needs_human_review=verdict == "REVIEW",
        confidence=round(score, 3),
    )
