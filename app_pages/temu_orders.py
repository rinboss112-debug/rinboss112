from __future__ import annotations

import hmac
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from temu_orders import (
    ORDER_STATUS_LABELS,
    TemuAPIConfig,
    TemuAPIError,
    TemuOpenAPIClient,
    TemuOrderNoteStore,
    normalize_order_items,
)


APP_DIR = Path(__file__).resolve().parents[1]
NOTES_PATH = APP_DIR / "output" / "temu_order_notes.json"
ORDER_STATUS_OPTIONS = {
    "Tất cả": 0,
    "Chờ xác nhận": 1,
    "Chờ gửi hàng": 2,
    "Đã hủy": 3,
    "Đã gửi hàng": 4,
    "Đã nhận hàng": 5,
    "Đã gửi một phần": 41,
    "Đã nhận một phần": 51,
}
ORDER_LABEL_OPTIONS = {
    "Sắp trễ": "soon_to_be_overdue",
    "Quá hạn": "past_due",
    "Khách yêu cầu hủy": "pending_buyer_cancellation",
    "Khách đổi địa chỉ": "pending_buyer_address_change",
    "Cảnh báo rủi ro": "pending_risk_control_alert",
}


def _secrets_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
        return {key: section[key] for key in section}
    except (FileNotFoundError, KeyError):
        return {}


def _require_admin() -> None:
    admin_config = _secrets_section("admin")
    expected = str(admin_config.get("password", "")).strip()
    if not expected:
        st.error(
            "Chưa cấu hình `[admin] password` trong Streamlit Secrets. "
            "Trang đơn Temu đang bị khóa an toàn.",
            icon=":material/lock:",
        )
        st.stop()
    st.session_state.setdefault("admin_authenticated", False)
    if st.session_state.admin_authenticated:
        return
    with st.container(horizontal_alignment="center"):
        st.badge("Chỉ dành cho admin", icon=":material/lock:", color="orange")
        st.title("Đăng nhập quản lý đơn Temu", text_alignment="center")
        password = st.text_input(
            "Mật khẩu admin",
            type="password",
            width=360,
            key="temu_orders_admin_password",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="temu_orders_admin_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Mật khẩu admin không đúng.")
    st.stop()


def _drive_config() -> dict[str, Any]:
    config = _secrets_section("google_drive")
    required = ("client_id", "client_secret", "refresh_token")
    return config if all(str(config.get(key, "")).strip() for key in required) else {}


def _format_datetime(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%m/%d/%Y %I:%M %p")
    return str(value)


def _display_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Mã đơn": row["parent_order_sn"],
                "Ảnh": row["image_url"],
                "Trạng thái": row["status"],
                "Đơn đã đi chưa": row["shipping_progress"],
                "Đúng hạn/trễ": row["deadline_state"],
                "Hạn gửi": _format_datetime(row["ship_deadline"]),
                "Ngày tạo": _format_datetime(row["order_time"]),
                "Sản phẩm": row["products"],
                "Biến thể": row["variants"],
                "SL": row["quantity"],
                "Fulfillment": row["fulfillment_type"],
                "Cảnh báo": row["warnings"] or row["abnormalities"],
                "Ghi chú": row["note"],
            }
            for row in rows
        ]
    )


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


_require_admin()

st.badge("Temu US Open API", icon=":material/receipt_long:", color="orange")
st.title("Trung tâm đơn hàng Temu US")
st.caption(
    "Kiểm tra đơn mới, theo dõi đã giao đơn vị vận chuyển hay chưa, cảnh báo sắp trễ/quá hạn, "
    "ghi chú nội bộ và lấy nhãn vận chuyển PDF."
)

temu_secret = _secrets_section("temu")
try:
    api_config = TemuAPIConfig.from_mapping(temu_secret)
