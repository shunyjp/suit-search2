"""LLM prompt templates – Phase 4.

Prompts for Dify workflow inputs when rule-based parsing returns unknown.
"""

from __future__ import annotations

SIZE_SUPPLEMENT_PROMPT = """\
以下のスーツ商品説明文から、未取得の寸法情報を抽出してください。

商品説明:
{description}

取得したい項目（未取得のもの）:
{unknown_fields}

回答はJSON形式で、値が不明な場合は null としてください。
cm単位の数値のみを返してください。
"""

MATERIAL_EXTRACT_PROMPT = """\
以下のスーツ商品説明から素材情報を抽出してください。

商品説明:
{description}

以下の形式でJSONを返してください:
{{
  "outer_material": [{{"fiber": "wool", "percentage": 100}}],
  "lining_material": [{{"fiber": "polyester", "percentage": 100}}]
}}
不明な場合は null を使用してください。
"""
