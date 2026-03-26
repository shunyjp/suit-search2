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

_DEFAULT_MODEL = "gemini-2.0-flash-lite"


class GeminiClient:
    """Async wrapper around the google-genai SDK."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        import google.genai as genai  # lazy import: optional dependency

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._config = {"response_mime_type": "application/json", "temperature": 0.0}

    async def generate_json(self, prompt: str) -> Optional[dict[str, Any]]:
        """Send prompt, return parsed JSON dict.  Returns None on any error."""
        try:
            import google.genai as genai
            from google.genai import types as genai_types

            config = genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            )
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=config,
            )
            return json.loads(response.text)
        except Exception as exc:
            logger.warning("Gemini request failed: %s", exc)
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