except ValueError as error:
    st.warning(
        "Chưa kết nối Temu Open API. Hãy thêm `app_key`, `app_secret` và `access_token` "
        "vào phần `[temu]` trong Streamlit Secrets.",
        icon=":material/key:",
    )
    with st.container(border=True):
        st.subheader("Cấu hình cần thêm", anchor=False)
        st.code(
            """[temu]
app_key = "YOUR_TEMU_APP_KEY"
app_secret = "YOUR_TEMU_APP_SECRET"
access_token = "YOUR_TEMU_ACCESS_TOKEN"
endpoint = "https://openapi-b-us.temu.com/openapi/router"
display_timezone = "America/Los_Angeles"
""",
            language="toml",
        )
        st.caption(
            "Không gửi token trong chat và không commit `.streamlit/secrets.toml` lên GitHub. "
            f"Chi tiết hiện tại: {error}"
        )
        st.link_button(
            "Mở Temu Partner Platform",
            "https://partner.temu.com/",
            icon=":material/open_in_new:",
        )
    st.stop()

client = TemuOpenAPIClient(api_config)
drive_config = _drive_config()
note_store = TemuOrderNoteStore(NOTES_PATH, drive_config)
if "temu_order_notes_payload" not in st.session_state:
    st.session_state.temu_order_notes_payload = note_store.load()
notes_payload = st.session_state.temu_order_notes_payload
if note_store.last_warning:
    st.warning(note_store.last_warning)
elif not drive_config:
    st.info(
        "Ghi chú hiện chỉ lưu trên máy chủ hiện tại. Cấu hình Google Drive để ghi chú không mất "
        "khi Streamlit Cloud khởi động lại.",
        icon=":material/cloud_off:",
    )

st.session_state.setdefault("temu_orders_rows", [])
st.session_state.setdefault("temu_orders_fetched_at", "")
st.session_state.setdefault("temu_label_documents", {})
st.session_state.setdefault("temu_order_packages", {})

with st.container(border=True):
    st.subheader("Lấy danh sách đơn", anchor=False)
    st.caption(
        f"Đang dùng máy chủ US · Hiển thị thời gian theo {api_config.display_timezone}. "
        "Bấm nút bên dưới mới gọi API; thay đổi bộ lọc bảng không gọi lại Temu."
    )
    with st.form("temu_orders_query_form"):
        form_row = st.container(horizontal=True, vertical_alignment="bottom")
        with form_row:
            date_range = st.date_input(
                "Khoảng ngày tạo đơn",
                value=(date.today() - timedelta(days=7), date.today()),
                max_value=date.today(),
                key="temu_orders_date_range",
            )
            selected_status = st.selectbox(
                "Trạng thái trên Temu",
                list(ORDER_STATUS_OPTIONS),
                index=0,
                key="temu_orders_api_status",
            )
            selected_labels = st.multiselect(
                "Cảnh báo Temu",
                list(ORDER_LABEL_OPTIONS),
                key="temu_orders_api_labels",
            )
        fetch_orders = st.form_submit_button(
            "Kiểm tra đơn Temu",
            type="primary",
            icon=":material/sync:",
        )

if fetch_orders:
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.error("Hãy chọn đủ ngày bắt đầu và ngày kết thúc.")
    else:
        start_date, end_date = date_range
        if (end_date - start_date).days > 90:
            st.error("Mỗi lần chỉ nên kiểm tra tối đa 90 ngày để tránh vượt giới hạn API Temu.")
        else:
            tz = ZoneInfo(api_config.display_timezone)
            create_after = int(datetime.combine(start_date, time.min, tzinfo=tz).timestamp())
            create_before = int(datetime.combine(end_date, time.max, tzinfo=tz).timestamp())
            try:
                with st.spinner("Đang kiểm tra đơn từ Temu US..."):
                    page_items = client.list_orders(
                        create_after=create_after,
                        create_before=create_before,
                        status_code=ORDER_STATUS_OPTIONS[selected_status],
                        order_labels=[ORDER_LABEL_OPTIONS[value] for value in selected_labels],
                        max_orders=5000,
                    )
                    rows = normalize_order_items(
                        page_items,
                        timezone_name=api_config.display_timezone,
                        notes=notes_payload.get("notes", {}),
                    )
                st.session_state.temu_orders_rows = rows
                st.session_state.temu_orders_fetched_at = datetime.now(tz).strftime(
                    "%m/%d/%Y %I:%M:%S %p"
                )
                st.session_state.temu_label_documents = {}
                st.session_state.temu_order_packages = {}
                st.success(f"Đã nhận {len(rows)} đơn từ Temu.")
            except TemuAPIError as error:
                st.error(str(error))

rows = list(st.session_state.temu_orders_rows)
if not rows:
    st.info("Chưa có dữ liệu. Nhấn **Kiểm tra đơn Temu** để tải danh sách mới nhất.")
    st.stop()

