"""Unit normalisation: convert measurement strings to floats in cm/JPY."""

from __future__ import annotations

import re
from typing import Optional


# cm variants in Japanese text
_CM_PATTERN = re.compile(r"(?:cm|CM|㎝|センチ)", re.IGNORECASE)

# mm variants
_MM_PATTERN = re.compile(r"(?:mm|MM|ミリ)", re.IGNORECASE)


def parse_cm(raw: str) -> Optional[float]:
    """Parse a raw string like '44.5cm' or '44' and return float cm.

    Returns None if no numeric value found.
    """
    raw = raw.strip()
    # Remove unit suffixes
    raw = _CM_PATTERN.sub("", raw)
    raw = _MM_PATTERN.sub("__mm__", raw)

    # Handle mm conversion
    mm_match = re.search(r"(\d+(?:\.\d+)?)\s*__mm__", raw)
    if mm_match:
        return float(mm_match.group(1)) / 10.0

    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    if m:
        return float(m.group(1))
    return None


def parse_jpy(raw: str) -> Optional[int]:
    """Parse a Japanese price string like '15,000円' → 15000."""
    # Remove 円, commas, spaces
    raw = re.sub(r"[円,\s　]", "", raw)
    m = re.search(r"(\d+)", raw)
    if m:
        return int(m.group(1))
    return None


def cm_to_mm(value_cm: float) -> float:
    return value_cm * 10.0


def mm_to_cm(value_mm: float) -> float:
    return value_mm / 10.0
