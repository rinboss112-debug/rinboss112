from __future__ import annotations

import json
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from streamlit.testing.v1 import AppTest

from amazon_extension_import import build_extension_zip


class ImageGalleryExtensionTests(unittest.TestCase):
    def test_extension_manifest_and_package(self) -> None:
        project = Path(__file__).resolve().parents[1]
        extension = project / "browser_extension" / "product_image_collector"
        manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["background"]["service_worker"], "background.js")
        self.assertIn("alarms", manifest["permissions"])
        self.assertIn("https://www.amazon.com/*", manifest["host_permissions"])
        self.assertIn("https://www.temu.com/*", manifest["host_permissions"])

        payload = build_extension_zip(extension)
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = set(archive.namelist())
        for filename in (
            "manifest.json", "background.js", "popup.html", "popup.js",
            "amazon_gallery.js", "temu_gallery.js",
        ):
            self.assertIn(filename, names)

    def test_extension_supports_csv_gallery_workflow(self) -> None:
        project = Path(__file__).resolve().parents[1]
        extension = project / "browser_extension" / "product_image_collector"
        popup = (extension / "popup.js").read_text(encoding="utf-8")
        background = (extension / "background.js").read_text(encoding="utf-8")
        amazon = (extension / "amazon_gallery.js").read_text(encoding="utf-8")
        temu = (extension / "temu_gallery.js").read_text(encoding="utf-8")
        self.assertIn("parseCsv", popup)
        self.assertIn("image_gallery_status", popup)
        self.assertIn("STOP_IMAGE_BATCH", background)
        self.assertIn("amazon_gallery.js", background)
        self.assertIn("temu_gallery.js", background)
        self.assertIn("data-a-dynamic-image", amazon)
        self.assertIn("application/ld+json", temu)

    def test_app_registers_and_renders_download_page(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = (project / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="image-extension"', source)
        self.assertIn("image_extension_page", source)

        app = AppTest.from_file(project / "app_pages" / "image_extension.py", default_timeout=30)
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(1, len(app.download_button))


if __name__ == "__main__":
    unittest.main()
