from __future__ import annotations

import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from amazon_scraper import (
    CSV_COLUMNS,
    PRODUCT_COLUMNS,
    _combined_delivery_text_from_card,
    _extract_full_delivery_offers,
    _extract_product,
    _extract_variants_from_detail_html,
    _find_search_cards,
    _infer_variants_from_title,
    _is_excluded_amazon_brand_product,
    _is_prime_member_delivery_text,
    _qualified_delivery_fallback,
    _qualified_fast_free_shipping_text,
    _shipping_detail_text,
    _zero_search_page_error,
    scrape_keyword,
)


class _FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        status_code: int = 200,
        url: str = "https://www.amazon.com/s?k=test",
    ) -> None:
        self.text = text
        self.content = text.encode()
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requested_urls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _FakeResponse:
        self.requested_urls.append(url)
        return _FakeResponse(self.text, url=url)

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
        )
        for title in excluded_titles:
            with self.subTest(title=title):
                self.assertTrue(_is_excluded_amazon_brand_product(title))

        self.assertFalse(
            _is_excluded_amazon_brand_product(
                "Phone stand compatible with Amazon Echo",
                "Independent Brand",
            )
        )

    def test_scrape_keyword_removes_requested_amazon_and_365_brands(self) -> None:
        search_html = """
        <html><body>
          <div data-component-type="s-search-result" data-asin="B000000071">
            <h2><span>Amazon Fresh Strawberry Snack Bars</span></h2>
          </div>
          <div data-component-type="s-search-result" data-asin="B000000072">
            <h2><span>365 by Whole Foods Market Organic Trail Mix</span></h2>
          </div>
          <div data-component-type="s-search-result" data-asin="B000000073">
            <h2><span>Phone Stand Compatible with Amazon Echo</span></h2>
            <div data-brand="Independent Brand"></div>
          </div>
        </body></html>
        """
        fake_session = _FakeSession(search_html)
        logs: list[str] = []
        with (
            patch("amazon_scraper._build_session", return_value=fake_session),
            patch("amazon_scraper._set_delivery_zip"),
        ):
            products = scrape_keyword(
                keyword="snacks",
                zip_code="92704",
                minimum_price=None,
                maximum_price=None,
                max_pages=1,
                max_products=10,
                only_deliverable=False,
                log_callback=logs.append,
            )

        self.assertEqual([product.asin for product in products], ["B000000073"])
        self.assertTrue(
            any("brand Amazon/365=2" in message for message in logs)
        )

    def test_csv_has_variants_and_delivery_but_no_internal_shipping_detail(self) -> None:
        self.assertEqual(
            CSV_COLUMNS[:6],
            [
                "title",
                "image_url",
                "price",
                "variants",
                "delivery_options",
                "keyword",
            ],
        )
        self.assertNotIn("delivery_detail", CSV_COLUMNS)
        self.assertIn("variants", CSV_COLUMNS)

    def test_variants_keep_only_size_and_flavor_matching_title(self) -> None:
        title = (
            "Squirrel Brand Sweet Brown Butter Cashews, 3.5 oz Resealable Bag | "
            "Gourmet Flavored Cashews Nuts, Gluten Free, Vegetarian"
        )
        detail_html = """
        <html><body><script>
        var data = {
          "variationDisplayLabels": {
            "flavor_name": "Flavor Name",
            "size_name": "Size"
          },
          "variationValues": {
            "flavor_name": [
              "Sweet Brown Butter Cashews",
              "Maple Glazed Cashews"
            ],
            "size_name": [
              "3.5 Ounce (Pack of 1)",
              "3.5 Ounce (Pack of 2)",
              "10 Ounce (Pack of 1)"
            ]
          }
        };
        </script></body></html>
        """

        self.assertEqual(
            _extract_variants_from_detail_html(detail_html, title),
            "Flavor Name: Sweet Brown Butter Cashews | "
            "Size: 3.5 Ounce (Pack of 1)",
        )

    def test_title_inference_builds_listing_variant_without_detail_page(self) -> None:
        title = (
            "Squirrel Brand Sweet Brown Butter Cashews, 3.5 oz Resealable Bag | "
            "Gourmet Flavored Cashews Nuts, Gluten Free, Vegetarian"
        )

        self.assertEqual(
            _infer_variants_from_title(title),
            "Flavor Name: Sweet Brown Butter Cashews | "
            "Size: 3.5 Ounce (Pack of 1)",
        )

    def test_title_inference_keeps_explicit_pack_count(self) -> None:
        self.assertEqual(
            _infer_variants_from_title(
                "Coffee Pods, Flavor: Dark Roast, 1.2 Ounce (Pack of 12)"
            ),
            "Flavor Name: Dark Roast | Size: 1.2 Ounce (Pack of 12)",
        )

    def test_scrape_keyword_autofills_variants_without_detail_request(self) -> None:
        title = (
            "Squirrel Brand Sweet Brown Butter Cashews, 3.5 oz Resealable Bag | "
            "Gourmet Flavored Cashews Nuts, Gluten Free, Vegetarian"
        )
        search_html = f"""
        <html><body>
          <div data-component-type="s-search-result" data-asin="B000000099">
            <h2><a href="/dp/B000000099"><span>{title}</span></a></h2>
          </div>
        </body></html>
        """
        fake_session = _FakeSession(search_html)
        with (
            patch("amazon_scraper._build_session", return_value=fake_session),
            patch("amazon_scraper._set_delivery_zip"),
            patch("amazon_scraper.time.sleep"),
        ):
            products = scrape_keyword(
                keyword="cashews",
                zip_code="92704",
                minimum_price=None,
                maximum_price=None,
                max_pages=1,
                max_products=1,
                only_deliverable=False,
                include_variants=True,
            )

        self.assertEqual(len(products), 1)
        self.assertEqual(
            products[0].variants,
            "Flavor Name: Sweet Brown Butter Cashews | "
            "Size: 3.5 Ounce (Pack of 1)",
        )
        self.assertEqual(
            fake_session.requested_urls,
            ["https://www.amazon.com/s?k=cashews&page=1"],
        )

    def test_search_card_reads_prime_shipping_from_unknown_html_class(self) -> None:
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
        self.assertEqual(
            product.delivery_options,
            "Or Prime members get FREE delivery Overnight 4 AM - 8 AM",
        )
        self.assertEqual(
            product.delivery_detail,
            "Prime member | FREE delivery | Overnight 4 AM - 8 AM",
        )
        self.assertTrue(
            _is_prime_member_delivery_text(_combined_delivery_text_from_card(card))
        )

    def test_visible_overnight_promise_wins_over_hidden_attribute(self) -> None:
        html = """
        <div data-asin="B000000030">
          <h2><a href="/dp/B000000030"><span>Visible Shipping Product</span></a></h2>
          <div class="new-amazon-delivery-layout">
            Join Prime to get FREE delivery
            <b>Overnight 4 AM - 8 AM</b> on eligible orders
          </div>
          <span data-csa-c-delivery-price="FREE"
                data-csa-c-delivery-time="Tomorrow, Aug 9"></span>
        </div>
        """
        card = BeautifulSoup(html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack")

        self.assertIsNotNone(product)
        self.assertEqual(
            _combined_delivery_text_from_card(card),
            "Join Prime to get FREE delivery Overnight 4 AM - 8 AM "
            "on eligible orders",
        )
        self.assertEqual(
            product.delivery_options,
            "Join Prime to get FREE delivery Overnight 4 AM - 8 AM "
            "on eligible orders",
        )
        self.assertNotIn("Tomorrow", product.delivery_options)

    def test_duplicate_asin_prefers_visible_overnight_card(self) -> None:
        html = """
        <html><body>
          <div data-component-type="s-search-result" data-asin="B01BXU1RV6">
            <h2><a href="/dp/B01BXU1RV6"><span>Nabisco Snacks</span></a></h2>
            <div>Join Prime to get FREE delivery <b>Sun, Aug 2</b></div>
            <div>Or Non-members get FREE delivery <b>Wed, Aug 5</b></div>
          </div>
          <div data-component-type="s-search-result" data-asin="B01BXU1RV6">
            <h2><a href="/dp/B01BXU1RV6"><span>Nabisco Snacks</span></a></h2>
            <div>
              Join Prime to get FREE delivery
              <b>Overnight 4 AM - 8 AM</b> on eligible orders
            </div>
            <div>Or Non-members get FREE delivery <b>Wed, Aug 5</b></div>
          </div>
        </body></html>
        """
        cards = _find_search_cards(BeautifulSoup(html, "lxml"))

        self.assertEqual(len(cards), 1)
        product = _extract_product(cards[0], "snacks")
        self.assertIsNotNone(product)
        self.assertEqual(product.asin, "B01BXU1RV6")
        self.assertEqual(
            product.delivery_options,
            "Join Prime to get FREE delivery Overnight 4 AM - 8 AM "
            "on eligible orders | Or Non-members get FREE delivery Wed, Aug 5",
        )
        self.assertNotIn("Sun, Aug 2", product.delivery_options)

    def test_search_cards_keep_all_bold_delivery_dates_and_ranges(self) -> None:
        prime_html = """
        <div data-asin="B000000020">
          <h2><a href="/dp/B000000020"><span>Chocolate Drink</span></a></h2>
          <div class="new-amazon-delivery-layout">
            <a>Join Prime</a> to get FREE delivery <b>Sun, Aug 2</b>
            Or Non-members get FREE delivery <b>Wed, Aug 5</b>
          </div>
        </div>
        """
        range_html = """
        <div data-asin="B000000021">
          <h2><a href="/dp/B000000021"><span>Snack Pack</span></a></h2>
          <div class="new-amazon-delivery-layout">
            FREE delivery <b>Aug 9 - 13</b> on $35 of items shipped by Amazon
            Or fastest delivery <b>Aug 9 - 10</b>
          </div>
        </div>
        """

        prime_card = BeautifulSoup(prime_html, "lxml").select_one("[data-asin]")
        range_card = BeautifulSoup(range_html, "lxml").select_one("[data-asin]")
        prime_product = _extract_product(prime_card, "chocolate")
        range_product = _extract_product(range_card, "snack")

        self.assertIsNotNone(prime_product)
        self.assertEqual(
            prime_product.delivery_options,
            "Join Prime to get FREE delivery Sun, Aug 2 | "
            "Or Non-members get FREE delivery Wed, Aug 5",
        )
        self.assertTrue(prime_product.free_shipping)
        self.assertTrue(prime_product.prime)

        self.assertIsNotNone(range_product)
        self.assertEqual(
            range_product.delivery_options,
            "FREE delivery Aug 9 - 13 on $35 of items shipped by Amazon | "
            "Or fastest delivery Aug 9 - 10",
        )
        self.assertTrue(range_product.free_shipping)
        self.assertTrue(range_product.fast_shipping)
        self.assertTrue(range_product.delivery_available)

    def test_search_card_builds_link_from_asin_with_new_anchor_layout(self) -> None:
        html = """
        <div data-component-type="s-search-result" data-asin="B07CBKMHSW">
          <a class="a-link-normal s-line-clamp-2" href="/example-tracking-link">
            <h2><span>Snack Gift Box</span></h2>
          </a>
          <div class="new-delivery-class">
            Join Prime to get FREE delivery Tomorrow, August 1
          </div>
        </div>
        """
        card = BeautifulSoup(html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "Snack Food Gifts")

        self.assertIsNotNone(product)
        self.assertEqual(
            product.product_url,
            "https://www.amazon.com/dp/B07CBKMHSW",
        )
        self.assertEqual(
            product.delivery_detail,
            "Prime member | FREE delivery | Tomorrow, August 1",
        )

    def test_fallback_card_layout_derives_asin_from_product_link(self) -> None:
        html = """
        <html><head><title>Amazon search</title></head><body>
          <div class="s-result-item">
            <a href="/dp/B07CBKMHSW/ref=sr_1_1">
              <h2><span>Snack Gift Box</span></h2>
            </a>
            <span data-csa-c-delivery-price="FREE"
                  data-csa-c-delivery-time="Today 2 PM – 6 PM">
              Join Prime to get FREE delivery Today 2 PM – 6 PM
            </span>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        cards = _find_search_cards(soup)

        self.assertEqual(len(cards), 1)
        product = _extract_product(cards[0], "snack")
        self.assertIsNotNone(product)
        self.assertEqual(product.asin, "B07CBKMHSW")
        self.assertEqual(
            product.product_url,
            "https://www.amazon.com/dp/B07CBKMHSW",
        )
        self.assertEqual(
            product.delivery_detail,
            "Prime member | FREE delivery | Today 2 PM - 6 PM",
        )

    def test_search_card_keeps_fresh_shipping_in_shared_delivery_column(
        self,
    ) -> None:
        html = """
        <div data-asin="B012345678">
          <h2><a href="/dp/B012345678"><span>Organic Grocery Snack</span></a></h2>
          <div data-cy="delivery-recipe">
            fresh
            FREE 2-hour delivery on orders over $100 with Prime
            Ships from AmazonFresh
            Sold by AmazonFresh
          </div>
        </div>
        """
        card = BeautifulSoup(html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack box")

        self.assertIsNotNone(product)
        self.assertEqual(
            product.delivery_detail,
            "Fresh | FREE delivery | Orders over $100 with Prime | "
            "Ships from: AmazonFresh | Sold by: AmazonFresh",
        )
        self.assertTrue(product.free_shipping)
        self.assertFalse(product.prime)
        self.assertTrue(product.delivery_available)

    def test_fresh_shipping_takes_precedence_over_prime_wording(self) -> None:
        html = """
        <div data-asin="B012345678">
          <h2><span>Organic Grocery Snack</span></h2>
          <div data-cy="delivery-recipe">
            FREE 2-hour delivery on orders over $100 with Prime
            Ships from AmazonFresh
            Sold by AmazonFresh
            Join Prime to get FREE delivery Today 2 PM - 6 PM
          </div>
        </div>
        """
        card = BeautifulSoup(html, "lxml").select_one("[data-asin]")
        product = _extract_product(card, "snack")

        self.assertIsNotNone(product)
        self.assertEqual(
            product.delivery_detail,
            "Fresh | FREE delivery | Orders over $100 with Prime | "
            "Ships from: AmazonFresh | Sold by: AmazonFresh",
        )
        self.assertFalse(product.prime)
        self.assertFalse(product.fast_shipping)
        self.assertEqual(
            product.delivery_options,
            "Fresh | FREE delivery | Orders over $100 with Prime | "
            "Ships from: AmazonFresh | Sold by: AmazonFresh",
        )

    def test_fresh_and_join_prime_cards_are_distinguished(self) -> None:
        fresh_html = """
        <div data-asin="B000000010">
          <h2><a href="/dp/B000000010"><span>Fresh Pudding</span></a></h2>
          <div data-cy="delivery-recipe">
            fresh
            FREE delivery Overnight 4 AM - 6 AM on orders over $100 with Prime
            Ships from AmazonFresh
            Sold by AmazonFresh
          </div>
        </div>
        """
        prime_html = """
        <div data-asin="B000000011">
          <h2><a href="/dp/B000000011"><span>Vanilla Pudding</span></a></h2>
          <div data-cy="delivery-recipe">
            Join Prime to get FREE delivery Sun, Aug 2
            Or Non-members get FREE delivery Thu, Aug 6 on $35 of items
            shipped by Amazon
          </div>
        </div>
        """

        fresh_card = BeautifulSoup(fresh_html, "lxml").select_one("[data-asin]")
        prime_card = BeautifulSoup(prime_html, "lxml").select_one("[data-asin]")
        fresh_product = _extract_product(fresh_card, "pudding")
        prime_product = _extract_product(prime_card, "pudding")

        self.assertIsNotNone(fresh_product)
        self.assertEqual(
            fresh_product.delivery_detail,
            "Fresh | FREE delivery | Overnight 4 AM - 6 AM | "
            "Orders over $100 with Prime | Ships from: AmazonFresh | "
            "Sold by: AmazonFresh",
        )
        self.assertTrue(fresh_product.free_shipping)
        self.assertFalse(fresh_product.prime)
        self.assertTrue(fresh_product.fast_shipping)
        self.assertEqual(
            fresh_product.delivery_options,
            "Fresh | FREE delivery | Overnight 4 AM - 6 AM | "
            "Orders over $100 with Prime | Ships from: AmazonFresh | "
            "Sold by: AmazonFresh",
        )

        self.assertIsNotNone(prime_product)
        self.assertEqual(
            prime_product.delivery_detail,
            "Prime member | FREE delivery | Sun, Aug 2 | "
            "Non-member | FREE delivery | Thu, Aug 6",
        )
        self.assertTrue(prime_product.free_shipping)
        self.assertTrue(prime_product.prime)
        self.assertFalse(prime_product.fast_shipping)
        self.assertEqual(
            prime_product.delivery_options,
            "Join Prime to get FREE delivery Sun, Aug 2 | "
            "Or Non-members get FREE delivery Thu, Aug 6 on $35 of items "
            "shipped by Amazon",
        )

    def test_full_delivery_offer_keeps_both_complete_visible_sentences(self) -> None:
        raw_text = (
            "Join Prime to get FREE delivery Overnight 4 AM - 8 AM "
            "on eligible orders Or Non-members get FREE delivery Wed, Aug 5"
        )

        self.assertEqual(
            _extract_full_delivery_offers(raw_text),
            "Join Prime to get FREE delivery Overnight 4 AM - 8 AM "
            "on eligible orders | Or Non-members get FREE delivery Wed, Aug 5",
        )

    def test_shipping_detail_never_uses_variant_or_snap_text(self) -> None:
        incorrect_texts = (
            "Variety Pack 2 16.5 Fl Oz (Pack of 4) | SNAP EBT eligible",
            "Caramel | SNAP EBT eligible",
            "20 Fl Oz (Pack of 4)",
            "Dark Chocolate 5.5 Fl Oz (Pack of 4)",
        )
        for value in incorrect_texts:
            with self.subTest(value=value):
                self.assertEqual(_shipping_detail_text(value), "")

    def test_shipping_detail_normalizes_supported_wording(self) -> None:
        cases = {
            (
                "Or Prime members get FREE delivery Today 10 AM - 3 PM "
                "on eligible orders."
            ): "Prime member | FREE delivery | Today 10 AM - 3 PM",
            (
                "Join Prime to get FREE delivery Tomorrow, August 1"
            ): "Prime member | FREE delivery | Tomorrow, August 1",
            (
                "FREE delivery Overnight 7 AM - 11 AM"
            ): "FREE delivery | Overnight 7 AM - 11 AM",
        }
        for raw_text, expected in cases.items():
            with self.subTest(raw_text=raw_text):
                self.assertEqual(_shipping_detail_text(raw_text), expected)

    def test_shipping_detail_separates_prime_and_non_member_times(self) -> None:
        raw_text = (
            "Join Prime to get FREE delivery Today 10 AM - 3 PM "
            "on eligible orders. Or Non-members get FREE delivery "
            "Tomorrow, August 5 on $35 of items shipped by Amazon."
        )

        self.assertEqual(
            _shipping_detail_text(raw_text),
            "Prime member | FREE delivery | Today 10 AM - 3 PM | "
            "Non-member | FREE delivery | Tomorrow, August 5",
        )

    def test_shipping_detail_matches_join_prime_tomorrow_card(self) -> None:
        raw_text = (
            "Join Prime to get FREE delivery Tomorrow, Aug 1 "
            "Or Non-members get FREE delivery Wed, Aug 5 on items shipped by Amazon"
        )

        self.assertEqual(
            _shipping_detail_text(raw_text),
            "Prime member | FREE delivery | Tomorrow, Aug 1 | "
            "Non-member | FREE delivery | Wed, Aug 5",
        )

    def test_shipping_detail_keeps_both_prime_and_non_member_promises(
        self,
    ) -> None:
        raw_text = (
            "Join Prime to get FREE delivery Tomorrow, Aug 1 "
            "Or Non-members get FREE delivery Wed, Aug 5"
        )

        self.assertEqual(
            _shipping_detail_text(raw_text),
            "Prime member | FREE delivery | Tomorrow, Aug 1 | "
            "Non-member | FREE delivery | Wed, Aug 5",
        )

    def test_qualified_shipping_requires_free_and_fast_terms_together(
        self,
    ) -> None:
        self.assertEqual(
            _qualified_fast_free_shipping_text(
                "Prime members get FREE delivery Tomorrow 7 AM - 11 AM"
            ),
            "Prime members get FREE delivery Tomorrow 7 AM - 11 AM",
        )
        self.assertEqual(
            _qualified_fast_free_shipping_text(
                "FREE delivery Saturday, August 1 | Overnight 7 AM - 11 AM"
            ),
            "",
        )

    def test_qualified_fallback_reads_offer_from_full_card_text(self) -> None:
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

    def test_scrape_keyword_uses_search_page_only_and_keeps_all_cards(
        self,
    ) -> None:
        search_html = """
        <html><body>
          <div data-component-type="s-search-result" data-asin="B000000001">
            <h2><a href="/dp/B000000001"><span>Snack Box One</span></a></h2>
            <span class="a-price"><span class="a-offscreen">€4.99</span></span>
            <div>
              Join Prime to get FREE delivery Today 2 PM - 6 PM
            </div>
          </div>
          <div data-component-type="s-search-result" data-asin="B000000002">
            <h2><a href="/dp/B000000002"><span>Snack Without Ship</span></a></h2>
          </div>
          <div data-component-type="s-search-result" data-asin="B000000003">
            <h2><a href="/dp/B000000003"><span>Slow Shipping Snack</span></a></h2>
            <span class="a-price"><span class="a-offscreen">$9.99</span></span>
            <div>Delivery next week for $6.99</div>
          </div>
        </body></html>
        """
        fake_session = _FakeSession(search_html)
        logs: list[str] = []
        with (
            patch("amazon_scraper._build_session", return_value=fake_session),
            patch("amazon_scraper._set_delivery_zip"),
        ):
            products = scrape_keyword(
                keyword="Snack Food Gifts",
                zip_code="92704",
                minimum_price=100.0,
                maximum_price=101.0,
                max_pages=1,
                max_products=10,
                only_deliverable=True,
                only_usd=True,
                log_callback=logs.append,
            )

        self.assertEqual(
            [product.asin for product in products],
            ["B000000001", "B000000002", "B000000003"],
        )
        self.assertEqual(
            products[0].delivery_detail,
            "Prime member | FREE delivery | Today 2 PM - 6 PM",
        )
        self.assertEqual(
            products[1].delivery_detail,
            "Không thấy thông tin ship",
        )
        self.assertEqual(
            fake_session.requested_urls,
            [
                "https://www.amazon.com/s"
                "?k=Snack+Food+Gifts&page=1"
            ],
        )
        self.assertTrue(
            any("không mở trang chi tiết" in message for message in logs)
        )

    def test_scrape_keyword_reports_robot_check_instead_of_zero_products(
        self,
    ) -> None:
        blocked_html = """
        <html><head><title>Robot Check</title></head>
        <body>
          <form action="/errors/validateCaptcha">
            <input name="captchacharacters">
          </form>
        </body></html>
        """
        fake_session = _FakeSession(blocked_html)
        logs: list[str] = []
        with (
            patch("amazon_scraper._build_session", return_value=fake_session),
            patch("amazon_scraper._set_delivery_zip"),
        ):
            with self.assertRaisesRegex(RuntimeError, "CAPTCHA/Robot Check"):
                scrape_keyword(
                    keyword="Snack Food Gifts",
                    zip_code="92704",
                    minimum_price=None,
                    maximum_price=None,
                    max_pages=1,
                    max_products=10,
                    only_deliverable=False,
                    log_callback=logs.append,
                )

        self.assertTrue(
            any("Chẩn đoán trang Amazon" in message for message in logs)
        )

    def test_amazon_sorry_page_is_classified_as_an_error(self) -> None:
        html = """
        <html><head><title>Sorry! Something went wrong!</title></head>
        <body>Please try again later.</body></html>
        """
        response = _FakeResponse(html)
        soup = BeautifulSoup(html, "lxml")

        self.assertEqual(
            _zero_search_page_error(response, soup),
            "Amazon trả trang lỗi hoặc nội dung rỗng thay vì kết quả tìm kiếm.",
        )

    def test_scrape_keyword_accepts_explicit_empty_search(self) -> None:
        empty_html = """
        <html><head><title>Amazon.com: No results</title></head>
        <body>No results for unusually-specific-niche</body></html>
        """
        fake_session = _FakeSession(empty_html)
        with (
            patch("amazon_scraper._build_session", return_value=fake_session),
            patch("amazon_scraper._set_delivery_zip"),
        ):
            products = scrape_keyword(
                keyword="unusually-specific-niche",
                zip_code="92704",
                minimum_price=None,
                maximum_price=None,
                max_pages=1,
                max_products=10,
                only_deliverable=False,
            )

        self.assertEqual(products, [])


if __name__ == "__main__":
    unittest.main()
