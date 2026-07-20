from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from amazon_scraper import slugify_filename
from cloud_storage import GoogleDriveConfig, GoogleDriveStorage


CUSTOM_PAGES_FILENAME = "custom_pages.json"
APP_TIMEZONE = ZoneInfo("Asia/Bangkok")
_CONTENT_LOCK = threading.RLock()


def _now_text() -> str:
    return datetime.now(APP_TIMEZONE).isoformat(timespec="seconds")


def _clean_slug(value: str) -> str:
    return slugify_filename(value).replace("_", "-")[:64] or "page"


def _clean_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (str, bool, int, float)):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value
    if hasattr(value, "item"):
        try:
            return _clean_cell(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple, dict, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def clean_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    """Return an editor-safe frame with unique, human-readable column names."""
    cleaned = frame.copy()
    columns: list[str] = []
    used: set[str] = set()
    for position, raw_name in enumerate(cleaned.columns, start=1):
        base = str(raw_name).strip() or f"Cột {position}"
        candidate = base
        suffix = 2
        while candidate.casefold() in used:
            candidate = f"{base} ({suffix})"
            suffix += 1
        used.add(candidate.casefold())
        columns.append(candidate)
    cleaned.columns = columns
    for column in cleaned.columns:
        cleaned[column] = cleaned[column].map(_clean_cell)
    return cleaned


def records_from_frame(frame: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]]]:
    cleaned = clean_dataframe(frame)
    columns = list(cleaned.columns)
    records = [
        {column: _clean_cell(row.get(column)) for column in columns}
        for row in cleaned.to_dict(orient="records")
    ]
    return columns, records


def frame_from_page(page: Mapping[str, Any]) -> pd.DataFrame:
    columns = [str(value) for value in page.get("columns", [])]
    rows = page.get("rows", [])
    if not columns:
        columns = ["Tên", "Ghi chú"]
    return pd.DataFrame(rows if isinstance(rows, list) else [], columns=columns)


def default_content() -> dict[str, Any]:
    return {
        "version": 1,
        "categories": [],
        "pages": [],
        "updated_at": _now_text(),
    }


def _normalize_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    content = default_content()
    categories: list[dict[str, Any]] = []
    category_ids: set[str] = set()
    for raw in payload.get("categories", []):
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        category_id = str(raw.get("id", "")).strip() or uuid.uuid4().hex
        category_ids.add(category_id)
        categories.append(
            {
                "id": category_id,
                "name": name,
                "slug": str(raw.get("slug", "")).strip() or _clean_slug(name),
                "description": str(raw.get("description", "")).strip(),
                "created_at": str(raw.get("created_at", _now_text())).strip(),
                "updated_at": str(raw.get("updated_at", _now_text())).strip(),
            }
        )

    pages: list[dict[str, Any]] = []
    for raw in payload.get("pages", []):
        if not isinstance(raw, Mapping):
            continue
        title = str(raw.get("title", "")).strip()
        if not title:
            continue
        page_id = str(raw.get("id", "")).strip() or uuid.uuid4().hex
        raw_columns = raw.get("columns", [])
        columns: list[str] = []
        used_columns: set[str] = set()
        if isinstance(raw_columns, list):
            for position, value in enumerate(raw_columns, start=1):
                base = str(value).strip() or f"Cột {position}"
                candidate = base
                suffix = 2
                while candidate.casefold() in used_columns:
                    candidate = f"{base} ({suffix})"
                    suffix += 1
                used_columns.add(candidate.casefold())
                columns.append(candidate)
        raw_rows = raw.get("rows", [])
        if not columns and isinstance(raw_rows, list):
            for row in raw_rows:
                if isinstance(row, Mapping):
                    for key in row:
                        name = str(key).strip()
                        if name and name.casefold() not in used_columns:
                            used_columns.add(name.casefold())
                            columns.append(name)
        columns = columns or ["Tên", "Ghi chú"]
        rows: list[dict[str, Any]] = []
        if isinstance(raw_rows, list):
            for row in raw_rows:
                if isinstance(row, Mapping):
                    rows.append(
                        {column: _clean_cell(row.get(column)) for column in columns}
                    )
        category_id = str(raw.get("category_id", "")).strip()
        if category_id not in category_ids:
            category_id = ""
        niche_ids = raw.get("niche_ids", [])
        pages.append(
            {
                "id": page_id,
                "title": title,
                "slug": str(raw.get("slug", "")).strip()
                or f"{_clean_slug(title)}-{page_id[:6]}",
                "description": str(raw.get("description", "")).strip(),
                "category_id": category_id,
                "published": bool(raw.get("published", False)),
                "columns": columns,
                "rows": rows,
                "niche_ids": list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in niche_ids
                        if str(value).strip()
                    )
                )
                if isinstance(niche_ids, list)
                else [],
                "revision": max(int(raw.get("revision", 1)), 1),
                "created_at": str(raw.get("created_at", _now_text())).strip(),
                "updated_at": str(raw.get("updated_at", _now_text())).strip(),
            }
        )

    content["categories"] = categories
    content["pages"] = pages
    content["updated_at"] = str(payload.get("updated_at", content["updated_at"]))
    return content


