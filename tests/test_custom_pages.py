from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from custom_pages import CustomPageStore, records_from_frame


SAMPLE_CONTENT = {
    "version": 1,
    "categories": [
        {
            "id": "category-1",
            "name": "Snack",
            "slug": "snack",
            "description": "Đồ ăn nhẹ",
            "created_at": "2026-07-20T12:00:00",
            "updated_at": "2026-07-20T12:00:00",
        }
    ],
    "pages": [
        {
            "id": "page-1",
            "title": "Snack bán chạy",
            "slug": "snack-ban-chay-page01",
            "description": "Danh sách để quản lý.",
            "category_id": "category-1",
            "published": True,
            "columns": ["Tên", "price", "image_url", "product_url"],
            "rows": [
                {
                    "Tên": "Snack A",
                    "price": 12.5,
                    "image_url": "https://example.com/a.jpg",
                    "product_url": "https://www.amazon.com/dp/B07CBKMHSW",
                }
            ],
            "niche_ids": [],
            "revision": 1,
            "created_at": "2026-07-20T12:00:00",
            "updated_at": "2026-07-20T12:00:00",
        }
    ],
    "updated_at": "2026-07-20T12:00:00",
}


class CustomPageStoreTests(unittest.TestCase):
    def test_category_page_and_table_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CustomPageStore(Path(directory) / "custom_pages.json")
            category = store.create_category("Snack", "Đồ ăn nhẹ")
            page = store.create_page("Snack bán chạy", category["id"], "Ghi nhớ")
            columns, rows = records_from_frame(
                pd.DataFrame([{"Tên": "Snack A", "Giá": 12.5}])
            )
            store.update_page(
                page["id"],
                title=page["title"],
                description=page["description"],
                category_id=category["id"],
                published=True,
                columns=columns,
                rows=rows,
                niche_ids=["niche-1"],
            )

            loaded = store.load()
            self.assertTrue(loaded["pages"][0]["published"])
            self.assertEqual(loaded["pages"][0]["rows"][0]["Tên"], "Snack A")
            self.assertEqual(loaded["pages"][0]["niche_ids"], ["niche-1"])

            store.delete_category(category["id"])
            self.assertEqual(store.load()["pages"][0]["category_id"], "")


class CustomPageViewTests(unittest.TestCase):
    def test_app_registers_published_dynamic_pages(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        with (
            patch("custom_pages.CustomPageStore.load", return_value=SAMPLE_CONTENT),
            patch("niche_catalog.NicheCatalogStore.load", return_value={"items": []}),
        ):
            app = AppTest.from_file(project_dir / "app.py", default_timeout=30)
            app.run()
            self.assertEqual([], list(app.exception))

    def test_public_page_renders(self) -> None:
        script = "\n".join(
            (
                "from custom_page_view import render_custom_page",
                f"page = {SAMPLE_CONTENT['pages'][0]!r}",
                "render_custom_page(page, 'Snack', {'items': []})",
            )
        )
        app = AppTest.from_string(script, default_timeout=20)
        app.run()
        self.assertEqual([], list(app.exception))

    def test_admin_editor_renders_with_existing_page(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        with (
            patch("custom_pages.CustomPageStore.load", return_value=SAMPLE_CONTENT),
            patch("niche_catalog.NicheCatalogStore.load", return_value={"items": []}),
        ):
            app = AppTest.from_file(
                project_dir / "app_pages" / "admin.py",
                default_timeout=30,
            )
            app.secrets = {
                "admin": {"password": "test", "enable_access_control": False}
            }
            app.session_state["admin_authenticated"] = True
            app.run()
            self.assertEqual([], list(app.exception))


if __name__ == "__main__":
    unittest.main()
