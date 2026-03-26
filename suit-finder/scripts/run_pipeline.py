#!/usr/bin/env python
"""Run the full analysis pipeline for a single Yahoo Auctions URL.

Usage:
    python scripts/run_pipeline.py <yahoo_auction_url>

Output: JSON with verdict, score, size, price, status, warnings.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from app.workflows.crawl_job import run_crawl_job


async def main(url: str) -> None:
    print(f"Running pipeline for: {url}\n")

    result = await run_crawl_job(url, headless=True)

    if not result.success:
        print(f"ERROR: {result.error}")
        sys.exit(1)

    assert result.package and result.merged and result.decision

    output = {
        "url": url,
        "item_id": result.package.item_id,
        "verdict": result.decision.verdict,
        "score": result.decision.score,
        "blocking_reasons": result.decision.blocking_reasons,
        "reasons": result.decision.reasons,
        "needs_llm_review": result.decision.needs_llm_review,
        "needs_human_review": result.decision.needs_human_review,
        "size": result.merged.size.model_dump(mode="json"),
        "price": result.merged.price.model_dump(mode="json"),
        "status": result.merged.status.model_dump(mode="json"),
        "warnings": result.warnings,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
