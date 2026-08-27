from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse


SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
_SHEET_ID_RE = re.compile(r"[A-Za-z0-9_-]{10,200}")
_SHEET_URL_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


class GoogleSheetConfigurationError(ValueError):
    pass


class GoogleSheetAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GoogleSheetConfig:
    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "GoogleSheetConfig":
        config = cls(
            client_id=str(values.get("client_id", "")).strip(),
            client_secret=str(values.get("client_secret", "")).strip(),
            refresh_token=str(values.get("refresh_token", "")).strip(),
        )
        missing = [
            name
            for name in ("client_id", "client_secret", "refresh_token")
            if not getattr(config, name)
        ]
        if missing:
            raise GoogleSheetConfigurationError(
                "Thiếu cấu hình Google Sheets: " + ", ".join(missing)
            )
        return config


@dataclass(frozen=True, slots=True)
class SpreadsheetMetadata:
    spreadsheet_id: str
    title: str
    sheet_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedSpreadsheet:
    spreadsheet_id: str
    spreadsheet_title: str
    discovered_sheet_count: int
    loaded_sheet_names: tuple[str, ...]
    total_rows: int
    title_index: dict[str, tuple[dict[str, Any], ...]]
    logs: tuple[str, ...]

    @property
    def loaded_sheet_count(self) -> int:
        return len(self.loaded_sheet_names)


ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[[str], None]


def extract_spreadsheet_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("Hãy nhập Google Sheet URL hoặc Sheet ID.")

    if _SHEET_ID_RE.fullmatch(candidate):
        return candidate

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Google Sheet URL hoặc Sheet ID không hợp lệ.")
    host = (parsed.hostname or "").casefold()
    if host not in {"docs.google.com", "drive.google.com"}:
        raise ValueError("URL phải thuộc docs.google.com hoặc drive.google.com.")

    match = _SHEET_URL_ID_RE.search(parsed.path)
    if match:
        return match.group(1)
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    if _SHEET_ID_RE.fullmatch(query_id):
        return query_id
    raise ValueError("Không tìm thấy Sheet ID trong URL đã nhập.")


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split()).casefold()


def quote_sheet_name(sheet_name: str) -> str:
    return "'" + str(sheet_name).replace("'", "''") + "'"


def _row_result(sheet_name: str, row_number: int, row: Sequence[Any]) -> dict[str, Any]:
    values = [str(value) if value is not None else "" for value in row[:4]]
    values.extend([""] * (4 - len(values)))
    return {
        "Sheet Name": sheet_name,
        "Row Number": row_number,
        "Column A": values[0],
        "Column B": values[1],
        "Column C": values[2],
        "Column D": values[3],
    }


def build_title_index(
    sheets: Sequence[tuple[str, Sequence[Sequence[Any]]]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    mutable_index: dict[str, list[dict[str, Any]]] = {}
    for sheet_name, rows in sheets:
        for row_number, row in enumerate(rows, start=1):
            result = _row_result(sheet_name, row_number, row)
            normalized_values = {
                normalized
                for value in row
                if (normalized := normalize_title(value))
            }
            for normalized in normalized_values:
                mutable_index.setdefault(normalized, []).append(result)
    return {key: tuple(results) for key, results in mutable_index.items()}


def search_title(
    title_index: Mapping[str, Sequence[Mapping[str, Any]]],
    product_title: str,
) -> list[dict[str, Any]]:
    normalized = normalize_title(product_title)
    if not normalized:
        return []
    return [dict(result) for result in title_index.get(normalized, ())]


class GoogleSheetsReader:
    """Read-only Google Sheets client used only during connect/load actions."""

    def __init__(self, config: GoogleSheetConfig, service: Any | None = None):
        self.config = config
        self._service = service

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as error:
            raise RuntimeError(
                "Thiếu thư viện Google Sheets. Hãy cài lại requirements.txt."
            ) from error

        credentials = Credentials(
            token=None,
            refresh_token=self.config.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            scopes=[SHEETS_READONLY_SCOPE],
        )
        try:
            credentials.refresh(Request())
            self._service = build(
                "sheets", "v4", credentials=credentials, cache_discovery=False
            )
        except Exception as error:
            raise GoogleSheetAccessError(
                "Không xác thực được Google Sheets. Hãy kiểm tra Secrets và tạo lại "
                "refresh token với quyền spreadsheets.readonly."
            ) from error
        return self._service

    def connect(self, spreadsheet_id: str) -> SpreadsheetMetadata:
        try:
            response = (
                self._get_service()
                .spreadsheets()
                .get(
                    spreadsheetId=spreadsheet_id,
                    includeGridData=False,
                    fields="spreadsheetId,properties(title),sheets(properties(title,index))",
                )
                .execute(num_retries=3)
            )
        except GoogleSheetAccessError:
            raise
        except Exception as error:
            raise GoogleSheetAccessError(
                "Không mở được Google Sheet. Hãy kiểm tra URL/ID, quyền chia sẻ và "
                "Google Sheets API."
            ) from error

        ordered_sheets = sorted(
            response.get("sheets", []),
            key=lambda sheet: int(sheet.get("properties", {}).get("index", 0)),
        )
        sheet_names = tuple(
            str(sheet.get("properties", {}).get("title", "")).strip()
            for sheet in ordered_sheets
            if str(sheet.get("properties", {}).get("title", "")).strip()
        )
        return SpreadsheetMetadata(
            spreadsheet_id=str(response.get("spreadsheetId", spreadsheet_id)),
            title=str(response.get("properties", {}).get("title", "Untitled")),
            sheet_names=sheet_names,
        )

    def load_all_sheets(
        self,
        metadata: SpreadsheetMetadata,
        *,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
    ) -> LoadedSpreadsheet:
        logs: list[str] = []
        loaded: list[tuple[str, Sequence[Sequence[Any]]]] = []
        total_rows = 0
        total_sheets = len(metadata.sheet_names)
        service = self._get_service()

        def log(message: str) -> None:
            logs.append(message)
            if log_callback:
                log_callback(message)

        for index, sheet_name in enumerate(metadata.sheet_names, start=1):
            try:
                response = (
                    service.spreadsheets()
                    .values()
                    .get(
                        spreadsheetId=metadata.spreadsheet_id,
                        range=quote_sheet_name(sheet_name),
                        majorDimension="ROWS",
                        valueRenderOption="FORMATTED_VALUE",
                        dateTimeRenderOption="FORMATTED_STRING",
                    )
                    .execute(num_retries=3)
                )
                rows = response.get("values", [])
                if not rows:
                    log(f"Bỏ qua tab trống: {sheet_name}.")
                else:
                    loaded.append((sheet_name, rows))
                    total_rows += len(rows)
                    log(f"Đã load {sheet_name}: {len(rows)} dòng.")
            except Exception as error:
                message = str(error).strip().replace("\n", " ")
                if len(message) > 240:
                    message = message[:237] + "..."
                log(f"Lỗi tab {sheet_name}; đã bỏ qua: {message or type(error).__name__}.")
            finally:
                if progress_callback:
                    progress_callback(index, total_sheets, sheet_name)

        return LoadedSpreadsheet(
            spreadsheet_id=metadata.spreadsheet_id,
            spreadsheet_title=metadata.title,
            discovered_sheet_count=total_sheets,
            loaded_sheet_names=tuple(name for name, _rows in loaded),
            total_rows=total_rows,
            title_index=build_title_index(loaded),
            logs=tuple(logs),
        )
