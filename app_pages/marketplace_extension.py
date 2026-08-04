from __future__ import annotations

from pathlib import Path

import streamlit as st

from amazon_extension_import import build_extension_zip


APP_DIR = Path(__file__).resolve().parents[1]
EXTENSION_DIR = APP_DIR / "browser_extension" / "marketplace_collector"


@st.cache_data(show_spinner=False)
def _extension_package() -> bytes:
    return build_extension_zip(EXTENSION_DIR)


with st.container(border=True):
    with st.container(horizontal=True):
        st.badge("Extension riêng", icon=":material/extension:", color="orange")
        st.badge("Temu US + Amazon", icon=":material/compare_arrows:", color="blue")
    st.title("RinBoss Marketplace Collector")
    st.caption(
        "Extension này cài song song với Amazon Collector cũ. Nó giữ hai kho Temu/Amazon riêng "
        "để tìm sản phẩm Temu giá cao hơn Amazon từ 2–3 lần."
    )

with st.container(border=True):
    st.subheader("Tải và cài đặt", anchor=False)
    st.markdown(
        "1. Tải ZIP và giải nén.\n"
        "2. Mở `chrome://extensions` và bật **Developer mode**.\n"
        "3. Chọn **Load unpacked** rồi chọn thư mục vừa giải nén.\n"
        "4. Ghim **RinBoss Marketplace Collector** lên thanh Chrome."
    )
    try:
        st.download_button(
            "Tải Marketplace Collector 2.0",
            data=_extension_package(),
            file_name="rinboss_marketplace_collector_v2.0.0.zip",
            mime="application/zip",
            icon=":material/download:",
            key="download_marketplace_extension",
        )
    except (OSError, FileNotFoundError) as error:
        st.error(f"Chưa đóng gói được extension: {error}")

steps = st.columns(2)
with steps[0].container(border=True, height="stretch"):
    st.subheader("1. Thu thập Temu US", anchor=False)
    st.markdown(
        "- Chọn **Temu US** trong extension.\n"
        "- Mở `temu.com`.\n"
        "- Nhập TXT, chọn số lượt cuộn và chạy.\n"
        "- Xuất **CSV toàn bộ nguồn**."
    )
with steps[1].container(border=True, height="stretch"):
    st.subheader("2. Thu thập Amazon", anchor=False)
    st.markdown(
        "- Chuyển sang **Amazon**.\n"
        "- Mở `amazon.com` và đặt ZIP.\n"
        "- Chạy lại cùng file TXT.\n"
        "- Xuất CSV Amazon."
    )

with st.container(border=True):
    st.subheader("3. So sánh", anchor=False)
    st.markdown(
        "Mở trang **So sánh Temu–Amazon**, upload hai CSV, sau đó lọc tỷ lệ 2–3x, "
        "độ khớp, số đã bán và lợi nhuận ước tính."
    )

st.warning(
    "Extension không vượt CAPTCHA và không bảo đảm hai listing là cùng một SKU. "
    "Phải kiểm tra lại ảnh, size, pack, thương hiệu và quyền bán trước khi sử dụng.",
    icon=":material/warning:",
)
