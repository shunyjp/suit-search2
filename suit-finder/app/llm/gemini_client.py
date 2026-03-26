"""Gemini API client for LLM supplementation.

Called only when rule-based parsers leave required fields unknown.
LLM results are merged with low confidence and never override parser results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient:
    """Async wrapper around the google-genai SDK."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        import google.genai as genai  # lazy import: optional dependency

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._config = {"response_mime_type": "application/json", "temperature": 0.0}

    def _make_config(self):  # type: ignore[return]
        from google.genai import types as genai_types
        return genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        )

    async def generate_json(self, prompt: str) -> Optional[dict[str, Any]]:
        """Send text prompt, return parsed JSON dict.  Returns None on any error."""
        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=self._make_config(),
            )
            return json.loads(response.text)
        except Exception as exc:
            logger.warning("Gemini request failed: %s", exc)
            return None

    async def generate_json_with_images(
        self,
        prompt: str,
        image_urls: list[str],
        max_images: int = 4,
    ) -> Optional[dict[str, Any]]:
        """Send images + text prompt to Gemini, return parsed JSON dict.

        Downloads up to max_images URLs and passes them as inline image parts.
        Returns None on any error (non-blocking).
        """
        try:
            import httpx
            from google.genai import types as genai_types

            parts: list = []
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as http:
                for url in image_urls[:max_images]:
                    try:
                        resp = await http.get(url)
                        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                        parts.append(
                            genai_types.Part.from_bytes(
                                data=resp.content, mime_type=mime
                            )
                        )
                    except Exception as img_exc:
                        logger.debug("Image download failed %s: %s", url, img_exc)

            if not parts:
                logger.debug("No images downloaded – skipping image supplement")
                return None

            parts.append(genai_types.Part.from_text(prompt))

            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=parts,
                config=self._make_config(),
            )
            return json.loads(response.text)
        except Exception as exc:
            logger.warning("Gemini image request failed: %s", exc)
            return None


def client_from_env(model: str = _DEFAULT_MODEL) -> Optional[GeminiClient]:
    """Create GeminiClient from GEMINI_API_KEY env var. Returns None if unset."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return GeminiClient(api_key=api_key, model=model)
    except Exception as exc:
        logger.warning("Failed to init GeminiClient: %s", exc)
        return None
