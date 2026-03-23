"""LLM result merger – Phase 4.

Merges LLM supplement outputs into existing parser outputs.
LLM values only fill in fields that are None; they never override
rule-based results.
"""

from __future__ import annotations

from typing import Any, Optional

from app.connectors.base import SizeParserOutput


def merge_llm_size_supplement(
    size_output: SizeParserOutput,
    llm_result: Optional[dict[str, Any]],
) -> SizeParserOutput:
    """Merge LLM size supplement into existing SizeParserOutput.

    Phase 4 stub – returns size_output unchanged.
    """
    return size_output
