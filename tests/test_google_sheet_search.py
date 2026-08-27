from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from google_sheet_search import (
    GoogleSheetConfig,
    GoogleSheetsReader,
    SpreadsheetMetadata,
    build_title_index,
    extract_spreadsheet_id,
    normalize_title,
    search_title,
)


class FakeRequest:
    def __init__(self, response: dict[str, Any] | None = None, error: Exception | None = None):
        self.response = response or {}
        self.error = error

    def execute(self, num_retries: int = 0) -> dict[str, Any]:
        if self.error:
            raise self.error
        return self.response


class FakeValues:
    def __init__(self, responses: dict[str, dict[str, Any] | Exception], calls: list[str]):
        self.responses = responses
        self.calls = calls

    def get(self, **kwargs: Any) -> FakeRequest:
        sheet_range = str(kwargs["range"])
        self.calls.append(sheet_range)
        response = self.responses[sheet_range]
        if isinstance(response, Exception):
            return FakeRequest(error=response)
        return FakeRequest(response=response)


class FakeSpreadsheets:
    def __init__(
        self,
        metadata: dict[str, Any],
        responses: dict[str, dict[str, Any] | Exception],
        value_calls: list[str],
    ):
        self.metadata = metadata
        self._values = FakeValues(responses, value_calls)
        self.metadata_calls = 0

    def get(self, **_kwargs: Any) -> FakeRequest:
        self.metadata_calls += 1
        return FakeRequest(response=self.metadata)

    def values(self) -> FakeValues:
        return self._values


class FakeService:
    def __init__(self, spreadsheets: FakeSpreadsheets):
        self._spreadsheets = spreadsheets

    def spreadsheets(self) -> FakeSpreadsheets:
        return self._spreadsheets


class GoogleSheetSearchTests(unittest.TestCase):
    def test_extracts_id_from_supported_url_and_raw_id(self) -> None:
        sheet_id = "1AbC_defGhijkLMNopQRstuVWxyz012345"
        self.assertEqual(extract_spreadsheet_id(sheet_id), sheet_id)
        self.assertEqual(
            extract_spreadsheet_id(
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid=0"
            ),
            sheet_id,
        )
        self.assertEqual(
            extract_spreadsheet_id(f"https://drive.google.com/open?id={sheet_id}"),
            sheet_id,
        )
        with self.assertRaises(ValueError):
            extract_spreadsheet_id("https://example.com/not-a-sheet")

    def test_normalizes_case_and_whitespace_without_fuzzy_matching(self) -> None:
        self.assertEqual(normalize_title("  Snack   FOOD\nGifts  "), "snack food gifts")
        self.assertNotEqual(normalize_title("Snack food gift"), normalize_title("Snack food gifts"))

    def test_searches_all_tabs_and_returns_all_exact_matches(self) -> None:
        index = build_title_index(
            [
                (
                    "Sheet 1",
                    [
                        ["Product Title", "SKU", "Price", "Note"],
                        ["Snack Food Gifts", "SKU-1", "$10", "First"],
                    ],
                ),
                (
                    "Other Tab",
                    [
                        ["SKU-2", "  SNACK   food gifts  ", "$11", "Second"],
                        ["Snack Food Gifts", "SKU-3", "$12", "Third"],
                        ["Different title", "SKU-4", "$13", "Fourth"],
                    ],
                ),
            ]
        )

        cases = {
            "title in Sheet 1": ("Snack Food Gifts", 3),
            "title in another sheet": ("Different title", 1),
            "different case": ("SNACK FOOD GIFTS", 3),
            "extra whitespace": ("  snack   food gifts ", 3),
            "not found": ("Missing product", 0),
        }
        for label, (query, expected_count) in cases.items():
            with self.subTest(label=label):
                self.assertEqual(len(search_title(index, query)), expected_count)

        results = search_title(index, "Snack Food Gifts")
        self.assertEqual(
            list(results[0]),
            ["Sheet Name", "Row Number", "Column A", "Column B", "Column C", "Column D"],
        )
        self.assertEqual(results[0]["Sheet Name"], "Sheet 1")
        self.assertEqual(results[0]["Row Number"], 2)
        self.assertEqual(results[0]["Column A"], "Snack Food Gifts")
        self.assertEqual(results[1]["Column A"], "SKU-2")

    def test_connects_and_loads_tabs_once_then_searches_without_api(self) -> None:
        metadata_response = {
            "spreadsheetId": "test-sheet-id-123",
            "properties": {"title": "Products"},
            "sheets": [
                {"properties": {"title": "Sheet 1", "index": 0}},
                {"properties": {"title": "Other's Tab", "index": 1}},
                {"properties": {"title": "Empty", "index": 2}},
                {"properties": {"title": "Broken", "index": 3}},
            ],
        }
        value_calls: list[str] = []
        fake_spreadsheets = FakeSpreadsheets(
            metadata_response,
            {
                "'Sheet 1'": {"values": [["Snack Food Gifts", "A", "B", "C"]]},
                "'Other''s Tab'": {"values": [["Snack Food Gifts", "D", "E", "F"]]},
                "'Empty'": {},
                "'Broken'": RuntimeError("permission denied"),
            },
            value_calls,
        )
        reader = GoogleSheetsReader(
            GoogleSheetConfig("client", "secret", "token"),
            service=FakeService(fake_spreadsheets),
        )

        metadata = reader.connect("test-sheet-id-123")
        progress: list[tuple[int, int, str]] = []
        loaded = reader.load_all_sheets(
            metadata,
            progress_callback=lambda done, total, name: progress.append((done, total, name)),
        )

        self.assertEqual(metadata.title, "Products")
        self.assertEqual(metadata.sheet_names, ("Sheet 1", "Other's Tab", "Empty", "Broken"))
        self.assertEqual(loaded.loaded_sheet_count, 2)
        self.assertEqual(loaded.total_rows, 2)
        self.assertEqual(len(value_calls), 4)
        self.assertEqual(progress[-1], (4, 4, "Broken"))
        self.assertTrue(any("Bỏ qua tab trống: Empty" in line for line in loaded.logs))
        self.assertTrue(any("Lỗi tab Broken" in line for line in loaded.logs))

        calls_before_search = len(value_calls)
        self.assertEqual(len(search_title(loaded.title_index, "SNACK FOOD GIFTS")), 2)
        self.assertEqual(len(search_title(loaded.title_index, "not present")), 0)
        self.assertEqual(len(value_calls), calls_before_search)

    def test_page_route_and_initial_render(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = (project / "app.py").read_text(encoding="utf-8")
        self.assertIn('url_path="google-sheet-search"', source)
        self.assertIn("google_sheet_search_page", source)

        app = AppTest.from_file(
            project / "app_pages" / "google_sheet_search.py",
            default_timeout=30,
        )
        app.secrets = {
            "admin": {"password": "test"},
            "google_drive": {
                "client_id": "client",
                "client_secret": "secret",
                "refresh_token": "token",
            },
        }
        app.session_state["admin_authenticated"] = True
        app.run()
        self.assertEqual([], list(app.exception))
        button_labels = [button.label for button in app.button]
        self.assertIn("CONNECT SHEET", button_labels)
        self.assertIn("LOAD ALL SHEETS", button_labels)
        self.assertIn("SEARCH TITLE", button_labels)


if __name__ == "__main__":
    unittest.main()
