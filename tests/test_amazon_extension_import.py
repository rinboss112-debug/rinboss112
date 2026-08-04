from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd

from amazon_extension_import import (
    ExtensionImportError,
    build_extension_zip,
    normalize_extension_frame,
    read_extension_export,
)
from amazon_scraper import CSV_COLUMNS


class AmazonExtensionImportTests(unittest.TestCase):
    def test_normalize_deduplicates_asin_and_parses_types(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "title": "Older",
                    "asin": "B07CBKMHSW",
                    "price": "7.49",
                    "prime": "false",
                },
                {
                    "title": "Snack Box",
                    "asin": "B07CBKMHSW",
                    "price": "9.49",
                    "prime": "true",
                    "product_url": "https://www.amazon.com/dp/B07CBKMHSW",
                },
            ]
        )
        result = normalize_extension_frame(frame)
        self.assertEqual(result.columns.tolist(), CSV_COLUMNS)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["title"], "Snack Box")
        self.assertEqual(result.iloc[0]["price"], 9.49)
        self.assertTrue(bool(result.iloc[0]["prime"]))

    def test_read_json_products(self) -> None:
        raw = json.dumps(
            {
                "products": [
                    {
                        "title": "Candy",
                        "asin": "B000000001",
                        "product_url": "https://www.amazon.com/dp/B000000001",
                    }
                ]
            }
        ).encode()
        result = read_extension_export(raw, "products.json")
        self.assertEqual(result.iloc[0]["asin"], "B000000001")

    def test_missing_title_is_rejected(self) -> None:
        with self.assertRaises(ExtensionImportError):
            normalize_extension_frame(pd.DataFrame([{"asin": "B000000001"}]))

    def test_build_zip_places_manifest_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "manifest.json").write_text("{}", encoding="utf-8")
            (path / "popup.js").write_text("", encoding="utf-8")
            payload = build_extension_zip(path)
        self.assertIn(b"manifest.json", payload)

    def test_app_registers_extension_route(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        source = (project_dir / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="amazon-extension"', source)
        self.assertIn("amazon_extension_page", source)

    def test_real_extension_has_batch_worker_and_is_packaged(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        extension_dir = project_dir / "browser_extension" / "amazon_product_collector"
        manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.2.0")
        self.assertEqual(manifest["background"]["service_worker"], "background.js")
        self.assertIn("alarms", manifest["permissions"])
        self.assertIn("unlimitedStorage", manifest["permissions"])
        self.assertIn("https://www.amazon.com/*", manifest["host_permissions"])

        payload = build_extension_zip(extension_dir)
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = set(archive.namelist())
        self.assertIn("manifest.json", names)
        self.assertIn("background.js", names)
        self.assertIn("popup.js", names)
        self.assertIn("content.js", names)

        popup_html = (extension_dir / "popup.html").read_text(encoding="utf-8")
        popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
        self.assertIn('id="filter-min-price"', popup_html)
        self.assertIn('id="filter-max-price"', popup_html)
        self.assertIn('id="export-all-csv"', popup_html)
        self.assertIn("filteredProducts", popup_js)


if __name__ == "__main__":
    unittest.main()
