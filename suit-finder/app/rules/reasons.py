"""Reason string constants and factories for decision engine."""

from __future__ import annotations

# Blocking constants
NO_BUY_NOW = "即決価格が設定されていないためNG (オークション形式)"
NO_PRICE = "価格を取得できませんでした"
UNKNOWN_SHOULDER = "肩幅が不明"
UNKNOWN_CHEST = "身幅が不明"
UNKNOWN_SLEEVE = "袖丈が不明"
UNKNOWN_WAIST = "ウエストが不明"
UNKNOWN_INSEAM = "股下が不明"


def price_over(actual: int, limit: int) -> str:
    return f"価格 {actual:,}円 が上限 {limit:,}円 を超えています"


def not_active(status: str) -> str:
    return f"販売状態が active でない: {status}"


def out_of_range(label: str, value: float, lo: float, hi: float) -> str:
    if hi >= 99:
        return f"{label} {value}cm が下限 {lo}cm を下回っています"
    return f"{label} {value}cm が範囲外 ({lo}–{hi}cm)"


def inseam_ng(value: float) -> str:
    return f"股下 {value}cm は絶対NG (70cm以下)"


def inseam_short(value: float, minimum: float, double_hem: bool) -> str:
    hem_note = " (裾ダブル許容)" if double_hem else ""
    return f"股下 {value}cm が最低値 {minimum}cm を下回っています{hem_note}"
