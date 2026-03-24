"""Load rule configuration from YAML files."""
from __future__ import annotations
import functools
from pathlib import Path
from typing import Any
import yaml

CONFIG_DIR = Path(__file__).parent


@functools.lru_cache(maxsize=None)
def load_judgement_rules() -> dict[str, Any]:
    path = CONFIG_DIR / "judgement_rules.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=None)
def load_parser_rules() -> dict[str, Any]:
    path = CONFIG_DIR / "parser_rules.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_judgement(key: str, default: Any = None) -> Any:
    """Get a value from judgement_rules.yaml by dot-separated key.

    Example: get_judgement("price.max_jpy") → 30000
    """
    data = load_judgement_rules()
    parts = key.split(".")
    node = data
    for part in parts:
        if not isinstance(node, dict):
            return default
        node = node.get(part, default)
    return node
