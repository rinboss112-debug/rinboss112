from __future__ import annotations

import hmac
import json
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from amazon_scraper import (
    PRODUCT_COLUMNS,
    Product,
    scrape_keywords,
    slugify_filename,
    test_amazon_connection,
)
from cloud_storage import GoogleDriveConfig, GoogleDriveStorage
from notifications import send_completion_notifications


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"
RUNS_DIR = OUTPUT_DIR / "runs"

st.set_page_config(
    page_title="Amazon Product Scraper",
    page_icon=":material/shopping_bag:",
    layout="wide",
)


@dataclass(frozen=True, slots=True)
class RunConfig:
    run_id: str
    output_dir: Path
    keywords: list[str]
    zip_code: str
    minimum_price: float | None
    maximum_price: float | None
    max_pages: int
    max_products: int
    only_deliverable: bool
    only_usd: bool
    overwrite_existing: bool
    drive_config: dict[str, Any] = field(default_factory=dict)
    telegram_config: dict[str, Any] = field(default_factory=dict)
    email_config: dict[str, Any] = field(default_factory=dict)

    def public_settings(self) -> dict[str, Any]:
        return {
            "zip_code": self.zip_code,
            "minimum_price": self.minimum_price,
            "maximum_price": self.maximum_price,
            "max_pages": self.max_pages,
            "max_products": self.max_products,
            "only_deliverable": self.only_deliverable,
            "only_usd": self.only_usd,
            "overwrite_existing": self.overwrite_existing,
            "google_drive_enabled": bool(self.drive_config),
        }


