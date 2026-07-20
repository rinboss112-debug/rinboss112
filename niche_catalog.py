from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from amazon_scraper import aggregate_csv_filename, slugify_filename
from cloud_storage import GoogleDriveConfig, GoogleDriveStorage


CATALOG_FILENAME = "niche_catalog.json"
APP_TIMEZONE = ZoneInfo("Asia/Bangkok")
_CATALOG_LOCK = threading.RLock()


def _now_text() -> str:
    return datetime.now(APP_TIMEZONE).isoformat(timespec="seconds")


def default_catalog() -> dict[str, Any]:
    return {"version": 1, "items": [], "updated_at": _now_text()}


def _normalize_catalog(payload: Mapping[str, Any]) -> dict[str, Any]:
    catalog = default_catalog()
    items: list[dict[str, Any]] = []
    for raw in payload.get("items", []):
        if not isinstance(raw, Mapping):
            continue
        keyword = str(raw.get("keyword", "")).strip()
        if not keyword:
            continue
        last_run_id = str(raw.get("last_run_id", "")).strip()
        raw_run_ids = raw.get("run_ids", [])
        run_ids = list(
            dict.fromkeys(
                str(value).strip()
                for value in raw_run_ids
                if str(value).strip()
            )
        ) if isinstance(raw_run_ids, list) else []
        if last_run_id and last_run_id not in run_ids:
            run_ids.append(last_run_id)
        items.append(
            {
                "id": str(raw.get("id", "")).strip() or uuid.uuid4().hex,
                "keyword": keyword,
                "published": bool(raw.get("published", False)),
                "product_count": max(int(raw.get("product_count", 0)), 0),
                "run_count": max(int(raw.get("run_count", 1)), len(run_ids), 1),
                "run_ids": run_ids,
                "last_run_id": last_run_id,
                "last_scraped_at": str(raw.get("last_scraped_at", "")).strip(),
                "requested_by": str(raw.get("requested_by", "")).strip(),
                "drive_folder_url": str(raw.get("drive_folder_url", "")).strip(),
                "niche_filename": str(
                    raw.get("niche_filename", f"{slugify_filename(keyword)}.csv")
                ).strip(),
                "aggregate_filename": str(raw.get("aggregate_filename", "")).strip(),
                "created_at": str(raw.get("created_at", _now_text())).strip(),
            }
        )
    catalog["items"] = items
    catalog["updated_at"] = str(payload.get("updated_at", catalog["updated_at"]))
    return catalog