class CustomPageStore:
    """Drive-backed store for admin-defined categories and editable pages."""

    def __init__(
        self,
        local_path: Path,
        drive_config: Mapping[str, Any] | None = None,
    ):
        self.local_path = Path(local_path)
        self.drive_config = dict(drive_config or {})
        self.last_warning = ""

    @property
    def uses_google_drive(self) -> bool:
        return bool(self.drive_config)

    def _drive(self) -> GoogleDriveStorage:
        return GoogleDriveStorage(GoogleDriveConfig.from_mapping(self.drive_config))

    def _read_local(self) -> dict[str, Any] | None:
        if not self.local_path.exists():
            return None
        payload = json.loads(self.local_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("File trang tùy chỉnh cục bộ không hợp lệ.")
        return payload

    def _write_local(self, content: Mapping[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(content, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(self.local_path)

    def load(self) -> dict[str, Any]:
        with _CONTENT_LOCK:
            self.last_warning = ""
            if self.uses_google_drive:
                try:
                    payload = self._drive().read_root_json(CUSTOM_PAGES_FILENAME)
                    if payload is not None:
                        content = _normalize_content(payload)
                        self._write_local(content)
                        return content
                except Exception as error:
                    self.last_warning = (
                        f"Không đọc được trang tùy chỉnh từ Google Drive ({error})."
                    )
                    local = self._read_local()
                    if local is not None:
                        return _normalize_content(local)
                    raise RuntimeError(self.last_warning) from error
            return _normalize_content(self._read_local() or default_content())

    def save(self, content: Mapping[str, Any]) -> dict[str, Any]:
        with _CONTENT_LOCK:
            normalized = _normalize_content(content)
            normalized["updated_at"] = _now_text()
            self._write_local(normalized)
            if self.uses_google_drive:
                try:
                    self._drive().upsert_root_json(CUSTOM_PAGES_FILENAME, normalized)
                except Exception as error:
                    raise RuntimeError(
                        "Đã lưu trang tùy chỉnh cục bộ nhưng chưa đồng bộ được lên "
                        f"Google Drive: {error}"
                    ) from error
            return normalized

    def create_category(self, name: str, description: str = "") -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Tên category không được để trống.")
        with _CONTENT_LOCK:
            content = self.load()
            if any(
                item["name"].casefold() == clean_name.casefold()
                for item in content["categories"]
            ):
                raise ValueError("Category này đã tồn tại.")
            now = _now_text()
            category = {
                "id": uuid.uuid4().hex,
                "name": clean_name,
                "slug": _clean_slug(clean_name),
                "description": description.strip(),
                "created_at": now,
                "updated_at": now,
            }
            content["categories"].append(category)
            self.save(content)
            return category

    def update_category(self, category_id: str, name: str, description: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Tên category không được để trống.")
        with _CONTENT_LOCK:
            content = self.load()
            category = next(
                (item for item in content["categories"] if item["id"] == category_id),
                None,
            )
            if category is None:
                raise ValueError("Không tìm thấy category.")
            if any(
                item["id"] != category_id
                and item["name"].casefold() == clean_name.casefold()
                for item in content["categories"]
            ):
                raise ValueError("Category này đã tồn tại.")
            category.update(
                {
                    "name": clean_name,
                    "description": description.strip(),
                    "updated_at": _now_text(),
                }
            )
            self.save(content)

    def delete_category(self, category_id: str) -> None:
        with _CONTENT_LOCK:
            content = self.load()
            remaining = [
                item for item in content["categories"] if item["id"] != category_id
            ]
            if len(remaining) == len(content["categories"]):
                raise ValueError("Không tìm thấy category.")
            content["categories"] = remaining
            for page in content["pages"]:
                if page["category_id"] == category_id:
                    page["category_id"] = ""
                    page["revision"] += 1
                    page["updated_at"] = _now_text()
            self.save(content)

    def create_page(
        self,
        title: str,
        category_id: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Tên page không được để trống.")
        with _CONTENT_LOCK:
            content = self.load()
            if category_id and not any(
                item["id"] == category_id for item in content["categories"]
            ):
                raise ValueError("Category đã chọn không tồn tại.")
            page_id = uuid.uuid4().hex
            now = _now_text()
            page = {
                "id": page_id,
                "title": clean_title,
                "slug": f"{_clean_slug(clean_title)}-{page_id[:6]}",
                "description": description.strip(),
                "category_id": category_id,
                "published": False,
                "columns": ["Tên", "Ghi chú"],
                "rows": [],
                "niche_ids": [],
                "revision": 1,
                "created_at": now,
                "updated_at": now,
            }
            content["pages"].append(page)
            self.save(content)
            return page

    def update_page(
        self,
        page_id: str,
        *,
        title: str,
        description: str,
        category_id: str,
        published: bool,
        columns: list[str],
        rows: list[dict[str, Any]],
        niche_ids: list[str],
    ) -> None:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Tên page không được để trống.")
        with _CONTENT_LOCK:
            content = self.load()
            page = next(
                (item for item in content["pages"] if item["id"] == page_id), None
            )
            if page is None:
                raise ValueError("Không tìm thấy page.")
            if category_id and not any(
                item["id"] == category_id for item in content["categories"]
            ):
                raise ValueError("Category đã chọn không tồn tại.")
            clean_columns, clean_rows = records_from_frame(
                pd.DataFrame(rows, columns=columns or ["Tên", "Ghi chú"])
            )
            page.update(
                {
                    "title": clean_title,
                    "description": description.strip(),
                    "category_id": category_id,
                    "published": bool(published),
                    "columns": clean_columns or ["Tên", "Ghi chú"],
                    "rows": clean_rows,
                    "niche_ids": list(dict.fromkeys(niche_ids)),
                    "revision": int(page.get("revision", 1)) + 1,
                    "updated_at": _now_text(),
                }
            )
            self.save(content)

    def delete_page(self, page_id: str) -> None:
        with _CONTENT_LOCK:
            content = self.load()
            remaining = [item for item in content["pages"] if item["id"] != page_id]
            if len(remaining) == len(content["pages"]):
                raise ValueError("Không tìm thấy page.")
            content["pages"] = remaining
            self.save(content)

