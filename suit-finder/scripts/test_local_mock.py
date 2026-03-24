#!/usr/bin/env python
"""Test fetcher against a local mock HTML page.

Serves the mock HTML fixture and runs the full pipeline against it.
Usage:
    python scripts/test_local_mock.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
MOCK_FILE = "mock_yahoo_auction_page.html"
PORT = 18765


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURES_DIR), **kwargs)

    def log_message(self, *args):
        pass  # suppress access logs


def _start_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    return server


async def main() -> None:
    print(f"Starting local HTTP server on port {PORT}...")
    server = _start_server()
    url = f"http://127.0.0.1:{PORT}/{MOCK_FILE}"
    print(f"Mock URL: {url}\n")

    from app.connectors.yahoo_auctions import YahooAuctionsConnector
    from app.evidence.cleaner import clean_blocks
    from app.evidence.extractor import build_evidence_package
    from app.evidence.merger import merge_attributes
    from app.parsers.condition_parser import parse_condition
    from app.parsers.material_parser import parse_material
    from app.parsers.price_parser import parse_price
    from app.parsers.size_parser import parse_size
    from app.parsers.status_parser import parse_status
    from app.parsers.style_parser import parse_style
    from app.rules.decision_engine import decide
    from app.connectors.base import ParserInput

    connector = YahooAuctionsConnector(headless=True, wait_ms=500)
    signals = await connector.fetch_page_signals(url)

    print("=== PageSignals ===")
    for field, val in signals.model_dump().items():
        if field in ("retrieved_at", "image_urls"):
            continue
        preview = str(val)[:120].replace("\n", "↵")
        print(f"  {field:20s}: {preview}")

    pkg = build_evidence_package(url=url, signals=signals)
    pkg.evidence_blocks = clean_blocks(pkg.evidence_blocks)
    print(f"\n=== EvidenceBlocks ({len(pkg.evidence_blocks)}) ===")
    for b in pkg.evidence_blocks:
        print(f"  [{b.source:12s}] conf={b.confidence:.2f} | {b.text[:80]}")

    pi = ParserInput(
        item_id=pkg.item_id,
        evidence_blocks=pkg.evidence_blocks,
        page_signals=pkg.page_signals,
    )

    size    = parse_size(pi)
    price   = parse_price(pi)
    status  = parse_status(pi)
    material = parse_material(pi)
    style   = parse_style(pi)
    condition = parse_condition(pi)

    print("\n=== Parsers ===")
    print(f"  price    : listing_type={price.listing_type} "
          f"buy_now={price.buy_now_price_jpy} current={price.current_price_jpy}")
    print(f"  status   : {status.normalized_status} (conf={status.confidence})")
    print(f"  jacket   : shoulder={_v(size.jacket.shoulder_cm)} "
          f"chest={_v(size.jacket.chest_width_cm)} "
          f"sleeve={_v(size.jacket.sleeve_cm)}")
    print(f"  pants    : waist_flat={_v(size.pants.waist_flat_cm)} "
          f"inseam={_v(size.pants.inseam_cm)} "
          f"hem={_cv(size.pants.hem_finish)}")
    print(f"  material : outer={material.outer_fibers}")
    print(f"  style    : type={style.button_type} count={style.button_count}")
    print(f"  condition: grade={condition.grade} stain={condition.has_stain} hole={condition.has_hole}")

    print(f"  size.unknown: {size.unknown_fields}")
    print(f"  price.unknown: {price.unknown_fields}")

    merged = merge_attributes(
        item_id=pkg.item_id,
        size=size, price=price, status=status,
        material=material, style=style, condition=condition,
    )
    decision = decide(merged)

    print(f"\n=== Decision ===")
    print(f"  verdict : {decision.verdict}")
    print(f"  score   : {decision.score}")
    if decision.blocking_reasons:
        print(f"  BLOCKING: {decision.blocking_reasons}")
    if decision.reasons:
        print(f"  notes   : {decision.reasons}")

    server.shutdown()


def _v(m) -> str:
    return f"{m.value}cm" if m else "?"


def _cv(m) -> str:
    return m.value if m else "?"


if __name__ == "__main__":
    asyncio.run(main())
