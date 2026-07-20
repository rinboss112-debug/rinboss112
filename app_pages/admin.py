from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from access_control import AccessControlStore
from niche_catalog import NicheCatalogStore


APP_DIR = Path(__file__).resolve().parents[1]
ACCESS_CONTROL_PATH = APP_DIR / "output" / "access_control.json"
NICHE_CATALOG_PATH = APP_DIR / "output" / "niche_catalog.json"


def _secrets_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
        return {key: section[key] for key in section}
    except (FileNotFoundError, KeyError):
        return {}


def _require_admin() -> dict[str, Any]:
    admin_config = _secrets_section("admin")
    expected = str(admin_config.get("password", "")).strip()
    if not expected:
        st.error(
            "Chưa cấu hình `[admin] password` trong Streamlit Secrets. "
            "Trang quản trị đang bị khóa an toàn.",
            icon=":material/lock:",
        )
        st.stop()

    st.session_state.setdefault("admin_authenticated", False)
    if not st.session_state.admin_authenticated:
        with st.container(horizontal_alignment="center"):
            st.title("Quản trị truy cập", text_alignment="center")
            st.caption(
                "Nhập mật khẩu quản trị. URL này không được hiển thị trong menu.",
                text_alignment="center",
            )
            password = st.text_input(
                "Mật khẩu admin",
                type="password",
                width=360,
                key="admin_password_input",
            )
            if st.button(
                "Đăng nhập quản trị",
                type="primary",
                icon=":material/admin_panel_settings:",
                key="admin_login",
            ):
                if hmac.compare_digest(password, expected):
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("Mật khẩu admin không đúng.")
        st.stop()
    return admin_config


def _drive_config() -> dict[str, Any]:
    config = _secrets_section("google_drive")
    required = ("client_id", "client_secret", "refresh_token")
    return config if all(str(config.get(key, "")).strip() for key in required) else {}


def _rerun_with_message(message: str) -> None:
    st.session_state["admin_flash"] = message
    st.rerun()


admin_config = _require_admin()
drive_config = _drive_config()
store = AccessControlStore(ACCESS_CONTROL_PATH, drive_config)
catalog_store = NicheCatalogStore(NICHE_CATALOG_PATH, drive_config)

try:
    policy = store.load()
except Exception as error:
    st.error(f"Không tải được dữ liệu phân quyền: {error}")
    st.stop()

try:
    niche_catalog = catalog_store.load()
except Exception as error:
    niche_catalog = {"items": []}
    st.warning(f"Chưa tải được danh mục ngách: {error}")

header = st.container(horizontal=True, vertical_alignment="center")
with header:
    st.title("Quản trị truy cập")
    if st.button("Đăng xuất", icon=":material/logout:", key="admin_logout"):
        st.session_state.admin_authenticated = False
        st.rerun()

if message := st.session_state.pop("admin_flash", ""):
    st.success(message)

enforcement_enabled = bool(admin_config.get("enable_access_control", False))
if enforcement_enabled:
    st.success("Trang scraper đang áp dụng mã truy cập và quota.")
else:
    st.warning(
        "Chế độ phân quyền chưa được bật trong Secrets. Thêm "
        "`enable_access_control = true` vào phần `[admin]`, sau đó reboot app."
    )

if drive_config:
    st.caption(
        "Phân quyền được lưu trong `access_control.json` trên Google Drive và có "
        "một bản dự phòng cục bộ."
    )
else:
    st.warning(
        "Google Drive chưa cấu hình. Thay đổi chỉ lưu cục bộ và có thể mất khi "
        "Streamlit Cloud khởi động lại."
    )
if store.last_warning:
    st.warning(store.last_warning)

metrics = st.columns(4)
metrics[0].metric("Quyền cào", "Đang mở" if policy["scraper_enabled"] else "Đã khóa")
metrics[1].metric("Người dùng", len(policy["users"]))
metrics[2].metric("Lượt/ngày", policy["daily_run_limit"])
metrics[3].metric("Ngách/lượt", policy["max_keywords_per_run"])

