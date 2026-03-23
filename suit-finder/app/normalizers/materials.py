"""Material name normalisation.

Maps Japanese/English material aliases to canonical English identifiers.
"""

from __future__ import annotations

# Canonical form → list of aliases (Japanese / English variants)
MATERIAL_ALIASES: dict[str, list[str]] = {
    "wool": ["ウール", "wool", "毛", "ウル"],
    "polyester": ["ポリエステル", "polyester", "ポリ"],
    "polyurethane": ["ポリウレタン", "polyurethane", "PU"],
    "cotton": ["コットン", "cotton", "綿"],
    "mohair": ["モヘア", "mohair", "モヘヤ"],
    "silk": ["シルク", "silk", "絹"],
    "linen": ["リネン", "linen", "麻"],
    "cashmere": ["カシミア", "cashmere", "カシミヤ"],
    "nylon": ["ナイロン", "nylon"],
    "rayon": ["レーヨン", "rayon", "人絹"],
    "acetate": ["アセテート", "acetate"],
    "acrylic": ["アクリル", "acrylic"],
}

# Build reverse map: alias (lowercased) → canonical
_REVERSE: dict[str, str] = {}
for _canonical, _aliases in MATERIAL_ALIASES.items():
    for _alias in _aliases:
        _REVERSE[_alias.lower()] = _canonical


def normalize_material(raw: str) -> str:
    """Return canonical material name, or the input lowercased if not found."""
    return _REVERSE.get(raw.lower(), raw.lower())
