"""Material parser – Phase 4 implementation.

Parses fiber content from evidence text using regex.
Handles:
  - 表地 (outer) / 裏地 (lining) distinction
  - ウール, モヘア, ポリエステル, コットン, etc.
  - Percentage formats: "ウール80%", "W/P=60/40", "毛100%"
"""

from __future__ import annotations

import re
from typing import Optional

from app.connectors.base import EvidenceBlock, MaterialParserOutput, ParserInput
from app.normalizers.materials import normalize_material
from app.normalizers.text import normalize_japanese_text


# ---------------------------------------------------------------------------
# Fiber aliases for matching (Japanese / English / abbreviated)
# ---------------------------------------------------------------------------

_FIBER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("wool",         re.compile(r"ウール|ウル|毛(?=\d|100)|[Ww]ool|[Ww](?=\s*\d+\s*%)", re.IGNORECASE)),
    ("mohair",       re.compile(r"モヘア|モヘヤ|[Mm]ohair", re.IGNORECASE)),
    ("polyester",    re.compile(r"ポリエステル|[Pp]olyester|[Pp]oly(?=\s*\d)", re.IGNORECASE)),
    ("polyurethane", re.compile(r"ポリウレタン|[Pp]olyurethane|PU(?=\s*\d)", re.IGNORECASE)),
    ("cotton",       re.compile(r"コットン|綿|[Cc]otton", re.IGNORECASE)),
    ("silk",         re.compile(r"シルク|絹|[Ss]ilk", re.IGNORECASE)),
    ("linen",        re.compile(r"リネン|麻|[Ll]inen", re.IGNORECASE)),
    ("cashmere",     re.compile(r"カシミア|カシミヤ|[Cc]ashmere", re.IGNORECASE)),
    ("nylon",        re.compile(r"ナイロン|[Nn]ylon", re.IGNORECASE)),
    ("rayon",        re.compile(r"レーヨン|人絹|[Rr]ayon", re.IGNORECASE)),
    ("acetate",      re.compile(r"アセテート|[Aa]cetate", re.IGNORECASE)),
    ("acrylic",      re.compile(r"アクリル|[Aa]crylic", re.IGNORECASE)),
]

# Percentage: matches number optionally followed by %
_PCT = r"(\d{1,3})\s*%?"

# Section markers for outer / lining
_OUTER_MARKER = re.compile(r"表地|表生地|アウター|外生地", re.IGNORECASE)
_LINING_MARKER = re.compile(r"裏地|裏生地|ライニング", re.IGNORECASE)

# "素材:" or "材質:" prefix for the material section
# Allow spaces inside the keyword, e.g. "素 材 ："
_MATERIAL_SECTION = re.compile(r"(?:素\s*材|材\s*質|生\s*地)[：:\s]", re.IGNORECASE)

# Slash-separated format: "ウール/ポリエステル 60/40" or "W/P=60/40"
_SLASH_PCT = re.compile(r"(\d{1,3})/(\d{1,3})")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_fiber_pct(text: str) -> list[dict[str, object]]:
    """Extract (fiber, percentage) pairs from a text fragment.

    Returns list of {"fiber": str, "percentage": int | None}.
    """
    results: list[dict[str, object]] = []
    for canonical, pat in _FIBER_PATTERNS:
        for m in pat.finditer(text):
            start = m.end()
            # Look for percentage immediately after the fiber name
            pct_m = re.match(r"\s*[：:/＝=\s]*" + _PCT, text[start:start + 12])
            pct: Optional[int] = int(pct_m.group(1)) if pct_m else None
            results.append({"fiber": canonical, "percentage": pct})
    return results


def _resolve_percentages(fibers: list[dict[str, object]]) -> list[dict[str, object]]:
    """If only one fiber and no percentage, infer 100%."""
    if len(fibers) == 1 and fibers[0]["percentage"] is None:
        fibers[0]["percentage"] = 100
    return fibers


