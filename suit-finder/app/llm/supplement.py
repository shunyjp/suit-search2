"""LLM supplementation orchestrator.

Decides whether to call Gemini, builds prompts, and merges results back.
Called from crawl_job after all rule-based parsers have run.

Trigger conditions (OR):
  - size.unknown_fields has more than 3 items
  - material.outer_fibers is empty (no fiber info extracted)

The function is non-blocking: if Gemini fails or is not configured,
the original parser outputs are returned unchanged.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.connectors.base import MaterialParserOutput, ParserInput, SizeParserOutput
from app.llm.gemini_client import GeminiClient, client_from_env
from app.llm.merger import merge_llm_material, merge_llm_size
from app.llm.prompts import (
    build_material_prompt,
    build_material_prompt_for_images,
    build_size_prompt,
    build_size_prompt_for_images,
)

logger = logging.getLogger(__name__)

_SIZE_UNKNOWN_THRESHOLD = 3   # trigger LLM if unknown_fields count exceeds this
_IMAGE_UNKNOWN_THRESHOLD = 5  # trigger image-based LLM if unknowns still exceed this


def _needs_llm(size: SizeParserOutput, material: MaterialParserOutput) -> bool:
    return len(size.unknown_fields) > _SIZE_UNKNOWN_THRESHOLD or not material.outer_fibers


def _build_text(parser_input: ParserInput) -> str:
    """Combine specs_text and description_text as LLM input."""
    parts = [
        parser_input.page_signals.specs_text,
        parser_input.page_signals.description_text,
    ]
    return "\n".join(p for p in parts if p).strip()


async def maybe_supplement(
    parser_input: ParserInput,
    size: SizeParserOutput,
    material: MaterialParserOutput,
    client: Optional[GeminiClient] = None,
) -> tuple[SizeParserOutput, MaterialParserOutput]:
    """Run LLM supplementation if needed and client is available.

    Parameters
    ----------
    parser_input:
        Contains page_signals with description_text and specs_text.
    size, material:
        Existing parser outputs.  Only None / empty fields are filled.
    client:
        GeminiClient instance.  If None, tries to create one from GEMINI_API_KEY.
        If env var is also absent, supplementation is skipped silently.
    """
    if not _needs_llm(size, material):
        return size, material

    if client is None:
        client = client_from_env()
    if client is None:
        logger.debug("GEMINI_API_KEY not set – skipping LLM supplement")
        return size, material

    text = _build_text(parser_input)
    if not text:
        return size, material

    logger.info(
        "Running LLM supplement: size_unknowns=%d outer_fibers=%s",
        len(size.unknown_fields),
        bool(material.outer_fibers),
    )

    # Size supplement – text-based
    if size.unknown_fields:
        size_result = await client.generate_json(
            build_size_prompt(text, size.unknown_fields)
        )
        if size_result:
            size = merge_llm_size(size, size_result)
            logger.debug("LLM size supplement: remaining unknowns=%s", size.unknown_fields)

    # Size supplement – image-based (when text extraction is insufficient)
    image_urls = parser_input.page_signals.image_urls
    if len(size.unknown_fields) > _IMAGE_UNKNOWN_THRESHOLD and image_urls:
        logger.info(
            "Running image-based LLM supplement: %d unknowns, %d images available",
            len(size.unknown_fields),
            len(image_urls),
        )
        img_result = await client.generate_json_with_images(
            build_size_prompt_for_images(size.unknown_fields),
            image_urls,
        )
        if img_result:
            size = merge_llm_size(size, img_result)
            logger.debug("LLM image supplement: remaining unknowns=%s", size.unknown_fields)

    # Material supplement – テキストベース
    if not material.outer_fibers:
        mat_result = await client.generate_json(build_material_prompt(text))
        if mat_result:
            material = merge_llm_material(material, mat_result)
            logger.debug("LLM material (text) supplement: outer=%s", material.outer_fibers)

    # Material supplement – 画像ベース（テキストで素材が取れなかった場合）
    # 例: 品質表示タグの写真、素材表が画像になっている出品
    image_urls = parser_input.page_signals.image_urls
    if not material.outer_fibers and image_urls:
        logger.info(
            "Running image-based material supplement: %d images available",
            len(image_urls),
        )
        mat_img_result = await client.generate_json_with_images(
            build_material_prompt_for_images(),
            image_urls,
            max_images=4,
        )
        if mat_img_result:
            material = merge_llm_material(material, mat_img_result)
            logger.info(
                "LLM material (image) supplement: outer=%s", material.outer_fibers
            )

    return size, material
