from __future__ import annotations

import hmac
from typing import Any

import pandas as pd
import streamlit as st

from temu_hot_products import (
    empty_temu_input,
    filter_temu_products,
    normalize_temu_products,
    read_temu_product_file,
    temu_csv_template,
    temu_results_csv,
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
            "Trang nghiên cứu Temu đang được khóa an toàn.",
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
        st.title("Đăng nhập để nghiên cứu Temu US", text_alignment="center")
        password = st.text_input(
            "Mật khẩu admin",
            type="password",
            width=360,
            key="temu_admin_password",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="temu_admin_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("Mật khẩu admin không đúng.")
    st.stop()


@st.cache_data(max_entries=8, show_spinner=False)
def _read_upload(filename: str, raw: bytes) -> pd.DataFrame:
    return read_temu_product_file(filename, raw)


_require_admin()

with st.container(border=True):
    with st.container(horizontal=True):
        st.badge(
            "Temu US",
            icon=":material/local_fire_department:",
            color="orange",
        )
        st.badge(
            "Dữ liệu được cấp quyền",
            icon=":material/verified_user:",
            color="green",
        )
    st.title("Sản phẩm hot trên Temu US")
    st.caption(
        "Chuẩn hóa dữ liệu Temu được phép sử dụng, lọc sản phẩm từ $20 và "
        "xếp hạng theo tín hiệu bán hàng. Trang này không tự động cào temu.com."
    )

st.info(
    "Điểm hot tối đa 100: số bán 40 điểm, review 20, rating 20, giảm giá 10, "
    "free shipping 5 và tốc độ giao 5. Dữ liệu thiếu không được tự suy đoán.",
    icon=":material/info:",
)

source_mode = st.segmented_control(
    "Nguồn dữ liệu",
    ["Upload CSV/XLSX", "Nhập thủ công"],
    default="Upload CSV/XLSX",
    key="temu_source_mode",
)

source = pd.DataFrame()
source_name = "temu_manual"
if source_mode == "Upload CSV/XLSX":
    with st.container(border=True):
        upload = st.file_uploader(
            "File sản phẩm Temu được phép sử dụng",
            type=["csv", "xlsx"],
            key="temu_source_file",
            help=(
                "Hỗ trợ tên cột phổ biến như Product Title, Category, Price, "
                "Units Sold, Reviews, Rating, Image URL và Product URL."
            ),
        )
        st.download_button(
            "Tải CSV mẫu",
            temu_csv_template(),
            file_name="temu_hot_products_template.csv",
            mime="text/csv",
            icon=":material/download:",
            on_click="ignore",
            key="download_temu_template",
        )
        if upload is not None:
            try:
                source = _read_upload(upload.name, upload.getvalue())
                source_name = upload.name
            except Exception as error:
                st.error(f"Không đọc được file Temu: {error}")
else:
    with st.container(border=True):
        st.caption(
            "Thêm hoặc xóa dòng trực tiếp. Chỉ dùng link và dữ liệu bạn được phép sử dụng."
        )
        source = st.data_editor(
            empty_temu_input(),
            num_rows="dynamic",
            hide_index=True,
            key="temu_manual_input",
            column_config={
                "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                "Original Price": st.column_config.NumberColumn(
                    "Original Price", format="$%.2f"
                ),
                "Rating": st.column_config.NumberColumn(
                    "Rating", min_value=0, max_value=5, format="%.1f"
                ),
                "Free Shipping": st.column_config.CheckboxColumn("Free Shipping"),
                "Image URL": st.column_config.LinkColumn("Image URL"),
                "Product URL": st.column_config.LinkColumn("Product URL"),
            },
        )

try:
    products = normalize_temu_products(source) if not source.empty else pd.DataFrame()
except Exception as error:
    st.error(f"Không chuẩn hóa được dữ liệu Temu: {error}")
    products = pd.DataFrame()

if products.empty:
    metric_columns = st.columns(4)
    metric_columns[0].metric("Dữ liệu đầu vào", 0)
    metric_columns[1].metric("Từ $20", 0)
    metric_columns[2].metric("Điểm từ 50", 0)
    metric_columns[3].metric("Kết quả", 0)
    st.warning(
        "Hãy upload file hoặc nhập sản phẩm thủ công để bắt đầu.",
        icon=":material/upload_file:",
    )
    st.stop()

available_categories = sorted(products["category_group"].dropna().unique().tolist())
with st.container(border=True):
    st.subheader("Bộ lọc sản phẩm", anchor=False)
    filter_row = st.columns([1, 1, 1, 1.4])
    minimum_price = filter_row[0].number_input(
        "Giá thấp nhất (USD)",
        min_value=0.0,
        value=20.0,
        step=1.0,
        format="%.2f",
        key="temu_minimum_price",
    )
    limit_maximum = filter_row[1].toggle(
        "Giới hạn giá cao nhất",
        value=False,
        key="temu_limit_maximum",
    )
    maximum_price = None
    if limit_maximum:
        maximum_price = filter_row[1].number_input(
            "Giá cao nhất (USD)",
            min_value=float(minimum_price),
            value=max(float(minimum_price), 200.0),
            step=5.0,
            format="%.2f",
            key="temu_maximum_price",
        )
    minimum_hot_score = filter_row[2].slider(
        "Điểm hot thấp nhất",
        min_value=0,
        max_value=100,
        value=30,
        step=5,
        key="temu_minimum_hot_score",
    )
    query = filter_row[3].text_input(
        "Tìm theo tên hoặc ngách",
        placeholder="snack, kitchen organizer...",
        key="temu_search_query",
    )
    categories = st.multiselect(
        "Nhóm ngách",
        available_categories,
        default=available_categories,
        key="temu_category_groups",
    )
    require_valid_link = st.checkbox(
        "Chỉ hiện sản phẩm có link Temu hợp lệ",
        value=True,
        key="temu_require_valid_link",
    )

filtered = filter_temu_products(
    products,
    minimum_price=float(minimum_price),
    maximum_price=float(maximum_price) if maximum_price is not None else None,
    minimum_hot_score=float(minimum_hot_score),
    categories=categories,
    query=query,
    require_valid_link=require_valid_link,
)

price_eligible = int(products["price"].ge(float(minimum_price)).sum())
hot_eligible = int(products["hot_score"].ge(50).sum())
metric_columns = st.columns(4)
metric_columns[0].metric("Dữ liệu đầu vào", len(products))
metric_columns[1].metric(f"Từ ${minimum_price:,.0f}", price_eligible)
metric_columns[2].metric("Điểm từ 50", hot_eligible)
metric_columns[3].metric("Kết quả", len(filtered))

if filtered.empty:
    st.warning(
        "Không có sản phẩm phù hợp. Hãy giảm điểm hot hoặc mở rộng nhóm ngách.",
        icon=":material/search_off:",
    )
    st.stop()

display_columns = [
    "image_url",
    "title",
    "category_group",
    "price",
    "discount_percent",
    "units_sold",
    "review_count",
    "rating",
    "free_shipping",
    "delivery_days",
    "hot_score",
    "hot_label",
    "data_quality",
    "product_url",
]
st.dataframe(
    filtered[display_columns],
    hide_index=True,
    column_config={
        "image_url": st.column_config.ImageColumn("Ảnh"),
        "title": st.column_config.TextColumn("Sản phẩm", pinned=True, width="large"),
        "category_group": st.column_config.TextColumn("Nhóm ngách"),
        "price": st.column_config.NumberColumn("Giá", format="$%.2f"),
        "discount_percent": st.column_config.NumberColumn("Giảm", format="%.0f%%"),
        "units_sold": st.column_config.NumberColumn("Đã bán", format="compact"),
        "review_count": st.column_config.NumberColumn("Review", format="compact"),
        "rating": st.column_config.NumberColumn("Rating", format="%.1f"),
        "free_shipping": st.column_config.CheckboxColumn("Free ship"),
        "delivery_days": st.column_config.NumberColumn("Ngày giao", format="%.0f"),
        "hot_score": st.column_config.ProgressColumn(
            "Điểm hot", min_value=0, max_value=100, format="%.1f"
        ),
        "hot_label": st.column_config.TextColumn("Đánh giá"),
        "data_quality": st.column_config.ProgressColumn(
            "Đủ dữ liệu", min_value=0, max_value=100, format="%.0f%%"
        ),
        "product_url": st.column_config.LinkColumn(
            "Mở Temu", display_text="Mở sản phẩm"
        ),
    },
)

safe_name = source_name.rsplit(".", 1)[0].strip() or "temu_hot_products"
st.download_button(
    "Tải danh sách đã lọc",
    temu_results_csv(filtered),
    file_name=f"{safe_name}_hot_filtered.csv",
    mime="text/csv",
    icon=":material/download:",
    on_click="ignore",
    key="download_temu_results",
)
