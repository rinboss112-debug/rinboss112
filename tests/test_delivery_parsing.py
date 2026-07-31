from __future__ import annotations

import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from amazon_scraper import (
    PRODUCT_COLUMNS,
    _combined_delivery_text_from_card,
    _delivery_text_from_detail_html,
    _enrich_delivery_from_detail,
    _extract_product,
    _extract_variants_from_detail_html,
    _is_excluded_amazon_brand_product,
    _is_prime_member_delivery_text,
    _qualified_delivery_fallback,
    _qualified_fast_free_shipping_text,
    scrape_keyword,
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

    def close(self) -> None:
        return None


class DeliveryParsingTests(unittest.TestCase):
    def test_private_label_brand_filter_is_targeted(self) -> None:
        excluded_titles = (
            "Amazon Fresh Toaster Pastries, Strawberry, 12 Count",
            "Amazon Saver Macaroni & Cheese",
            "Amazon Grocery Peanut Butter",
            "Amazon Brand - Happy Belly Mixed Nuts",
            "365 Everyday Value Organic Trail Mix",
            "365 by Whole Foods Market Organic Granola",
            "365 Whole Foods Market Sparkling Water",
        )
        for title in excluded_titles:
            with self.subTest(title=title):
                self.assertTrue(_is_excluded_amazon_brand_product(title))

        self.assertTrue(
            _is_excluded_amazon_brand_product(
                "Organic Granola", "Amazon Fresh"
            )
        )
        self.assertFalse(
            _is_excluded_amazon_brand_product(
                "Phone stand compatible with Amazon Echo",
                "Independent Brand",
            )
        )
        self.assertFalse(
            _is_excluded_amazon_brand_product(
                "Healthy snack shipped by Amazon tomorrow",
                "Snack Maker",
            )
        )

    def test_csv_starts_with_requested_business_columns(self) -> None:
        self.assertEqual(
            PRODUCT_COLUMNS[:5],
            ["title", "image_url", "price", "variants", "delivery_detail"],
        )

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
        self.assertEqual(
            product.delivery_detail,
            "Or Prime members get FREE delivery Overnight 4 AM - 8 AM",
        )
        self.assertTrue(
            _is_prime_member_delivery_text(_combined_delivery_text_from_card(card))
        )

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
          <h2><a href="/dp/B012345678"><span>Healthy Snack Pack 12 Count</span></a></h2>
          <span class="a-price"><span class="a-offscreen">$19.99</span></span>
          <div data-cy="delivery-recipe">FREE delivery Monday</div>
        </div>
        """
        detail_html = """
        <div id="mir-layout-DELIVERY_BLOCK">
          Prime members get FREE delivery Overnight 4 AM - 8 AM
        </div>
        <div id="variation_size_name">
          <span class="a-form-label">Size:</span>
          <span class="selection">12 Count</span>
          <ul>
            <li title="Click to select 12 Count"></li>
            <li title="Click to select 24 Count"></li>
          </ul>
        </div>
        """
        card = BeautifulSoup(search_html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")
        self.assertIsNotNone(product)
        self.assertTrue(product.free_shipping)
        self.assertEqual(product.delivery_options, "")

        session = _FakeSession(detail_html)
        status = _enrich_delivery_from_detail(session, product)

        self.assertEqual(status, "enriched")
        self.assertTrue(product.free_shipping)
        self.assertEqual(product.delivery_options, "Overnight")
        self.assertEqual(
            product.delivery_detail,
            "Prime members get FREE delivery Overnight 4 AM - 8 AM",
        )
        self.assertEqual(product.variants, "Size: 12 Count")
        self.assertEqual(
            session.requested_urls,
            ["https://www.amazon.com/gp/aw/d/B012345678?th=1&psc=1"],
        )

    def test_variant_parser_keeps_only_size_and_flavor_found_in_title(self) -> None:
        detail_html = """
        <div id="variation_size_name">
          <span class="a-form-label">Size:</span>
          <span class="selection">12 Count</span>
          <ul>
            <li title="Click to select 12 Count"></li>
            <li title="Click to select 24 Count"></li>
            <li title="Click to select 36 Count - Currently unavailable."></li>
          </ul>
        </div>
        <script>
          {
            "variationDisplayLabels": {
              "size_name": "Size",
              "flavor_name": "Flavor"
            },
            "variationValues": {
              "size_name": ["12 Count", "24 Count"],
              "flavor_name": ["Chocolate", "Vanilla"],
              "color_name": ["Red"]
            }
          }
        </script>
        """
        self.assertEqual(
            _extract_variants_from_detail_html(
                detail_html,
                "Chocolate snack bars, 24 Count",
            ),
            "Size: 24 Count | Flavor: Chocolate",
        )

    def test_detail_page_separates_fresh_only_offer(self) -> None:
        search_html = """
        <div data-asin="B012345678">
          <h2><a href="/dp/B012345678"><span>Organic Snack Box</span></a></h2>
          <span class="a-price"><span class="a-offscreen">$19.99</span></span>
        </div>
        """
        detail_html = """
        <div id="mir-layout-DELIVERY_BLOCK">
          FREE 2-hour delivery on orders over $100 with Prime
        </div>
        <div>Ships from AmazonFresh</div>
        <div>Sold by AmazonFresh</div>
        """
        card = BeautifulSoup(search_html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")
        self.assertIsNotNone(product)

        status = _enrich_delivery_from_detail(_FakeSession(detail_html), product)

        self.assertEqual(status, "fresh")
        self.assertIn("AmazonFresh", product.delivery_detail)
        self.assertTrue(product.delivery_available)
        self.assertEqual(product.variants, "")

    def test_detail_page_rejects_offer_when_fresh_is_also_present(self) -> None:
        search_html = """
        <div data-asin="B012345678">
          <h2><a href="/dp/B012345678"><span>Organic Snack Box</span></a></h2>
          <span class="a-price"><span class="a-offscreen">$19.99</span></span>
        </div>
        """
        detail_html = """
        <div id="mir-layout-DELIVERY_BLOCK">
          Prime members get FREE delivery Tomorrow
          | FREE grocery delivery is available to Prime members.
        </div>
        <div>Ships from AmazonFresh</div>
        """
        card = BeautifulSoup(search_html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")
        self.assertIsNotNone(product)

        status = _enrich_delivery_from_detail(_FakeSession(detail_html), product)

        self.assertEqual(status, "fresh")
        self.assertIn("Prime members get FREE delivery Tomorrow", product.delivery_detail)
        self.assertIn("AmazonFresh", product.delivery_detail)

    def test_scrape_keyword_keeps_cards_even_when_legacy_filters_do_not_match(
        self,
    ) -> None:
        search_html = """
        <html><body>
          <div data-component-type="s-search-result" data-asin="B000000001">
            <h2><a href="/dp/B000000001"><span>Amazon Fresh Snack Box</span></a></h2>
            <span class="a-price"><span class="a-offscreen">€4.99</span></span>
            <div>Fresh delivery in two hours</div>
          </div>
          <div data-component-type="s-search-result" data-asin="B000000002">
            <h2><a href="/dp/B000000002"><span>Snack Without Price</span></a></h2>
          </div>
          <div data-component-type="s-search-result" data-asin="B000000003">
            <h2><a href="/dp/B000000003"><span>Slow Shipping Snack</span></a></h2>
            <span class="a-price"><span class="a-offscreen">$9.99</span></span>
            <div>Delivery next week for $6.99</div>
          </div>
        </body></html>
        """
        fake_session = _FakeSession(search_html)
        with (
            patch("amazon_scraper._build_session", return_value=fake_session),
            patch("amazon_scraper._set_delivery_zip"),
            patch("amazon_scraper._enrich_delivery_from_detail", return_value="missing"),
        ):
            products = scrape_keyword(
                keyword="snack",
                zip_code="92704",
                minimum_price=100.0,
                maximum_price=101.0,
                max_pages=1,
                max_products=10,
                only_deliverable=True,
                only_usd=True,
            )

        self.assertEqual([product.asin for product in products], [
            "B000000001",
            "B000000002",
            "B000000003",
        ])
        self.assertEqual(products[1].delivery_detail, "Không thấy thông tin ship")

    def test_detail_page_keeps_non_prime_delivery(self) -> None:
        search_html = """
        <div data-asin="B012345678">
          <h2><a href="/dp/B012345678"><span>Organic Snack Box</span></a></h2>
          <span class="a-price"><span class="a-offscreen">$19.99</span></span>
        </div>
        """
        detail_html = """
        <div id="mir-layout-DELIVERY_BLOCK">
          FREE delivery Overnight 4 AM - 8 AM
        </div>
        """
        card = BeautifulSoup(search_html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")
        self.assertIsNotNone(product)

        status = _enrich_delivery_from_detail(_FakeSession(detail_html), product)

        self.assertEqual(status, "enriched")
        self.assertEqual(
            product.delivery_detail,
            "FREE delivery Overnight 4 AM - 8 AM",
        )

    def test_prime_matcher_accepts_with_prime_wording(self) -> None:
        delivery_text = (
            "FREE delivery Overnight 5 AM - 7 AM "
            "on orders over $100 with Prime"
        )
        self.assertTrue(_is_prime_member_delivery_text(delivery_text))
        self.assertEqual(
            _qualified_fast_free_shipping_text(delivery_text),
            delivery_text,
        )

    def test_qualified_shipping_requires_all_terms_on_same_line(self) -> None:
        delivery_text = (
            "Or Prime members get FREE delivery Saturday, August 1 "
            "| Overnight 7 AM - 11 AM"
        )
        self.assertEqual(_qualified_fast_free_shipping_text(delivery_text), "")

    def test_qualified_shipping_accepts_prime_members_overnight(self) -> None:
        delivery_text = (
            "Or Prime members get FREE delivery Overnight 7 AM - 11 AM "
            "on eligible orders."
        )
        self.assertEqual(
            _qualified_fast_free_shipping_text(delivery_text),
            delivery_text,
        )

    def test_qualified_shipping_does_not_require_prime(self) -> None:
        delivery_text = "FREE delivery Tomorrow, July 31"
        self.assertEqual(
            _qualified_fast_free_shipping_text(delivery_text),
            delivery_text,
        )

    def test_qualified_shipping_accepts_join_prime_overnight_wording(self) -> None:
        delivery_text = (
            "Join Prime to get FREE delivery Overnight 7 AM - 11 AM "
            "on eligible orders"
        )
        self.assertEqual(
            _qualified_fast_free_shipping_text(delivery_text),
            delivery_text,
        )

    def test_qualified_fallback_reads_offer_from_full_page_text(self) -> None:
        page_text = (
            "Get Fast, Free Shipping with Amazon Prime "
            "FREE delivery Tuesday on orders over $35. "
            "Or Prime members get FREE delivery Tomorrow, July 31. "
            "Order within 2 hrs. Join Prime."
        )
        self.assertEqual(
            _qualified_delivery_fallback(page_text),
            "Or Prime members get FREE delivery Tomorrow, July 31",
        )


if __name__ == "__main__":
    unittest.main()
