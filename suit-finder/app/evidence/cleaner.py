"""Evidence block cleaning utilities.

Removes blocks that are empty, too short, or contain only noise.
Also de-duplicates blocks with identical text across sources.
"""

from __future__ import annotations

from app.connectors.base import EvidenceBlock


MIN_TEXT_LEN = 3  # characters


def is_noise(block: EvidenceBlock) -> bool:
    """Return True if the block should be discarded."""
    if len(block.text) < MIN_TEXT_LEN:
        return True
    # Pure number blocks (e.g. page number artefacts)
    if block.text.isdigit():
        return True
    return False


def deduplicate(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    """Remove duplicate text keeping highest-confidence block."""
    seen: dict[str, EvidenceBlock] = {}
    for block in blocks:
        key = block.text
        if key not in seen or block.confidence > seen[key].confidence:
            seen[key] = block
    # Preserve original order by iterating blocks again
    result: list[EvidenceBlock] = []
    used: set[str] = set()
    for block in blocks:
        key = block.text
        if key not in used and seen[key] is block:
            result.append(block)
            used.add(key)
    return result


def clean_blocks(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    """Remove noise then deduplicate."""
    filtered = [b for b in blocks if not is_noise(b)]
    return deduplicate(filtered)
