from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import quote, quote_plus, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


AMAZON_BASE_URL = "https://www.amazon.com"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_DELAY_SECONDS = 1.25

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, str, str, int], None]
ResultCallback = Callable[[str, list["Product"], list["Product"]], None]
StopCallback = Callable[[], bool]


@dataclass(slots=True)
class Product:
    keyword: str
    asin: str
    title: str
    price: float | None
    currency: str | None
    rating: float | None
    review_count: int | None
    prime: bool
    free_shipping: bool
    fast_shipping: bool
    delivery_available: bool
    delivery_options: str
    delivery_detail: str
    image_url: str
    product_url: str
    sponsored: bool
    scraped_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PRODUCT_COLUMNS = [field_name for field_name in Product.__annotations__]
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _log(callback: LogCallback | None, message: str) -> None:
    if callback is None:
        return
    try:
        callback(message)
    except Exception:
        # Logging must never stop a scrape.
        pass


def slugify_filename(value: str) -> str:
    """Create a lowercase, accent-free and Windows-safe filename stem."""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    # Vietnamese đ/Đ are not decomposed by Unicode NFKD.
    without_accents = without_accents.replace("đ", "d").replace("Đ", "D")
    slug = without_accents.lower().strip()
    slug = re.sub(r'[\\/:*?"<>|]+', " ", slug)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("._ ")
    slug = slug[:120].rstrip("._ ") or "niche"
    if slug.upper() in WINDOWS_RESERVED_NAMES:
        slug = f"niche_{slug}"
    return slug


def aggregate_csv_filename(first_keyword: str) -> str:
    """Name the merged CSV after the first niche so runs are easy to recognize."""
    return f"{slugify_filename(first_keyword)}_all_products.csv"


def _timestamped_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    candidate = path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{timestamp}_{counter}{path.suffix}")
        counter += 1
    return candidate


def _products_frame(products: Sequence[Product]) -> pd.DataFrame:
    return pd.DataFrame(
        [product.to_dict() for product in products],
        columns=PRODUCT_COLUMNS,
    )


