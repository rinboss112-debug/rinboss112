from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from amazon_scraper import CSV_COLUMNS


BOOLEAN_COLUMNS = (
    "prime",
    "free_shipping",
    "fast_shipping",
    "delivery_available",
    "sponsored",
)
TEXT_COLUMNS = tuple(
    column
    for column in CSV_COLUMNS
    if column not in {"price", "rating", "review_count", *BOOLEAN_COLUMNS}
)
ASIN_FROM_URL = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


class ExtensionImportError(ValueError):
    """Raised when an extension export cannot be normalized safely."""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "có", "co"}


def _asin_from_url(value: Any) -> str:
    match = ASIN_FROM_URL.search(str(value or ""))
    return match.group(1).upper() if match else ""


def normalize_extension_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=CSV_COLUMNS)
    normalized = frame.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    if "title" not in normalized.columns:
        raise ExtensionImportError("File không có cột title.")
    if "asin" not in normalized.columns:
        normalized["asin"] = ""
    if "product_url" not in normalized.columns:
        normalized["product_url"] = ""

    normalized["asin"] = normalized.apply(
        lambda row: str(row.get("asin", "")).strip().upper()
        or _asin_from_url(row.get("product_url", "")),
        axis=1,
    )
    normalized = normalized[normalized["asin"].str.fullmatch(r"[A-Z0-9]{10}", na=False)]
    normalized["product_url"] = normalized.apply(
        lambda row: str(row.get("product_url", "")).strip()
        or f"https://www.amazon.com/dp/{row['asin']}",
        axis=1,
    )

    for column in CSV_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = False if column in BOOLEAN_COLUMNS else ""
    for column in TEXT_COLUMNS:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
    for column in ("price", "rating", "review_count"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    for column in BOOLEAN_COLUMNS:
        normalized[column] = normalized[column].map(_as_bool)

    normalized = normalized[normalized["title"].ne("")]
    normalized = normalized.drop_duplicates(subset=["asin"], keep="last")
    return normalized.loc[:, CSV_COLUMNS].reset_index(drop=True)


def read_extension_export(raw: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.casefold()
    try:
        if suffix == ".json":
            payload = json.loads(raw.decode("utf-8-sig"))
            if isinstance(payload, dict):
                payload = payload.get("products", [])
            if not isinstance(payload, list):
                raise ExtensionImportError("JSON không có danh sách products.")
            frame = pd.DataFrame(payload)
        elif suffix == ".csv":
            frame = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
        else:
            raise ExtensionImportError("Chỉ hỗ trợ file CSV hoặc JSON từ extension.")
    except ExtensionImportError:
        raise
    except (UnicodeError, ValueError, TypeError, pd.errors.ParserError) as error:
        raise ExtensionImportError(f"Không đọc được file extension: {error}") from error
    return normalize_extension_frame(frame)


def build_extension_zip(extension_dir: Path) -> bytes:
    extension_dir = Path(extension_dir)
    required = extension_dir / "manifest.json"
    if not required.exists():
        raise FileNotFoundError("Không tìm thấy manifest.json của extension.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(extension_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(extension_dir).as_posix())
    return output.getvalue()
