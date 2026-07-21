from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from amazon_scraper import (
    _delivery_text_from_detail_html,
    _enrich_delivery_from_detail,
    _extract_product,
)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requested_urls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _FakeResponse:
        self.requested_urls.append(url)
        return _FakeResponse(self.text)


class DeliveryParsingTests(unittest.TestCase):
    def test_delivery_fallback_handles_new_unknown_html_class(self) -> None:
        html = """
        <div data-asin="B012345678">
          <h2><a href="/dp/B012345678"><span>Healthy Snack Pack</span></a></h2>
          <img class="s-image" src="https://example.com/product.jpg" />
          <span class="a-price"><span class="a-offscreen">$19.99</span></span>
          <div class="new-delivery-class-from-amazon">
            Or Prime members get FREE delivery Overnight 4 AM - 8 AM
          </div>
        </div>
        """
        card = BeautifulSoup(html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")
        self.assertIsNotNone(product)
        self.assertTrue(product.free_shipping)
        self.assertEqual(product.delivery_options, "Overnight")
        self.assertEqual(product.delivery_detail, "Overnight 4 AM - 8 AM")

    def test_detail_page_parser_reads_delivery_block_and_attributes(self) -> None:
        html = """
        <div id="mir-layout-DELIVERY_BLOCK">
          <span data-csa-c-delivery-price="FREE"
                data-csa-c-delivery-time="Tomorrow, July 22">
            FREE delivery Tomorrow, July 22
          </span>
        </div>
        """
        delivery_text = _delivery_text_from_detail_html(html)
        self.assertIn("FREE delivery", delivery_text)
        self.assertIn("Tomorrow", delivery_text)

    def test_detail_page_enriches_cloud_search_card(self) -> None:
        search_html = """
        <div data-asin="B012345678">
          <h2><a href="/dp/B012345678"><span>Healthy Snack Pack</span></a></h2>
          <span class="a-price"><span class="a-offscreen">$19.99</span></span>
          <div data-cy="delivery-recipe">FREE delivery Monday</div>
        </div>
        """
        detail_html = """
        <div id="mir-layout-DELIVERY_BLOCK">
          Get it Overnight 4 AM - 8 AM
        </div>
        """
        card = BeautifulSoup(search_html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")
        self.assertIsNotNone(product)
        self.assertTrue(product.free_shipping)
        self.assertEqual(product.delivery_options, "")

        session = _FakeSession(detail_html)
        status = _enrich_delivery_from_detail(session, product)

        self.assertEqual(status, "verified")
        self.assertTrue(product.free_shipping)
        self.assertEqual(product.delivery_options, "Overnight")
        self.assertEqual(product.delivery_detail, "Overnight 4 AM - 8 AM")
        self.assertEqual(session.requested_urls, ["https://www.amazon.com/dp/B012345678"])


if __name__ == "__main__":
    unittest.main()