with st.container(border=True):
    st.subheader("Duyệt ngách đã cào", anchor=False)
    catalog_rows = NicheCatalogStore.admin_rows(niche_catalog)
    if not catalog_rows:
        st.info(
            "Chưa có ngách chờ duyệt. Mỗi ngách cào thành công sẽ tự xuất hiện tại đây."
        )
    else:
        catalog_frame = pd.DataFrame(catalog_rows)
        st.dataframe(
            catalog_frame,
            hide_index=True,
            column_order=[
                "Ngách",
                "Trạng thái",
                "Sản phẩm",
                "Số lần cào",
                "Lần cào gần nhất",
                "Người cào",
                "Google Drive",
            ],
            column_config={
                "Ngách": st.column_config.TextColumn("Ngách", pinned=True),
                "Sản phẩm": st.column_config.NumberColumn("Sản phẩm"),
                "Số lần cào": st.column_config.NumberColumn("Số lần cào"),
                "Google Drive": st.column_config.LinkColumn(
                    "Google Drive", display_text="Mở dữ liệu"
                ),
            },
            key="admin_niche_catalog_table",
        )
        catalog_by_label = {
            f"{row['Ngách']} — {row['Trạng thái']}": row for row in catalog_rows
        }
        selected_catalog_label = st.selectbox(
            "Chọn ngách để duyệt",
            list(catalog_by_label),
            key="admin_selected_niche",
        )
        selected_niche = catalog_by_label[selected_catalog_label]
        is_published = selected_niche["Trạng thái"] == "Đã công khai"
        catalog_actions = st.container(horizontal=True)
        with catalog_actions:
            if st.button(
                "Ẩn khỏi trang chủ" if is_published else "Công khai lên trang chủ",
                type="secondary" if is_published else "primary",
                icon=":material/visibility_off:" if is_published else ":material/publish:",
                key="admin_toggle_niche_publication",
            ):
                try:
                    catalog_store.set_published(selected_niche["id"], not is_published)
                    action = "ẩn" if is_published else "công khai"
                    _rerun_with_message(
                        f"Đã {action} ngách {selected_niche['Ngách']} trên trang chủ."
                    )
                except Exception as error:
                    st.error(str(error))

        confirm_delete_niche = st.checkbox(
            f"Tôi xác nhận xóa ngách {selected_niche['Ngách']} khỏi danh mục",
            key="admin_confirm_delete_niche",
        )
        if st.button(
            "Xóa khỏi danh mục",
            icon=":material/delete:",
            disabled=not confirm_delete_niche,
            key="admin_delete_niche",
        ):
            try:
                catalog_store.delete_item(selected_niche["id"])
                _rerun_with_message(
                    f"Đã xóa ngách {selected_niche['Ngách']} khỏi danh mục."
                )
            except Exception as error:
                st.error(str(error))

    if catalog_store.last_warning:
        st.warning(catalog_store.last_warning)

with st.container(border=True):
    st.subheader("Cài đặt bảo vệ", anchor=False)
    with st.form("admin_policy_form"):
        scraper_enabled = st.toggle(
            "Cho phép người dùng bắt đầu cào",
            value=policy["scraper_enabled"],
        )
        limits = st.columns(2)
        daily_run_limit = limits[0].number_input(
            "Số lượt tối đa/người/ngày",
            min_value=1,
            value=int(policy["daily_run_limit"]),
            step=1,
        )
        max_keywords_per_run = limits[1].number_input(
            "Số ngách tối đa mỗi lượt",
            min_value=1,
            value=int(policy["max_keywords_per_run"]),
            step=1,
        )
        scrape_limits = st.columns(2)
        max_pages_per_niche = scrape_limits[0].number_input(
            "Số trang tối đa mỗi ngách",
            min_value=1,
            value=int(policy["max_pages_per_niche"]),
            step=1,
        )
        max_products_per_niche = scrape_limits[1].number_input(
            "Số sản phẩm tối đa mỗi ngách",
            min_value=1,
            value=int(policy["max_products_per_niche"]),
            step=5,
        )
        save_policy = st.form_submit_button(
            "Lưu cài đặt",
            type="primary",
            icon=":material/save:",
        )
    if save_policy:
        try:
            store.update_settings(
                scraper_enabled=scraper_enabled,
                daily_run_limit=int(daily_run_limit),
                max_keywords_per_run=int(max_keywords_per_run),
                max_pages_per_niche=int(max_pages_per_niche),
                max_products_per_niche=int(max_products_per_niche),
            )
            _rerun_with_message("Đã cập nhật cài đặt bảo vệ.")
        except Exception as error:
            st.error(str(error))

