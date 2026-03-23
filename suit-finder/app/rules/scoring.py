"""Scoring helpers for the decision engine."""

from __future__ import annotations

from app.connectors.base import MergedStructuredAttributes


def compute_score(
    attrs: MergedStructuredAttributes,
    blocking: list[str],
    notes: list[str],
) -> float:
    """Simple heuristic score 0–1.

    Start from 1.0, subtract penalties for blocking reasons and unknowns.
    Full scoring model is Phase 4.
    """
    score = 1.0

    # Each blocking reason removes 0.4 (capped at 0)
    score -= len(blocking) * 0.4

    # Each note removes 0.05
    score -= len(notes) * 0.05

    # Unknown fields penalty
    unknown_count = len(attrs.size.unknown_fields)
    score -= unknown_count * 0.03

    return max(0.0, min(1.0, round(score, 3)))
