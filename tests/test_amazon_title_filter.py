from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from amazon_scraper import _extract_product, _title_contains_amazon


class AmazonTitleFilterTests(unittest.TestCase):
    def test_rejects_amazon_in_any_common_form(self) -> None:
        rejected = (
            "Amazon Basics Storage Box",
            "amazon.com Gift Card",
            "AMAZON Fire TV Stick",
            "AmazonBasics Cable",
        )
        for title in rejected:
            with self.subTest(title=title):
                self.assertTrue(_title_contains_amazon(title))

    def test_keeps_titles_without_amazon(self) -> None:
        accepted = (
            "Healthy Snack Variety Pack",
            "Kitchen Drawer Organizer",
            "Pet Grooming Brush",
        )
        for title in accepted:
            with self.subTest(title=title):
                self.assertFalse(_title_contains_amazon(title))

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
