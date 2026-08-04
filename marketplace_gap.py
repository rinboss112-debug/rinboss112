from __future__ import annotations

import io
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from amazon_extension_import import normalize_extension_frame


TEMU_COLUMNS = [
    "title",
    "image_url",
    "price",
    "original_price",
    "keyword",
    "product_id",
    "product_url",
    "units_sold",
    "sold_text",
    "rating",
    "review_count",
    "badge",
    "free_shipping",
    "scraped_at",
]

STOP_WORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to",
    "with", "new", "pcs", "piece", "pieces", "temu", "amazon",
}


class MarketplaceImportError(ValueError):
    """Raised when a marketplace export cannot be normalized."""


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "có", "co"}


def _number(value: Any) -> float | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([kKmM])?", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = (match.group(2) or "").casefold()
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    return number


def _first_column(frame: pd.DataFrame, names: tuple[str, ...], default: Any = "") -> pd.Series:
    normalized = {
        re.sub(r"[^a-z0-9]+", " ", str(column).casefold()).strip(): column
        for column in frame.columns
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
        if key in normalized:
            return frame[normalized[key]]
    return pd.Series([default] * len(frame), index=frame.index)


def normalize_temu_extension_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=TEMU_COLUMNS)
    result = pd.DataFrame(index=frame.index)
    aliases = {
        "title": ("title", "product title", "product name", "name"),
        "image_url": ("image_url", "image url", "image", "product image"),
        "price": ("price", "sale price", "current price", "us price"),
        "original_price": ("original_price", "original price", "list price", "msrp"),
        "keyword": ("keyword", "niche", "category", "search keyword"),
        "product_id": ("product_id", "product id", "goods id", "goods_id"),
        "product_url": ("product_url", "product url", "temu url", "temu link", "url", "link"),
        "units_sold": ("units_sold", "units sold", "sold", "sold count", "sales"),
        "sold_text": ("sold_text", "sold text", "sales text"),
        "rating": ("rating", "stars", "star rating"),
        "review_count": ("review_count", "review count", "reviews", "ratings count"),
        "badge": ("badge", "badges", "label"),
        "free_shipping": ("free_shipping", "free shipping"),
        "scraped_at": ("scraped_at", "scraped at", "collected at"),
    }
    for column, names in aliases.items():
        result[column] = _first_column(frame, names, False if column == "free_shipping" else "")

    for column in ("title", "image_url", "keyword", "product_id", "product_url", "sold_text", "badge", "scraped_at"):
        result[column] = result[column].fillna("").astype(str).str.strip()
    for column in ("price", "original_price", "units_sold", "rating", "review_count"):
        result[column] = result[column].map(_number)
    result["free_shipping"] = result["free_shipping"].map(_bool)
    result = result[result["title"].ne("") & result["price"].gt(0)]
    identity = result["product_id"].where(result["product_id"].ne(""), result["product_url"])
    identity = identity.where(identity.ne(""), result["title"].str.casefold())
    result = result.assign(_identity=identity).drop_duplicates("_identity", keep="last")
    return result.drop(columns="_identity").loc[:, TEMU_COLUMNS].reset_index(drop=True)


