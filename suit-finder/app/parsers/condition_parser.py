"""Condition parser – stub (Phase 4).

Detects item condition: grade, stains, holes, etc.
"""

from __future__ import annotations

from app.connectors.base import ConditionParserOutput, ParserInput


def parse_condition(parser_input: ParserInput) -> ConditionParserOutput:
    """Phase 4 stub – always returns empty output."""
    return ConditionParserOutput(
        unknown_fields=["grade", "has_stain", "has_hole"],
        warnings=["condition_parser は未実装 (Phase 4)"],
        confidence=0.0,
    )
