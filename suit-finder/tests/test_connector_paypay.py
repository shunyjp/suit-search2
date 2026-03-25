"""Unit tests for PayPay Flea Market connector (non-browser parts)."""

from __future__ import annotations

import pytest

from app.connectors.paypay_flea_market import _apply_next_data_paypay


def _base_item(**overrides) -> dict:
    """Return a minimal PayPay Flea Market item dict."""
    base = {
        "id": "z578889786",
        "title": "テストスーツ",
        "description": "肩幅約44cm\n股下約75cm",
        "price": 9_080,
        "status": "OPEN",
        "isPurchased": False,
        "images": [
            {"url": "https://auctions.c.yimg.jp/img/test1.jpg"},
            {"url": "https://auctions.c.yimg.jp/img/test2.jpg"},
        ],
        "categoryList": [
            {"id": 13457, "name": "ファッション"},
            {"id": 2495, "name": "メンズファッション"},
            {"id": 36672, "name": "スーツ、フォーマル"},
        ],
        "brand": {"id": 1, "name": "TEST BRAND"},
        "condition": {"key": "used20", "text": "目立った傷や汚れなし"},
    }
    base.update(overrides)
    return base


class TestApplyNextDataPayPay:

    def _run(self, **overrides) -> dict:
        signals: dict = {
            "title_text": "", "price_text": "", "status_text": "",
            "description_text": "", "all_text": "", "specs_text": "",
            "brand_text": "", "category_text": "", "image_urls": [],
        }
        _apply_next_data_paypay(signals, _base_item(**overrides))
        return signals

    # --- title ---
    def test_title(self):
        s = self._run()
        assert s["title_text"] == "テストスーツ"

    # --- price ---
    def test_price_formatted_as_buy_now(self):
        """PayPay フリマは固定価格なので 即決 XXXX円 形式に変換する。"""
        s = self._run(price=9_080)
        assert "即決" in s["price_text"]
        assert "9,080" in s["price_text"]

    def test_zero_price_omitted(self):
        s = self._run(price=0)
        assert s["price_text"] == ""

    # --- status ---
    def test_status_open(self):
        s = self._run(status="OPEN", isPurchased=False)
        assert s["status_text"] == "出品中"

    def test_status_sold(self):
        s = self._run(status="SOLD", isPurchased=False)
        assert s["status_text"] == "終了"

    def test_status_is_purchased(self):
        """isPurchased=True は OPEN でも sold 扱い。"""
        s = self._run(status="OPEN", isPurchased=True)
        assert s["status_text"] == "終了"

    def test_status_closed(self):
        s = self._run(status="CLOSED")
        assert s["status_text"] == "終了"

    # --- description ---
    def test_description_text(self):
        s = self._run(description="肩幅約44cm\n股下約75cm")
        assert "肩幅約44cm" in s["description_text"]
        assert s["description_text"] == s["all_text"]

    def test_description_empty(self):
        s = self._run(description="")
        assert s["description_text"] == ""

    # --- images ---
    def test_image_urls(self):
        s = self._run()
        assert len(s["image_urls"]) == 2
        assert all("auctions.c.yimg.jp" in u for u in s["image_urls"])

    def test_image_urls_no_images(self):
        s = self._run(images=[])
        assert s["image_urls"] == []

    # --- category ---
    def test_category_text(self):
        s = self._run()
        assert "ファッション" in s["category_text"]
        assert "スーツ、フォーマル" in s["category_text"]

    # --- brand ---
    def test_brand_text(self):
        s = self._run()
        assert s["brand_text"] == "TEST BRAND"

    def test_brand_missing(self):
        s = self._run(brand=None)
        assert s["brand_text"] == ""

    # --- specs / condition ---
    def test_specs_condition(self):
        s = self._run()
        assert "目立った傷や汚れなし" in s["specs_text"]

    def test_specs_no_condition(self):
        s = self._run(condition=None)
        assert s["specs_text"] == ""


class TestConnectorUrlRouting:
    """Verify _connector_for_url picks the right class."""

    def test_yahoo_auctions_url(self):
        from app.workflows.crawl_job import _connector_for_url
        from app.connectors.yahoo_auctions import YahooAuctionsConnector
        c = _connector_for_url("https://auctions.yahoo.co.jp/jp/auction/x12345")
        assert isinstance(c, YahooAuctionsConnector)

    def test_paypay_flea_market_url(self):
        from app.workflows.crawl_job import _connector_for_url
        from app.connectors.paypay_flea_market import PayPayFleaMarketConnector
        c = _connector_for_url("https://paypayfleamarket.yahoo.co.jp/item/z578889786")
        assert isinstance(c, PayPayFleaMarketConnector)
