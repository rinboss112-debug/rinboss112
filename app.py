from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from amazon_scraper import PRODUCT_COLUMNS, Product, scrape_keywords


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"

st.set_page_config(
    page_title="Amazon Product Scraper",
    page_icon=":material/shopping_bag:",
    layout="wide",
)


@dataclass(frozen=True, slots=True)
class RunConfig:
    keywords: list[str]
    zip_code: str
    minimum_price: float | None
    maximum_price: float | None
    max_pages: int
    max_products: int
    only_deliverable: bool
    only_usd: bool
    overwrite_existing: bool


@dataclass
class RunController:
    status: str = "Chờ"
    running: bool = False
    stop_requested: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    current_keyword: str = ""
    completed: int = 0
    total: int = 0
    total_products: int = 0
    errors: int = 0
    logs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    final_message: str = "Sẵn sàng nhận danh sách ngách."

    def begin(self, total: int) -> None:
        with self.lock:
            self.status = "Đang chạy"
            self.running = True
            self.current_keyword = ""
            self.completed = 0
            self.total = total
            self.total_products = 0
            self.errors = 0
            self.logs = []
            self.warnings = []
            self.results = []
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

    def update_progress(
        self,
        completed: int,
        total: int,
        keyword: str,
        result_status: str,
        _product_count: int,
    ) -> None:
        with self.lock:
            self.completed = completed
            self.total = total
            self.current_keyword = keyword
            if result_status == "error":
                self.errors += 1

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
            self.final_message = f"Phiên chạy dừng do lỗi hệ thống: {error}"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
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
                "final_message": self.final_message,
            }


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


def _run_job(controller: RunController, config: RunConfig) -> None:
    try:
        scrape_keywords(
            keywords=config.keywords,
            zip_code=config.zip_code,
            minimum_price=config.minimum_price,
            maximum_price=config.maximum_price,
            max_pages=config.max_pages,
            max_products=config.max_products,
            only_deliverable=config.only_deliverable,
            only_usd=config.only_usd,
            output_dir=OUTPUT_DIR,
            overwrite_existing=config.overwrite_existing,
            progress_callback=controller.update_progress,
            log_callback=controller.add_log,
            result_callback=controller.update_results,
            stop_requested_callback=controller.stop_requested.is_set,
        )
        controller.finish()
    except Exception as error:
        controller.fail(error)


def _start_job(config: RunConfig) -> RunController:
    controller = RunController()
    controller.begin(len(config.keywords))
    thread = threading.Thread(
        target=_run_job,
        args=(controller, config),
        name="amazon-scraper-worker",
        daemon=True,
    )
    controller.thread = thread
    thread.start()
    return controller


def _results_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=PRODUCT_COLUMNS)
    if frame.empty:
        return frame
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    for column in (
        "prime",
        "free_shipping",
        "fast_shipping",
        "delivery_available",
        "sponsored",
    ):
        frame[column] = frame[column].fillna(False).astype(bool)
    return frame


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
            ["Free shipping", "Fast shipping", "Delivery available"],
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
    mapping = {
        "Free shipping": "free_shipping",
        "Fast shipping": "fast_shipping",
        "Delivery available": "delivery_available",
    }
    for label in shipping_filters:
        filtered = filtered[filtered[mapping[label]]]
    return filtered


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def _render_table(frame: pd.DataFrame) -> None:
    display_columns = [
        "image_url",
        "keyword",
        "title",
        "price",
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


st.session_state.setdefault("controller", RunController())
controller: RunController = st.session_state.controller
initial_snapshot = controller.snapshot()
if initial_snapshot["running"]:
    st.session_state["monitor_was_running"] = True

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
        "Trang/ngách", min_value=1, max_value=50, value=2, step=1, key="max_pages"
    )
    max_products = limit_columns[1].number_input(
        "Sản phẩm/ngách", min_value=1, max_value=5000, value=50, step=5, key="max_products"
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
            config = RunConfig(
                keywords=keywords,
                zip_code=zip_code.strip(),
                minimum_price=minimum_price_input or None,
                maximum_price=maximum_price_input or None,
                max_pages=int(max_pages),
                max_products=int(max_products),
                only_deliverable=only_deliverable,
                only_usd=only_usd,
                overwrite_existing=file_mode == "Ghi đè",
            )
            st.session_state.controller = _start_job(config)
            st.rerun()

    st.caption(f"File được lưu tại `{OUTPUT_DIR}`")


st.title("Amazon Product Scraper")
st.caption(
    "Quản lý nhiều ngách, theo dõi tiến trình trực tiếp và lưu dữ liệu an toàn sau từng ngách."
)


@st.fragment(run_every="1s" if initial_snapshot["running"] else None)
def render_live_dashboard() -> None:
    live_controller: RunController = st.session_state.controller
    snapshot = live_controller.snapshot()
    if not snapshot["running"] and st.session_state.get("monitor_was_running", False):
        st.session_state["monitor_was_running"] = False
        st.rerun(scope="app")
    entered_niches = snapshot["total"] if snapshot["running"] or snapshot["completed"] else len(keywords)

    with st.container(horizontal=True):
        st.metric("Số ngách", entered_niches, border=True)
        st.metric(
            "Tiến độ",
            f"{snapshot['completed']}/{snapshot['total'] or entered_niches}",
            border=True,
        )
        st.metric("Tổng sản phẩm", snapshot["total_products"], border=True)
        st.metric("Ngách lỗi", snapshot["errors"], border=True)

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

    with st.container(border=True):
        st.subheader("Log trực tiếp", anchor=False)
        log_text = "\n".join(snapshot["logs"][-120:]) or "Chưa có log."
        st.code(log_text, language=None, height=230, wrap_lines=True)

    full_frame = _results_frame(snapshot["results"])
    st.subheader("Kết quả sản phẩm", anchor=False)
    if full_frame.empty:
        if snapshot["running"]:
            st.info(
                "Kết quả sẽ xuất hiện sau khi ngách đầu tiên hoàn tất và được lưu.",
                icon=":material/hourglass_top:",
            )
        else:
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


render_live_dashboard()