@dataclass
class RunController:
    status: str = "Chờ"
    running: bool = False
    stop_requested: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    config: RunConfig | None = None
    current_keyword: str = ""
    completed: int = 0
    total: int = 0
    total_products: int = 0
    errors: int = 0
    logs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    failed_keywords: list[str] = field(default_factory=list)
    niche_counts: dict[str, int] = field(default_factory=dict)
    drive_folder_url: str = ""
    drive_status: str = "Chưa cấu hình"
    archive_path: str = ""
    started_at: str = ""
    finished_at: str = ""
    started_monotonic: float = 0.0
    final_message: str = "Sẵn sàng nhận danh sách ngách."

    def begin(self, config: RunConfig) -> None:
        with self.lock:
            self.config = config
            self.status = "Đang chạy"
            self.running = True
            self.current_keyword = ""
            self.completed = 0
            self.total = len(config.keywords)
            self.total_products = 0
            self.errors = 0
            self.logs = []
            self.warnings = []
            self.results = []
            self.failed_keywords = []
            self.niche_counts = {}
            self.drive_folder_url = ""
            self.drive_status = (
                "Đang kết nối" if config.drive_config else "Chưa cấu hình"
            )
            self.archive_path = ""
            self.started_at = datetime.now().isoformat(timespec="seconds")
            self.finished_at = ""
            self.started_monotonic = time.monotonic()
            self.final_message = "Đang khởi tạo phiên cào..."
            self.stop_requested.clear()

    def add_log(self, message: str) -> None:
        timestamped = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        with self.lock:
            self.logs.append(timestamped)
            self.logs = self.logs[-500:]
            if "CẢNH BÁO:" in message:
                self.warnings.append(message)
                self.warnings = self.warnings[-20:]
            if message.startswith("Bắt đầu ngách '"):
                self.current_keyword = message.removeprefix("Bắt đầu ngách '").removesuffix("'.")

    def set_drive(self, status: str, folder_url: str = "") -> None:
        with self.lock:
            self.drive_status = status
            if folder_url:
                self.drive_folder_url = folder_url

    def set_archive(self, path: Path) -> None:
        with self.lock:
            self.archive_path = str(path)

    def update_progress(
        self,
        completed: int,
        total: int,
        keyword: str,
        result_status: str,
        product_count: int,
    ) -> None:
        with self.lock:
            self.completed = completed
            self.total = total
            self.current_keyword = keyword
            self.niche_counts[keyword] = product_count
            if result_status == "error":
                self.errors += 1
                if keyword not in self.failed_keywords:
                    self.failed_keywords.append(keyword)

    def update_results(
        self,
        _keyword: str,
        _niche_products: list[Product],
        all_products: list[Product],
    ) -> None:
        rows = [product.to_dict() for product in all_products]
        with self.lock:
            self.results = rows
            self.total_products = len(rows)

    def request_stop(self) -> None:
        if not self.stop_requested.is_set():
            self.stop_requested.set()
            self.add_log("Đã yêu cầu dừng. Ngách hiện tại vẫn được hoàn tất và lưu file.")

    def finish(self) -> None:
        with self.lock:
            self.running = False
            self.current_keyword = ""
            self.finished_at = datetime.now().isoformat(timespec="seconds")
            stopped = self.stop_requested.is_set() and self.completed < self.total
            if self.errors:
                self.status = "Có lỗi"
                self.final_message = (
                    f"Đã xử lý {self.completed}/{self.total} ngách; "
                    f"{self.errors} ngách gặp lỗi."
                )
            elif stopped:
                self.status = "Hoàn tất"
                self.final_message = (
                    f"Đã dừng an toàn sau {self.completed}/{self.total} ngách."
                )
            else:
                self.status = "Hoàn tất"
                self.final_message = f"Đã hoàn tất {self.completed}/{self.total} ngách."

    def fail(self, error: BaseException) -> None:
        self.add_log(f"LỖI hệ thống: {error}")
        with self.lock:
            self.running = False
            self.status = "Có lỗi"
            self.errors += 1
            self.current_keyword = ""
            self.finished_at = datetime.now().isoformat(timespec="seconds")
            self.final_message = f"Phiên chạy dừng do lỗi hệ thống: {error}"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            elapsed = (
                max(time.monotonic() - self.started_monotonic, 0.0)
                if self.started_monotonic
                else 0.0
            )
            eta = 0.0
            if self.running and self.completed and self.total > self.completed:
                eta = elapsed / self.completed * (self.total - self.completed)
            return {
                "run_id": self.config.run_id if self.config else "",
                "status": self.status,
                "running": self.running,
                "stop_requested": self.stop_requested.is_set(),
                "current_keyword": self.current_keyword,
                "completed": self.completed,
                "total": self.total,
                "total_products": self.total_products,
                "errors": self.errors,
                "logs": list(self.logs),
                "warnings": list(self.warnings),
                "results": list(self.results),
                "failed_keywords": list(self.failed_keywords),
                "niche_counts": dict(self.niche_counts),
                "drive_folder_url": self.drive_folder_url,
                "drive_status": self.drive_status,
                "archive_path": self.archive_path,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
                "final_message": self.final_message,
            }


def _secrets_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
        return {key: section[key] for key in section}
    except (FileNotFoundError, KeyError):
        return {}


def _require_password() -> None:
    expected = str(_secrets_section("app").get("password", "")).strip()
    if not expected:
        return
    st.session_state.setdefault("app_authenticated", False)
    if st.session_state.app_authenticated:
        return

    with st.container(horizontal_alignment="center"):
        st.title("Amazon Product Scraper", text_alignment="center")
        st.caption("Nhập mật khẩu để sử dụng ứng dụng.", text_alignment="center")
        password = st.text_input(
            "Mật khẩu",
            type="password",
            width=360,
            key="app_password_input",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="app_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.app_authenticated = True
                st.rerun()
            else:
                st.error("Mật khẩu không đúng.", icon=":material/error:")
    st.stop()


def _new_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _unique_lines(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        value = " ".join(line.strip().split())
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def _decode_upload(uploaded_file: Any) -> str:
    raw = uploaded_file.getvalue()
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _collect_keywords(uploaded_file: Any, direct_text: str) -> list[str]:
    uploaded_text = _decode_upload(uploaded_file) if uploaded_file is not None else ""
    return _unique_lines("\n".join((uploaded_text, direct_text)))


def _products_frame_from_models(products: list[Product]) -> pd.DataFrame:
    return pd.DataFrame(
        [product.to_dict() for product in products], columns=PRODUCT_COLUMNS
    )


def _results_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=PRODUCT_COLUMNS)
    if frame.empty:
        return frame
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["delivery_options"] = frame["delivery_options"].fillna("").astype(str)
    for column in (
        "prime",
        "free_shipping",
        "fast_shipping",
        "delivery_available",
        "sponsored",
    ):
        frame[column] = frame[column].fillna(False).astype(bool)
    return frame


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def _format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}g {minutes:02d}p"
    if minutes:
        return f"{minutes}p {secs:02d}s"
    return f"{secs}s"


