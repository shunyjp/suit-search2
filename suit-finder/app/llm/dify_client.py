"""Dify API client – stub (Phase 4).

Will be used to supplement unknown fields after rule-based parsing.
LLM is only invoked when:
1. A required field is None after all parsers have run.
2. Confidence is below a threshold.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class DifyClient:
    """Minimal async client for the Dify workflow API."""

    def __init__(self, api_url: str, api_key: str, timeout: float = 30.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Run a Dify workflow and return the output dict.

        Returns None on error (LLM is non-blocking).
        """
        url = f"{self.api_url}/workflows/run"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "workflow_id": workflow_id,
            "inputs": inputs,
            "response_mode": "blocking",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("Dify workflow %s failed: %s", workflow_id, exc)
            return None
