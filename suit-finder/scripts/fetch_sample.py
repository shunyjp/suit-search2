#!/usr/bin/env python
"""Fetch one Yahoo Auctions item and print the PageSignals.

Usage:
    python scripts/fetch_sample.py <yahoo_auction_url>

Example:
    python scripts/fetch_sample.py https://page.auctions.yahoo.co.jp/jp/auction/x12345678
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows (avoids garbled Japanese text)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.connectors.yahoo_auctions import YahooAuctionsConnector
from app.connectors.paypay_flea_market import PayPayFleaMarketConnector
from app.evidence.extractor import build_evidence_package


def _connector_for_url(url: str):
    if "paypayfleamarket.yahoo.co.jp" in url:
        return PayPayFleaMarketConnector(headless=True)
    return YahooAuctionsConnector(headless=True)


async def main(url: str) -> None:
    print(f"Fetching: {url}\n")

    connector = _connector_for_url(url)
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
