"""LLM result merger.

Merges Gemini output into existing parser outputs.
Rules:
- LLM values only fill fields that are currently None.
- LLM values never override rule-based parser results.
- LLM-filled fields get confidence=LLM_CONF and source="llm_gemini".
"""

from __future__ import annotations

from typing import Any, Optional

from app.connectors.base import (
    MaterialParserOutput,
    MeasurementValue,
    SizeParserOutput,
)
from app.normalizers.measurements import is_plausible

LLM_CONF = 0.4  # confidence assigned to LLM-extracted values


def _make_llm_measurement(
    field: str,
    raw_value: Any,
    warnings: list[str],
) -> Optional[MeasurementValue]:
    """Parse a raw LLM value into a MeasurementValue, or None if invalid."""
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    ok, warn = is_plausible(field, value)
    if not ok:
        warnings.append(warn or f"{field} LLM値 {value} は妥当範囲外")
        return None
    return MeasurementValue(
        value=value,
        unit="cm",
        confidence=LLM_CONF,
        evidence=f"LLM抽出: {value}cm",
        source="llm_gemini",
    )


def merge_llm_size(
    size: SizeParserOutput,
    llm_result: dict[str, Any],
) -> SizeParserOutput:
    """Fill None size fields from LLM result.  Returns updated SizeParserOutput."""
    warnings = list(size.warnings)
    jacket = size.jacket.model_copy()
    pants = size.pants.model_copy()
    filled: list[str] = []

    # Jacket fields
    _JACKET_MAP = {
        "jacket_shoulder_cm": "shoulder_cm",
        "jacket_chest_width_cm": "chest_width_cm",
        "jacket_length_cm": "length_cm",
        "jacket_sleeve_cm": "sleeve_cm",
    }
    for llm_key, attr in _JACKET_MAP.items():
        if getattr(jacket, attr) is None and llm_key in llm_result:
            mv = _make_llm_measurement(llm_key, llm_result[llm_key], warnings)
            if mv is not None:
                setattr(jacket, attr, mv)
                filled.append(llm_key)

    # Pants fields
    _PANTS_MAP = {
        "pants_waist_flat_cm": "waist_flat_cm",
        "pants_waist_circ_cm": "waist_circumference_cm",
        "pants_rise_cm": "rise_cm",
        "pants_inseam_cm": "inseam_cm",
        "pants_hem_width_cm": "hem_width_cm",
        "pants_thigh_cm": "thigh_cm",
        "pants_total_length_cm": "total_length_cm",
    }
    for llm_key, attr in _PANTS_MAP.items():
        if getattr(pants, attr) is None and llm_key in llm_result:
            if llm_key == "pants_waist_flat_cm":
                # Try flat with a temporary warning buffer first.
                tmp: list[str] = []
                mv = _make_llm_measurement(llm_key, llm_result[llm_key], tmp)
                if mv is not None:
                    setattr(pants, attr, mv)
                    filled.append(llm_key)
                    warnings.extend(tmp)
                elif pants.waist_circumference_cm is None:
                    # Flat failed – try as circumference (e.g. 74 cm = girth).
                    mv_circ = _make_llm_measurement("pants_waist_circ_cm", llm_result[llm_key], tmp)
                    if mv_circ is not None:
                        pants.waist_circumference_cm = mv_circ
                        filled.append(llm_key)
                        # Suppress the flat-range warning; value is valid as circumference.
                    else:
                        warnings.extend(tmp)  # Both failed – surface the warnings.
                else:
                    warnings.extend(tmp)
            else:
                mv = _make_llm_measurement(llm_key, llm_result[llm_key], warnings)
                if mv is not None:
                    setattr(pants, attr, mv)
                    filled.append(llm_key)

    if not filled:
        return size

    new_unknowns = [f for f in size.unknown_fields if f not in filled]
    return size.model_copy(update={
        "jacket": jacket,
        "pants": pants,
        "unknown_fields": new_unknowns,
        "warnings": warnings,
    })


def merge_llm_material(
    material: MaterialParserOutput,
    llm_result: dict[str, Any],
) -> MaterialParserOutput:
    """Fill empty material fields from LLM result."""
    updates: dict[str, Any] = {}

    if not material.outer_fibers:
        outer = llm_result.get("outer_fibers")
        if isinstance(outer, list) and outer:
            updates["outer_fibers"] = outer
            unknown = [f for f in material.unknown_fields if f != "outer_fibers"]
            updates["unknown_fields"] = unknown

    if not material.lining_fibers:
        lining = llm_result.get("lining_fibers")
        if isinstance(lining, list) and lining:
            updates["lining_fibers"] = lining

    if not updates:
        return material

    return material.model_copy(update=updates)
