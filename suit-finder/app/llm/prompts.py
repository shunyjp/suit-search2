"""LLM prompt builders for Gemini supplementation.

Each builder returns a complete prompt string.
Gemini is configured with response_mime_type="application/json",
so prompts only need to specify the JSON schema in the instruction.
"""

from __future__ import annotations

# Field label → Japanese display name (for prompt readability)
_SIZE_FIELD_LABELS: dict[str, str] = {
    "jacket_shoulder_cm": "肩幅 (cm)",
    "jacket_chest_width_cm": "身幅 (cm)",
    "jacket_length_cm": "着丈 (cm)",
    "jacket_sleeve_cm": "袖丈 (cm)",
    "pants_waist_flat_cm": "ウエスト平置き (cm)",
    "pants_waist_circ_cm": "ウエスト周り (cm)",
    "pants_rise_cm": "股上 (cm)",
    "pants_inseam_cm": "股下 (cm)",
    "pants_hem_width_cm": "裾幅 (cm)",
    "pants_thigh_cm": "ワタリ (cm)",
    "pants_total_length_cm": "総丈 (cm)",
}


def build_size_prompt(text: str, unknown_fields: list[str]) -> str:
    """Prompt to extract missing size measurements from product description."""
    target_lines = "\n".join(
        f'  "{f}": {_SIZE_FIELD_LABELS.get(f, f)} の数値 (cm), なければ null'
        for f in unknown_fields
        if f in _SIZE_FIELD_LABELS
    )
    if not target_lines:
        target_lines = '  "note": "対象フィールドなし"'

    return f"""\
以下は中古メンズスーツの商品説明文です。
寸法情報を読み取り、指定のJSONキーに cm 単位の数値を入れてください。
記載がない項目は null にしてください。数値以外（単位、テキスト）は含めないでください。

--- 商品説明 ---
{text}
--- 説明終わり ---

抽出してほしい項目:
{target_lines}

JSONのみ返してください。説明は不要です。
"""


def build_material_prompt(text: str) -> str:
    """Prompt to extract fiber composition from product description."""
    return f"""\
以下は中古メンズスーツの商品説明文です。
素材（繊維組成）を読み取り、指定のJSON形式で返してください。
不明な場合は空配列 [] を使用してください。

--- 商品説明 ---
{text}
--- 説明終わり ---

以下のJSON形式のみ返してください:
{{
  "outer_fibers": [{{"fiber": "wool", "percentage": 100}}],
  "lining_fibers": [{{"fiber": "polyester", "percentage": 100}}]
}}

fiber の値は英語小文字で: wool / polyester / mohair / cotton / silk /
cashmere / linen / nylon / acrylic / polyurethane / rayon / other
percentage は整数、不明なら null。
"""
