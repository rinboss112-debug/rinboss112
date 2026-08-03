from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from cloud_storage import GoogleDriveConfig, GoogleDriveStorage


TEMU_US_API_URL = "https://openapi-b-us.temu.com/openapi/router"
TEMU_NOTES_FILENAME = "temu_order_notes.json"
ORDER_LIST_API = "bg.order.list.v2.get"
UNSHIPPED_PACKAGES_API = "bg.order.unshipped.package.get"
SHIPPING_DOCUMENT_API = "bg.logistics.shipment.document.get"
LABEL_LIST_API = "temu.logistics.label.list.get"

ORDER_STATUS_LABELS = {
    0: "Tất cả",
    1: "Chờ xác nhận",
    2: "Chờ gửi hàng",
    3: "Đã hủy",
    4: "Đã gửi hàng",
    5: "Đã nhận hàng",
    41: "Đã gửi một phần",
    51: "Đã nhận một phần",
}
SHIPPED_STATUS_CODES = {4, 5, 41, 51}
FINISHED_STATUS_CODES = {3, 4, 5, 41, 51}
_NOTES_LOCK = threading.RLock()


class TemuAPIError(RuntimeError):
    """Safe error raised for Temu Open API failures."""


@dataclass(frozen=True, slots=True)
class TemuAPIConfig:
    app_key: str
    app_secret: str
    access_token: str
    endpoint: str = TEMU_US_API_URL
    display_timezone: str = "America/Los_Angeles"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "TemuAPIConfig":
        config = cls(
            app_key=str(values.get("app_key", "")).strip(),
            app_secret=str(values.get("app_secret", "")).strip(),
            access_token=str(values.get("access_token", "")).strip(),
            endpoint=str(values.get("endpoint", TEMU_US_API_URL)).strip()
            or TEMU_US_API_URL,
            display_timezone=str(
                values.get("display_timezone", "America/Los_Angeles")
            ).strip()
            or "America/Los_Angeles",
        )
        missing = [
            name
            for name in ("app_key", "app_secret", "access_token")
            if not getattr(config, name)
        ]
        if missing:
            raise ValueError("Thiếu cấu hình Temu: " + ", ".join(missing))
        parsed = urlparse(config.endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Endpoint Temu phải là URL HTTPS hợp lệ.")
        try:
            ZoneInfo(config.display_timezone)
        except Exception as error:
            raise ValueError("Múi giờ hiển thị Temu không hợp lệ.") from error
        return config


def _signature_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, bool)):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    return str(value)


def sign_temu_parameters(parameters: Mapping[str, Any], app_secret: str) -> str:
    """Create the uppercase MD5 signature required by Temu Open API."""
    clean = {
        str(key): value
        for key, value in parameters.items()
        if key != "sign" and value is not None
    }
    middle = "".join(
        f"{key}{_signature_value(clean[key])}" for key in sorted(clean)
    )
    raw = f"{app_secret}{middle}{app_secret}".encode("utf-8")
    return hashlib.md5(raw).hexdigest().upper()


