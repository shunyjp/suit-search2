"""Status parser – Phase 2.

Determines normalized_status: "active" | "sold" | "ended" | "unknown"
"""

from __future__ import annotations

import re

from app.connectors.base import ParserInput, StatusParserOutput
from app.normalizers.text import normalize_japanese_text


# ---------------------------------------------------------------------------
# Status keyword patterns
# ---------------------------------------------------------------------------

_SOLD_PATTERNS = [
    re.compile(r"落札済み?", re.IGNORECASE),
    re.compile(r"sold\s*out", re.IGNORECASE),
    re.compile(r"売り?切れ", re.IGNORECASE),
    re.compile(r"購入済み?", re.IGNORECASE),
]

_ENDED_PATTERNS = [
    # 「終了します」(will end) は active なので除外。「終了しました」「終了済み」「終了」単独はNG
    re.compile(r"終了(?!します)", re.IGNORECASE),
    re.compile(r"オークション終了", re.IGNORECASE),
    re.compile(r"期限切れ", re.IGNORECASE),
    re.compile(r"出品終了", re.IGNORECASE),
]

_ACTIVE_PATTERNS = [
    re.compile(r"出品中", re.IGNORECASE),
    re.compile(r"販売中", re.IGNORECASE),
    re.compile(r"入札受付中", re.IGNORECASE),
    re.compile(r"出品中・送料込み", re.IGNORECASE),
    # remaining time patterns: "残り XX時間" "残り X日"
    re.compile(r"残り\s*\d+\s*(?:日|時間|分)", re.IGNORECASE),
]


def _detect(patterns: list[re.Pattern[str]], text: str) -> tuple[bool, str]:
    """Return (matched, matched_text)."""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return True, m.group(0)
    return False, ""


def parse_status(parser_input: ParserInput) -> StatusParserOutput:
    """Parse listing status from evidence blocks.

    Priority: 'status' source > 'title' > 'description' > 'all_text'
    """
    output = StatusParserOutput()

    # Prefer status block
    status_blocks = [
        b for b in parser_input.evidence_blocks if b.source == "status"
    ]
    other_blocks = [
        b for b in parser_input.evidence_blocks
        if b.source in ("title", "description", "all_text")
    ]

    all_status_texts = [
        normalize_japanese_text(b.text) for b in status_blocks
    ]
    combined_status = "\n".join(all_status_texts)

    all_other_texts = [normalize_japanese_text(b.text) for b in other_blocks]
    combined_other = "\n".join(all_other_texts)

    # Determine from status blocks first
    for text, source_label in [
        (combined_status, "status_block"),
        (combined_other, "content_block"),
    ]:
        if not text.strip():
            continue

        # sold takes priority over ended/active
        matched, evidence = _detect(_SOLD_PATTERNS, text)
        if matched:
            output.normalized_status = "sold"
            output.raw_status = evidence
            output.evidence = evidence
            output.confidence = 0.95 if source_label == "status_block" else 0.8
            return output

        matched, evidence = _detect(_ENDED_PATTERNS, text)
        if matched:
            output.normalized_status = "ended"
            output.raw_status = evidence
            output.evidence = evidence
            output.confidence = 0.9 if source_label == "status_block" else 0.75
            return output

        matched, evidence = _detect(_ACTIVE_PATTERNS, text)
        if matched:
            output.normalized_status = "active"
            output.raw_status = evidence
            output.evidence = evidence
            output.confidence = 0.9 if source_label == "status_block" else 0.75
            return output

    # Unknown
    raw = combined_status or combined_other
    output.normalized_status = "unknown"
    output.raw_status = raw[:80] if raw else ""
    output.evidence = raw[:80] if raw else ""
    output.confidence = 0.3
    output.warnings.append("販売状態を特定できませんでした")
    return output
