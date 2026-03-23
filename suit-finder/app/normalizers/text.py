"""Japanese text normalisation utilities.

Converts full-width characters, cleans whitespace, and normalises
common punctuation variations so downstream parsers can use simple
half-width patterns.
"""

from __future__ import annotations

import re
import unicodedata


# Full-width → half-width digit / ASCII map (beyond what unicodedata handles)
_FW_SPACE = "\u3000"  # 全角スペース


def to_half_width(text: str) -> str:
    """Convert full-width alphanumerics/punctuation to half-width via NFKC."""
    return unicodedata.normalize("NFKC", text)


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace (including 全角スペース) to single ASCII space."""
    text = text.replace(_FW_SPACE, " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_japanese_text(text: str) -> str:
    """Full pipeline: NFKC → whitespace normalisation."""
    text = to_half_width(text)
    text = normalize_whitespace(text)
    return text


def normalize_colon(text: str) -> str:
    """Unify full-width colon '：' and '/' to ASCII ':'."""
    return text.replace("：", ":").replace("／", "/")


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text (simple regex, not a full parser)."""
    return re.sub(r"<[^>]+>", " ", text)


def clean_text(text: str) -> str:
    """Full cleaning pipeline used before feeding evidence to parsers."""
    text = strip_html_tags(text)
    text = to_half_width(text)
    text = normalize_colon(text)
    text = normalize_whitespace(text)
    return text
