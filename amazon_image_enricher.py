from __future__ import annotations

import html
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from amazon_scraper import AMAZON_BASE_URL, DEFAULT_TIMEOUT_SECONDS, _looks_blocked


IMAGE_COLUMNS = [f"image_url_{index}" for index in range(1, 6)]
STATUS_COLUMN = "image_gallery_status"
ProgressCallback = Callable[[int, int, object, str], None]
LogCallback = Callable[[str], None]


def _normalize_image_url(value: object) -> str:
    text = html.unescape(str(value or "").strip())
    if not text:
        return ""
    text = text.replace("\\/", "/")
    try:
        text = bytes(text, "utf-8").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    if text.startswith("//"):
        text = f"https:{text}"
    if not text.startswith(("https://", "http://")):
        return ""
    text = re.sub(
        r"\._[^/?]+_(?=\.[a-zA-Z0-9]+(?:[?#]|$))",
        "",
        text,
    )
    return text


def _append_unique(images: list[str], value: object, limit: int) -> None:
    normalized = _normalize_image_url(value)
    if (
        normalized
        and "amazon.com/images/" in normalized
        and normalized not in images
        and len(images) < limit
    ):
        images.append(normalized)


def _dynamic_images(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, dict):
        return []

    def image_area(item: tuple[object, object]) -> int:
        dimensions = item[1]
        if (
            isinstance(dimensions, list)
            and len(dimensions) >= 2
            and all(isinstance(part, (int, float)) for part in dimensions[:2])
        ):
            return int(dimensions[0] * dimensions[1])
        return 0

    return [str(url) for url, _ in sorted(parsed.items(), key=image_area, reverse=True)]


def extract_amazon_gallery_images(
    page_html: str,
    fallback_url: str = "",
    limit: int = 5,
) -> list[str]:
    """Extract up to five original-size Amazon image URLs from a detail page."""
    limit = max(1, int(limit))
    images: list[str] = []
    soup = BeautifulSoup(page_html or "", "lxml")

    selectors = (
        "#landingImage",
        "#imgTagWrapperId img",
        "#altImages img",
        "img[data-a-dynamic-image]",
    )
    for selector in selectors:
        for image in soup.select(selector):
            _append_unique(images, image.get("data-old-hires", ""), limit)
            dynamic_value = str(image.get("data-a-dynamic-image", ""))
            for dynamic_url in _dynamic_images(dynamic_value):
                _append_unique(images, dynamic_url, limit)
            _append_unique(images, image.get("src", ""), limit)
            if len(images) >= limit:
                return images[:limit]

    script_patterns = (
        r'"hiRes"\s*:\s*"([^"]+)"',
        r'"large"\s*:\s*"([^"]+)"',
        r'"mainUrl"\s*:\s*"([^"]+)"',
    )
    for pattern in script_patterns:
        for match in re.findall(pattern, page_html or "", flags=re.IGNORECASE):
            _append_unique(images, match, limit)
            if len(images) >= limit:
                return images[:limit]

    _append_unique(images, fallback_url, limit)
    return images[:limit]


def read_amazon_product_csv(raw: bytes) -> pd.DataFrame:
    if not raw:
        raise ValueError("File CSV đang trống.")
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            frame = pd.read_csv(BytesIO(raw), encoding=encoding)
            break
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            errors.append(str(error))
    else:
        raise ValueError(f"Không đọc được CSV: {'; '.join(errors[-2:])}")
    if "asin" not in frame.columns and "product_url" not in frame.columns:
        raise ValueError("CSV cần có cột 'asin' hoặc 'product_url'.")
    return ensure_image_columns(frame)


def ensure_image_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    original = (
        result["image_url"].fillna("").astype(str)
        if "image_url" in result.columns
        else pd.Series("", index=result.index, dtype=str)
    )
    for position, column in enumerate(IMAGE_COLUMNS):
        if column not in result.columns:
            result[column] = original if position == 0 else ""
        else:
            result[column] = result[column].fillna("").astype(str)
    if STATUS_COLUMN not in result.columns:
        result[STATUS_COLUMN] = ""
    else:
        result[STATUS_COLUMN] = result[STATUS_COLUMN].fillna("").astype(str)
    return result


