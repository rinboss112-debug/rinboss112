from __future__ import annotations

import hmac
from typing import Any

import pandas as pd
import streamlit as st

from marketplace_gap import (
    MarketplaceImportError,
    compare_marketplaces,
    read_marketplace_export,
    results_csv,
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
        st.error("Chưa cấu hình mật khẩu admin. Trang so sánh đang được khóa an toàn.", icon=":material/lock:")
        st.stop()
    st.session_state.setdefault("admin_authenticated", False)
    if st.session_state.admin_authenticated:
        return
    with st.container(horizontal_alignment="center"):
        st.badge("Chỉ dành cho admin", icon=":material/admin_panel_settings:", color="orange")
        st.title("Đăng nhập để so sánh thị trường", text_alignment="center")
        password = st.text_input("Mật khẩu admin", type="password", width=360, key="gap_admin_password")
        if st.button("Đăng nhập", type="primary", icon=":material/login:", key="gap_admin_login"):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("Mật khẩu admin không đúng.")
    st.stop()


@st.cache_data(max_entries=12, show_spinner=False)
def _read_upload(raw: bytes, filename: str, marketplace: str) -> pd.DataFrame:
    return read_marketplace_export(raw, filename, marketplace)


_require_admin()

with st.container(border=True):
    with st.container(horizontal=True):
        st.badge("TEMU US → AMAZON", icon=":material/compare_arrows:", color="orange")
        st.badge("Duyệt thủ công", icon=":material/fact_check:", color="blue")
    st.title("Tìm khoảng giá 2–3 lần")
    st.caption(
        "Extension thu thập dữ liệu đang hiển thị trên Temu US và Amazon. Tool ghép ứng viên, "
        "tính chênh lệch giá và lợi nhuận ước tính; bạn vẫn cần xác nhận đúng mẫu, size và pack trước khi dùng."
    )

st.info(
    "Tín hiệu “đang bán tốt” chỉ dựa trên số đã bán, review, rating hoặc badge mà Temu hiển thị. "
    "Không có tín hiệu thì tool để trống, không tự đoán doanh số.",
    icon=":material/info:",
)

upload_columns = st.columns(2)
with upload_columns[0].container(border=True):
    st.subheader("1. File Temu US", anchor=False)
    temu_upload = st.file_uploader(
        "CSV/JSON Temu từ extension",
        type=["csv", "json"],
        key="gap_temu_upload",
        help="Trong extension chọn nguồn Temu US, chạy ngách rồi xuất CSV Temu.",
    )
with upload_columns[1].container(border=True):
    st.subheader("2. File Amazon", anchor=False)
    amazon_upload = st.file_uploader(
        "CSV/JSON Amazon từ extension",
        type=["csv", "json"],
        key="gap_amazon_upload",
        help="Nên dùng cùng danh sách ngách để tăng độ chính xác khi ghép.",
    )

if temu_upload is None or amazon_upload is None:
    st.warning("Hãy tải lên đủ hai file Temu US và Amazon để bắt đầu đối chiếu.", icon=":material/upload_file:")
    st.stop()

try:
    temu = _read_upload(temu_upload.getvalue(), temu_upload.name, "temu")
    amazon = _read_upload(amazon_upload.getvalue(), amazon_upload.name, "amazon")
except MarketplaceImportError as error:
    st.error(str(error))
    st.stop()

metrics = st.columns(3)
metrics[0].metric("Sản phẩm Temu", len(temu))
metrics[1].metric("Sản phẩm Amazon", len(amazon))
metrics[2].metric("Có tín hiệu đã bán", int(temu["units_sold"].notna().sum()))

with st.container(border=True):
    st.subheader("Chi phí và điều kiện", anchor=False)
    fields = st.columns(4)
    fee_percent = fields[0].number_input(
        "Phí Temu ước tính (%)", min_value=0.0, max_value=80.0, value=15.0, step=0.5,
        key="gap_fee_percent",
    )
    other_cost = fields[1].number_input(
        "Ship/quảng cáo/chi phí khác ($)", min_value=0.0, value=0.0, step=0.5,
        key="gap_other_cost",
    )
    minimum_ratio = fields[2].number_input(
        "Tỷ lệ thấp nhất", min_value=1.0, value=2.0, step=0.1,
        key="gap_min_ratio",
    )
    maximum_ratio = fields[3].number_input(
        "Tỷ lệ cao nhất", min_value=float(minimum_ratio), value=max(3.0, float(minimum_ratio)), step=0.1,
        key="gap_max_ratio",
    )

    filters = st.columns(4)
    minimum_match = filters[0].slider("Độ khớp tối thiểu", 0, 100, 45, 5, key="gap_min_match")
    minimum_temu_price = filters[1].number_input(
        "Giá Temu tối thiểu ($)", min_value=0.0, value=20.0, step=1.0, key="gap_min_temu_price"
    )
    minimum_sold = filters[2].number_input(
        "Đã bán tối thiểu", min_value=0, value=0, step=10, key="gap_min_sold"
    )
    only_profit = filters[3].toggle("Chỉ lợi nhuận dương", value=True, key="gap_only_profit")

with st.spinner("Đang ghép tiêu đề, size và pack…", show_time=True):
    compared = compare_marketplaces(
        temu,
        amazon,
        temu_fee_percent=float(fee_percent),
        other_cost=float(other_cost),
    )

filtered = compared.copy()
if not filtered.empty:
    filtered = filtered[
        filtered["price_ratio"].between(float(minimum_ratio), float(maximum_ratio), inclusive="both")
        & filtered["match_score"].ge(float(minimum_match))
        & filtered["temu_price"].ge(float(minimum_temu_price))
    ]
    if int(minimum_sold) > 0:
        filtered = filtered[filtered["temu_sold"].fillna(0).ge(int(minimum_sold))]
    if only_profit:
        filtered = filtered[filtered["estimated_profit"].gt(0)]
    filtered = filtered.reset_index(drop=True)

summary = st.columns(4)
summary[0].metric("Cặp đã đối chiếu", len(compared))
summary[1].metric("Đạt bộ lọc", len(filtered))
summary[2].metric(
    "Lợi nhuận ước tính TB",
    f"${filtered['estimated_profit'].mean():,.2f}" if not filtered.empty else "$0.00",
)
summary[3].metric(
    "Độ khớp TB",
    f"{filtered['match_score'].mean():.0f}/100" if not filtered.empty else "0/100",
)

if filtered.empty:
    st.warning("Chưa có cặp nào đạt bộ lọc. Hãy giảm độ khớp hoặc mở rộng khoảng tỷ lệ giá.", icon=":material/search_off:")
    st.stop()

st.subheader("Ứng viên cần duyệt", anchor=False, divider="orange")
event = st.dataframe(
    filtered,
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
    column_order=[
        "temu_image", "temu_title", "temu_price", "temu_sold", "temu_rating", "temu_url",
        "amazon_image", "amazon_title", "amazon_price", "amazon_url", "price_ratio",
        "estimated_profit", "estimated_roi", "match_score", "match_warning", "keyword",
    ],
    column_config={
        "temu_image": st.column_config.ImageColumn("Ảnh Temu", width="small"),
        "temu_title": st.column_config.TextColumn("Tên Temu", width="large", pinned=True),
        "temu_price": st.column_config.NumberColumn("Giá Temu", format="$%.2f"),
        "temu_sold": st.column_config.NumberColumn("Đã bán", format="%.0f"),
        "temu_rating": st.column_config.NumberColumn("Rating", format="%.1f"),
        "temu_url": st.column_config.LinkColumn("Link Temu", display_text="Mở Temu"),
        "amazon_image": st.column_config.ImageColumn("Ảnh Amazon", width="small"),
        "amazon_title": st.column_config.TextColumn("Tên Amazon", width="large"),
        "amazon_price": st.column_config.NumberColumn("Giá Amazon", format="$%.2f"),
        "amazon_url": st.column_config.LinkColumn("Link Amazon", display_text="Mở Amazon"),
        "price_ratio": st.column_config.NumberColumn("Temu/Amazon", format="%.2fx"),
        "estimated_profit": st.column_config.NumberColumn("Lãi ước tính", format="$%.2f"),
        "estimated_roi": st.column_config.NumberColumn("ROI ước tính", format="%.1f%%"),
        "match_score": st.column_config.ProgressColumn("Độ khớp", min_value=0, max_value=100, format="%.0f"),
        "match_warning": st.column_config.TextColumn("Cảnh báo đối chiếu", width="medium"),
        "keyword": st.column_config.TextColumn("Ngách"),
    },
    key="gap_candidate_table",
)

selected_rows = list(event.selection.rows)
selected = filtered.iloc[selected_rows] if selected_rows else pd.DataFrame()
download_columns = st.columns(2)
download_columns[0].download_button(
    "Tải toàn bộ kết quả đang lọc",
    results_csv(filtered),
    file_name="temu_amazon_gap_filtered.csv",
    mime="text/csv",
    icon=":material/download:",
    on_click="ignore",
    key="gap_download_all",
)
download_columns[1].download_button(
    f"Tải {len(selected)} dòng đã chọn",
    results_csv(selected),
    file_name="temu_amazon_gap_selected.csv",
    mime="text/csv",
    icon=":material/check_circle:",
    disabled=selected.empty,
    on_click="ignore",
    key="gap_download_selected",
)

st.warning(
    "Không mua/list tự động từ kết quả này. Hãy mở cả hai link và xác nhận đúng sản phẩm, size, pack, "
    "thương hiệu, quyền bán và tổng chi phí thực tế.",
    icon=":material/warning:",
)
