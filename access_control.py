from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from cloud_storage import GoogleDriveConfig, GoogleDriveStorage


ACCESS_CONTROL_FILENAME = "access_control.json"
PASSWORD_ITERATIONS = 240_000
APP_TIMEZONE = ZoneInfo("Asia/Bangkok")
_POLICY_LOCK = threading.RLock()


def _now() -> datetime:
    return datetime.now(APP_TIMEZONE)


def _today_key() -> str:
    return _now().date().isoformat()


def default_policy() -> dict[str, Any]:
    return {
        "version": 1,
        "scraper_enabled": False,
        "daily_run_limit": 3,
        "max_keywords_per_run": 10,
        "max_pages_per_niche": 3,
        "max_products_per_niche": 100,
        "users": [],
        "updated_at": _now().isoformat(timespec="seconds"),
    }


def _normalize_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    policy = default_policy()
    policy["scraper_enabled"] = bool(payload.get("scraper_enabled", False))
    policy["daily_run_limit"] = max(int(payload.get("daily_run_limit", 3)), 1)
    policy["max_keywords_per_run"] = max(
        int(payload.get("max_keywords_per_run", 10)), 1
    )
    policy["max_pages_per_niche"] = max(
        int(payload.get("max_pages_per_niche", 3)), 1
    )
    policy["max_products_per_niche"] = max(
        int(payload.get("max_products_per_niche", 100)), 1
    )
    policy["updated_at"] = str(payload.get("updated_at", policy["updated_at"]))
    users: list[dict[str, Any]] = []
    for raw_user in payload.get("users", []):
        if not isinstance(raw_user, Mapping):
            continue
        user_id = str(raw_user.get("id", "")).strip()
        name = str(raw_user.get("name", "")).strip()
        salt = str(raw_user.get("salt", "")).strip()
        code_hash = str(raw_user.get("code_hash", "")).strip()
        if not all((user_id, name, salt, code_hash)):
            continue
        usage = raw_user.get("usage", {})
        clean_usage = (
            {
                str(day): max(int(count), 0)
                for day, count in usage.items()
            }
            if isinstance(usage, Mapping)
            else {}
        )
        users.append(
            {
                "id": user_id,
                "name": name,
                "salt": salt,
                "code_hash": code_hash,
                "enabled": bool(raw_user.get("enabled", True)),
                "usage": clean_usage,
                "created_at": str(
                    raw_user.get("created_at", _now().isoformat(timespec="seconds"))
                ),
            }
        )
    policy["users"] = users
    return policy


def _hash_code(code: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        code.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PASSWORD_ITERATIONS,
    ).hex()