with st.container(border=True):
    st.subheader("Thêm người dùng", anchor=False)
    st.session_state.setdefault("admin_new_access_code", secrets.token_urlsafe(9))
    if st.button(
        "Tạo mã ngẫu nhiên khác",
        icon=":material/key:",
        key="admin_generate_code",
    ):
        st.session_state.admin_new_access_code = secrets.token_urlsafe(9)
        st.rerun()
    with st.form("admin_add_user_form", clear_on_submit=False):
        new_name = st.text_input("Tên người dùng", placeholder="Ví dụ: Nhân viên A")
        new_code = st.text_input(
            "Mã truy cập",
            key="admin_new_access_code",
            help="Mã chỉ hiện rõ tại đây; trên Drive chỉ lưu bản băm bảo mật.",
        )
        add_user = st.form_submit_button(
            "Thêm người dùng",
            type="primary",
            icon=":material/person_add:",
        )
    if add_user:
        try:
            created = store.add_user(new_name, new_code)
            st.session_state["admin_last_created"] = {
                "name": created["name"],
                "code": new_code,
            }
            _rerun_with_message(f"Đã thêm người dùng {created['name']}.")
        except Exception as error:
            st.error(str(error))

if last_created := st.session_state.get("admin_last_created"):
    st.info(
        f"Mã của **{last_created['name']}** — hãy sao chép và gửi riêng cho người đó:"
    )
    st.code(last_created["code"], language=None)

with st.container(border=True):
    st.subheader("Danh sách người dùng", anchor=False)
    rows = AccessControlStore.user_rows(policy)
    if not rows:
        st.info("Chưa có người dùng. Hãy thêm ít nhất một mã trước khi mở quyền cào.")
    else:
        users_frame = pd.DataFrame(rows)
        st.dataframe(
            users_frame,
            hide_index=True,
            column_order=["Tên", "Trạng thái", "Lượt hôm nay", "Ngày tạo"],
            column_config={
                "Tên": st.column_config.TextColumn("Tên", pinned=True),
                "Lượt hôm nay": st.column_config.NumberColumn("Lượt hôm nay"),
            },
            key="admin_users_table",
        )
        user_by_name = {row["Tên"]: row for row in rows}
        selected_name = st.selectbox(
            "Chọn người dùng để quản lý",
            list(user_by_name),
            key="admin_selected_user",
        )
        selected = user_by_name[selected_name]
        selected_is_enabled = selected["Trạng thái"] == "Đang hoạt động"
        actions = st.container(horizontal=True)
        with actions:
            if st.button(
                "Khóa" if selected_is_enabled else "Mở khóa",
                icon=":material/lock:" if selected_is_enabled else ":material/lock_open:",
                key="admin_toggle_user",
            ):
                try:
                    store.set_user_enabled(selected["id"], not selected_is_enabled)
                    _rerun_with_message("Đã cập nhật trạng thái người dùng.")
                except Exception as error:
                    st.error(str(error))
            if st.button(
                "Đặt lại lượt hôm nay",
                icon=":material/restart_alt:",
                key="admin_reset_usage",
            ):
                try:
                    store.reset_today(selected["id"])
                    _rerun_with_message("Đã đặt lại lượt sử dụng hôm nay.")
                except Exception as error:
                    st.error(str(error))

        confirm_delete = st.checkbox(
            f"Tôi xác nhận xóa người dùng {selected_name}",
            key="admin_confirm_delete",
        )
        if st.button(
            "Xóa người dùng",
            icon=":material/delete:",
            disabled=not confirm_delete,
            key="admin_delete_user",
        ):
            try:
                store.delete_user(selected["id"])
                st.session_state.pop("admin_last_created", None)
                _rerun_with_message(f"Đã xóa người dùng {selected_name}.")
            except Exception as error:
                st.error(str(error))

st.caption(
    "Mở trang này trực tiếp bằng `/admin`. Không chia sẻ mật khẩu admin hoặc "
    "nội dung Streamlit Secrets."
)
