"""Unit tests for Yahoo Auctions connector (non-browser parts)."""

from __future__ import annotations

import pytest

from app.connectors.yahoo_auctions import build_item_url, build_search_url


class TestBuildSearchUrl:
    def test_contains_query(self):
        url = build_search_url("メンズ スーツ")
        assert "p=" in url or "va=" in url

    def test_max_price(self):
        url = build_search_url("スーツ", max_price=20000)
        assert "max=20000" in url

    def test_page_2(self):
        url = build_search_url("スーツ", page=2)
        # page 2: b=51
        assert "b=51" in url

    def test_category_included(self):
        url = build_search_url("スーツ", category="2084228408")
        assert "2084228408" in url

    def test_no_category(self):
        url = build_search_url("スーツ", category=None)
        assert "auccat" not in url


class TestBuildItemUrl:
    def test_item_url_format(self):
        url = build_item_url("x12345678")
        assert url == "https://page.auctions.yahoo.co.jp/jp/auction/x12345678"
