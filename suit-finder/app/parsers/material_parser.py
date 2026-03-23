"""Material parser – stub (Phase 4).

Phase 3 only: returns empty output so imports don't break.
Phase 4 will parse fiber content from description/specs text.
"""

from __future__ import annotations

from app.connectors.base import MaterialParserOutput, ParserInput


def parse_material(parser_input: ParserInput) -> MaterialParserOutput:
    """Phase 4 stub – always returns empty output."""
    return MaterialParserOutput(
        unknown_fields=["outer_fibers", "lining_fibers"],
        warnings=["material_parser は未実装 (Phase 4)"],
        confidence=0.0,
    )
