"""Measurement-level normalisation helpers.

Provides plausibility checks and range validators for garment dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MeasurementBounds:
    min_cm: float
    max_cm: float
    description: str


# Plausible bounds for adult male garment measurements
BOUNDS: dict[str, MeasurementBounds] = {
    "jacket_shoulder_cm":     MeasurementBounds(36.0, 55.0, "ジャケット肩幅"),
    "jacket_chest_width_cm":  MeasurementBounds(44.0, 70.0, "ジャケット身幅"),
    "jacket_length_cm":       MeasurementBounds(60.0, 90.0, "ジャケット着丈"),
    "jacket_sleeve_cm":       MeasurementBounds(50.0, 75.0, "ジャケット袖丈"),
    "pants_waist_flat_cm":    MeasurementBounds(30.0, 60.0, "パンツウエスト平置き"),
    "pants_waist_circ_cm":    MeasurementBounds(60.0, 120.0, "パンツウエストぐるり"),
    "pants_rise_cm":          MeasurementBounds(20.0, 40.0, "パンツ股上"),
    "pants_inseam_cm":        MeasurementBounds(55.0, 95.0, "パンツ股下"),
    "pants_hem_width_cm":     MeasurementBounds(14.0, 30.0, "パンツ裾幅"),
    "pants_thigh_cm":         MeasurementBounds(22.0, 45.0, "パンツワタリ"),
    "pants_total_length_cm":  MeasurementBounds(85.0, 130.0, "パンツ総丈"),
}


def is_plausible(field: str, value_cm: float) -> tuple[bool, Optional[str]]:
    """Return (ok, warning_message).

    ok=False means the value is clearly out of range.
    ok=True with warning_message means it is in range but worth flagging.
    """
    bounds = BOUNDS.get(field)
    if bounds is None:
        return True, None
    if value_cm < bounds.min_cm or value_cm > bounds.max_cm:
        msg = (
            f"{bounds.description} {value_cm}cm は妥当範囲外 "
            f"({bounds.min_cm}–{bounds.max_cm}cm)"
        )
        return False, msg
    return True, None