def _deduplicate(fibers: list[dict[str, object]]) -> list[dict[str, object]]:
    """Remove duplicate fiber entries, preferring those with explicit percentages.

    When 'ウール混のスーツ … ウール60%' is parsed, the wool fiber appears twice:
    once with percentage=None (from '混') and once with percentage=60.
    We keep the most informative entry for each fiber name.
    """
    best: dict[str, dict] = {}
    for f in fibers:
        name = str(f["fiber"])
        existing = best.get(name)
        if existing is None:
            best[name] = f
        elif existing["percentage"] is None and f["percentage"] is not None:
            best[name] = f   # explicit beats inferred
    return list(best.values())


def _split_outer_lining(text: str) -> tuple[str, str]:
    """Split text into (outer_section, lining_section).

    Returns (outer, lining) where either may be empty.
    """
    outer_m = _OUTER_MARKER.search(text)
    lining_m = _LINING_MARKER.search(text)

    if outer_m and lining_m:
        if outer_m.start() < lining_m.start():
            outer = text[outer_m.end():lining_m.start()]
            lining = text[lining_m.end():]
        else:
            lining = text[lining_m.end():outer_m.start()]
            outer = text[outer_m.end():]
        return outer, lining

    if outer_m:
        return text[outer_m.end():], ""
    if lining_m:
        return "", text[lining_m.end():]

    # No markers – treat all as outer
    return text, ""


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_material(parser_input: ParserInput) -> MaterialParserOutput:
    """Parse fiber content from evidence blocks."""
    warnings: list[str] = []
    unknown_fields: list[str] = []

    # Priority order: specs > description > title > all_text
    priority = ["specs", "description", "title", "all_text"]
    ordered = sorted(
        parser_input.evidence_blocks,
        key=lambda b: next((i for i, s in enumerate(priority) if b.source == s), 99),
    )

    outer_fibers: list[dict] = []
    lining_fibers: list[dict] = []
    confidence = 0.0

    # Fallback accumulator: fibers found without explicit percentages or markers
    _fallback_outer: list[dict] = []

    for block in ordered:
        text = normalize_japanese_text(block.text)

        # Only process blocks that look like material info
        has_fiber_keyword = any(pat.search(text) for _, pat in _FIBER_PATTERNS)
        if not has_fiber_keyword:
            continue

        outer_text, lining_text = _split_outer_lining(text)

        # Check whether this block has explicit material authority:
        #   • explicit outer/lining section markers (表地/裏地/素材:)
        #   • at least one fiber with an explicit percentage (not inferred)
        has_explicit_marker = bool(
            _OUTER_MARKER.search(text)
            or _LINING_MARKER.search(text)
            or _MATERIAL_SECTION.search(text)
        )

        raw_outer  = _deduplicate(_extract_fiber_pct(outer_text))  if outer_text.strip()  else []
        raw_lining = _deduplicate(_extract_fiber_pct(lining_text)) if lining_text.strip() else []
        has_explicit_pct = any(
            f.get("percentage") is not None
            for f in (raw_outer + raw_lining)
        )
        is_authoritative = has_explicit_marker or has_explicit_pct

        if raw_outer:
            fibers = _resolve_percentages(raw_outer)
            if not outer_fibers:
                if is_authoritative:
                    outer_fibers = fibers
                    confidence = max(confidence, block.confidence * 0.9)
                elif not _fallback_outer:
                    # Save as low-confidence fallback (e.g. "ウール混" with no %)
                    _fallback_outer = fibers

        if raw_lining:
            fibers = _resolve_percentages(raw_lining)
            if fibers and not lining_fibers:
                lining_fibers = fibers
                confidence = max(confidence, block.confidence * 0.7)

        # Stop only when we have authoritative outer fibers
        if outer_fibers:
            break

    # If no authoritative block found, use the fallback (better than nothing)
    if not outer_fibers and _fallback_outer:
        outer_fibers = _fallback_outer
        confidence = max(confidence, 0.3)

    if not outer_fibers:
        unknown_fields.append("outer_fibers")
        warnings.append("表地素材を特定できませんでした")

    if not lining_fibers:
        unknown_fields.append("lining_fibers")
        # Not a warning – lining is optional info

    return MaterialParserOutput(
        outer_fibers=outer_fibers,
        lining_fibers=lining_fibers,
        unknown_fields=unknown_fields,
        warnings=warnings,
        confidence=round(confidence, 3),
    )
