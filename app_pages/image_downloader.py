from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st

from image_batch_downloader import (
    MAX_IMAGES_PER_BATCH,
    ImageDownloadResult,
    build_named_image_archive,
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
            "Chưa cấu hình mật khẩu admin. Trang tải ảnh đang được khóa an toàn.",
            icon=":material/lock:",
        )
        st.stop()
    st.session_state.setdefault("admin_authenticated", False)
    if st.session_state.admin_authenticated:
        return
    with st.container(horizontal_alignment="center"):
        st.badge("Chỉ dành cho admin", icon=":material/admin_panel_settings:", color="orange")
        st.title("Đăng nhập để tải ảnh", text_alignment="center")
        password = st.text_input(
            "Mật khẩu admin",
            type="password",
            width=360,
            key="image_downloader_admin_password",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="image_downloader_admin_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("Mật khẩu admin không đúng.")
    st.stop()


@st.cache_data(max_entries=6, show_spinner=False)
def _read_upload(filename: str, raw: bytes) -> pd.DataFrame:
    if filename.casefold().endswith(".xlsx"):
        frame = pd.read_excel(BytesIO(raw))
    else:
        errors: list[str] = []
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                frame = pd.read_csv(BytesIO(raw), encoding=encoding)
                break
            except (UnicodeDecodeError, pd.errors.ParserError) as error:
                errors.append(str(error))
        else:
            raise ValueError(f"Không đọc được CSV: {'; '.join(errors[-2:])}")
    if frame.empty:
        raise ValueError("File không có dòng dữ liệu.")
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.fillna("")


def _clean_rows(frame: pd.DataFrame, name_column: str, url_column: str) -> pd.DataFrame:
    result = frame.copy()
    result[name_column] = result[name_column].fillna("").astype(str).str.strip()
    result[url_column] = result[url_column].fillna("").astype(str).str.strip()
    return result[result[name_column].ne("") | result[url_column].ne("")].reset_index(drop=True)


_require_admin()
st.session_state.setdefault("named_image_download_result", None)
st.session_state.setdefault("named_image_download_filename", "")

with st.container(border=True):
    with st.container(horizontal=True):
        st.badge("Đặt tên tự động", icon=":material/drive_file_rename_outline:", color="orange")
        st.badge("Tải ZIP", icon=":material/folder_zip:", color="blue")
    st.title("Tải ảnh theo tên đã nhập")
    st.caption(
        "Dán hai cột tên và link hoặc tải CSV/XLSX. Tool tải ảnh, đặt đúng tên an toàn "
        "cho Windows và gom vào một file ZIP để tải về máy."
    )

source_mode = st.segmented_control(
    "Nguồn danh sách",
    ["Dán trực tiếp", "Tải CSV/XLSX"],
    default="Dán trực tiếp",
    key="named_image_source_mode",
)

if source_mode == "Tải CSV/XLSX":
    uploaded = st.file_uploader(
        "Chọn file chứa tên và link ảnh",
        type=["csv", "xlsx"],
        key="named_image_upload",
    )
    if uploaded is None:
        st.info("Hãy tải CSV/XLSX lên để chọn cột tên và cột link ảnh.", icon=":material/upload_file:")
        st.stop()
    try:
        source_frame = _read_upload(uploaded.name, uploaded.getvalue())
    except (ValueError, OSError) as error:
        st.error(str(error))
        st.stop()
    column_row = st.container(horizontal=True)
    with column_row:
        name_column = st.selectbox(
            "Cột tên ảnh",
            list(source_frame.columns),
            key="named_image_name_column",
        )
        url_candidates = [
            column for column in source_frame.columns
            if any(word in column.casefold() for word in ("url", "link", "image", "ảnh"))
        ]
        default_url = list(source_frame.columns).index(url_candidates[0]) if url_candidates else 0
        url_column = st.selectbox(
            "Cột link ảnh",
            list(source_frame.columns),
            index=default_url,
            key="named_image_url_column",
        )
    if name_column == url_column:
        st.error("Cột tên ảnh và cột link ảnh phải khác nhau.")
        st.stop()
    working_frame = _clean_rows(source_frame, name_column, url_column)
else:
    template = pd.DataFrame(
        {
            "image_name": pd.Series(["", "", "", "", ""], dtype="string"),
            "image_url": pd.Series(["", "", "", "", ""], dtype="string"),
        }
    )
    st.caption("Có thể copy hai cột từ Excel rồi dán thẳng vào bảng. Thêm hoặc xóa dòng tùy ý.")
    edited = st.data_editor(
        template,
        num_rows="dynamic",
        hide_index=True,
        key="named_image_manual_editor",
        column_config={
            "image_name": st.column_config.TextColumn(
                "Tên ảnh",
                help="Ví dụ: snack_box_01 hoặc snack_box_01.jpg",
                required=True,
                pinned=True,
            ),
            "image_url": st.column_config.LinkColumn(
                "Link ảnh",
                help="Link trực tiếp bắt đầu bằng https://",
                required=True,
            ),
        },
    )
    name_column = "image_name"
    url_column = "image_url"
    working_frame = _clean_rows(edited, name_column, url_column)

if working_frame.empty:
    st.info("Chưa có tên và link ảnh để xử lý.", icon=":material/link:")
    st.stop()

input_signature = hashlib.sha256(
    working_frame[[name_column, url_column]].to_csv(index=False).encode("utf-8")
).hexdigest()
if st.session_state.get("named_image_download_signature") != input_signature:
    st.session_state.named_image_download_result = None
    st.session_state.named_image_download_filename = ""
    st.session_state.named_image_download_signature = input_signature

total = len(working_frame)
missing_names = int(working_frame[name_column].eq("").sum())
missing_urls = int(working_frame[url_column].eq("").sum())
metrics = st.columns(3)
metrics[0].metric("Tổng dòng", total)
metrics[1].metric("Thiếu tên", missing_names)
metrics[2].metric("Thiếu link", missing_urls)

preview = working_frame[[name_column, url_column]].rename(
    columns={name_column: "Tên ảnh", url_column: "Link ảnh"}
)
st.dataframe(
    preview,
    hide_index=True,
    height=min(520, 90 + len(preview) * 35),
    column_config={
        "Tên ảnh": st.column_config.TextColumn("Tên ảnh", pinned=True),
        "Link ảnh": st.column_config.LinkColumn("Link ảnh", display_text="Mở"),
    },
)

if total > MAX_IMAGES_PER_BATCH:
    st.error(f"Mỗi lượt hỗ trợ tối đa {MAX_IMAGES_PER_BATCH} ảnh. Hãy chia file thành nhiều lượt.")
    st.stop()

progress_slot = st.empty()
log_slot = st.empty()
submitted = st.button(
    "Tạo ZIP và tải ảnh",
    type="primary",
    icon=":material/download_for_offline:",
    disabled=bool(missing_names or missing_urls),
    key="build_named_image_zip",
)

if submitted:
    logs: list[str] = []
    progress = progress_slot.progress(0, text="Đang chuẩn bị tải ảnh…")

    def show_progress(processed: int, count: int, image_name: str, status: str) -> None:
        progress.progress(
            processed / count if count else 1.0,
            text=f"Đã xử lý {processed}/{count} — {image_name}: {status}",
        )
        logs.append(f"{processed}. {image_name}: {status}")
        log_slot.code("\n".join(logs[-12:]), language=None)

    try:
        with st.spinner("Đang tải ảnh và đóng gói ZIP…"):
            result = build_named_image_archive(
                working_frame.to_dict(orient="records"),
                name_column=name_column,
                url_column=url_column,
                progress_callback=show_progress,
            )
        st.session_state.named_image_download_result = result
        st.session_state.named_image_download_filename = (
            f"named_images_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        st.session_state.named_image_download_signature = input_signature
    except ValueError as error:
        st.error(str(error))

result: ImageDownloadResult | None = st.session_state.get("named_image_download_result")
if result is not None:
    if result.success_count:
        st.success(
            f"Đã tải thành công {result.success_count} ảnh; lỗi {result.error_count}. "
            "Bấm nút dưới để lưu ZIP về máy."
        )
    else:
        st.error("Không tải được ảnh nào. Xem báo cáo lỗi phía dưới.")

    st.download_button(
        "Tải ZIP ảnh đã đặt tên",
        data=result.archive,
        file_name=st.session_state.named_image_download_filename or "named_images.zip",
        mime="application/zip",
        type="primary",
        icon=":material/folder_zip:",
        key="download_named_image_zip",
    )
    st.subheader("Báo cáo tải ảnh", anchor=False)
    st.dataframe(
        result.report,
        hide_index=True,
        column_config={
            "image_url": st.column_config.LinkColumn("Link ảnh", display_text="Mở"),
            "bytes": st.column_config.NumberColumn("Dung lượng", format="%d B"),
        },
    )

st.caption(
    "Tên có ký tự Windows cấm sẽ được thay bằng dấu gạch dưới. Nếu có hai tên trùng nhau, "
    "tool tự thêm _2, _3 để không ghi đè. ZIP luôn có file _download_report.csv."
)
