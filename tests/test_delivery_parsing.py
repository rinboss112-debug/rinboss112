from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from amazon_scraper import _extract_product


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


if __name__ == "__main__":
    unittest.main()