def read_marketplace_export(raw: bytes, filename: str, marketplace: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.casefold()
    try:
        if suffix == ".json":
            payload = json.loads(raw.decode("utf-8-sig"))
            if isinstance(payload, dict):
                key = "temu_products" if marketplace == "temu" else "amazon_products"
                payload = payload.get(key, payload.get("products", []))
            if not isinstance(payload, list):
                raise MarketplaceImportError("JSON không có danh sách sản phẩm.")
            frame = pd.DataFrame(payload)
        elif suffix == ".csv":
            frame = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
        else:
            raise MarketplaceImportError("Chỉ hỗ trợ file CSV hoặc JSON từ extension.")
    except MarketplaceImportError:
        raise
    except (UnicodeError, ValueError, TypeError, pd.errors.ParserError) as error:
        raise MarketplaceImportError(f"Không đọc được file: {error}") from error
    if marketplace == "temu":
        return normalize_temu_extension_frame(frame)
    if marketplace == "amazon":
        return normalize_extension_frame(frame)
    raise MarketplaceImportError("Nguồn dữ liệu không hợp lệ.")


def _ascii(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def title_tokens(value: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _ascii(value))
    return {word for word in words if len(word) > 1 and word not in STOP_WORDS}


def _pack_count(value: Any) -> int | None:
    text = _ascii(value)
    patterns = (
        r"pack\s+of\s+(\d+)", r"(\d+)\s*[- ]?pack\b", r"(\d+)\s*(?:count|ct|pcs|pieces)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _size_ounces(value: Any) -> float | None:
    text = _ascii(value)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(fl\s*oz|ounces?|oz|lbs?|pounds?|kg|g|ml|liters?|l)\b", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = re.sub(r"\s+", "", match.group(2))
    factors = {
        "floz": 1.0, "ounce": 1.0, "ounces": 1.0, "oz": 1.0,
        "lb": 16.0, "lbs": 16.0, "pound": 16.0, "pounds": 16.0,
        "g": 0.035274, "kg": 35.274, "ml": 0.033814,
        "l": 33.814, "liter": 33.814, "liters": 33.814,
    }
    return amount * factors[unit]


def match_titles(temu_title: Any, amazon_title: Any) -> tuple[float, str]:
    temu_tokens = title_tokens(temu_title)
    amazon_tokens = title_tokens(amazon_title)
    if not temu_tokens or not amazon_tokens:
        return 0.0, "Thiếu tiêu đề để đối chiếu"
    intersection = len(temu_tokens & amazon_tokens)
    union = len(temu_tokens | amazon_tokens)
    jaccard = intersection / union if union else 0.0
    sequence = SequenceMatcher(None, " ".join(sorted(temu_tokens)), " ".join(sorted(amazon_tokens))).ratio()
    containment = intersection / min(len(temu_tokens), len(amazon_tokens))
    score = (0.45 * jaccard + 0.30 * sequence + 0.25 * containment) * 100

    warnings: list[str] = []
    temu_pack, amazon_pack = _pack_count(temu_title), _pack_count(amazon_title)
    if temu_pack and amazon_pack and temu_pack != amazon_pack:
        score *= 0.55
        warnings.append(f"Khác pack ({temu_pack} vs {amazon_pack})")
    temu_size, amazon_size = _size_ounces(temu_title), _size_ounces(amazon_title)
    if temu_size and amazon_size:
        ratio = max(temu_size, amazon_size) / min(temu_size, amazon_size)
        if ratio > 1.20:
            score *= 0.55
            warnings.append("Khác size/khối lượng")
    if intersection < 2:
        warnings.append("Ít từ khóa trùng")
    return round(score, 1), "; ".join(warnings) or "Cần kiểm tra ảnh, size và pack"


def compare_marketplaces(
    temu: pd.DataFrame,
    amazon: pd.DataFrame,
    *,
    temu_fee_percent: float = 15.0,
    other_cost: float = 0.0,
) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    amazon_valid = amazon[amazon["price"].notna() & amazon["price"].gt(0)].copy()
    for _, temu_row in temu[temu["price"].notna() & temu["price"].gt(0)].iterrows():
        best: tuple[float, pd.Series, str] | None = None
        temu_keyword = str(temu_row.get("keyword", "")).casefold().strip()
        candidates = amazon_valid
        if temu_keyword and "keyword" in amazon_valid:
            same_keyword = amazon_valid[
                amazon_valid["keyword"].fillna("").astype(str).str.casefold().eq(temu_keyword)
            ]
            if not same_keyword.empty:
                candidates = same_keyword
        for _, amazon_row in candidates.iterrows():
            score, warning = match_titles(temu_row["title"], amazon_row["title"])
            if best is None or score > best[0]:
                best = (score, amazon_row, warning)
        if best is None:
            continue
        score, amazon_row, warning = best
        temu_price = float(temu_row["price"])
        amazon_price = float(amazon_row["price"])
        ratio = temu_price / amazon_price
        revenue_after_fee = temu_price * (1 - float(temu_fee_percent) / 100)
        estimated_profit = revenue_after_fee - amazon_price - float(other_cost)
        roi = estimated_profit / amazon_price * 100 if amazon_price else math.nan
        output.append({
            "temu_image": temu_row.get("image_url", ""),
            "temu_title": temu_row["title"],
            "temu_price": round(temu_price, 2),
            "temu_sold": temu_row.get("units_sold"),
            "temu_rating": temu_row.get("rating"),
            "temu_reviews": temu_row.get("review_count"),
            "temu_badge": temu_row.get("badge", ""),
            "temu_url": temu_row.get("product_url", ""),
            "amazon_image": amazon_row.get("image_url", ""),
            "amazon_title": amazon_row["title"],
            "amazon_price": round(amazon_price, 2),
            "amazon_asin": amazon_row.get("asin", ""),
            "amazon_url": amazon_row.get("product_url", ""),
            "price_ratio": round(ratio, 2),
            "gross_spread": round(temu_price - amazon_price, 2),
            "estimated_profit": round(estimated_profit, 2),
            "estimated_roi": round(roi, 1),
            "match_score": score,
            "match_warning": warning,
            "keyword": temu_row.get("keyword", ""),
        })
    columns = [
        "temu_image", "temu_title", "temu_price", "temu_sold", "temu_rating", "temu_reviews",
        "temu_badge", "temu_url", "amazon_image", "amazon_title", "amazon_price", "amazon_asin",
        "amazon_url", "price_ratio", "gross_spread", "estimated_profit", "estimated_roi",
        "match_score", "match_warning", "keyword",
    ]
    result = pd.DataFrame(output, columns=columns)
    if result.empty:
        return result
    return result.sort_values(
        ["price_ratio", "match_score", "temu_sold"], ascending=[False, False, False], na_position="last"
    ).reset_index(drop=True)


def results_csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")