metrics = st.columns(5)
metrics[0].metric("Tổng đơn", len(rows))
metrics[1].metric("Chờ gửi", sum(row["status_code"] == 2 for row in rows))
metrics[2].metric("Sắp trễ", sum(row["deadline_state"] == "Sắp trễ" for row in rows))
metrics[3].metric("Quá hạn", sum(row["deadline_state"] == "Quá hạn" for row in rows))
metrics[4].metric(
    "Đã giao đi",
    sum(row["deadline_state"] == "Đã giao đi" for row in rows),
)
if st.session_state.temu_orders_fetched_at:
    st.caption(f"Cập nhật gần nhất: {st.session_state.temu_orders_fetched_at}")

with st.container(border=True):
    st.subheader("Lọc và chọn đơn", anchor=False)
    filter_row = st.container(horizontal=True, vertical_alignment="bottom")
    with filter_row:
        search_text = st.text_input(
            "Tìm mã đơn hoặc sản phẩm",
            placeholder="Nhập mã PO hoặc tên sản phẩm",
            key="temu_orders_search",
        )
        deadline_filters = st.multiselect(
            "Tình trạng hạn gửi",
            ["Đúng hạn", "Sắp trễ", "Quá hạn", "Đã giao đi", "Đã hủy", "Chưa có hạn gửi"],
            key="temu_orders_deadline_filter",
        )
        progress_filters = st.multiselect(
            "Đơn đã đi chưa",
            sorted({row["shipping_progress"] for row in rows}),
            key="temu_orders_progress_filter",
        )

    filtered_rows = rows
    needle = search_text.strip().casefold()
    if needle:
        filtered_rows = [
            row
            for row in filtered_rows
            if needle in row["parent_order_sn"].casefold()
            or needle in row["products"].casefold()
            or needle in " ".join(row["order_sns"]).casefold()
        ]
    if deadline_filters:
        filtered_rows = [
            row for row in filtered_rows if row["deadline_state"] in deadline_filters
        ]
    if progress_filters:
        filtered_rows = [
            row for row in filtered_rows if row["shipping_progress"] in progress_filters
        ]

    display_frame = _display_frame(filtered_rows)
    event = st.dataframe(
        display_frame,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Mã đơn": st.column_config.TextColumn("Mã đơn", pinned=True),
            "Ảnh": st.column_config.ImageColumn("Ảnh", width="small"),
            "SL": st.column_config.NumberColumn("SL", format="%d"),
        },
        key="temu_orders_table",
    )
    st.download_button(
        "Tải danh sách đang lọc",
        data=_csv_bytes(display_frame),
        file_name="temu_us_orders_filtered.csv",
        mime="text/csv",
        icon=":material/download:",
        key="download_temu_orders_csv",
    )

selected_indices = event.selection.rows
if not selected_indices:
    st.caption("Chọn một dòng trong bảng để ghi chú hoặc lấy nhãn vận chuyển.")
    st.stop()

selected_row = filtered_rows[selected_indices[0]]
order_sn = selected_row["parent_order_sn"]

with st.container(border=True):
    detail_header = st.container(horizontal=True, vertical_alignment="center")
    with detail_header:
        st.subheader(f"Chi tiết {order_sn}", anchor=False)
        st.badge(selected_row["status"], color="orange")
        deadline_color = (
            "red"
            if selected_row["deadline_state"] == "Quá hạn"
            else "orange"
            if selected_row["deadline_state"] == "Sắp trễ"
            else "green"
        )
        st.badge(selected_row["deadline_state"], color=deadline_color)
    detail_metrics = st.columns(4)
    detail_metrics[0].metric("Đơn đã đi chưa", selected_row["shipping_progress"])
    detail_metrics[1].metric("Hạn gửi", _format_datetime(selected_row["ship_deadline"]) or "Chưa có")
    detail_metrics[2].metric("Số lượng", selected_row["quantity"])
    detail_metrics[3].metric("Mã đơn con", len(selected_row["order_sns"]))
    st.write(selected_row["products"] or "Không có tên sản phẩm")
    if selected_row["variants"]:
        st.caption(f"Biến thể: {selected_row['variants']}")
    if selected_row["warnings"] or selected_row["abnormalities"]:
        st.warning(selected_row["warnings"] or selected_row["abnormalities"])

    note_value = st.text_area(
        "Ghi chú nội bộ",
        value=selected_row["note"],
        placeholder="Ví dụ: đã kiểm tra địa chỉ, chờ bổ sung tồn kho...",
        key=f"temu_note_{order_sn}",
    )
    if st.button(
        "Lưu ghi chú",
        type="primary",
        icon=":material/save:",
        key=f"save_temu_note_{order_sn}",
    ):
        try:
            saved_notes = note_store.save_note(order_sn, note_value)
            st.session_state.temu_order_notes_payload = saved_notes
            for row in st.session_state.temu_orders_rows:
                if row["parent_order_sn"] == order_sn:
                    row["note"] = note_value.strip()
            st.success("Đã lưu ghi chú nội bộ.")
        except Exception as error:
            st.error(str(error))