def save_products_csv(
    products: Sequence[Product],
    destination: Path,
    log_callback: LogCallback | None = None,
) -> Path:
    """Atomically save products, falling back to a timestamp on PermissionError."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.stem}.{uuid.uuid4().hex}.tmp{destination.suffix}"
    )
    frame = _products_frame(products)

    try:
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        try:
            os.replace(temporary, destination)
            return destination
        except PermissionError:
            fallback = _timestamped_path(destination)
            os.replace(temporary, fallback)
            _log(
                log_callback,
                "CẢNH BÁO: Không thể ghi đè "
                f"'{destination.name}' (có thể file đang mở trong Excel). "
                f"Đã lưu thành '{fallback.name}'.",
            )
            return fallback
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _append_error(
    output_dir: Path,
    keyword: str,
    error: BaseException,
    log_callback: LogCallback | None,
) -> Path | None:
    entry = (
        f"[{datetime.now().isoformat(timespec='seconds')}] keyword={keyword!r}\n"
        f"{''.join(traceback.format_exception(type(error), error, error.__traceback__))}\n"
    )
    error_path = output_dir / "errors.log"
    try:
        with error_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        return error_path
    except PermissionError:
        fallback = _timestamped_path(error_path)
        try:
            fallback.write_text(entry, encoding="utf-8")
            _log(
                log_callback,
                "CẢNH BÁO: errors.log đang bị khóa; lỗi được lưu vào "
                f"'{fallback.name}'.",
            )
            return fallback
        except OSError as fallback_error:
            _log(log_callback, f"Không thể ghi nhật ký lỗi: {fallback_error}")
            return None


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
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
            "Cache-Control": "no-cache",
        }
    )
    return session


def _set_delivery_zip(
    session: requests.Session,
    zip_code: str,
    log_callback: LogCallback | None,
) -> bool:
    """Best-effort Amazon delivery location update for a requests session."""
    endpoint = f"{AMAZON_BASE_URL}/gp/delivery/ajax/address-change.html"
    payload = {
        "locationType": "LOCATION_INPUT",
        "zipCode": zip_code,
        "storeContext": "generic",
        "deviceType": "web",
        "pageType": "Gateway",
        "actionSource": "glow",
    }
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Origin": AMAZON_BASE_URL,
        "Referer": f"{AMAZON_BASE_URL}/",
    }
    try:
        session.get(AMAZON_BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
        response = session.post(
            endpoint,
            data=payload,
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        accepted = zip_code in response.text or response.headers.get(
            "content-type", ""
        ).startswith("application/json")
        if accepted:
            _log(log_callback, f"Đã đặt khu vực giao hàng theo ZIP {zip_code}.")
        else:
            _log(
                log_callback,
                f"CẢNH BÁO: Amazon chưa xác nhận ZIP {zip_code}; tiếp tục với vị trí hiện tại.",
            )
        return accepted
    except requests.RequestException as error:
        _log(
            log_callback,
            f"CẢNH BÁO: Không đặt được ZIP {zip_code} ({error}); vẫn tiếp tục cào.",
        )
        return False


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _select_text(node: Tag, selector: str) -> str:
    selected = node.select_one(selector)
    return _clean_text(selected.get_text(" ", strip=True) if selected else "")


def _parse_number(value: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_integer(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _parse_price(card: Tag) -> tuple[float | None, str | None]:
    price_text = _select_text(card, ".a-price .a-offscreen")
    if not price_text:
        whole = _select_text(card, ".a-price-whole").replace(",", "")
        fraction = _select_text(card, ".a-price-fraction")
        if whole:
            price_text = f"{whole}.{fraction or '00'}"
    currency = None
    if "$" in price_text or "USD" in price_text.upper():
        currency = "USD"
    elif "€" in price_text:
        currency = "EUR"
    elif "£" in price_text:
        currency = "GBP"
    return _parse_number(price_text), currency


def _extract_delivery_text(card: Tag) -> str:
    selectors = (
        "[data-cy='delivery-recipe']",
        ".s-delivery-instructions-style",
        ".a-row.a-size-base.a-color-secondary",
    )
    pieces: list[str] = []
    for selector in selectors:
        for node in card.select(selector):
            text = _clean_text(node.get_text(" ", strip=True))
            if text and text not in pieces:
                pieces.append(text)
    return " | ".join(pieces)


def _canonical_product_url(asin: str) -> str:
    """Return a stable Amazon product URL without tracking parameters."""
    return f"{AMAZON_BASE_URL}/dp/{quote(asin.strip(), safe='')}"


def _original_image_url(value: str) -> str:
    """Remove Amazon image-resize directives such as ._AC_UL320_."""
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    image_url = urljoin(AMAZON_BASE_URL, cleaned)
    return re.sub(
        r"\._[^/?]+_(?=\.[a-zA-Z0-9]+(?:[?#]|$))",
        "",
        image_url,
    )


def _extract_delivery_options(delivery_text: str) -> str:
    """Return one of the compact delivery values exposed in CSV and UI."""
    lowered = delivery_text.lower()
    has_today = re.search(r"\btoday\b", lowered) is not None
    has_tomorrow = re.search(r"\btomorrow\b", lowered) is not None
    if re.search(r"\bovernight\b", lowered):
        return "Overnight"
    if has_tomorrow and has_today:
        return "Tomorrow, Today"
    if has_today:
        return "Today"
    if has_tomorrow:
        return "Tomorrow"
    return ""


def _extract_delivery_detail(delivery_text: str) -> str:
    """Keep only the useful Today/Tomorrow/Overnight phrase from Amazon text."""
    if not delivery_text:
        return ""

    overnight = re.search(
        r"\bovernight\b(?:\s+(?:by\s+)?\d{1,2}(?::\d{2})?\s*(?:AM|PM)"
        r"\s*(?:-|–|—|to)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?",
        delivery_text,
        flags=re.IGNORECASE,
    )
    if overnight:
        return _clean_text(overnight.group(0)).replace("–", "-").replace("—", "-")

    matches = re.findall(
        r"\b(?:today|tomorrow)\b(?:,\s*(?:[A-Za-z]+\s+)?\d{1,2})?",
        delivery_text,
        flags=re.IGNORECASE,
    )
    details: list[str] = []
    seen: set[str] = set()
    for match in matches:
        clean = _clean_text(match)
        key = clean.casefold()
        if key not in seen:
            seen.add(key)
            details.append(clean[0].upper() + clean[1:])
    return ", ".join(details)


def _extract_product(card: Tag, keyword: str) -> Product | None:
    asin = _clean_text(card.get("data-asin"))
    title = _select_text(card, "h2 span") or _select_text(card, "h2")
    link = card.select_one("h2 a[href], a.a-link-normal.s-no-outline[href]")
    if not asin or not title or not link:
        return None

    product_url = _canonical_product_url(asin)
    image = card.select_one("img.s-image")
    image_url = _original_image_url(str(image.get("src", ""))) if image else ""
    price, currency = _parse_price(card)
    rating_text = _select_text(card, "i.a-icon-star-small span.a-icon-alt")
    if not rating_text:
        rating_text = _select_text(card, "span.a-icon-alt")
    rating = _parse_number(rating_text)
    review_text = _select_text(card, "span.a-size-base.s-underline-text")
    review_count = _parse_integer(review_text)
    delivery_text = _extract_delivery_text(card)
    delivery_lower = delivery_text.lower()
    delivery_options = _extract_delivery_options(delivery_text)
    delivery_detail = _extract_delivery_detail(delivery_text)
    card_text = _clean_text(card.get_text(" ", strip=True))
    card_lower = card_text.lower()

    unavailable_markers = ("cannot be shipped", "not deliverable", "unavailable")
    has_unavailable_marker = any(marker in delivery_lower for marker in unavailable_markers)
    delivery_available = bool(delivery_text) and not has_unavailable_marker
    free_shipping = "free delivery" in delivery_lower or "free shipping" in delivery_lower
    fast_shipping = bool(delivery_options)
    prime = card.select_one("i.a-icon-prime, [aria-label*='Prime']") is not None
    sponsored = "sponsored" in card_lower

    return Product(
        keyword=keyword,
        asin=asin,
        title=title,
        price=price,
        currency=currency,
        rating=rating,
        review_count=review_count,
        prime=prime,
        free_shipping=free_shipping,
        fast_shipping=fast_shipping,
        delivery_available=delivery_available,
        delivery_options=delivery_options,
        delivery_detail=delivery_detail,
        image_url=image_url,
        product_url=product_url,
        sponsored=sponsored,
        scraped_at=datetime.now().isoformat(timespec="seconds"),
    )


def _looks_blocked(page_text: str) -> bool:
    lowered = page_text.lower()
    return any(
        marker in lowered
        for marker in (
            "enter the characters you see below",
            "sorry, we just need to make sure you're not a robot",
            "automated access to amazon data",
        )
    )


def test_amazon_connection(zip_code: str) -> tuple[bool, str]:
    """Check Amazon reachability and CAPTCHA status without scraping a niche."""
    zip_code = _clean_text(zip_code)
    if not zip_code:
        return False, "ZIP Code không được để trống."
    session = _build_session()
    messages: list[str] = []
    try:
        zip_applied = _set_delivery_zip(session, zip_code, messages.append)
        response = session.get(
            f"{AMAZON_BASE_URL}/s?k=amazon",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if _looks_blocked(response.text):
            return False, "Amazon đang yêu cầu CAPTCHA hoặc chặn IP hiện tại."
        location_note = "ZIP đã được xác nhận" if zip_applied else "ZIP chưa được xác nhận"
        return True, f"Kết nối Amazon thành công; {location_note}."
    except requests.RequestException as error:
        return False, f"Không kết nối được Amazon: {error}"
    finally:
        session.close()


def scrape_keyword(
    keyword: str,
    zip_code: str,
    minimum_price: float | None,
    maximum_price: float | None,
    max_pages: int,
    max_products: int,
    only_deliverable: bool,
    only_usd: bool = False,
    log_callback: LogCallback | None = None,
) -> list[Product]:
    """Scrape one Amazon keyword without interactive input."""
    keyword = _clean_text(keyword)
    zip_code = _clean_text(zip_code)
    if not keyword:
        raise ValueError("Keyword không được để trống.")
    if not zip_code:
        raise ValueError("ZIP Code không được để trống.")
    if max_pages < 1 or max_products < 1:
        raise ValueError("max_pages và max_products phải lớn hơn 0.")
    if (
        minimum_price is not None
        and maximum_price is not None
        and minimum_price > maximum_price
    ):
        raise ValueError("Giá thấp nhất không được lớn hơn giá cao nhất.")

    products: list[Product] = []
    seen_asins: set[str] = set()
    session = _build_session()
    try:
        _log(log_callback, f"Bắt đầu ngách '{keyword}'.")
        _set_delivery_zip(session, zip_code, log_callback)

        for page_number in range(1, max_pages + 1):
            if len(products) >= max_products:
                break
            search_url = (
                f"{AMAZON_BASE_URL}/s?k={quote_plus(keyword)}&page={page_number}"
            )
            _log(log_callback, f"Đang đọc trang {page_number}/{max_pages}...")
            response = session.get(search_url, timeout=DEFAULT_TIMEOUT_SECONDS)
            response.raise_for_status()
            if _looks_blocked(response.text):
                raise RuntimeError(
                    "Amazon yêu cầu xác minh CAPTCHA hoặc đã chặn truy cập tự động."
                )

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.select(
                "[data-component-type='s-search-result'][data-asin]"
            )
            if not cards:
                _log(log_callback, "Không tìm thấy thẻ sản phẩm ở trang này; dừng ngách.")
                break

            accepted_on_page = 0
            for card in cards:
                product = _extract_product(card, keyword)
                if product is None or product.asin in seen_asins:
                    continue
                seen_asins.add(product.asin)
                # This app only publishes genuinely free and urgent delivery offers.
                if not product.free_shipping or not product.delivery_options:
                    continue
                if minimum_price is not None and (
                    product.price is None or product.price < minimum_price
                ):
                    continue
                if maximum_price is not None and (
                    product.price is None or product.price > maximum_price
                ):
                    continue
                if only_deliverable and not product.delivery_available:
                    continue
                if only_usd and product.currency != "USD":
                    continue
                products.append(product)
                accepted_on_page += 1
                if len(products) >= max_products:
                    break

            _log(
                log_callback,
                f"Trang {page_number}: nhận {accepted_on_page} sản phẩm, "
                f"tổng ngách {len(products)}.",
            )
            if page_number < max_pages and len(products) < max_products:
                time.sleep(DEFAULT_DELAY_SECONDS)

        _log(log_callback, f"Hoàn tất '{keyword}': {len(products)} sản phẩm.")
        return products
    finally:
        session.close()


def _unique_keywords(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean_text(value)
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def scrape_keywords(
    keywords: list[str],
    zip_code: str,
    minimum_price: float | None,
    maximum_price: float | None,
    max_pages: int,
    max_products: int,
    only_deliverable: bool,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    log_callback: LogCallback | None = None,
    *,
    only_usd: bool = False,
    overwrite_existing: bool = True,
    result_callback: ResultCallback | None = None,
    stop_requested_callback: StopCallback | None = None,
) -> list[Product]:
    """Scrape keywords sequentially and persist after every completed niche."""
    clean_keywords = _unique_keywords(keywords)
    if not clean_keywords:
        raise ValueError("Danh sách ngách đang trống.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(clean_keywords)
    all_products: list[Product] = []
    aggregate_path = output_dir / aggregate_csv_filename(clean_keywords[0])
    if not overwrite_existing and aggregate_path.exists():
        aggregate_path = _timestamped_path(aggregate_path)

    _log(log_callback, f"Chuẩn bị chạy {total} ngách. Dữ liệu lưu tại: {output_dir}")
    for index, keyword in enumerate(clean_keywords, start=1):
        if index > 1 and stop_requested_callback and stop_requested_callback():
            _log(log_callback, "Đã nhận yêu cầu dừng; không bắt đầu ngách tiếp theo.")
            break

        status = "success"
        niche_products: list[Product] = []
        try:
            niche_products = scrape_keyword(
                keyword=keyword,
                zip_code=zip_code,
                minimum_price=minimum_price,
                maximum_price=maximum_price,
                max_pages=max_pages,
                max_products=max_products,
                only_deliverable=only_deliverable,
                only_usd=only_usd,
                log_callback=log_callback,
            )
            niche_path = output_dir / f"{slugify_filename(keyword)}.csv"
            if not overwrite_existing and niche_path.exists():
                niche_path = _timestamped_path(niche_path)
            saved_niche_path = save_products_csv(
                niche_products, niche_path, log_callback=log_callback
            )
            all_products.extend(niche_products)
            aggregate_path = save_products_csv(
                all_products, aggregate_path, log_callback=log_callback
            )
            _log(
                log_callback,
                f"Đã lưu '{saved_niche_path.name}' và cập nhật "
                f"'{aggregate_path.name}'.",
            )
            if result_callback:
                result_callback(keyword, list(niche_products), list(all_products))
        except Exception as error:
            status = "error"
            _append_error(output_dir, keyword, error, log_callback)
            _log(log_callback, f"LỖI ngách '{keyword}': {error}")
        finally:
            if progress_callback:
                try:
                    progress_callback(index, total, keyword, status, len(niche_products))
                except Exception:
                    pass

        if stop_requested_callback and stop_requested_callback():
            _log(log_callback, "Đã hoàn tất ngách hiện tại và dừng theo yêu cầu.")
            break

    return all_products


def _read_keywords(path: Path) -> list[str]:
    return _unique_keywords(path.read_text(encoding="utf-8-sig").splitlines())


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Amazon product scraper")
    parser.add_argument("--niches", type=Path, default=Path("niches.txt"))
    parser.add_argument("--zip-code", default="92704")
    parser.add_argument("--minimum-price", type=float)
    parser.add_argument("--maximum-price", type=float)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--max-products", type=int, default=50)
    parser.add_argument("--only-deliverable", action="store_true")
    parser.add_argument("--only-usd", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--timestamp-existing",
        action="store_true",
        help="Tạo file có timestamp thay vì ghi đè file đã tồn tại.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_cli_parser().parse_args(argv)
    try:
        keywords = _read_keywords(args.niches)
        products = scrape_keywords(
            keywords=keywords,
            zip_code=args.zip_code,
            minimum_price=args.minimum_price,
            maximum_price=args.maximum_price,
            max_pages=args.max_pages,
            max_products=args.max_products,
            only_deliverable=args.only_deliverable,
            only_usd=args.only_usd,
            output_dir=args.output_dir,
            overwrite_existing=not args.timestamp_existing,
            progress_callback=lambda done, total, keyword, status, count: print(
                f"[{done}/{total}] {keyword}: {status} ({count} sản phẩm)"
            ),
            log_callback=print,
        )
        print(f"Hoàn tất: {len(products)} sản phẩm.")
        return 0
    except Exception as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