def _manifest_payload(
    config: RunConfig,
    snapshot: Mapping[str, Any],
    drive_folder_url: str,
) -> dict[str, Any]:
    predicted_status = "Có lỗi" if snapshot["errors"] else "Hoàn tất"
    return {
        "run_id": config.run_id,
        "status": predicted_status,
        "started_at": snapshot["started_at"],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "keywords": config.keywords,
        "failed_keywords": snapshot["failed_keywords"],
        "completed_keywords": snapshot["completed"],
        "total_keywords": snapshot["total"],
        "total_products": snapshot["total_products"],
        "errors": snapshot["errors"],
        "niche_counts": snapshot["niche_counts"],
        "settings": config.public_settings(),
        "drive_folder_url": drive_folder_url,
    }


def _write_manifest(config: RunConfig, payload: Mapping[str, Any]) -> Path:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    path = config.output_dir / "manifest.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def _build_archive(config: RunConfig) -> Path:
    archive_path = config.output_dir / f"{config.run_id}.zip"
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(config.output_dir.iterdir()):
            if path.is_file() and path != archive_path:
                archive.write(path, arcname=path.name)
    return archive_path


def _load_local_history() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not RUNS_DIR.exists():
        return pd.DataFrame()
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows.append(
                {
                    "Phiên": payload.get("run_id", manifest_path.parent.name),
                    "Bắt đầu": payload.get("started_at", ""),
                    "Trạng thái": payload.get("status", ""),
                    "Số ngách": payload.get("total_keywords", 0),
                    "Sản phẩm": payload.get("total_products", 0),
                    "Lỗi": payload.get("errors", 0),
                    "Google Drive": payload.get("drive_folder_url", ""),
                }
            )
        except (OSError, ValueError, TypeError):
            continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Bắt đầu", ascending=False).reset_index(drop=True)


def _sync_drive_result(
    drive: GoogleDriveStorage,
    keyword: str,
    niche_products: list[Product],
    all_products: list[Product],
) -> None:
    niche_frame = _products_frame_from_models(niche_products)
    all_frame = _products_frame_from_models(all_products)
    drive.upsert_bytes(
        f"{slugify_filename(keyword)}.csv",
        _csv_bytes(niche_frame),
        "text/csv",
    )
    drive.upsert_bytes("all_products.csv", _csv_bytes(all_frame), "text/csv")