def pending_image_rows(frame: pd.DataFrame) -> int:
    prepared = ensure_image_columns(frame)
    complete = prepared[IMAGE_COLUMNS].apply(
        lambda row: sum(bool(str(value).strip()) for value in row) >= 5,
        axis=1,
    )
    return int((~complete).sum())


def _product_url(row: pd.Series) -> str:
    value = str(row.get("product_url", "") or "").strip()
    if value.startswith(("https://www.amazon.com/", "http://www.amazon.com/")):
        return value
    asin = str(row.get("asin", "") or "").strip()
    if asin:
        return f"{AMAZON_BASE_URL}/dp/{quote(asin, safe='')}"
    return ""


def _build_image_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        status=0,
        backoff_factor=0.5,
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=2)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }
    )
    return session


def enrich_amazon_product_images(
    frame: pd.DataFrame,
    batch_size: int = 10,
    session: requests.Session | None = None,
    delay_seconds: float = 1.5,
    progress_callback: ProgressCallback | None = None,
    log_callback: LogCallback | None = None,
) -> pd.DataFrame:
    """Enrich a small CSV batch and preserve progress in the returned frame."""
    result = ensure_image_columns(frame)
    batch_size = max(1, min(int(batch_size), 20))
    candidates = [
        index
        for index, row in result.iterrows()
        if sum(bool(str(row[column]).strip()) for column in IMAGE_COLUMNS) < 5
    ][:batch_size]
    total = len(candidates)
    own_session = session is None
    active_session = session or _build_image_session()

    try:
        for processed, index in enumerate(candidates, start=1):
            row = result.loc[index]
            url = _product_url(row)
            if not url:
                result.at[index, STATUS_COLUMN] = "missing_url"
                if log_callback:
                    log_callback(f"Dòng {index}: thiếu ASIN/link sản phẩm.")
                if progress_callback:
                    progress_callback(processed, total, index, "missing_url")
                continue

            try:
                response = active_session.get(
                    url,
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    headers={"Referer": AMAZON_BASE_URL},
                )
                if response.status_code in (429, 503):
                    result.at[index, STATUS_COLUMN] = "blocked"
                    if log_callback:
                        log_callback(
                            f"Dòng {index}: Amazon trả HTTP {response.status_code}; "
                            "đã dừng lô để bảo vệ kết nối."
                        )
                    if progress_callback:
                        progress_callback(processed, total, index, "blocked")
                    break
                response.raise_for_status()
                if _looks_blocked(response.text):
                    result.at[index, STATUS_COLUMN] = "blocked"
                    if log_callback:
                        log_callback(
                            f"Dòng {index}: Amazon yêu cầu CAPTCHA; đã dừng lô."
                        )
                    if progress_callback:
                        progress_callback(processed, total, index, "blocked")
                    break

                fallback = str(row.get("image_url", "") or "")
                images = extract_amazon_gallery_images(
                    response.text,
                    fallback_url=fallback,
                    limit=5,
                )
                for position, column in enumerate(IMAGE_COLUMNS):
                    result.at[index, column] = (
                        images[position] if position < len(images) else ""
                    )
                status = "complete" if len(images) >= 5 else "partial"
                result.at[index, STATUS_COLUMN] = status
                if log_callback:
                    asin = str(row.get("asin", "") or index)
                    log_callback(f"{asin}: lấy được {len(images)}/5 ảnh.")
                if progress_callback:
                    progress_callback(processed, total, index, status)
            except requests.RequestException as error:
                result.at[index, STATUS_COLUMN] = "error"
                if log_callback:
                    log_callback(f"Dòng {index}: lỗi kết nối - {error}")
                if progress_callback:
                    progress_callback(processed, total, index, "error")

            if processed < total and delay_seconds > 0:
                time.sleep(float(delay_seconds))
    finally:
        if own_session:
            active_session.close()
    return result


def amazon_images_csv(frame: pd.DataFrame) -> bytes:
    return ensure_image_columns(frame).to_csv(index=False).encode("utf-8-sig")


def enriched_filename(source_name: str) -> str:
    stem = Path(source_name or "amazon_products").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "amazon_products"
    return f"{safe_stem}_5_images.csv"
