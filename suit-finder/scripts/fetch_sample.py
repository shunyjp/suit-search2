#!/usr/bin/env python
"""Fetch one Yahoo Auctions item and print the PageSignals.

Usage:
    python scripts/fetch_sample.py <yahoo_auction_url>

Example:
    python scripts/fetch_sample.py https://page.auctions.yahoo.co.jp/jp/auction/x12345678
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.connectors.yahoo_auctions import YahooAuctionsConnector
from app.evidence.extractor import build_evidence_package


async def main(url: str) -> None:
    print(f"Fetching: {url}\n")

    connector = YahooAuctionsConnector(headless=True)
    signals = await connector.fetch_page_signals(url)

    print("=== PageSignals ===")
    print(json.dumps(signals.model_dump(mode="json"), ensure_ascii=False, indent=2))

    package = build_evidence_package(url=url, signals=signals)
    print(f"\n=== EvidencePackage: {len(package.evidence_blocks)} blocks ===")
    for i, block in enumerate(package.evidence_blocks):
        print(f"[{i}] source={block.source} conf={block.confidence:.2f}: {block.text[:80]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