def _run_job(controller: RunController, config: RunConfig) -> None:
    drive: GoogleDriveStorage | None = None
    try:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        if config.drive_config:
            try:
                drive = GoogleDriveStorage(
                    GoogleDriveConfig.from_mapping(config.drive_config)
                )
                folder_url = drive.begin_run(config.run_id)
                controller.set_drive("Đang đồng bộ", folder_url)
                controller.add_log("Đã tạo thư mục phiên chạy trên Google Drive.")
            except Exception as error:
                drive = None
                controller.set_drive("Kết nối lỗi")
                controller.add_log(
                    f"CẢNH BÁO: Không kết nối được Google Drive ({error}); "
                    "vẫn tiếp tục lưu cục bộ."
                )

        def handle_result(
            keyword: str,
            niche_products: list[Product],
            all_products: list[Product],
        ) -> None:
            controller.update_results(keyword, niche_products, all_products)
            if drive is None:
                return
            try:
                _sync_drive_result(drive, keyword, niche_products, all_products)
                controller.add_log(f"Đã đồng bộ ngách '{keyword}' lên Google Drive.")
            except Exception as error:
                controller.set_drive("Đồng bộ có lỗi", drive.run_folder_url)
                controller.add_log(
                    f"CẢNH BÁO: Không đồng bộ được ngách '{keyword}' lên Drive: {error}"
                )

        scrape_keywords(
            keywords=config.keywords,
            zip_code=config.zip_code,
            minimum_price=config.minimum_price,
            maximum_price=config.maximum_price,
            max_pages=config.max_pages,
            max_products=config.max_products,
            only_deliverable=config.only_deliverable,
            only_usd=config.only_usd,
            output_dir=config.output_dir,
            overwrite_existing=config.overwrite_existing,
            progress_callback=controller.update_progress,
            log_callback=controller.add_log,
            result_callback=handle_result,
            stop_requested_callback=controller.stop_requested.is_set,
        )

        snapshot = controller.snapshot()
        drive_url = drive.run_folder_url if drive else ""
        manifest_payload = _manifest_payload(config, snapshot, drive_url)
        manifest_path = _write_manifest(config, manifest_payload)
        archive_path = _build_archive(config)
        controller.set_archive(archive_path)

        if drive is not None:
            try:
                drive.upload_path(manifest_path, "application/json")
                error_path = config.output_dir / "errors.log"
                if error_path.exists():
                    drive.upload_path(error_path, "text/plain")
                drive.upload_path(archive_path, "application/zip")
                controller.set_drive("Đã đồng bộ", drive.run_folder_url)
                controller.add_log("Đã đồng bộ manifest và file ZIP lên Google Drive.")
            except Exception as error:
                controller.set_drive("Đồng bộ có lỗi", drive.run_folder_url)
                controller.add_log(
                    f"CẢNH BÁO: Không tải được file tổng kết lên Drive: {error}"
                )

        notification_message = (
            f"Amazon Product Scraper hoàn tất phiên {config.run_id}.\n"
            f"Ngách: {snapshot['completed']}/{snapshot['total']}\n"
            f"Sản phẩm: {snapshot['total_products']}\n"
            f"Lỗi: {snapshot['errors']}"
        )
        if drive_url:
            notification_message += f"\nGoogle Drive: {drive_url}"
        for result in send_completion_notifications(
            config.telegram_config,
            config.email_config,
            f"Hoàn tất {config.run_id}",
            notification_message,
        ):
            controller.add_log(result)
        controller.finish()
    except Exception as error:
        controller.fail(error)


def _start_job(config: RunConfig) -> RunController:
    controller = RunController()
    controller.begin(config)
    thread = threading.Thread(
        target=_run_job,
        args=(controller, config),
        name=f"amazon-scraper-{config.run_id}",
        daemon=True,
    )
    controller.thread = thread
    thread.start()
    return controller


def _retry_config(config: RunConfig, keywords: list[str]) -> RunConfig:
    run_id = _new_run_id()
    return replace(
        config,
        run_id=run_id,
        output_dir=RUNS_DIR / run_id,
        keywords=keywords,
    )


