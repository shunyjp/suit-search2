"""Merge evidence from multiple parsers or LLM into unified attributes.

This module is responsible for combining parser outputs (rule-based) with
optional LLM supplements. LLM values only fill in fields that are None
after rule-based parsing.
"""

from __future__ import annotations

from app.connectors.base import (
    MergedStructuredAttributes,
    SizeParserOutput,
    PriceParserOutput,
    StatusParserOutput,
    MaterialParserOutput,
    StyleParserOutput,
    ConditionParserOutput,
)


def merge_attributes(
    item_id: str,
    size: SizeParserOutput,
    price: PriceParserOutput,
    status: StatusParserOutput,
    material: MaterialParserOutput | None = None,
    style: StyleParserOutput | None = None,
    condition: ConditionParserOutput | None = None,
) -> MergedStructuredAttributes:
    """Combine all parser outputs into MergedStructuredAttributes."""
    return MergedStructuredAttributes(
        item_id=item_id,
        size=size,
        price=price,
        status=status,
        material=material or MaterialParserOutput(),
        style=style or StyleParserOutput(),
        condition=condition or ConditionParserOutput(),
    )