class AccessControlStore:
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
            raise ValueError("File phân quyền cục bộ không hợp lệ.")
        return payload

    def _write_local(self, policy: Mapping[str, Any]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.local_path)

    def load(self) -> dict[str, Any]:
        with _POLICY_LOCK:
            self.last_warning = ""
            if self.uses_google_drive:
                try:
                    payload = self._drive().read_root_json(ACCESS_CONTROL_FILENAME)
                    if payload is not None:
                        policy = _normalize_policy(payload)
                        self._write_local(policy)
                        return policy
                except Exception as error:
                    self.last_warning = (
                        f"Không đọc được phân quyền từ Google Drive ({error})."
                    )
                    local_payload = self._read_local()
                    if local_payload is not None:
                        return _normalize_policy(local_payload)
                    raise RuntimeError(self.last_warning) from error

            local_payload = self._read_local()
            return _normalize_policy(local_payload or default_policy())

    def save(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        with _POLICY_LOCK:
            normalized = _normalize_policy(policy)
            normalized["updated_at"] = _now().isoformat(timespec="seconds")
            self._write_local(normalized)
            if self.uses_google_drive:
                try:
                    self._drive().upsert_root_json(
                        ACCESS_CONTROL_FILENAME, normalized
                    )
                except Exception as error:
                    raise RuntimeError(
                        "Đã lưu bản cục bộ nhưng chưa đồng bộ được phân quyền lên "
                        f"Google Drive: {error}"
                    ) from error
            return normalized

    def authenticate(self, code: str) -> dict[str, str] | None:
        candidate = code.strip()
        if not candidate:
            return None
        policy = self.load()
        for user in policy["users"]:
            candidate_hash = _hash_code(candidate, user["salt"])
            if hmac.compare_digest(candidate_hash, user["code_hash"]):
                if not user["enabled"]:
                    return None
                return {"id": user["id"], "name": user["name"]}
        return None

    def get_enabled_user(self, user_id: str) -> dict[str, Any] | None:
        policy = self.load()
        return next(
            (
                user
                for user in policy["users"]
                if user["id"] == user_id and user["enabled"]
            ),
            None,
        )

    def add_user(self, name: str, code: str) -> dict[str, Any]:
        clean_name = name.strip()
        clean_code = code.strip()
        if not clean_name:
            raise ValueError("Tên người dùng không được để trống.")
        if len(clean_code) < 8:
            raise ValueError("Mã truy cập phải có ít nhất 8 ký tự.")
        with _POLICY_LOCK:
            policy = self.load()
            if any(
                user["name"].casefold() == clean_name.casefold()
                for user in policy["users"]
            ):
                raise ValueError("Tên người dùng đã tồn tại.")
            salt = secrets.token_hex(16)
            user = {
                "id": uuid.uuid4().hex,
                "name": clean_name,
                "salt": salt,
                "code_hash": _hash_code(clean_code, salt),
                "enabled": True,
                "usage": {},
                "created_at": _now().isoformat(timespec="seconds"),
            }
            policy["users"].append(user)
            self.save(policy)
            return {"id": user["id"], "name": user["name"]}

    def update_settings(
        self,
        *,
        scraper_enabled: bool,
        daily_run_limit: int,
        max_keywords_per_run: int,
        max_pages_per_niche: int,
        max_products_per_niche: int,
    ) -> dict[str, Any]:
        with _POLICY_LOCK:
            policy = self.load()
            policy["scraper_enabled"] = bool(scraper_enabled)
            policy["daily_run_limit"] = max(int(daily_run_limit), 1)
            policy["max_keywords_per_run"] = max(int(max_keywords_per_run), 1)
            policy["max_pages_per_niche"] = max(int(max_pages_per_niche), 1)
            policy["max_products_per_niche"] = max(
                int(max_products_per_niche), 1
            )
            return self.save(policy)

    def set_user_enabled(self, user_id: str, enabled: bool) -> None:
        with _POLICY_LOCK:
            policy = self.load()
            user = next(
                (item for item in policy["users"] if item["id"] == user_id), None
            )
            if user is None:
                raise ValueError("Không tìm thấy người dùng.")
            user["enabled"] = bool(enabled)
            self.save(policy)

    def delete_user(self, user_id: str) -> None:
        with _POLICY_LOCK:
            policy = self.load()
            remaining = [
                user for user in policy["users"] if user["id"] != user_id
            ]
            if len(remaining) == len(policy["users"]):
                raise ValueError("Không tìm thấy người dùng.")
            policy["users"] = remaining
            self.save(policy)

    def reset_today(self, user_id: str) -> None:
        with _POLICY_LOCK:
            policy = self.load()
            user = next(
                (item for item in policy["users"] if item["id"] == user_id), None
            )
            if user is None:
                raise ValueError("Không tìm thấy người dùng.")
            user["usage"].pop(_today_key(), None)
            self.save(policy)

    def reserve_run(
        self,
        user_id: str,
        keyword_count: int,
        max_pages: int,
        max_products: int,
    ) -> tuple[bool, str]:
        with _POLICY_LOCK:
            policy = self.load()
            if not policy["scraper_enabled"]:
                return False, "Admin đang tạm khóa chức năng cào sản phẩm."
            user = next(
                (
                    item
                    for item in policy["users"]
                    if item["id"] == user_id and item["enabled"]
                ),
                None,
            )
            if user is None:
                return False, "Mã truy cập đã bị khóa hoặc bị xóa."
            if keyword_count > policy["max_keywords_per_run"]:
                return (
                    False,
                    "Phiên này có quá nhiều ngách. Giới hạn hiện tại là "
                    f"{policy['max_keywords_per_run']} ngách/lượt.",
                )
            if max_pages > policy["max_pages_per_niche"]:
                return (
                    False,
                    "Số trang/ngách vượt giới hạn admin: "
                    f"{policy['max_pages_per_niche']}.",
                )
            if max_products > policy["max_products_per_niche"]:
                return (
                    False,
                    "Số sản phẩm/ngách vượt giới hạn admin: "
                    f"{policy['max_products_per_niche']}.",
                )
            day = _today_key()
            used = int(user["usage"].get(day, 0))
            if used >= policy["daily_run_limit"]:
                return (
                    False,
                    "Bạn đã dùng hết "
                    f"{policy['daily_run_limit']} lượt cào trong ngày hôm nay.",
                )
            user["usage"] = {day: used + 1}
            self.save(policy)
            remaining = policy["daily_run_limit"] - used - 1
            return True, f"Đã ghi nhận lượt chạy; còn {remaining} lượt hôm nay."

    @staticmethod
    def user_rows(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
        day = _today_key()
        return [
            {
                "id": user["id"],
                "Tên": user["name"],
                "Trạng thái": "Đang hoạt động" if user["enabled"] else "Đã khóa",
                "Lượt hôm nay": int(user["usage"].get(day, 0)),
                "Ngày tạo": user["created_at"],
            }
            for user in policy["users"]
        ]