with st.container(border=True):
    st.subheader("Nhãn vận chuyển", anchor=False)
    st.caption(
        "Nhãn chỉ có sau khi đơn đã được tạo kiện thành công bằng kênh vận chuyển tích hợp Temu. "
        "App ưu tiên định dạng PDF theo khuyến nghị của Temu."
    )
    if st.button(
        "Lấy nhãn PDF",
        icon=":material/print:",
        key=f"fetch_temu_label_{order_sn}",
    ):
        try:
            with st.spinner("Đang lấy thông tin kiện và nhãn từ Temu..."):
                packages = client.get_order_packages(
                    parent_order_sn=order_sn,
                    order_sns=selected_row["order_sns"],
                )
                package_sns = [
                    str(item.get("packageSn", "")).strip()
                    for item in packages
                    if str(item.get("packageSn", "")).strip()
                ]
                documents = client.get_shipping_documents(package_sns)
            st.session_state.temu_order_packages[order_sn] = packages
            st.session_state.temu_label_documents[order_sn] = documents
            if not package_sns:
                st.info("Temu chưa trả packageSn cho đơn này; có thể đơn chưa tạo kiện.")
            elif not documents:
                st.info("Đã thấy kiện nhưng Temu chưa trả nhãn in. Hãy thử lại sau.")
        except TemuAPIError as error:
            st.error(str(error))

    packages = st.session_state.temu_order_packages.get(order_sn, [])
    for package in packages:
        package_sn = str(package.get("packageSn", "")).strip() or "Không rõ mã kiện"
        tracking_rows = package.get("trackingInfoList", [])
        tracking_text = ""
        if isinstance(tracking_rows, list):
            tracking_parts = [
                " / ".join(
                    value
                    for value in (
                        str(item.get("shippingCompanyName", "")).strip(),
                        str(item.get("trackingNumber", "")).strip(),
                    )
                    if value
                )
                for item in tracking_rows
                if isinstance(item, dict)
            ]
            tracking_text = " · ".join(value for value in tracking_parts if value)
        if not tracking_text:
            tracking_text = " / ".join(
                value
                for value in (
                    str(package.get("carrierName", "")).strip(),
                    str(package.get("trackingNumber", "")).strip(),
                )
                if value
            )
        st.caption(f"Kiện {package_sn}" + (f" · {tracking_text}" if tracking_text else ""))

    documents = st.session_state.temu_label_documents.get(order_sn, [])
    if documents:
        for position, document in enumerate(documents, start=1):
            label = document["package_sn"] or f"Kiện {position}"
            st.link_button(
                f"Mở / in label PDF · {label}",
                document["url"],
                icon=":material/open_in_new:",
                key=f"temu_label_link_{order_sn}_{position}",
            )

with st.expander("Giải thích dữ liệu"):
    st.markdown(
        "- **Đơn đã đi chưa** lấy từ `parentOrderStatus` chính thức của Temu.\n"
        "- **Hạn gửi** lấy từ `expectShipLatestTime`; `past_due` và `soon_to_be_overdue` "
        "được ưu tiên khi Temu trả nhãn cảnh báo.\n"
        "- **Ghi chú nội bộ** chỉ lưu trong tool/Google Drive, không sửa ghi chú trên Temu.\n"
        "- **Label PDF** lấy qua API nhãn vận chuyển của Temu, không phải label hoàn hàng."
    )