class TemuOpenAPIClient:
    def __init__(
        self,
        config: TemuAPIConfig,
        *,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ):
        self.config = config
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "RinBoss-Commerce/1.0",
            }
        )

    def build_payload(
        self,
        api_name: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            str(key): value
            for key, value in dict(parameters or {}).items()
            if value is not None
        }
        payload.update(
            {
                "type": api_name,
                "app_key": self.config.app_key,
                "access_token": self.config.access_token,
                "timestamp": int(timestamp if timestamp is not None else time.time()),
                "data_type": "JSON",
            }
        )
        payload["sign"] = sign_temu_parameters(payload, self.config.app_secret)
        return payload

    def call(self, api_name: str, parameters: Mapping[str, Any] | None = None) -> Any:
        payload = self.build_payload(api_name, parameters)
        try:
            response = self.session.post(
                self.config.endpoint,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as error:
            raise TemuAPIError(f"Không kết nối được Temu Open API: {error}") from error
        except ValueError as error:
            raise TemuAPIError("Temu trả dữ liệu không phải JSON hợp lệ.") from error

        if not isinstance(body, Mapping):
            raise TemuAPIError("Temu trả cấu trúc dữ liệu không hợp lệ.")
        if not bool(body.get("success", False)):
            error_code = body.get("errorCode", body.get("error_code", "không rõ"))
            error_message = body.get("errorMsg", body.get("error_msg", "Lỗi Temu"))
            raise TemuAPIError(f"Temu API {error_code}: {error_message}")
        return body.get("result", {})

    def list_orders(
        self,
        *,
        create_after: int,
        create_before: int,
        status_code: int = 0,
        order_labels: Iterable[str] = (),
        page_size: int = 100,
        max_orders: int = 1000,
    ) -> list[dict[str, Any]]:
        page_size = min(max(int(page_size), 1), 100)
        max_orders = min(max(int(max_orders), 1), 5000)
        records: list[dict[str, Any]] = []
        page_number = 1
        while len(records) < max_orders:
            params: dict[str, Any] = {
                "pageNumber": page_number,
                "pageSize": min(page_size, max_orders - len(records)),
                "parentOrderStatus": int(status_code),
                "createAfter": int(create_after),
                "createBefore": int(create_before),
                "regionId": 211,
                "sortby": "createTime",
            }
            labels = [str(value).strip() for value in order_labels if str(value).strip()]
            if labels:
                params["parentOrderLabel"] = labels
            result = self.call(ORDER_LIST_API, params)
            if not isinstance(result, Mapping):
                raise TemuAPIError("API danh sách đơn không trả về object kết quả.")
            page_items = result.get("pageItems", [])
            if not isinstance(page_items, list):
                raise TemuAPIError("API danh sách đơn không trả về pageItems hợp lệ.")
            records.extend(item for item in page_items if isinstance(item, Mapping))
            total = _as_int(result.get("totalItemNum"), len(records))
            if not page_items or len(records) >= total:
                break
            page_number += 1
        return records[:max_orders]

    def get_unshipped_packages(
        self,
        *,
        parent_order_sn: str,
        order_sns: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "pageNumber": 1,
            "pageSize": 100,
            "parentOrderSnList": [parent_order_sn],
        }
        children = [str(value).strip() for value in order_sns if str(value).strip()]
        if children:
            params["orderSnList"] = children[:20]
        result = self.call(UNSHIPPED_PACKAGES_API, params)
        if not isinstance(result, Mapping):
            return []
        packages = result.get("unshippedPackage", [])
        return [dict(item) for item in packages if isinstance(item, Mapping)]

    def get_shipping_documents(
        self,
        package_sns: Iterable[str],
        *,
        document_type: str = "SHIPPING_LABEL_PDF",
    ) -> list[dict[str, str]]:
        package_list = list(
            dict.fromkeys(str(value).strip() for value in package_sns if str(value).strip())
        )
        if not package_list:
            return []
        result = self.call(
            SHIPPING_DOCUMENT_API,
            {
                "documentType": document_type,
                "packageSnList": package_list[:100],
            },
        )
        if not isinstance(result, Mapping):
            return []
        rows = result.get("shippingLabelUrlList", [])
        documents: list[dict[str, str]] = []
        for item in rows if isinstance(rows, list) else []:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url", "")).strip()
            if urlparse(url).scheme != "https":
                continue
            documents.append(
                {
                    "package_sn": str(item.get("packageSn", "")).strip(),
                    "document_type": str(item.get("documentType", "")).strip(),
                    "url": url,
                }
            )
        return documents

    def get_label_packages(self, parent_order_sn: str) -> list[dict[str, Any]]:
        """Return Temu-shipping packages, including previously printed/shipped labels."""
        result = self.call(
            LABEL_LIST_API,
            {
                "pageNumber": 1,
                "pageSize": 100,
                "parentOrderSnList": [parent_order_sn],
            },
        )
        if not isinstance(result, Mapping):
            return []
        packages = result.get("shippingLabelInfoList", [])
        return [dict(item) for item in packages if isinstance(item, Mapping)]

    def get_order_packages(
        self,
        *,
        parent_order_sn: str,
        order_sns: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        packages = self.get_unshipped_packages(
            parent_order_sn=parent_order_sn,
            order_sns=order_sns,
        )
        if packages:
            return packages
        return self.get_label_packages(parent_order_sn)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _timestamp_to_datetime(value: Any, timezone_name: str) -> datetime | None:
    timestamp = _as_int(value)
    if timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).astimezone(
            ZoneInfo(timezone_name)
        )
    except (OverflowError, OSError, ValueError):
        return None


def _label_names(value: Any) -> list[str]:
    labels: list[str] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            name = str(item.get("name", "")).strip()
            if name:
                labels.append(name)
        elif str(item).strip():
            labels.append(str(item).strip())
    return labels


def classify_deadline(
    status_code: int,
    deadline: datetime | None,
    labels: Iterable[str] = (),
    *,
    now: datetime | None = None,
) -> str:
    if status_code == 3:
        return "Đã hủy"
    if status_code in SHIPPED_STATUS_CODES:
        return "Đã giao đi"
    normalized = {str(value).strip().casefold() for value in labels}
    if "past_due" in normalized:
        return "Quá hạn"
    if "soon_to_be_overdue" in normalized:
        return "Sắp trễ"
    if deadline is None:
        return "Chưa có hạn gửi"
    current = now or datetime.now(deadline.tzinfo or timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=deadline.tzinfo or timezone.utc)
    remaining = (deadline - current).total_seconds()
    if remaining < 0:
        return "Quá hạn"
    if remaining <= 24 * 60 * 60:
        return "Sắp trễ"
    return "Đúng hạn"


def shipping_progress(status_code: int, abnormalities: Iterable[str] = ()) -> str:
    abnormal = [str(value).strip() for value in abnormalities if str(value).strip()]
    if abnormal:
        return "Bất thường: " + ", ".join(dict.fromkeys(abnormal))
    return {
        1: "Chưa sẵn sàng gửi",
        2: "Chưa giao đơn vị vận chuyển",
        3: "Đơn đã hủy",
        4: "Đã giao đơn vị vận chuyển",
        5: "Khách đã nhận",
        41: "Đã giao một phần",
        51: "Khách đã nhận một phần",
    }.get(status_code, "Chưa xác định")


def normalize_order_items(
    page_items: Iterable[Mapping[str, Any]],
    *,
    timezone_name: str = "America/Los_Angeles",
    notes: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    note_map = dict(notes or {})
    rows: list[dict[str, Any]] = []
    for raw_item in page_items:
        parent = raw_item.get("parentOrderMap", {})
        if not isinstance(parent, Mapping):
            parent = {}
        children = [
            item
            for item in _as_list(raw_item.get("orderList", []))
            if isinstance(item, Mapping)
        ]
        parent_sn = str(parent.get("parentOrderSn", "")).strip()
        status_code = _as_int(parent.get("parentOrderStatus"))
        deadline = _timestamp_to_datetime(
            parent.get("expectShipLatestTime"), timezone_name
        )
        labels = _label_names(parent.get("parentOrderLabel"))
        product_names = list(
            dict.fromkeys(
                str(item.get("goodsName") or item.get("originalGoodsName") or "").strip()
                for item in children
                if str(item.get("goodsName") or item.get("originalGoodsName") or "").strip()
            )
        )
        specs = list(
            dict.fromkeys(
                str(item.get("spec") or item.get("originalSpecName") or "").strip()
                for item in children
                if str(item.get("spec") or item.get("originalSpecName") or "").strip()
            )
        )
        abnormalities: list[str] = []
        fulfillment_types: list[str] = []
        warnings: list[str] = [
            str(value).strip()
            for value in _as_list(parent.get("fulfillmentWarning"))
            if str(value).strip()
        ]
        for child in children:
            abnormalities.extend(
                str(value).strip()
                for value in _as_list(child.get("packageAbnormalTypeList"))
                if str(value).strip()
            )
            fulfillment = str(child.get("fulfillmentType", "")).strip()
            if fulfillment:
                fulfillment_types.append(fulfillment)
            warnings.extend(
                str(value).strip()
                for value in _as_list(child.get("fulfillmentWarning"))
                if str(value).strip()
            )
        order_sns = [
            str(item.get("orderSn", "")).strip()
            for item in children
            if str(item.get("orderSn", "")).strip()
        ]
        image_url = next(
            (
                str(item.get("thumbUrl", "")).strip()
                for item in children
                if str(item.get("thumbUrl", "")).strip()
            ),
            "",
        )
        rows.append(
            {
                "parent_order_sn": parent_sn,
                "status_code": status_code,
                "status": ORDER_STATUS_LABELS.get(status_code, f"Mã {status_code}"),
                "shipping_progress": shipping_progress(status_code, abnormalities),
                "deadline_state": classify_deadline(
                    status_code, deadline, labels, now=now
                ),
                "ship_deadline": deadline,
                "order_time": _timestamp_to_datetime(
                    parent.get("parentOrderTime"), timezone_name
                ),
                "confirm_time": _timestamp_to_datetime(
                    parent.get("parentConfirmTime"), timezone_name
                ),
                "shipping_time": _timestamp_to_datetime(
                    parent.get("parentShippingTime"), timezone_name
                ),
                "products": " | ".join(product_names),
                "variants": " | ".join(specs),
                "quantity": sum(_as_int(item.get("quantity")) for item in children),
                "fulfillment_type": " | ".join(dict.fromkeys(fulfillment_types)),
                "order_labels": " | ".join(labels),
                "warnings": " | ".join(dict.fromkeys(warnings)),
                "abnormalities": " | ".join(dict.fromkeys(abnormalities)),
                "order_sns": order_sns,
                "image_url": image_url,
                "note": str(note_map.get(parent_sn, "")),
                "raw": dict(raw_item),
            }
        )
    return rows


def default_notes() -> dict[str, Any]:
    return {"version": 1, "notes": {}, "updated_at": ""}


def _normalize_notes(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_notes = payload.get("notes", {})
    notes = {
        str(key).strip(): str(value).strip()
        for key, value in (raw_notes.items() if isinstance(raw_notes, Mapping) else [])
        if str(key).strip() and str(value).strip()
    }
    return {
        "version": 1,
        "notes": notes,
        "updated_at": str(payload.get("updated_at", "")),
    }


class TemuOrderNoteStore:
    """Persist internal seller notes locally and optionally in Google Drive."""

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
        return payload if isinstance(payload, dict) else None

    def _write_local(self, payload: Mapping[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.local_path)

    def load(self) -> dict[str, Any]:
        with _NOTES_LOCK:
            self.last_warning = ""
            if self.uses_google_drive:
                try:
                    remote = self._drive().read_root_json(TEMU_NOTES_FILENAME)
                    if remote is not None:
                        normalized = _normalize_notes(remote)
                        self._write_local(normalized)
                        return normalized
                except Exception as error:
                    self.last_warning = (
                        f"Không đọc được ghi chú Temu từ Google Drive ({error})."
                    )
            return _normalize_notes(self._read_local() or default_notes())

    def save_note(self, parent_order_sn: str, note: str) -> dict[str, Any]:
        clean_order_sn = parent_order_sn.strip()
        if not clean_order_sn:
            raise ValueError("Mã đơn Temu không hợp lệ.")
        with _NOTES_LOCK:
            payload = self.load()
            if note.strip():
                payload["notes"][clean_order_sn] = note.strip()
            else:
                payload["notes"].pop(clean_order_sn, None)
            payload["updated_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            self._write_local(payload)
            if self.uses_google_drive:
                try:
                    self._drive().upsert_root_json(TEMU_NOTES_FILENAME, payload)
                except Exception as error:
                    raise RuntimeError(
                        "Đã lưu ghi chú cục bộ nhưng chưa đồng bộ được lên Google Drive: "
                        f"{error}"
                    ) from error
            return payload
