from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode, urlsplit

import pandas as pd


TEMU_PRODUCT_COLUMNS = [
    "title",
    "category",
    "category_group",
    "price",
    "original_price",
    "discount_percent",
    "units_sold",
    "review_count",
    "rating",
    "free_shipping",
    "delivery_days",
    "image_url",
    "product_url",
    "valid_temu_link",
    "data_quality",
    "hot_score",
    "hot_label",
]

TEMU_SEARCH_URL = "https://www.temu.com/search_result.html"


_ALIASES: dict[str, tuple[str, ...]] = {
    "title": (
        "title",
        "product title",
        "product name",
        "item name",
        "name",
    ),
    "category": (
        "category",
        "product category",
        "category name",
        "niche",
        "ngach",
        "ngách",
    ),
    "price": (
        "price",
        "sale price",
        "current price",
        "product price",
        "retail price",
        "us price",
    ),
    "original_price": (
        "original price",
        "list price",
        "regular price",
        "was price",
        "msrp",
    ),
    "discount_percent": (
        "discount percent",
        "discount",
        "discount percentage",
        "off percent",
    ),
    "units_sold": (
        "units sold",
        "sold",
        "sold count",
        "sales",
        "sales volume",
        "orders",
    ),
    "review_count": (
        "review count",
        "reviews",
        "ratings count",
        "number of reviews",
    ),
    "rating": (
        "rating",
        "star rating",
        "stars",
        "product rating",
    ),
    "free_shipping": (
        "free shipping",
        "free_shipping",
        "shipping",
        "shipping type",
    ),
    "delivery_days": (
        "delivery days",
        "shipping days",
        "estimated delivery days",
        "delivery time",
    ),
    "image_url": (
        "image url",
        "image_url",
        "main image",
        "product image",
        "image",
    ),
    "product_url": (
        "product url",
        "product_url",
        "temu url",
        "temu link",
        "product link",
        "url",
        "link",
    ),
}


_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Food & Grocery",
        (
            "food",
            "grocery",
            "snack",
            "beverage",
            "drink",
            "cereal",
            "pantry",
            "coffee",
            "tea",
            "candy",
            "chocolate",
        ),
    ),
    ("Home & Kitchen", ("home", "kitchen", "furniture", "decor", "garden")),
    ("Beauty & Health", ("beauty", "health", "skin", "makeup", "hair")),
    ("Pet Supplies", ("pet", "dog", "cat", "aquarium")),
    ("Sports & Outdoors", ("sport", "outdoor", "fitness", "camping")),
    ("Tools & Improvement", ("tool", "hardware", "improvement", "repair")),
    ("Electronics", ("electronic", "phone", "computer", "smart home")),
    ("Automotive", ("automotive", "car", "motorcycle")),
    ("Toys & Games", ("toy", "game", "puzzle")),
    ("Fashion", ("fashion", "clothing", "shoe", "jewelry", "bag")),
    ("Office & School", ("office", "school", "stationery", "book")),
)


def _normalized_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().casefold()).strip()


def _source_series(
    frame: pd.DataFrame,
    field: str,
    default: Any = "",
) -> pd.Series:
    normalized_columns = {
        _normalized_name(column): column for column in frame.columns
    }
    for alias in _ALIASES[field]:
        column = normalized_columns.get(_normalized_name(alias))
        if column is not None:
            return frame[column]
    return pd.Series([default] * len(frame), index=frame.index)


def _parse_number(value: object) -> float | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().casefold().replace(",", "")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([kmb])?", text)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(
        match.group(2) or "",
        1,
    )
    return number * multiplier


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.map(_parse_number), errors="coerce")


def _boolean_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value):
        return bool(value)
    text = str(value or "").strip().casefold()
    if any(token in text for token in ("free shipping", "miễn phí", "mien phi")):
        return True
    return text in {"1", "true", "yes", "y", "free", "có", "co"}


def normalize_temu_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text.lstrip('/')}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"}:
        return ""
    host = (parsed.hostname or "").casefold().rstrip(".")
    valid_host = (
        host == "temu.com"
        or host.endswith(".temu.com")
        or host == "temu.to"
        or host.endswith(".temu.to")
    )
    return text if valid_host else ""


def classify_category(category: object, title: object = "") -> str:
    searchable = f"{category} {title}".casefold()
    for group, keywords in _CATEGORY_RULES:
        if any(keyword in searchable for keyword in keywords):
            return group
    return "Other"


