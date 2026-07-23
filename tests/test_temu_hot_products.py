from __future__ import annotations

import io
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from temu_hot_products import (
    classify_category,
    filter_temu_products,
    normalize_temu_products,
    read_temu_product_file,
    temu_csv_template,
)


def _source() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Product Title": "Premium healthy snack gift box",
                "Category": "Food & Grocery / Snacks",
                "Price": "$29.99",
                "Original Price": "$49.99",
                "Units Sold": "12.5K+ sold",
                "Reviews": "2.4K",
                "Rating": "4.8",
                "Free Shipping": "Yes",
                "Delivery Days": "3 days",
                "Image URL": "https://img.example.com/snack.jpg",
                "Product URL": "https://www.temu.com/goods.html?goods_id=1001",
            },
            {
                "Product Title": "Small phone stand",
                "Category": "Electronics",
                "Price": "$8.99",
                "Units Sold": "200",
                "Reviews": "10",
                "Rating": "3.8",
                "Product URL": "https://www.temu.com/goods.html?goods_id=1002",
            },
            {
                "Product Title": "Kitchen storage organizer set",
                "Category": "Home & Kitchen",
                "Price": "$34.00",
                "Discount Percent": "25%",
                "Units Sold": "1.1K",
                "Reviews": "350",
                "Rating": "4.6",
                "Free Shipping": True,
                "Delivery Days": 5,
                "Product URL": "https://example.com/not-temu",
            },
        ]
    )


class TemuHotProductTests(unittest.TestCase):
    def test_blank_manual_rows_are_ignored(self) -> None:
        from temu_hot_products import empty_temu_input

        self.assertTrue(normalize_temu_products(empty_temu_input()).empty)

    def test_normalize_aliases_numbers_categories_and_links(self) -> None:
        products = normalize_temu_products(_source())
        self.assertEqual(products.loc[0, "category_group"], "Food & Grocery")
        self.assertEqual(products.loc[0, "price"], 29.99)
        self.assertEqual(products.loc[0, "units_sold"], 12_500)
        self.assertEqual(products.loc[0, "review_count"], 2_400)
        self.assertAlmostEqual(products.loc[0, "discount_percent"], 40.01, places=1)
        self.assertTrue(products.loc[0, "valid_temu_link"])
        self.assertFalse(products.loc[2, "valid_temu_link"])
        self.assertGreater(products.loc[0, "hot_score"], products.loc[1, "hot_score"])

    def test_filter_price_food_score_and_valid_link(self) -> None:
        products = normalize_temu_products(_source())
        filtered = filter_temu_products(
            products,
            minimum_price=20,
            minimum_hot_score=30,
            categories=["Food & Grocery"],
            require_valid_link=True,
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.loc[0, "title"], "Premium healthy snack gift box")

    def test_category_uses_title_when_category_is_missing(self) -> None:
        self.assertEqual(classify_category("", "Organic coffee gift set"), "Food & Grocery")

    def test_csv_reader_and_download_template(self) -> None:
        raw = _source().to_csv(index=False).encode("utf-8-sig")
        frame = read_temu_product_file("temu.csv", raw)
        self.assertEqual(len(frame), 3)
        template = pd.read_csv(io.BytesIO(temu_csv_template()))
        self.assertIn("Product URL", template.columns)
        self.assertTrue(template.empty)

    def test_page_renders_for_authenticated_admin(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "temu_hot_products.py",
            default_timeout=30,
        )
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.file_uploader), 1)
        self.assertEqual(len(app.metric), 4)

    def test_page_processes_uploaded_csv(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "temu_hot_products.py",
            default_timeout=30,
        )
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        raw = _source().to_csv(index=False).encode("utf-8-sig")
        app.file_uploader[0].set_value(("temu.csv", raw, "text/csv"))
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.metric[0].value, "3")
        self.assertEqual(app.metric[3].value, "1")

    def test_page_manual_mode_starts_empty(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "temu_hot_products.py",
            default_timeout=30,
        )
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        app.segmented_control[0].set_value("Nhập thủ công")
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.metric[0].value, "0")

    def test_app_registers_temu_route(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        source = (project_dir / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="temu-hot-products"', source)
        self.assertIn("temu_hot_products_page", source)


if __name__ == "__main__":
    unittest.main()