class NicheCatalogStore:
    """Drive-backed catalog of scraped niches and their publication state."""

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
            raise ValueError("File danh mục ngách cục bộ không hợp lệ.")
        return payload

    def _write_local(self, catalog: Mapping[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.local_path)

    def load(self) -> dict[str, Any]:
        with _CATALOG_LOCK:
            self.last_warning = ""
            if self.uses_google_drive:
                try:
                    payload = self._drive().read_root_json(CATALOG_FILENAME)
                    if payload is not None:
                        catalog = _normalize_catalog(payload)
                        self._write_local(catalog)
                        return catalog
                except Exception as error:
                    self.last_warning = f"Không đọc được danh mục ngách từ Drive ({error})."
                    local = self._read_local()
                    if local is not None:
                        return _normalize_catalog(local)
                    raise RuntimeError(self.last_warning) from error

            return _normalize_catalog(self._read_local() or default_catalog())

    def save(self, catalog: Mapping[str, Any]) -> dict[str, Any]:
        with _CATALOG_LOCK:
            normalized = _normalize_catalog(catalog)
            normalized["updated_at"] = _now_text()
            self._write_local(normalized)
            if self.uses_google_drive:
                try:
                    self._drive().upsert_root_json(CATALOG_FILENAME, normalized)
                except Exception as error:
                    raise RuntimeError(
                        "Đã lưu danh mục cục bộ nhưng chưa đồng bộ được lên Google Drive: "
                        f"{error}"
                    ) from error
            return normalized

    def register_run(
        self,
        *,
        run_id: str,
        keywords: list[str],
        niche_counts: Mapping[str, int],
        failed_keywords: list[str],
        requested_by: str,
        drive_folder_url: str,
        aggregate_filename: str,
        scraped_at: str = "",
    ) -> None:
        with _CATALOG_LOCK:
            catalog = self.load()
            self._register_run_into(
                catalog,
                run_id=run_id,
                keywords=keywords,
                niche_counts=niche_counts,
                failed_keywords=failed_keywords,
                requested_by=requested_by,
                drive_folder_url=drive_folder_url,
                aggregate_filename=aggregate_filename,
                scraped_at=scraped_at or _now_text(),
            )
            self.save(catalog)

    @staticmethod
    def _register_run_into(
        catalog: dict[str, Any],
        *,
        run_id: str,
        keywords: list[str],
        niche_counts: Mapping[str, int],
        failed_keywords: list[str],
        requested_by: str,
        drive_folder_url: str,
        aggregate_filename: str,
        scraped_at: str,
    ) -> int:
        failed = {value.casefold() for value in failed_keywords}
        by_keyword = {
            item["keyword"].casefold(): item for item in catalog["items"]
        }
        added_niches = 0
        for keyword in keywords:
            clean_keyword = str(keyword).strip()
            key = clean_keyword.casefold()
            if not clean_keyword or key in failed:
                continue
            item = by_keyword.get(key)
            if item is None:
                item = {
                    "id": uuid.uuid4().hex,
                    "keyword": clean_keyword,
                    "published": False,
                    "product_count": 0,
                    "run_count": 0,
                    "run_ids": [],
                    "created_at": scraped_at,
                }
                catalog["items"].append(item)
                by_keyword[key] = item
                added_niches += 1

            run_ids = item.setdefault("run_ids", [])
            is_new_run = bool(run_id) and run_id not in run_ids
            if is_new_run:
                run_ids.append(run_id)
                item["run_count"] = max(
                    int(item.get("run_count", 0)) + 1,
                    len(run_ids),
                )
            if not item.get("last_scraped_at") or scraped_at >= str(
                item.get("last_scraped_at", "")
            ):
                item.update(
                    {
                        "keyword": clean_keyword,
                        "product_count": max(int(niche_counts.get(clean_keyword, 0)), 0),
                        "last_run_id": run_id,
                        "last_scraped_at": scraped_at,
                        "requested_by": requested_by,
                        "drive_folder_url": drive_folder_url,
                        "niche_filename": f"{slugify_filename(clean_keyword)}.csv",
                        "aggregate_filename": aggregate_filename,
                    }
                )
        return added_niches

    def import_drive_history(self) -> tuple[int, int]:
        """Import old Drive run manifests without duplicating already-known runs."""
        if not self.uses_google_drive:
            raise RuntimeError("Google Drive chưa được cấu hình.")
        records = self._drive().list_run_manifests()
        with _CATALOG_LOCK:
            catalog = self.load()
            added_niches = 0
            for record in records:
                manifest = record.get("manifest", {})
                if not isinstance(manifest, Mapping):
                    continue
                keywords = [
                    str(value).strip()
                    for value in manifest.get("keywords", [])
                    if str(value).strip()
                ]
                if not keywords:
                    continue
                settings = manifest.get("settings", {})
                settings = settings if isinstance(settings, Mapping) else {}
                aggregate_name = str(manifest.get("aggregate_filename", "")).strip()
                added_niches += self._register_run_into(
                    catalog,
                    run_id=str(manifest.get("run_id", "")).strip(),
                    keywords=keywords,
                    niche_counts=(
                        manifest.get("niche_counts", {})
                        if isinstance(manifest.get("niche_counts", {}), Mapping)
                        else {}
                    ),
                    failed_keywords=[
                        str(value) for value in manifest.get("failed_keywords", [])
                    ],
                    requested_by=str(settings.get("requested_by", "")).strip(),
                    drive_folder_url=str(record.get("folder_url", "")).strip(),
                    aggregate_filename=(
                        aggregate_name or aggregate_csv_filename(keywords[0])
                    ),
                    scraped_at=str(
                        manifest.get("finished_at")
                        or manifest.get("started_at")
                        or _now_text()
                    ),
                )
            self.save(catalog)
        return len(records), added_niches

    def set_published(self, item_id: str, published: bool) -> None:
        with _CATALOG_LOCK:
            catalog = self.load()
            item = next(
                (value for value in catalog["items"] if value["id"] == item_id), None
            )
            if item is None:
                raise ValueError("Không tìm thấy ngách.")
            item["published"] = bool(published)
            self.save(catalog)

    def delete_item(self, item_id: str) -> None:
        with _CATALOG_LOCK:
            catalog = self.load()
            remaining = [item for item in catalog["items"] if item["id"] != item_id]
            if len(remaining) == len(catalog["items"]):
                raise ValueError("Không tìm thấy ngách.")
            catalog["items"] = remaining
            self.save(catalog)

    @staticmethod
    def admin_rows(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
        items = sorted(
            catalog.get("items", []),
            key=lambda item: str(item.get("last_scraped_at", "")),
            reverse=True,
        )
        return [
            {
                "id": item["id"],
                "Ngách": item["keyword"],
                "Trạng thái": "Đã công khai" if item["published"] else "Chờ duyệt",
                "Sản phẩm": item["product_count"],
                "Số lần cào": item["run_count"],
                "Lần cào gần nhất": item["last_scraped_at"],
                "Người cào": item["requested_by"] or "Không xác định",
                "Google Drive": item["drive_folder_url"],
            }
            for item in items
        ]

    @staticmethod
    def public_rows(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "Ngách": item["keyword"],
                "Sản phẩm": item["product_count"],
                "Cập nhật": item["last_scraped_at"],
                "Google Drive": item["drive_folder_url"],
            }
            for item in sorted(
                catalog.get("items", []),
                key=lambda value: str(value.get("last_scraped_at", "")),
                reverse=True,
            )
            if item.get("published", False)
        ]
