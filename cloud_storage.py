from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleDriveConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GoogleDriveConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    folder_name: str = "Amazon Product Scraper"
    root_folder_id: str = ""

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "GoogleDriveConfig":
        config = cls(
            client_id=str(values.get("client_id", "")).strip(),
            client_secret=str(values.get("client_secret", "")).strip(),
            refresh_token=str(values.get("refresh_token", "")).strip(),
            folder_name=str(
                values.get("folder_name", "Amazon Product Scraper")
            ).strip()
            or "Amazon Product Scraper",
            root_folder_id=str(values.get("root_folder_id", "")).strip(),
        )
        missing = [
            name
            for name in ("client_id", "client_secret", "refresh_token")
            if not getattr(config, name)
        ]
        if missing:
            raise GoogleDriveConfigurationError(
                "Thiếu cấu hình Google Drive: " + ", ".join(missing)
            )
        return config


class GoogleDriveStorage:
    """Small Drive API wrapper for one app-owned folder and its run folders."""

    def __init__(self, config: GoogleDriveConfig):
        self.config = config
        self._service: Any | None = None
        self.root_folder_id = config.root_folder_id
        self.run_folder_id = ""
        self.run_folder_url = ""
        self._uploaded_file_ids: dict[str, str] = {}

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as error:
            raise RuntimeError(
                "Thiếu thư viện Google Drive. Hãy cài lại requirements.txt."
            ) from error

        credentials = Credentials(
            token=None,
            refresh_token=self.config.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            scopes=[DRIVE_FILE_SCOPE],
        )
        credentials.refresh(Request())
        self._service = build(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )
        return self._service

    @staticmethod
    def _escape_query(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _find_folder(self, name: str, parent_id: str | None = None) -> str:
        service = self._get_service()
        clauses = [
            f"name = '{self._escape_query(name)}'",
            f"mimeType = '{DRIVE_FOLDER_MIME}'",
            "trashed = false",
        ]
        if parent_id:
            clauses.append(f"'{parent_id}' in parents")
        response = (
            service.files()
            .list(
                q=" and ".join(clauses),
                spaces="drive",
                fields="files(id,name,createdTime)",
                pageSize=10,
            )
            .execute(num_retries=3)
        )
        files = response.get("files", [])
        return str(files[0]["id"]) if files else ""

    def _create_folder(self, name: str, parent_id: str | None = None) -> str:
        metadata: dict[str, Any] = {"name": name, "mimeType": DRIVE_FOLDER_MIME}
        if parent_id:
            metadata["parents"] = [parent_id]
        folder = (
            self._get_service()
            .files()
            .create(body=metadata, fields="id,webViewLink")
            .execute(num_retries=3)
        )
        return str(folder["id"])

    def ensure_root_folder(self) -> str:
        if self.root_folder_id:
            self._get_service().files().get(
                fileId=self.root_folder_id, fields="id,name,mimeType"
            ).execute(num_retries=3)
            return self.root_folder_id
        folder_id = self._find_folder(self.config.folder_name)
        if not folder_id:
            folder_id = self._create_folder(self.config.folder_name)
        self.root_folder_id = folder_id
        return folder_id

    def check_connection(self) -> str:
        folder_id = self.ensure_root_folder()
        return f"https://drive.google.com/drive/folders/{folder_id}"

    def begin_run(self, run_id: str) -> str:
        root_id = self.ensure_root_folder()
        folder_id = self._find_folder(run_id, root_id)
        if not folder_id:
            folder_id = self._create_folder(run_id, root_id)
        self.run_folder_id = folder_id
        self.run_folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
        return self.run_folder_url

    def upsert_bytes(self, name: str, data: bytes, mime_type: str) -> str:
        if not self.run_folder_id:
            raise RuntimeError("Chưa khởi tạo thư mục phiên chạy trên Google Drive.")
        try:
            from googleapiclient.http import MediaIoBaseUpload
        except ImportError as error:
            raise RuntimeError(
                "Thiếu thư viện Google Drive. Hãy cài lại requirements.txt."
            ) from error

        media = MediaIoBaseUpload(
            io.BytesIO(data), mimetype=mime_type, resumable=len(data) > 5_000_000
        )
        service = self._get_service()
        existing_id = self._uploaded_file_ids.get(name)
        if existing_id:
            result = (
                service.files()
                .update(
                    fileId=existing_id,
                    media_body=media,
                    fields="id,name,webViewLink",
                )
                .execute(num_retries=3)
            )
        else:
            result = (
                service.files()
                .create(
                    body={"name": name, "parents": [self.run_folder_id]},
                    media_body=media,
                    fields="id,name,webViewLink",
                )
                .execute(num_retries=3)
            )
            self._uploaded_file_ids[name] = str(result["id"])
        return str(result.get("webViewLink", ""))

    def upload_path(self, path: Path, mime_type: str) -> str:
        return self.upsert_bytes(path.name, path.read_bytes(), mime_type)

    def upload_json(self, name: str, payload: Mapping[str, Any]) -> str:
        data = json.dumps(
            payload, ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")
        return self.upsert_bytes(name, data, "application/json")
