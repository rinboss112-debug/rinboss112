from __future__ import annotations

import io
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from amazon_image_enricher import (
    IMAGE_COLUMNS,
    STATUS_COLUMN,
    amazon_images_csv,
    enrich_amazon_product_images,
    enriched_filename,
    extract_amazon_gallery_images,
    pending_image_rows,
    read_amazon_product_csv,
)


GALLERY_HTML = """
<html>
  <img id="landingImage"
       data-old-hires="https://m.media-amazon.com/images/I/71MAIN._AC_SL1500_.jpg"
       data-a-dynamic-image='{
         "https://m.media-amazon.com/images/I/71MAIN._AC_SX679_.jpg": [679, 679]
       }'
       src="https://m.media-amazon.com/images/I/71MAIN._AC_UL320_.jpg">
  <div id="altImages">
    <img src="https://m.media-amazon.com/images/I/61SIDE1._AC_US100_.jpg">
    <img src="https://m.media-amazon.com/images/I/61SIDE2._AC_US100_.jpg">
  </div>
  <script>
    {"hiRes":"https:\\/\\/m.media-amazon.com\\/images\\/I\\/61SIDE3._AC_SL1500_.jpg",
     "large":"https://m.media-amazon.com/images/I/61SIDE4._AC_SL1500_.jpg"}
  </script>
</html>
"""


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _FakeResponse:
        self.requested_urls.append(url)
        return self.responses.pop(0)


class AmazonImageEnricherTests(unittest.TestCase):
    def test_extracts_five_original_size_gallery_images(self) -> None:
        images = extract_amazon_gallery_images(GALLERY_HTML)
        self.assertEqual(len(images), 5)
        self.assertEqual(images[0], "https://m.media-amazon.com/images/I/71MAIN.jpg")
        self.assertEqual(len(images), len(set(images)))
        self.assertTrue(all("._AC_" not in url for url in images))

    def test_enriches_only_requested_batch_and_preserves_rows(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "asin": "B012345678",
                    "title": "First product",
                    "image_url": "https://m.media-amazon.com/images/I/71MAIN._AC_UL320_.jpg",
                },
                {
                    "asin": "B087654321",
                    "title": "Second product",
                    "image_url": "https://m.media-amazon.com/images/I/51FALLBACK.jpg",
                },
            ]
        )
        session = _FakeSession([_FakeResponse(GALLERY_HTML)])
        result = enrich_amazon_product_images(
            frame,
            batch_size=1,
            session=session,
            delay_seconds=0,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result.loc[0, STATUS_COLUMN], "complete")
        self.assertTrue(all(result.loc[0, column] for column in IMAGE_COLUMNS))
        self.assertEqual(result.loc[1, STATUS_COLUMN], "")
        self.assertEqual(
            session.requested_urls,
            ["https://www.amazon.com/dp/B012345678"],
        )
        self.assertEqual(pending_image_rows(result), 1)

    def test_csv_reader_adds_columns_and_export_keeps_utf8(self) -> None:
        raw = pd.DataFrame(
            [{"asin": "B012345678", "title": "Miếng dán mụn", "image_url": "x"}]
        ).to_csv(index=False).encode("utf-8-sig")
        frame = read_amazon_product_csv(raw)
        self.assertTrue(all(column in frame.columns for column in IMAGE_COLUMNS))
        exported = pd.read_csv(io.BytesIO(amazon_images_csv(frame)))
        self.assertEqual(exported.loc[0, "title"], "Miếng dán mụn")
        self.assertEqual(enriched_filename("amazon products (3).csv"), "amazon_products_3_5_images.csv")

    def test_page_renders_for_authenticated_admin(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "amazon_images.py",
            default_timeout=30,
        )
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(len(app.file_uploader), 1)

    def test_page_previews_uploaded_csv_without_network_request(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        app = AppTest.from_file(
            project_dir / "app_pages" / "amazon_images.py",
            default_timeout=30,
        )
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        raw = pd.DataFrame(
            [
                {
                    "asin": "B012345678",
                    "title": "Acne patches",
                    "image_url": "https://m.media-amazon.com/images/I/example.jpg",
                }
            ]
        ).to_csv(index=False).encode("utf-8-sig")
        app.file_uploader[0].set_value(("amazon.csv", raw, "text/csv"))
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(app.metric[0].value, "1")
        self.assertEqual(len(app.dataframe), 1)

    def test_app_registers_amazon_images_route(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        source = (project_dir / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="amazon-images"', source)
        self.assertIn("amazon_images_page", source)


if __name__ == "__main__":
    unittest.main()
