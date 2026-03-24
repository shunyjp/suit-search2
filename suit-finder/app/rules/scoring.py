"""Scoring helpers for the decision engine."""

from __future__ import annotations

from app.connectors.base import MergedStructuredAttributes


def _mohair_bonus(attrs: MergedStructuredAttributes) -> float:
    """Compute mohair priority bonus from outer_fibers.

    - mohair >= 60%: +0.15
    - mohair > 0% and < 60%: +0.05 × (pct/60)
    """
    for entry in attrs.material.outer_fibers:
        if str(entry.get("fiber", "")) == "mohair":
            pct = entry.get("percentage")
            if pct is None:
                # Mohair present but unknown %; treat as small bonus
                return 0.05 * (0.0 / 60)
            pct = float(pct)
            if pct >= 60.0:
                return 0.15
            if pct > 0.0:
                return 0.05 * (pct / 60.0)
    return 0.0


def _wool_bonus(attrs: MergedStructuredAttributes) -> float:
    """Compute wool bonus: if wool >= 80% in outer_fibers, +0.05."""
    for entry in attrs.material.outer_fibers:
        if str(entry.get("fiber", "")) == "wool":
            pct = entry.get("percentage")
            if pct is not None and float(pct) >= 80.0:
                return 0.05
    return 0.0


def compute_score(
    attrs: MergedStructuredAttributes,
    blocking: list[str],
    notes: list[str],
) -> float:
    """Heuristic score 0–1.

    Start from 1.0, subtract penalties, add material bonuses.
    Clamped to [0.0, 1.0].
    """
    score = 1.0

    # Each blocking reason removes 0.4 (capped at 0)
    score -= len(blocking) * 0.4

    # Each note removes 0.05
    score -= len(notes) * 0.05

    # Unknown fields penalty
    unknown_count = len(attrs.size.unknown_fields)
    score -= unknown_count * 0.03

    # Material quality bonuses
    score += _mohair_bonus(attrs)
    score += _wool_bonus(attrs)

    return max(0.0, min(1.0, round(score, 3)))