def normalize_niches(values: str | Iterable[str]) -> list[str]:
    source = values.splitlines() if isinstance(values, str) else values
    niches: list[str] = []
    seen: set[str] = set()
    for value in source:
        niche = re.sub(r"\s+", " ", str(value)).strip()
        identity = niche.casefold()
        if not niche or identity in seen:
            continue
        seen.add(identity)
        niches.append(niche)
    return niches


def build_temu_search_url(niche: str) -> str:
    normalized = normalize_niches([niche])
    if not normalized:
        raise ValueError("Tên ngách không được để trống.")
    query = urlencode({"search_key": normalized[0]}, quote_via=quote)
    return f"{TEMU_SEARCH_URL}?{query}"


def build_temu_niche_links(values: str | Iterable[str]) -> pd.DataFrame:
    niches = normalize_niches(values)
    return pd.DataFrame(
        {
            "niche": pd.Series(niches, dtype="string"),
            "category_group": pd.Series(
                [classify_category("", niche) for niche in niches],
                dtype="string",
            ),
            "temu_search_url": pd.Series(
                [build_temu_search_url(niche) for niche in niches],
                dtype="string",
            ),
        }
    )


def temu_niche_links_csv(frame: pd.DataFrame) -> bytes:
    columns = ["niche", "category_group", "temu_search_url"]
    return frame.reindex(columns=columns).to_csv(index=False).encode("utf-8-sig")


def _hot_label(score: float) -> str:
    if score >= 70:
        return "Rất hot"
    if score >= 50:
        return "Tiềm năng"
    if score >= 30:
        return "Theo dõi"
    return "Dữ liệu yếu"


