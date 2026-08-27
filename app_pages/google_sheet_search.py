from __future__ import annotations

import hmac
from typing import Any

import pandas as pd
import streamlit as st

from google_sheet_search import (
    GoogleSheetConfig,
    GoogleSheetConfigurationError,
    GoogleSheetsReader,
    LoadedSpreadsheet,
    SpreadsheetMetadata,
    extract_spreadsheet_id,
    search_title,
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
            "Chưa cấu hình mật khẩu admin. Trang tìm Google Sheets đang được khóa an toàn.",
            icon=":material/lock:",
        )
        st.stop()
    st.session_state.setdefault("admin_authenticated", False)
    if st.session_state.admin_authenticated:
        return
    with st.container(horizontal_alignment="center"):
        st.badge("Chỉ dành cho admin", icon=":material/lock:", color="orange")
        st.title("Đăng nhập để tìm Google Sheets", text_alignment="center")
        password = st.text_input(
            "Mật khẩu admin",
            type="password",
            width=360,
            key="sheet_search_admin_password",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="sheet_search_admin_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("Mật khẩu admin không đúng.")
    st.stop()


def _google_sheets_config() -> dict[str, Any]:
    config = _secrets_section("google_sheets") or _secrets_section("google_drive")
    required = ("client_id", "client_secret", "refresh_token")
    return config if all(str(config.get(key, "")).strip() for key in required) else {}


_require_admin()

st.session_state.setdefault("sheet_search_metadata", None)
st.session_state.setdefault("sheet_search_loaded", None)
st.session_state.setdefault("sheet_search_logs", [])
st.session_state.setdefault("sheet_search_results", [])
st.session_state.setdefault("sheet_search_attempted", False)

with st.container(border=True):
    with st.container(horizontal=True):
        st.badge("Phase 1", icon=":material/filter_1:", color="orange")
        st.badge("Chỉ đọc", icon=":material/visibility:", color="green")
        st.badge("Exact match", icon=":material/check_circle:", color="blue")
    st.title("Tìm sản phẩm trên toàn bộ Google Sheets")
    st.caption(
        "Kết nối một file, load tất cả tab vào RAM một lần rồi tìm exact title mà "
        "không gọi lại Google Sheets API ở mỗi lần search."
    )

config_values = _google_sheets_config()
if not config_values:
    st.warning(
        "Chưa cấu hình `[google_sheets]` hoặc `[google_drive]` trong Streamlit Secrets. "
        "Cần OAuth refresh token có quyền `spreadsheets.readonly`.",
        icon=":material/key:",
    )

with st.container(border=True):
    st.subheader("1. Kết nối file", anchor=False)
    with st.form("sheet_search_connect_form", border=False):
        sheet_input = st.text_input(
            "Google Sheet URL / ID",
            placeholder="https://docs.google.com/spreadsheets/d/.../edit hoặc Sheet ID",
            key="sheet_search_source",
        )
        connect_clicked = st.form_submit_button(
            "CONNECT SHEET",
            type="primary",
            icon=":material/link:",
            disabled=not bool(config_values),
        )

    if connect_clicked:
        try:
            spreadsheet_id = extract_spreadsheet_id(sheet_input)
            config = GoogleSheetConfig.from_mapping(config_values)
            with st.spinner("Đang kết nối và lấy danh sách tab…"):
                metadata = GoogleSheetsReader(config).connect(spreadsheet_id)
            st.session_state.sheet_search_metadata = metadata
            st.session_state.sheet_search_loaded = None
            st.session_state.sheet_search_results = []
            st.session_state.sheet_search_attempted = False
            st.session_state.sheet_search_logs = [
                f"Đã kết nối {metadata.title}: phát hiện {len(metadata.sheet_names)} tab."
            ]
            st.success(
                f"Đã kết nối “{metadata.title}” và tìm thấy {len(metadata.sheet_names)} tab."
            )
        except (ValueError, GoogleSheetConfigurationError) as error:
            st.error(str(error))
        except Exception as error:
            st.error(str(error))

metadata: SpreadsheetMetadata | None = st.session_state.sheet_search_metadata
if metadata:
    st.info(
        f"File đang kết nối: **{metadata.title}** · Sheet ID: `{metadata.spreadsheet_id}` · "
        f"{len(metadata.sheet_names)} tab.",
        icon=":material/table_view:",
    )
    tab_preview = ", ".join(metadata.sheet_names[:12])
    if len(metadata.sheet_names) > 12:
        tab_preview += f", … (+{len(metadata.sheet_names) - 12})"
    st.caption(f"Danh sách tab: {tab_preview or 'Không có tab'}")

with st.container(border=True):
    st.subheader("2. Load toàn bộ tab", anchor=False)
    load_clicked = st.button(
        "LOAD ALL SHEETS",
        type="primary",
        icon=":material/download:",
        disabled=metadata is None or not bool(metadata.sheet_names) or not bool(config_values),
        key="sheet_search_load_all",
    )
    if load_clicked and metadata:
        progress = st.progress(0.0, text="Chuẩn bị load dữ liệu…")
        current = st.empty()
        live_logs: list[str] = []

        def update_progress(done: int, total: int, sheet_name: str) -> None:
            ratio = done / total if total else 1.0
            progress.progress(
                ratio,
                text=f"Đã xử lý {done}/{total} tab",
            )
            current.caption(f"Tab vừa xử lý: {sheet_name}")

        def append_log(message: str) -> None:
            live_logs.append(message)

        try:
            config = GoogleSheetConfig.from_mapping(config_values)
            loaded = GoogleSheetsReader(config).load_all_sheets(
                metadata,
                progress_callback=update_progress,
                log_callback=append_log,
            )
            st.session_state.sheet_search_loaded = loaded
            st.session_state.sheet_search_logs = [
                f"Đã kết nối {metadata.title}: phát hiện {len(metadata.sheet_names)} tab.",
                *live_logs,
            ]
            st.session_state.sheet_search_results = []
            st.session_state.sheet_search_attempted = False
            if loaded.loaded_sheet_count:
                st.success(
                    f"Đã load {loaded.loaded_sheet_count} tab, tổng {loaded.total_rows:,} dòng."
                )
            else:
                st.warning("Không có tab nào load được. Hãy mở log để xem nguyên nhân.")
        except Exception as error:
            st.error(str(error))

loaded: LoadedSpreadsheet | None = st.session_state.sheet_search_loaded
result_count = len(st.session_state.sheet_search_results)
metrics = st.columns(3)
metrics[0].metric("Số sheet đã load", loaded.loaded_sheet_count if loaded else 0)
metrics[1].metric("Tổng số dòng đã đọc", f"{loaded.total_rows:,}" if loaded else "0")
metrics[2].metric("Số kết quả tìm thấy", result_count)

with st.container(border=True):
    st.subheader("3. Tìm Product Title", anchor=False)
    st.caption(
        "Tool exact-match trên mọi ô của mọi tab đã load; không phân biệt hoa/thường và "
        "tự chuẩn hóa khoảng trắng. Không fuzzy match."
    )
    with st.form("sheet_search_title_form", border=False):
        product_title = st.text_input(
            "Product Title",
            placeholder="Nhập nguyên tiêu đề sản phẩm",
            key="sheet_search_title",
        )
        search_clicked = st.form_submit_button(
            "SEARCH TITLE",
            type="primary",
            icon=":material/search:",
            disabled=loaded is None,
        )

    if search_clicked:
        if not product_title.strip():
            st.error("Hãy nhập Product Title.")
        elif loaded is None:
            st.error("Hãy LOAD ALL SHEETS trước khi tìm.")
        else:
            st.session_state.sheet_search_results = search_title(
                loaded.title_index,
                product_title,
            )
            st.session_state.sheet_search_attempted = True

results = st.session_state.sheet_search_results
if st.session_state.sheet_search_attempted:
    if results:
        st.dataframe(
            pd.DataFrame(
                results,
                columns=[
                    "Sheet Name",
                    "Row Number",
                    "Column A",
                    "Column B",
                    "Column C",
                    "Column D",
                ],
            ),
            hide_index=True,
        )
    else:
        st.error("NOT FOUND", icon=":material/search_off:")

logs = st.session_state.sheet_search_logs
if logs:
    with st.expander("Log kết nối và load dữ liệu"):
        st.code("\n".join(logs), language=None)
