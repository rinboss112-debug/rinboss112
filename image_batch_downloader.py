from __future__ import annotations

import ipaddress
import re
import socket
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit

import pandas as pd
import requests


MAX_IMAGES_PER_BATCH = 200
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
ProgressCallback = Callable[[int, int, str, str], None]
UrlValidator = Callable[[str], str]


@dataclass(frozen=True)
class ImageDownloadResult:
    archive: bytes
    report: pd.DataFrame

    @property
    def success_count(self) -> int:
        return int(self.report["status"].eq("downloaded").sum())

    @property
    def error_count(self) -> int:
        return int(self.report["status"].eq("error").sum())


def sanitize_image_name(value: object, fallback: str = "image") -> str:
    """Return a Windows-safe filename while preserving readable Unicode text."""
    text = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    suffix = PurePath(text).suffix.casefold()
    if suffix and suffix not in ALLOWED_EXTENSIONS:
        text = text[: -len(PurePath(text).suffix)].rstrip(" .") or fallback
    stem = PurePath(text).stem.strip(" .") or fallback
    suffix = PurePath(text).suffix.casefold()
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    stem = stem[:140].rstrip(" .") or fallback
    return f"{stem}{suffix}"


def _validate_public_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Link phải bắt đầu bằng http:// hoặc https://.")
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        raise ValueError("Không chấp nhận địa chỉ nội bộ.")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise ValueError("Không phân giải được tên miền ảnh.") from error
    if not addresses:
        raise ValueError("Tên miền ảnh không có địa chỉ hợp lệ.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        ):
            raise ValueError("Không chấp nhận địa chỉ mạng nội bộ hoặc dành riêng.")
    return url


def _detected_extension(data: bytes, content_type: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:12] in {b"ftypavif", b"ftypavis"}:
        return ".avif"
    normalized = content_type.split(";", 1)[0].strip().casefold()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
    }.get(normalized, "")


def _unique_filename(value: object, extension: str, used: set[str], row_number: int) -> str:
    safe = sanitize_image_name(value, fallback=f"image_{row_number}")
    current_suffix = PurePath(safe).suffix.casefold()
    if not current_suffix:
        safe = f"{safe}{extension}"
    stem = PurePath(safe).stem
    suffix = PurePath(safe).suffix.casefold() or extension
    candidate = f"{stem}{suffix}"
    counter = 2
    while candidate.casefold() in used:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _excel_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _download_one(
    session: requests.Session,
    raw_url: str,
    validator: UrlValidator,
) -> tuple[bytes, str, str]:
    current_url = validator(raw_url)
    for _redirect in range(4):
        response = session.get(
            current_url,
            stream=True,
            timeout=(8, 30),
            allow_redirects=False,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif;q=0.9,*/*;q=0.5",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
            },
        )
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                raise ValueError("Máy chủ chuyển hướng nhưng không gửi link mới.")
            current_url = validator(urljoin(current_url, location))
            continue
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        if content_length > MAX_IMAGE_BYTES:
            response.close()
            raise ValueError("Ảnh vượt quá 15 MB.")
        payload = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) > MAX_IMAGE_BYTES:
                    raise ValueError("Ảnh vượt quá 15 MB.")
        finally:
            response.close()
        data = bytes(payload)
        content_type = str(response.headers.get("Content-Type", ""))
        extension = _detected_extension(data, content_type)
        if not data or not extension:
            raise ValueError("Link không trả về định dạng ảnh JPG/PNG/WebP/GIF/AVIF hợp lệ.")
        return data, extension, current_url
    raise ValueError("Ảnh chuyển hướng quá nhiều lần.")


def build_named_image_archive(
    rows: Iterable[dict[str, Any]],
    *,
    name_column: str,
    url_column: str,
    session: requests.Session | None = None,
    progress_callback: ProgressCallback | None = None,
    url_validator: UrlValidator = _validate_public_url,
) -> ImageDownloadResult:
    records = list(rows)
    if not records:
        raise ValueError("Danh sách ảnh đang trống.")
    if len(records) > MAX_IMAGES_PER_BATCH:
        raise ValueError(f"Mỗi lượt hỗ trợ tối đa {MAX_IMAGES_PER_BATCH} ảnh để bảo vệ bộ nhớ Cloud.")

    own_session = session is None
    active_session = session or requests.Session()
    used_names: set[str] = set()
    report_rows: list[dict[str, Any]] = []
    total_bytes = 0
    output = BytesIO()
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for position, row in enumerate(records, start=1):
                requested_name = str(row.get(name_column, "") or "").strip()
                raw_url = str(row.get(url_column, "") or "").strip()
                saved_name = ""
                status = "error"
                message = ""
                size = 0
                try:
                    if not requested_name:
                        raise ValueError("Thiếu tên ảnh.")
                    if not raw_url:
                        raise ValueError("Thiếu link ảnh.")
                    data, extension, final_url = _download_one(active_session, raw_url, url_validator)
                    if total_bytes + len(data) > MAX_TOTAL_BYTES:
                        raise ValueError("Tổng dung lượng lượt tải vượt quá 250 MB.")
                    saved_name = _unique_filename(requested_name, extension, used_names, position)
                    archive.writestr(saved_name, data)
                    total_bytes += len(data)
                    size = len(data)
                    status = "downloaded"
                    message = "Thành công" if final_url == raw_url else "Thành công sau chuyển hướng"
                except (ValueError, requests.RequestException, OSError) as error:
                    message = str(error)
                report_rows.append(
                    {
                        "row": position,
                        "requested_name": requested_name,
                        "image_url": raw_url,
                        "saved_name": saved_name,
                        "status": status,
                        "message": message,
                        "bytes": size,
                    }
                )
                if progress_callback:
                    progress_callback(position, len(records), requested_name, status)

            report = pd.DataFrame(report_rows)
            safe_report = report.apply(lambda column: column.map(_excel_safe))
            archive.writestr(
                "_download_report.csv",
                safe_report.to_csv(index=False).encode("utf-8-sig"),
            )
    finally:
        if own_session:
            active_session.close()
    return ImageDownloadResult(archive=output.getvalue(), report=pd.DataFrame(report_rows))