def _filter_results(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    with st.container(border=True):
        st.subheader("Bộ lọc kết quả", anchor=False)
        keyword_options = ["Tất cả", *sorted(frame["keyword"].dropna().unique().tolist())]
        filter_row = st.columns([1.8, 1, 1], vertical_alignment="bottom")
        selected_keyword = filter_row[0].selectbox(
            "Tên ngách", keyword_options, key="result_keyword"
        )
        filter_minimum = filter_row[1].number_input(
            "Giá từ (USD)", min_value=0.0, value=0.0, step=1.0, key="result_minimum"
        )
        filter_maximum = filter_row[2].number_input(
            "Giá đến (USD, 0 = không giới hạn)",
            min_value=0.0,
            value=0.0,
            step=1.0,
            key="result_maximum",
        )
        shipping_filters = st.pills(
            "Điều kiện vận chuyển",
            [
                "Free shipping",
                "Fast shipping",
                "Delivery available",
                "Today",
                "Tomorrow",
                "Overnight",
            ],
            selection_mode="multi",
            key="result_shipping_filters",
        ) or []

    filtered = frame.copy()
    if selected_keyword != "Tất cả":
        filtered = filtered[filtered["keyword"] == selected_keyword]
    if filter_minimum > 0:
        filtered = filtered[filtered["price"].notna() & (filtered["price"] >= filter_minimum)]
    if filter_maximum > 0:
        filtered = filtered[filtered["price"].notna() & (filtered["price"] <= filter_maximum)]
    boolean_mapping = {
        "Free shipping": "free_shipping",
        "Fast shipping": "fast_shipping",
        "Delivery available": "delivery_available",
    }
    for label in shipping_filters:
        if label in boolean_mapping:
            filtered = filtered[filtered[boolean_mapping[label]]]
        else:
            filtered = filtered[
                filtered["delivery_options"].str.contains(
                    rf"(?:^|, ){label}(?:, |$)", regex=True, na=False
                )
            ]
    return filtered


def _render_table(frame: pd.DataFrame) -> None:
    display_columns = [
        "image_url",
        "keyword",
        "title",
        "price",
        "delivery_options",
        "delivery_text",
        "rating",
        "review_count",
        "prime",
        "free_shipping",
        "fast_shipping",
        "delivery_available",
        "product_url",
    ]
    st.dataframe(
        frame,
        hide_index=True,
        height=520,
        row_height=72,
        column_order=display_columns,
        column_config={
            "image_url": st.column_config.ImageColumn("Ảnh", width="small"),
            "keyword": st.column_config.TextColumn("Ngách", pinned=True),
            "title": st.column_config.TextColumn("Sản phẩm", width="large"),
            "price": st.column_config.NumberColumn("Giá", format="$%.2f"),
            "delivery_options": st.column_config.TextColumn(
                "Tốc độ giao", width="medium"
            ),
            "delivery_text": st.column_config.TextColumn(
                "Thông tin giao hàng", width="large"
            ),
            "rating": st.column_config.NumberColumn("Đánh giá", format="%.1f ⭐"),
            "review_count": st.column_config.NumberColumn("Lượt đánh giá", format="localized"),
            "prime": st.column_config.CheckboxColumn("Prime"),
            "free_shipping": st.column_config.CheckboxColumn("Free ship"),
            "fast_shipping": st.column_config.CheckboxColumn("Giao nhanh"),
            "delivery_available": st.column_config.CheckboxColumn("Giao được"),
            "product_url": st.column_config.LinkColumn(
                "Mở Amazon", display_text="Mở sản phẩm"
            ),
        },
        key="products_table",
    )


def _render_results_view(full_frame: pd.DataFrame) -> None:
    if full_frame.empty:
        st.caption("Chưa có sản phẩm để hiển thị.")
        return
    filtered_frame = _filter_results(full_frame)
    st.caption(f"Hiển thị {len(filtered_frame):,}/{len(full_frame):,} sản phẩm.")
    _render_table(filtered_frame)
    with st.container(horizontal=True):
        st.download_button(
            "Tải CSV đang lọc",
            data=_csv_bytes(filtered_frame),
            file_name="amazon_products_filtered.csv",
            mime="text/csv",
            icon=":material/download:",
            on_click="ignore",
            disabled=filtered_frame.empty,
        )
        st.download_button(
            "Tải toàn bộ kết quả gộp",
            data=_csv_bytes(full_frame),
            file_name="all_products.csv",
            mime="text/csv",
            type="primary",
            icon=":material/download:",
            on_click="ignore",
        )


def _render_statistics_view(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.caption("Chưa có dữ liệu để thống kê.")
        return
    counts = (
        frame.groupby("keyword", as_index=False)
        .size()
        .rename(columns={"keyword": "Ngách", "size": "Sản phẩm"})
    )
    average_prices = (
        frame.dropna(subset=["price"])
        .groupby("keyword", as_index=False)["price"]
        .mean()
        .rename(columns={"keyword": "Ngách", "price": "Giá trung bình"})
    )
    chart_columns = st.columns(2)
    with chart_columns[0].container(border=True, height="stretch"):
        st.subheader("Sản phẩm theo ngách", anchor=False)
        st.bar_chart(counts, x="Ngách", y="Sản phẩm")
    with chart_columns[1].container(border=True, height="stretch"):
        st.subheader("Giá trung bình", anchor=False)
        if average_prices.empty:
            st.caption("Chưa có sản phẩm có giá.")
        else:
            st.bar_chart(average_prices, x="Ngách", y="Giá trung bình")

    delivery_options = frame["delivery_options"].fillna("").astype(str)
    shipping = pd.DataFrame(
        {
            "Điều kiện": [
                "Free shipping",
                "Fast shipping",
                "Giao được",
                "Today",
                "Tomorrow",
                "Overnight",
            ],
            "Sản phẩm": [
                int(frame["free_shipping"].sum()),
                int(frame["fast_shipping"].sum()),
                int(frame["delivery_available"].sum()),
                int(delivery_options.str.contains(r"(?:^|, )Today(?:, |$)").sum()),
                int(delivery_options.str.contains(r"(?:^|, )Tomorrow(?:, |$)").sum()),
                int(delivery_options.str.contains(r"(?:^|, )Overnight(?:, |$)").sum()),
            ],
        }
    )
    with st.container(border=True):
        st.subheader("Tình trạng vận chuyển", anchor=False)
        st.bar_chart(shipping, x="Điều kiện", y="Sản phẩm")


def _render_history_view() -> None:
    history = _load_local_history()
    if history.empty:
        st.caption("Chưa có lịch sử phiên chạy trên máy chủ hiện tại.")
        return
    st.dataframe(
        history,
        hide_index=True,
        column_config={
            "Google Drive": st.column_config.LinkColumn(
                "Google Drive", display_text="Mở thư mục"
            )
        },
        key="run_history_table",
    )
    st.caption(
        "Lịch sử cục bộ có thể mất khi Streamlit Cloud khởi động lại; "
        "bản CSV/ZIP trên Google Drive vẫn được giữ."
    )


_require_password()
RUNS_DIR.mkdir(parents=True, exist_ok=True)
st.session_state.setdefault("controller", RunController())
controller: RunController = st.session_state.controller
initial_snapshot = controller.snapshot()
if initial_snapshot["running"]:
    st.session_state["monitor_was_running"] = True

drive_secrets = _secrets_section("google_drive")
telegram_secrets = _secrets_section("telegram")
email_secrets = _secrets_section("email")
drive_ready = all(
    str(drive_secrets.get(key, "")).strip()
    for key in ("client_id", "client_secret", "refresh_token")
)

with st.sidebar:
    st.header("Thiết lập phiên cào", anchor=False)
    st.caption("Nguồn ngách từ file TXT và ô nhập sẽ được gộp, tự loại dòng trùng.")
    zip_code = st.text_input("ZIP Code", value="92704", max_chars=10, key="zip_code")
    uploaded_file = st.file_uploader(
        "Tải file TXT chứa danh sách ngách", type=["txt"], key="niches_file"
    )
    direct_text = st.text_area(
        "Hoặc nhập trực tiếp, mỗi dòng một ngách",
        height=140,
        placeholder="halloween outdoor decorations\nkitchen organizer\npet grooming tools",
        key="niches_text",
    )
    keywords = _collect_keywords(uploaded_file, direct_text)
    st.caption(f"Đã nhận {len(keywords)} ngách duy nhất.")

    price_columns = st.columns(2)
    minimum_price_input = price_columns[0].number_input(
        "Giá thấp nhất", min_value=0.0, value=0.0, step=1.0, key="minimum_price"
    )
    maximum_price_input = price_columns[1].number_input(
        "Giá cao nhất", min_value=0.0, value=0.0, step=1.0, key="maximum_price"
    )
    st.caption("Để 0 nếu không muốn đặt giới hạn giá tương ứng.")

    limit_columns = st.columns(2)
    max_pages = limit_columns[0].number_input(
        "Trang/ngách", min_value=1, value=2, step=1, key="max_pages"
    )
    max_products = limit_columns[1].number_input(
        "Sản phẩm/ngách", min_value=1, value=50, step=5, key="max_products"
    )
    only_deliverable = st.checkbox(
        "Chỉ lấy sản phẩm giao được tới ZIP", key="only_deliverable"
    )
    only_usd = st.checkbox("Chỉ lấy sản phẩm có giá USD", key="only_usd")
    file_mode = st.selectbox(
        "Khi file đã tồn tại",
        ["Ghi đè", "Tạo tên có timestamp"],
        key="file_mode",
    )

    with st.container(border=True):
        st.markdown("**Kết nối dịch vụ**")
        if drive_ready:
            st.badge("Google Drive đã cấu hình", color="green")
            if st.button(
                "Kiểm tra Google Drive",
                icon=":material/cloud_done:",
                disabled=initial_snapshot["running"],
                key="test_google_drive",
            ):
                try:
                    with st.spinner("Đang kết nối Google Drive..."):
                        drive_url = GoogleDriveStorage(
                            GoogleDriveConfig.from_mapping(drive_secrets)
                        ).check_connection()
                    st.session_state["drive_test_url"] = drive_url
                    st.success("Kết nối Google Drive thành công.")
                except Exception as error:
                    st.error(f"Kết nối Drive thất bại: {error}")
            if st.session_state.get("drive_test_url"):
                st.link_button(
                    "Mở thư mục Drive",
                    st.session_state.drive_test_url,
                    icon=":material/open_in_new:",
                )
        else:
            st.badge("Google Drive chưa cấu hình", color="orange")
            st.caption("Xem README để tạo OAuth và thêm Streamlit Secrets.")

        if st.button(
            "Kiểm tra kết nối Amazon",
            icon=":material/wifi_tethering:",
            disabled=initial_snapshot["running"],
            key="test_amazon",
        ):
            with st.spinner("Đang kiểm tra Amazon..."):
                ok, message = test_amazon_connection(zip_code)
            if ok:
                st.success(message)
            else:
                st.error(message)

        if telegram_secrets or email_secrets:
            st.caption("Thông báo hoàn tất đã được cấu hình.")

    validation_error = ""
    if not zip_code.strip():
        validation_error = "Vui lòng nhập ZIP Code."
    elif not keywords:
        validation_error = "Vui lòng tải file TXT hoặc nhập ít nhất một ngách."
    elif maximum_price_input > 0 and minimum_price_input > maximum_price_input:
        validation_error = "Giá thấp nhất không được lớn hơn giá cao nhất."

    start_clicked = st.button(
        "Bắt đầu cào sản phẩm",
        type="primary",
        icon=":material/play_arrow:",
        width="stretch",
        disabled=initial_snapshot["running"],
        key="start_scraping",
    )
    if start_clicked:
        if validation_error:
            st.error(validation_error, icon=":material/error:")
        else:
            run_id = _new_run_id()
            config = RunConfig(
                run_id=run_id,
                output_dir=RUNS_DIR / run_id,
                keywords=keywords,
                zip_code=zip_code.strip(),
                minimum_price=minimum_price_input or None,
                maximum_price=maximum_price_input or None,
                max_pages=int(max_pages),
                max_products=int(max_products),
                only_deliverable=only_deliverable,
                only_usd=only_usd,
                overwrite_existing=file_mode == "Ghi đè",
                drive_config=dict(drive_secrets) if drive_ready else {},
                telegram_config=dict(telegram_secrets),
                email_config=dict(email_secrets),
            )
            st.session_state.controller = _start_job(config)
            st.rerun()

    st.caption("Mỗi lần chạy được lưu trong một thư mục riêng.")


st.title("Amazon Product Scraper")
st.caption(
    "Quản lý nhiều ngách, đồng bộ Google Drive và giữ dữ liệu tách biệt theo từng phiên."
)

if keywords and not initial_snapshot["running"]:
    preview = st.expander(
        f"Xem trước {len(keywords)} ngách",
        icon=":material/preview:",
        on_change="rerun",
    )
    if preview.open:
        with preview:
            st.dataframe(
                pd.DataFrame(
                    {"STT": range(1, len(keywords) + 1), "Tên ngách": keywords}
                ),
                hide_index=True,
                key="keyword_preview_table",
            )


@st.fragment(run_every="1s" if initial_snapshot["running"] else None)
def render_live_dashboard() -> None:
    live_controller: RunController = st.session_state.controller
    snapshot = live_controller.snapshot()
    if not snapshot["running"] and st.session_state.get("monitor_was_running", False):
        st.session_state["monitor_was_running"] = False
        st.rerun(scope="app")
    entered_niches = (
        snapshot["total"]
        if snapshot["running"] or snapshot["completed"]
        else len(keywords)
    )

    with st.container(horizontal=True):
        st.metric("Số ngách", entered_niches, border=True)
        st.metric(
            "Tiến độ",
            f"{snapshot['completed']}/{snapshot['total'] or entered_niches}",
            border=True,
        )
        st.metric("Tổng sản phẩm", snapshot["total_products"], border=True)
        st.metric(
            "Thời gian",
            _format_duration(snapshot["elapsed_seconds"]),
            delta=(
                f"Còn khoảng {_format_duration(snapshot['eta_seconds'])}"
                if snapshot["eta_seconds"]
                else None
            ),
            border=True,
        )

    status_colors = {
        "Chờ": "gray",
        "Đang chạy": "blue",
        "Hoàn tất": "green",
        "Có lỗi": "red",
    }
    with st.container(border=True):
        status_row = st.container(
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        )
        with status_row:
            st.badge(snapshot["status"], color=status_colors[snapshot["status"]])
            st.caption(f"Drive: {snapshot['drive_status']}")
            if snapshot["running"]:
                stop_clicked = st.button(
                    "Dừng sau ngách hiện tại",
                    icon=":material/stop_circle:",
                    disabled=snapshot["stop_requested"],
                    key="stop_after_current",
                )
                if stop_clicked:
                    live_controller.request_stop()
                    st.rerun(scope="fragment")

        total = snapshot["total"] or max(entered_niches, 1)
        progress_value = min(snapshot["completed"] / total, 1.0)
        current_text = snapshot["current_keyword"] or snapshot["final_message"]
        st.progress(progress_value, text=f"Ngách hiện tại: {current_text}")
        if snapshot["warnings"]:
            st.warning(snapshot["warnings"][-1], icon=":material/warning:")

        with st.container(horizontal=True):
            if snapshot["drive_folder_url"]:
                st.link_button(
                    "Mở phiên trên Google Drive",
                    snapshot["drive_folder_url"],
                    icon=":material/add_to_drive:",
                )
            archive_path = Path(snapshot["archive_path"]) if snapshot["archive_path"] else None
            if archive_path and archive_path.exists():
                st.download_button(
                    "Tải toàn bộ phiên dạng ZIP",
                    archive_path.read_bytes(),
                    file_name=archive_path.name,
                    mime="application/zip",
                    icon=":material/folder_zip:",
                    on_click="ignore",
                )
            if (
                snapshot["failed_keywords"]
                and not snapshot["running"]
                and live_controller.config is not None
            ):
                if st.button(
                    f"Chạy lại {len(snapshot['failed_keywords'])} ngách lỗi",
                    icon=":material/replay:",
                    key="retry_failed_keywords",
                ):
                    retry = _retry_config(
                        live_controller.config, snapshot["failed_keywords"]
                    )
                    st.session_state.controller = _start_job(retry)
                    st.rerun(scope="app")

    with st.container(border=True):
        st.subheader("Log trực tiếp", anchor=False)
        log_text = "\n".join(snapshot["logs"][-120:]) or "Chưa có log."
        st.code(log_text, language=None, height=230, wrap_lines=True)

    full_frame = _results_frame(snapshot["results"])
    if full_frame.empty and snapshot["running"]:
        st.info(
            "Kết quả sẽ xuất hiện sau khi ngách đầu tiên hoàn tất và được lưu.",
            icon=":material/hourglass_top:",
        )

    view = st.segmented_control(
        "Khu vực dữ liệu",
        ["Kết quả", "Thống kê", "Lịch sử"],
        default="Kết quả",
        key="dashboard_view",
    )
    if view == "Kết quả":
        _render_results_view(full_frame)
    elif view == "Thống kê":
        _render_statistics_view(full_frame)
    else:
        _render_history_view()


render_live_dashboard()
