from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from marketplace_gap import (
    compare_marketplaces,
    match_titles,
    normalize_temu_extension_frame,
    read_marketplace_export,
)


class MarketplaceGapTests(unittest.TestCase):
    def test_temu_normalization_parses_sales_and_deduplicates(self) -> None:
        frame = pd.DataFrame([
            {
                "title": "Kitchen Organizer 2 Pack",
                "price": "$29.99",
                "units_sold": "1.2K+ sold",
                "product_id": "123456789",
            },
            {
                "title": "Kitchen Organizer 2 Pack - new",
                "price": "31.99",
                "units_sold": "2K sold",
                "product_id": "123456789",
            },
        ])
        result = normalize_temu_extension_frame(frame)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["price"], 31.99)
        self.assertEqual(result.iloc[0]["units_sold"], 2000)

    def test_json_can_read_two_source_extension_export(self) -> None:
        payload = json.dumps({
            "version": 2,
            "temu_products": [{"title": "Pet brush", "price": 25, "product_id": "999999"}],
            "amazon_products": [],
        }).encode()
        result = read_marketplace_export(payload, "marketplace.json", "temu")
        self.assertEqual(result.iloc[0]["title"], "Pet brush")

    def test_pack_conflict_reduces_match_score(self) -> None:
        matching, _ = match_titles("Snack bags 20 count", "Snack bags 20 count")
        conflict, warning = match_titles("Snack bags 20 count", "Snack bags 5 count")
        self.assertGreater(matching, conflict)
        self.assertIn("Khác pack", warning)

    def test_comparison_calculates_ratio_profit_and_best_match(self) -> None:
        temu = normalize_temu_extension_frame(pd.DataFrame([{
            "title": "Clear acrylic kitchen drawer organizer 2 pack",
            "price": 30,
            "units_sold": "3K+ sold",
            "product_id": "111111",
            "keyword": "kitchen organizer",
        }]))
        amazon = pd.DataFrame([{
            "title": "Clear acrylic kitchen drawer organizer, 2 pack",
            "price": 10,
            "keyword": "kitchen organizer",
            "asin": "B000000001",
            "product_url": "https://www.amazon.com/dp/B000000001",
            "image_url": "",
        }])
        for column in (
            "variants", "delivery_options", "currency", "rating", "review_count", "prime",
            "free_shipping", "fast_shipping", "delivery_available", "sponsored", "scraped_at",
        ):
            amazon[column] = False if column in {
                "prime", "free_shipping", "fast_shipping", "delivery_available", "sponsored"
            } else ""
        result = compare_marketplaces(temu, amazon, temu_fee_percent=10, other_cost=2)
        self.assertEqual(result.iloc[0]["price_ratio"], 3.0)
        self.assertEqual(result.iloc[0]["estimated_profit"], 15.0)
        self.assertGreaterEqual(result.iloc[0]["match_score"], 90)

    def test_app_registers_gap_route(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = (project / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="temu-amazon-gap"', source)
        self.assertIn("marketplace_gap_page", source)

    def test_marketplace_extension_is_separate_and_packaged(self) -> None:
        project = Path(__file__).resolve().parents[1]
        amazon_dir = project / "browser_extension" / "amazon_product_collector"
        market_dir = project / "browser_extension" / "marketplace_collector"
        amazon_manifest = json.loads((amazon_dir / "manifest.json").read_text(encoding="utf-8"))
        market_manifest = json.loads((market_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(amazon_manifest["version"], "1.2.0")
        self.assertEqual(market_manifest["version"], "2.0.0")
        self.assertNotEqual(amazon_manifest["name"], market_manifest["name"])
        self.assertIn("https://www.temu.com/*", market_manifest["host_permissions"])
        self.assertTrue((market_dir / "temu_content.js").exists())
        app_source = (project / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="marketplace-extension"', app_source)

    def test_gap_page_renders_for_authenticated_admin(self) -> None:
        project = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(project / "app_pages" / "marketplace_gap.py", default_timeout=30)
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.file_uploader), 2)

    def test_marketplace_extension_download_page_renders(self) -> None:
        project = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(project / "app_pages" / "marketplace_extension.py", default_timeout=30)
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.download_button), 1)


if __name__ == "__main__":
    unittest.main()
