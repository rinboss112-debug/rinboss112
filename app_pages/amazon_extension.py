from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from amazon_extension_import import (
    ExtensionImportError,
    build_extension_zip,
    read_extension_export,
)
from amazon_scraper import CSV_COLUMNS


APP_DIR = Path(__file__).resolve().parents[1]
EXTENSION_DIR = APP_DIR / "browser_extension" / "amazon_product_collector"


@st.cache_data(show_spinner=False)
def _extension_package() -> bytes:
    return build_extension_zip(EXTENSION_DIR)


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.loc[:, CSV_COLUMNS].to_csv(index=False).encode("utf-8-sig")


st.badge("Chrome Extension", icon=":material/extension:", color="orange")
st.title("Nhập sản phẩm từ Amazon Extension")
st.caption(
    "Thu thập dữ liệu từ trang Amazon đang mở trên máy của bạn, sau đó lọc và tải CSV trong tool."
)

with st.container(border=True):
    st.subheader("Cài extension", anchor=False)
    st.markdown(
        "1. Tải và giải nén gói bên dưới.\n"
        "2. Mở `chrome://extensions` và bật **Developer mode**.\n"
        "3. Chọn **Load unpacked** rồi chọn thư mục vừa giải nén.\n"
        "4. Ghim **RinBoss Amazon Collector** lên thanh công cụ."
    )
    try:
        st.download_button(
            "Tải RinBoss Amazon Collector",
            data=_extension_package(),
            file_name="rinboss_amazon_collector_v1.3.0.zip",
            mime="application/zip",
            icon=":material/download:",
            key="download_amazon_extension",
        )
    except (OSError, FileNotFoundError) as error:
        st.error(f"Chưa đóng gói được extension: {error}")

with st.container(border=True):
    st.subheader("Cách lấy dữ liệu", anchor=False)
    st.markdown(
        "1. Tạo file TXT, mỗi dòng là một ngách; hoặc dán trực tiếp danh sách vào extension.\n"
        "2. Mở `amazon.com`, đặt đúng ZIP rồi mở extension.\n"
        "3. Bấm **Nhập TXT**, chọn số trang cho mỗi ngách và thời gian nghỉ.\n"
        "4. Bấm **Bắt đầu cào danh sách**; extension tự tìm lần lượt và gộp trùng theo ASIN.\n"
        "5. Có thể bấm **Dừng sau trang hiện tại**. Khi hoàn tất, lọc giá/tiêu đề/giao hàng rồi tải **CSV đã lọc** hoặc **CSV toàn bộ**."
    )
    st.info(
        "Amazon Collector 1.3.0 có bộ lọc từ khóa cảnh báo sản phẩm dễ cần hồ sơ Temu US. Bộ lọc chỉ hỗ trợ sàng lọc; hãy kiểm tra yêu cầu category trong Seller Center trước khi đăng.",
        icon=":material/policy:",
    )
    st.warning(
        "Extension tự dừng khi thấy CAPTCHA/Robot Check và không có chức năng vượt chặn. Không nên giảm thời gian nghỉ hoặc chạy danh sách quá lớn.",
        icon=":material/shield:",
    )

uploaded = st.file_uploader(
    "Tải file CSV/JSON từ extension",
    type=["csv", "json"],
    key="amazon_extension_upload",
)
if uploaded is None:
    st.info("Chưa có file. Hãy thu thập một trang Amazon và xuất CSV từ extension.")
    st.stop()

try:
    source_frame = read_extension_export(uploaded.getvalue(), uploaded.name)
except ExtensionImportError as error:
    st.error(str(error))
    st.stop()

if source_frame.empty:
    st.warning("File không có sản phẩm hợp lệ hoặc không đọc được ASIN.")
    st.stop()

metrics = st.columns(4)
metrics[0].metric("Tổng sản phẩm", len(source_frame))
metrics[1].metric("Có giá", int(source_frame["price"].notna().sum()))
metrics[2].metric("Có ship", int(source_frame["delivery_available"].sum()))
metrics[3].metric("Ship nhanh", int(source_frame["fast_shipping"].sum()))

with st.container(border=True):
    st.subheader("Lọc dữ liệu", anchor=False)
    filter_row = st.container(horizontal=True, vertical_alignment="bottom")
    with filter_row:
        title_query = st.text_input(
            "Tìm tiêu đề",
            placeholder="Ví dụ: snack, candy…",
            key="extension_title_query",
        )
        keyword_options = [
            "Tất cả",
            *sorted(value for value in source_frame["keyword"].dropna().unique() if value),
        ]
        keyword = st.selectbox("Ngách", keyword_options, key="extension_keyword")
        minimum = st.number_input(
            "Giá thấp nhất",
            min_value=0.0,
            value=0.0,
            step=1.0,
            key="extension_min_price",
        )
        maximum = st.number_input(
            "Giá cao nhất",
            min_value=0.0,
            value=0.0,
            step=1.0,
            key="extension_max_price",
        )
    flags = st.pills(
        "Điều kiện ship",
        ["Prime", "Free shipping", "Today/Tomorrow/Overnight", "Không Fresh"],
        selection_mode="multi",
        key="extension_shipping_flags",
    ) or []

filtered = source_frame.copy()
needle = title_query.strip().casefold()
if needle:
    filtered = filtered[filtered["title"].str.casefold().str.contains(needle, regex=False)]
if keyword != "Tất cả":
    filtered = filtered[filtered["keyword"] == keyword]
if minimum > 0:
    filtered = filtered[filtered["price"].ge(minimum)]
if maximum > 0:
    filtered = filtered[filtered["price"].le(maximum)]
if "Prime" in flags:
    filtered = filtered[filtered["prime"]]
if "Free shipping" in flags:
    filtered = filtered[filtered["free_shipping"]]
if "Today/Tomorrow/Overnight" in flags:
    filtered = filtered[filtered["fast_shipping"]]
if "Không Fresh" in flags:
    filtered = filtered[
        ~filtered["delivery_options"].str.contains("fresh", case=False, na=False)
    ]

st.caption(f"Đang hiển thị {len(filtered)}/{len(source_frame)} sản phẩm.")
display_columns = [
    "title",
    "image_url",
    "price",
    "variants",
    "delivery_options",
    "keyword",
    "asin",
    "product_url",
]
st.dataframe(
    filtered.loc[:, display_columns],
    hide_index=True,
    column_config={
        "title": st.column_config.TextColumn("Tiêu đề", width="large"),
        "image_url": st.column_config.ImageColumn("Ảnh", width="small"),
        "price": st.column_config.NumberColumn("Giá", format="$%.2f"),
        "variants": st.column_config.TextColumn("Biến thể"),
        "delivery_options": st.column_config.TextColumn("Thời gian giao", width="large"),
        "keyword": st.column_config.TextColumn("Ngách"),
        "asin": st.column_config.TextColumn("ASIN"),
        "product_url": st.column_config.LinkColumn("Mở Amazon", display_text="Mở sản phẩm"),
    },
)
st.download_button(
    "Tải CSV đang lọc",
    data=_csv_bytes(filtered),
    file_name="amazon_extension_filtered.csv",
    mime="text/csv",
    icon=":material/download:",
    disabled=filtered.empty,
    key="download_extension_filtered",
)
