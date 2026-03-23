"""Style parser – stub (Phase 4).

Detects jacket style: button type/count/color, single/double breasted.
"""

from __future__ import annotations

from app.connectors.base import ParserInput, StyleParserOutput


def parse_style(parser_input: ParserInput) -> StyleParserOutput:
    """Phase 4 stub – always returns empty output."""
    return StyleParserOutput(
        unknown_fields=["button_type", "button_count", "button_color"],
        warnings=["style_parser は未実装 (Phase 4)"],
        confidence=0.0,
    )