def _score_hot_products(frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    sold = scored["units_sold"].fillna(0).clip(lower=0)
    reviews = scored["review_count"].fillna(0).clip(lower=0)
    rating = scored["rating"].fillna(0).clip(lower=0, upper=5)
    discount = scored["discount_percent"].fillna(0).clip(lower=0, upper=100)
    delivery = scored["delivery_days"].fillna(30).clip(lower=0)

    sold_points = sold.map(lambda value: min(math.log10(value + 1) / 5, 1) * 40)
    review_points = reviews.map(
        lambda value: min(math.log10(value + 1) / 4, 1) * 20
    )
    rating_points = ((rating - 3) / 2).clip(lower=0, upper=1) * 20
    discount_points = (discount / 50).clip(lower=0, upper=1) * 10
    shipping_points = scored["free_shipping"].fillna(False).astype(bool) * 5
    delivery_points = ((10 - delivery) / 9).clip(lower=0, upper=1) * 5

    scored["hot_score"] = (
        sold_points
        + review_points
        + rating_points
        + discount_points
        + shipping_points
        + delivery_points
    ).round(1)
    quality_fields = [
        "units_sold",
        "review_count",
        "rating",
        "discount_percent",
        "delivery_days",
    ]
    scored["data_quality"] = (
        scored[quality_fields].notna().sum(axis=1) / len(quality_fields) * 100
    ).round(0)
    scored["hot_label"] = scored["hot_score"].map(_hot_label)
    return scored


def normalize_temu_products(source: pd.DataFrame) -> pd.DataFrame:
    frame = source.copy().dropna(how="all").reset_index(drop=True)
    result = pd.DataFrame(index=frame.index)
    result["title"] = _source_series(frame, "title").fillna("").astype(str).str.strip()
    result["category"] = (
        _source_series(frame, "category").fillna("").astype(str).str.strip()
    )
    result["price"] = _numeric_series(_source_series(frame, "price", None))
    result["original_price"] = _numeric_series(
        _source_series(frame, "original_price", None)
    )
    result["discount_percent"] = _numeric_series(
        _source_series(frame, "discount_percent", None)
    )
    ratio_discount = (
        (result["original_price"] - result["price"])
        / result["original_price"]
        * 100
    )
    valid_ratio = (
        result["original_price"].gt(0)
        & result["price"].ge(0)
        & result["original_price"].ge(result["price"])
    )
    result["discount_percent"] = result["discount_percent"].where(
        result["discount_percent"].notna(),
        ratio_discount.where(valid_ratio),
    )
    result["discount_percent"] = result["discount_percent"].clip(0, 100)
    result["units_sold"] = _numeric_series(
        _source_series(frame, "units_sold", None)
    )
    result["review_count"] = _numeric_series(
        _source_series(frame, "review_count", None)
    )
    result["rating"] = _numeric_series(_source_series(frame, "rating", None)).clip(
        0, 5
    )
    result["free_shipping"] = _source_series(
        frame, "free_shipping", False
    ).map(_boolean_value)
    result["delivery_days"] = _numeric_series(
        _source_series(frame, "delivery_days", None)
    )
    result["image_url"] = (
        _source_series(frame, "image_url").fillna("").astype(str).str.strip()
    )
    result["product_url"] = _source_series(frame, "product_url").map(
        normalize_temu_url
    )
    result["valid_temu_link"] = result["product_url"].ne("")
    meaningful_rows = (
        result["title"].ne("")
        | result["price"].notna()
        | result["product_url"].ne("")
    )
    result = result.loc[meaningful_rows].reset_index(drop=True)
    result["category_group"] = [
        classify_category(category, title)
        for category, title in zip(result["category"], result["title"])
    ]
    return _score_hot_products(result)[TEMU_PRODUCT_COLUMNS]


def filter_temu_products(
    frame: pd.DataFrame,
    *,
    minimum_price: float = 20.0,
    maximum_price: float | None = None,
    minimum_hot_score: float = 0.0,
    categories: Iterable[str] | None = None,
    query: str = "",
    require_valid_link: bool = True,
) -> pd.DataFrame:
    filtered = frame.copy()
    filtered = filtered.loc[filtered["price"].ge(float(minimum_price))]
    if maximum_price is not None:
        filtered = filtered.loc[filtered["price"].le(float(maximum_price))]
    filtered = filtered.loc[filtered["hot_score"].ge(float(minimum_hot_score))]
    category_values = {str(value) for value in (categories or []) if str(value)}
    if category_values:
        filtered = filtered.loc[filtered["category_group"].isin(category_values)]
    if require_valid_link:
        filtered = filtered.loc[filtered["valid_temu_link"]]
    normalized_query = str(query).strip().casefold()
    if normalized_query:
        searchable = (
            filtered["title"].fillna("").astype(str)
            + " "
            + filtered["category"].fillna("").astype(str)
            + " "
            + filtered["category_group"].fillna("").astype(str)
        ).str.casefold()
        filtered = filtered.loc[searchable.str.contains(normalized_query, regex=False)]
    return filtered.sort_values(
        ["hot_score", "units_sold", "review_count"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)


def read_temu_product_file(filename: str, raw: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".xlsx":
        frame = pd.read_excel(io.BytesIO(raw))
    elif suffix == ".csv":
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
            try:
                frame = pd.read_csv(
                    io.BytesIO(raw),
                    encoding=encoding,
                    sep=None,
                    engine="python",
                )
                break
            except (UnicodeDecodeError, pd.errors.ParserError) as error:
                last_error = error
        else:
            raise ValueError(f"Không đọc được file CSV: {last_error}")
    else:
        raise ValueError("Chỉ hỗ trợ file CSV hoặc XLSX.")
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.dropna(how="all").reset_index(drop=True)


def empty_temu_input(rows: int = 3) -> pd.DataFrame:
    text_values = [""] * rows
    numeric_values = [None] * rows
    return pd.DataFrame(
        {
            "Product Title": pd.Series(text_values, dtype="string"),
            "Category": pd.Series(text_values, dtype="string"),
            "Price": pd.Series(numeric_values, dtype="Float64"),
            "Original Price": pd.Series(numeric_values, dtype="Float64"),
            "Units Sold": pd.Series(text_values, dtype="string"),
            "Reviews": pd.Series(text_values, dtype="string"),
            "Rating": pd.Series(numeric_values, dtype="Float64"),
            "Discount Percent": pd.Series(numeric_values, dtype="Float64"),
            "Free Shipping": pd.Series([False] * rows, dtype="boolean"),
            "Delivery Days": pd.Series(numeric_values, dtype="Float64"),
            "Image URL": pd.Series(text_values, dtype="string"),
            "Product URL": pd.Series(text_values, dtype="string"),
        }
    )


def temu_csv_template() -> bytes:
    return empty_temu_input(rows=0).to_csv(index=False).encode("utf-8-sig")


def temu_results_csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")
