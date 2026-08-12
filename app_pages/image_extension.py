from __future__ import annotations

from pathlib import Path

import streamlit as st

from amazon_extension_import import build_extension_zip


APP_DIR = Path(__file__).resolve().parents[1]
EXTENSION_DIR = APP_DIR / "browser_extension" / "product_image_collector"


@st.cache_data(show_spinner=False)
def _extension_package() -> bytes:
    return build_extension_zip(EXTENSION_DIR)


with st.container(border=True):
    with st.container(horizontal=True):
        st.badge("Extension ảnh riêng", icon=":material/imagesmode:", color="orange")
        st.badge("Amazon + Temu", icon=":material/language:", color="blue")
    st.title("RinBoss Product Image Collector")
    st.caption(
        "Nhập CSV đã cào, dùng trình duyệt của bạn để mở từng sản phẩm và bổ sung nhiều "
        "ảnh gallery. Cách này không gửi yêu cầu từ IP Streamlit Cloud."
    )

with st.container(border=True):
    st.subheader("Tải extension", anchor=False)
    st.markdown(
        "1. Tải ZIP và giải nén.\n"
        "2. Mở `chrome://extensions` và bật **Developer mode**.\n"
        "3. Chọn **Load unpacked**, sau đó chọn thư mục vừa giải nén.\n"
        "4. Ghim **RinBoss Product Image Collector** lên thanh Chrome."
    )
    try:
        st.download_button(
            "Tải Product Image Collector 1.1.1",
            data=_extension_package(),
            file_name="rinboss_product_image_collector_v1.1.1.zip",
            mime="application/zip",
            icon=":material/download:",
            key="download_product_image_collector",
        )
    except (OSError, FileNotFoundError) as error:
        st.error(f"Chưa đóng gói được extension: {error}")

steps = st.columns(3)
with steps[0].container(border=True, height="stretch"):
    st.subheader("1. Dán link hoặc nhập CSV", anchor=False)
    st.markdown(
        "Có thể dán trực tiếp tối đa 10 link, mỗi dòng một link. Hoặc nhập CSV có cột "
        "`product_url`, `amazon_url`, `temu_url`, `url`, `link`; Amazon cũng nhận cột `asin`."
    )
with steps[1].container(border=True, height="stretch"):
    st.subheader("2. Lấy gallery", anchor=False)
    st.markdown(
        "Chọn từ 1–10 ảnh và thời gian nghỉ. Extension mở một tab nền, xử lý lần lượt "
        "và cho phép dừng sau sản phẩm hiện tại."
    )
with steps[2].container(border=True, height="stretch"):
    st.subheader("3. Xuất CSV", anchor=False)
    st.markdown(
        "File mới giữ nguyên toàn bộ cột cũ và thêm `image_url_1...`, "
        "`image_gallery_count`, `image_gallery_status`."
    )

with st.container(border=True):
    st.subheader("Trạng thái trong file kết quả", anchor=False)
    st.dataframe(
        {
            "Trạng thái": ["complete", "partial", "no_images", "blocked", "error", "missing_url"],
            "Ý nghĩa": [
                "Đủ số ảnh đã chọn",
                "Có ảnh nhưng chưa đủ",
                "Trang tải được nhưng không tìm thấy gallery",
                "Website yêu cầu CAPTCHA/xác minh",
                "Lỗi riêng ở sản phẩm; extension tiếp tục dòng sau",
                "Dòng không có link/ASIN hợp lệ",
            ],
        },
        hide_index=True,
    )

st.warning(
    "Nên chạy 3–10 link mỗi lượt và để nghỉ 8–15 giây giữa sản phẩm. Extension không vượt CAPTCHA, không đổi IP "
    "và sẽ tự dừng khi website yêu cầu xác minh.",
    icon=":material/warning:",
)
