from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pandas as pd
import streamlit as st

from amazon_image_enricher import (
    IMAGE_COLUMNS,
    STATUS_COLUMN,
    amazon_images_csv,
    enrich_amazon_product_images,
    enriched_filename,
    pending_image_rows,
    read_amazon_product_csv,
)


def _secrets_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
        return {key: section[key] for key in section}
    except (FileNotFoundError, KeyError):
        return {}


def _require_admin() -> None:
    expected = str(_secrets_section("admin").get("password", "")).strip()
    if not expected:
        st.error(
            "Chưa cấu hình admin password trong Streamlit Secrets. "
            "Trang bổ sung ảnh Amazon đang được khóa an toàn.",
            icon=":material/lock:",
        )
        st.stop()
    st.session_state.setdefault("admin_authenticated", False)
    if st.session_state.admin_authenticated:
        return
    with st.container(horizontal_alignment="center"):
        st.badge(
            "Chỉ dành cho admin",
            icon=":material/admin_panel_settings:",
            color="orange",
        )
        st.title("Đăng nhập để bổ sung ảnh Amazon", text_alignment="center")
        password = st.text_input(
            "Mật khẩu admin",
            type="password",
            width=360,
            key="amazon_images_admin_password",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="amazon_images_admin_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("Mật khẩu admin không đúng.")
    st.stop()


@st.cache_data(max_entries=6, show_spinner=False)
def _read_upload(raw: bytes) -> pd.DataFrame:
    return read_amazon_product_csv(raw)


_require_admin()

with st.container(border=True):
    with st.container(horizontal=True):
        st.badge("Amazon", icon=":material/imagesmode:", color="orange")
        st.badge("Tối đa 5 ảnh / sản phẩm", icon=":material/photo_library:", color="blue")
    st.title("Bổ sung 5 ảnh vào CSV Amazon")
    st.caption(
        "Tải CSV đã cào lên, xử lý theo từng lô nhỏ và tải file mới xuống. "
        "Tool giữ nguyên toàn bộ cột cũ, đồng thời thêm image_url_1 đến image_url_5."
    )

uploaded = st.file_uploader(
    "Chọn file CSV sản phẩm Amazon",
    type=["csv"],
    help="CSV cần có cột asin hoặc product_url.",
)

if uploaded is None:
    st.info(
        "Hãy tải file CSV lên để bắt đầu. Tool không tự gửi yêu cầu đến Amazon "
        "khi bạn chưa bấm nút xử lý.",
        icon=":material/upload_file:",
    )
    st.stop()

raw = uploaded.getvalue()
upload_key = hashlib.sha256(raw).hexdigest()
if st.session_state.get("amazon_images_upload_key") != upload_key:
    try:
        st.session_state.amazon_images_frame = _read_upload(raw)
        st.session_state.amazon_images_upload_key = upload_key
        st.session_state.amazon_images_logs = []
    except ValueError as error:
        st.error(str(error))
        st.stop()

frame: pd.DataFrame = st.session_state.amazon_images_frame
pending = pending_image_rows(frame)
complete = int(
    frame[IMAGE_COLUMNS]
    .apply(lambda row: sum(bool(str(value).strip()) for value in row) >= 5, axis=1)
    .sum()
)
blocked = int(frame[STATUS_COLUMN].eq("blocked").sum())

metric_columns = st.columns(4)
metric_columns[0].metric("Tổng sản phẩm", len(frame))
metric_columns[1].metric("Đủ 5 ảnh", complete)
metric_columns[2].metric("Còn chờ", pending)
metric_columns[3].metric("Bị Amazon chặn", blocked)

with st.form("amazon_images_batch_form", border=True):
    st.subheader("Thiết lập lô xử lý")
    left, right = st.columns(2)
    batch_size = left.number_input(
        "Số sản phẩm trong một lô",
        min_value=1,
        max_value=20,
        value=min(10, max(1, pending)),
        step=1,
        disabled=pending == 0,
    )
    delay_seconds = right.number_input(
        "Khoảng nghỉ giữa sản phẩm (giây)",
        min_value=1.0,
        max_value=8.0,
        value=2.0,
        step=0.5,
        disabled=pending == 0,
        help="Nên giữ từ 2 giây trở lên khi chạy trên Streamlit Cloud.",
    )
    submitted = st.form_submit_button(
        "Lấy tối đa 5 ảnh",
        type="primary",
        icon=":material/add_photo_alternate:",
        disabled=pending == 0,
    )

progress_slot = st.empty()
status_slot = st.empty()

if submitted:
    logs: list[str] = []
    progress_bar = progress_slot.progress(0, text="Đang chuẩn bị...")

    def show_log(message: str) -> None:
        logs.append(message)
        status_slot.code("\n".join(logs[-12:]), language=None)

    def show_progress(processed: int, total: int, row_index: object, status: str) -> None:
        ratio = processed / total if total else 1.0
        progress_bar.progress(
            ratio,
            text=f"Đã xử lý {processed}/{total} — dòng {row_index}: {status}",
        )

    with st.spinner("Đang đọc thư viện ảnh trên trang sản phẩm Amazon..."):
        updated = enrich_amazon_product_images(
            frame,
            batch_size=int(batch_size),
            delay_seconds=float(delay_seconds),
            progress_callback=show_progress,
            log_callback=show_log,
        )
    st.session_state.amazon_images_frame = updated
    st.session_state.amazon_images_logs = logs
    st.rerun()

saved_logs = st.session_state.get("amazon_images_logs", [])
if saved_logs:
    with st.expander("Nhật ký lô gần nhất", expanded=True):
        st.code("\n".join(saved_logs[-20:]), language=None)

if blocked:
    st.warning(
        "Amazon đã chặn ít nhất một yêu cầu trong lô gần nhất. Hãy tải CSV hiện tại "
        "xuống để giữ tiến độ và đợi trước khi xử lý tiếp.",
        icon=":material/shield:",
    )
elif pending == 0:
    st.success("Tất cả sản phẩm đã có đủ 5 link ảnh.")

st.subheader("Xem trước kết quả")
preview_columns = [
    column
    for column in ("keyword", "asin", "title", STATUS_COLUMN, *IMAGE_COLUMNS, "product_url")
    if column in frame.columns
]
column_config: dict[str, Any] = {
    STATUS_COLUMN: st.column_config.TextColumn("Trạng thái"),
    "product_url": st.column_config.LinkColumn("Link Amazon", display_text="Mở"),
}
for position, column in enumerate(IMAGE_COLUMNS, start=1):
    column_config[column] = st.column_config.ImageColumn(
        f"Ảnh {position}",
        width="small",
    )
st.dataframe(
    frame[preview_columns],
    column_config=column_config,
    width="stretch",
    height=520,
    hide_index=True,
)

st.download_button(
    "Tải CSV có 5 cột ảnh",
    data=amazon_images_csv(frame),
    file_name=enriched_filename(uploaded.name),
    mime="text/csv",
    type="primary",
    icon=":material/download:",
)

st.caption(
    "Một số sản phẩm thực tế có ít hơn 5 ảnh hoặc Amazon không gửi đầy đủ thư viện "
    "ảnh cho máy chủ Cloud; các trường hợp đó được đánh dấu partial thay vì tạo link giả."
)
