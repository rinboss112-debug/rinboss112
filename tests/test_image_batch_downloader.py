from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from image_batch_downloader import build_named_image_archive, sanitize_image_name


JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-data"


class FakeResponse:
    def __init__(self, data: bytes, content_type: str = "image/jpeg") -> None:
        self.status_code = 200
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(data)),
        }
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._data

    def close(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def get(self, _url: str, **_kwargs) -> FakeResponse:
        return FakeResponse(JPEG)

    def close(self) -> None:
        self.closed = True


class ImageBatchDownloaderTests(unittest.TestCase):
    def test_sanitize_filename_keeps_unicode_and_removes_windows_characters(self) -> None:
        self.assertEqual(sanitize_image_name('Bánh snack: vị bò?/01.jpg'), "Bánh snack_ vị bò_01.jpg")
        self.assertEqual(sanitize_image_name("CON.png"), "_CON.png")

    def test_archive_uses_requested_names_and_renames_duplicates(self) -> None:
        rows = [
            {"name": "snack box", "url": "https://cdn.example.com/a"},
            {"name": "snack box", "url": "https://cdn.example.com/b"},
        ]
        result = build_named_image_archive(
            rows,
            name_column="name",
            url_column="url",
            session=FakeSession(),
            url_validator=lambda value: value,
        )
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.report["saved_name"].tolist(), ["snack box.jpg", "snack box_2.jpg"])
        with zipfile.ZipFile(io.BytesIO(result.archive)) as archive:
            self.assertEqual(archive.read("snack box.jpg"), JPEG)
            self.assertIn("_download_report.csv", archive.namelist())

    def test_app_registers_and_renders_admin_page(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = (project / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="download-images"', source)
        self.assertIn("image_downloader_page", source)

        app = AppTest.from_file(project / "app_pages" / "image_downloader.py", default_timeout=30)
        app.secrets = {"admin": {"password": "test"}}
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        self.assertEqual(1, len(app.segmented_control))


if __name__ == "__main__":
    unittest.main()
