"""Recheck job – re-run pipeline on already-fetched records.

Phase 2+ stub. Will reload stored EvidencePackages and re-run parsers
when parser rules are updated, without re-fetching from the web.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_recheck_job(item_id: str) -> None:
    """Phase 2 stub."""
    logger.info("recheck_job: not yet implemented for item_id=%s", item_id)
