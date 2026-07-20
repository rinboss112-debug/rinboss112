from __future__ import annotations

import hmac
import io
import secrets
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from access_control import AccessControlStore
from custom_pages import CustomPageStore, clean_dataframe, frame_from_page, records_from_frame
from niche_catalog import NicheCatalogStore


APP_DIR = Path(__file__).resolve().parents[1]
ACCESS_CONTROL_PATH = APP_DIR / "output" / "access_control.json"
NICHE_CATALOG_PATH = APP_DIR / "output" / "niche_catalog.json"
CUSTOM_PAGES_PATH = APP_DIR / "output" / "custom_pages.json"


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
            st.badge(
                "RinBoss Commerce",
                icon=":material/storefront:",
                color="orange",
            )
            st.title("Trung tâm quản trị", text_alignment="center")
            st.caption(
                "Quản lý thành viên, nội dung và dữ liệu bán hàng trong một nơi.",
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
    st.cache_data.clear()
    st.rerun()


def _read_uploaded_table(uploaded_file: Any) -> pd.DataFrame:
    raw = uploaded_file.getvalue()
    suffix = Path(uploaded_file.name).suffix.casefold()
    if suffix == ".xlsx":
        return clean_dataframe(pd.read_excel(io.BytesIO(raw)))
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
        try:
            return clean_dataframe(
                pd.read_csv(
                    io.BytesIO(raw),
                    encoding=encoding,
                    sep=None,
                    engine="python",
                )
            )
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            last_error = error
    raise ValueError(f"Không đọc được file CSV: {last_error}")


def _save_custom_page(
    store: CustomPageStore,
    page_id: str,
    *,
    title: str,
    description: str,
    category_id: str,
    published: bool,
    frame: pd.DataFrame,
    niche_ids: list[str],
) -> None:
    columns, rows = records_from_frame(frame)
    store.update_page(
        page_id,
        title=title,
        description=description,
        category_id=category_id,
        published=published,
        columns=columns,
        rows=rows,
        niche_ids=niche_ids,
    )


admin_config = _require_admin()
drive_config = _drive_config()
store = AccessControlStore(ACCESS_CONTROL_PATH, drive_config)
catalog_store = NicheCatalogStore(NICHE_CATALOG_PATH, drive_config)
custom_store = CustomPageStore(CUSTOM_PAGES_PATH, drive_config)

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

try:
    custom_content = custom_store.load()
except Exception as error:
    custom_content = {"categories": [], "pages": []}
    st.warning(f"Chưa tải được page tùy chỉnh: {error}")

st.badge(
    "RinBoss Commerce",
    icon=":material/storefront:",
    color="orange",
)
header = st.container(horizontal=True, vertical_alignment="center")
with header:
    st.title("Trung tâm quản trị")
    if st.button("Đăng xuất", icon=":material/logout:", key="admin_logout"):
        st.session_state.admin_authenticated = False
        st.rerun()
st.caption("Kiểm soát quyền truy cập, duyệt ngách và tổ chức page dữ liệu bán hàng.")

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
    if drive_config and st.button(
        "Quét các phiên cũ từ Google Drive",
        icon=":material/history:",
        key="admin_import_drive_history",
    ):
        try:
            with st.spinner("Đang đọc manifest của các phiên cũ trên Drive..."):
                scanned_runs, added_niches = catalog_store.import_drive_history()
            _rerun_with_message(
                f"Đã quét {scanned_runs} phiên trên Drive và thêm {added_niches} ngách cũ."
            )
        except Exception as error:
            st.error(f"Không nhập được lịch sử Drive: {error}")
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
    st.subheader("Category, page và bảng dữ liệu", anchor=False)
    st.caption(
        "Tạo page theo category, nhập CSV/XLSX, sửa dữ liệu như Excel và gắn các "
        "ngách đã cào. Chỉ page được công khai mới xuất hiện trên menu trang web."
    )
    overview = st.container(horizontal=True)
    with overview:
        st.metric("Category", len(custom_content.get("categories", [])), border=True)
        st.metric("Page", len(custom_content.get("pages", [])), border=True)
        st.metric(
            "Đang công khai",
            sum(
                1
                for page in custom_content.get("pages", [])
                if page.get("published", False)
            ),
            border=True,
        )

    manager_view = st.segmented_control(
        "Nội dung cần quản lý",
        ["Page và bảng dữ liệu", "Category"],
        default="Page và bảng dữ liệu",
        key="admin_custom_content_view",
    )

    categories = custom_content.get("categories", [])
    category_by_id = {str(item["id"]): item for item in categories}
    category_options = [""] + list(category_by_id)

    def category_label(category_id: str) -> str:
        if not category_id:
            return "Chưa phân loại"
        return str(category_by_id.get(category_id, {}).get("name", "Không xác định"))

    if manager_view == "Category":
        with st.form("admin_create_category_form", clear_on_submit=True):
            new_category_name = st.text_input(
                "Tên category",
                placeholder="Ví dụ: Snack, Nhà bếp, Thú cưng",
            )
            new_category_description = st.text_area(
                "Mô tả category",
                placeholder="Mô tả ngắn để dễ nhớ nội dung bên trong.",
            )
            create_category = st.form_submit_button(
                "Tạo category",
                type="primary",
                icon=":material/create_new_folder:",
            )
        if create_category:
            try:
                created = custom_store.create_category(
                    new_category_name, new_category_description
                )
                _rerun_with_message(f"Đã tạo category {created['name']}.")
            except Exception as error:
                st.error(str(error))

        if not categories:
            st.info("Chưa có category. Hãy tạo category đầu tiên ở phía trên.")
        else:
            selected_category_id = st.selectbox(
                "Chọn category để sửa",
                list(category_by_id),
                format_func=category_label,
                key="admin_selected_custom_category",
            )
            selected_category = category_by_id[selected_category_id]
            category_revision = selected_category.get("updated_at", "")
            with st.form(f"admin_edit_category_{selected_category_id}_{category_revision}"):
                edited_category_name = st.text_input(
                    "Tên category",
                    value=selected_category["name"],
                )
                edited_category_description = st.text_area(
                    "Mô tả category",
                    value=selected_category.get("description", ""),
                )
                update_category = st.form_submit_button(
                    "Lưu category",
                    type="primary",
                    icon=":material/save:",
                )
            if update_category:
                try:
                    custom_store.update_category(
                        selected_category_id,
                        edited_category_name,
                        edited_category_description,
                    )
                    _rerun_with_message("Đã cập nhật category.")
                except Exception as error:
                    st.error(str(error))

            pages_in_category = sum(
                1
                for page in custom_content.get("pages", [])
                if page.get("category_id", "") == selected_category_id
            )
            st.caption(
                f"Category này đang có {pages_in_category} page. Nếu xóa, các page "
                "sẽ chuyển sang Chưa phân loại và không bị mất dữ liệu."
            )
            confirm_delete_category = st.checkbox(
                f"Tôi xác nhận xóa category {selected_category['name']}",
                key=f"admin_confirm_delete_category_{selected_category_id}",
            )
            if st.button(
                "Xóa category",
                icon=":material/delete:",
                disabled=not confirm_delete_category,
                key=f"admin_delete_category_{selected_category_id}",
            ):
                try:
                    custom_store.delete_category(selected_category_id)
                    _rerun_with_message("Đã xóa category; các page được giữ nguyên.")
                except Exception as error:
                    st.error(str(error))

    else:
        with st.form("admin_create_custom_page_form", clear_on_submit=True):
            new_page_title = st.text_input(
                "Tên page mới",
                placeholder="Ví dụ: Snack bán chạy",
            )
            new_page_category = st.selectbox(
                "Category",
                category_options,
                format_func=category_label,
            )
            new_page_description = st.text_area(
                "Mô tả page",
                placeholder="Nội dung giới thiệu hiển thị phía trên bảng.",
            )
            create_page = st.form_submit_button(
                "Tạo page",
                type="primary",
                icon=":material/note_add:",
            )
        if create_page:
            try:
                created = custom_store.create_page(
                    new_page_title,
                    new_page_category,
                    new_page_description,
                )
                st.session_state["admin_selected_custom_page"] = created["id"]
                _rerun_with_message(f"Đã tạo page {created['title']}.")
            except Exception as error:
                st.error(str(error))

        custom_pages = custom_content.get("pages", [])
        if not custom_pages:
            st.info("Chưa có page. Hãy tạo page đầu tiên ở phía trên.")
        else:
            page_by_id = {str(item["id"]): item for item in custom_pages}
            selected_page_id = st.selectbox(
                "Chọn page để chỉnh sửa",
                list(page_by_id),
                format_func=lambda page_id: str(page_by_id[page_id]["title"]),
                key="admin_selected_custom_page",
            )
            selected_page = page_by_id[selected_page_id]
            revision = int(selected_page.get("revision", 1))
            key_prefix = f"custom_page_{selected_page_id}_{revision}"

            st.subheader(selected_page["title"], anchor=False)
            page_title = st.text_input(
                "Tên page",
                value=selected_page["title"],
                key=f"{key_prefix}_title",
            )
            page_description = st.text_area(
                "Mô tả page",
                value=selected_page.get("description", ""),
                key=f"{key_prefix}_description",
            )
            page_category = st.selectbox(
                "Category của page",
                category_options,
                index=category_options.index(selected_page.get("category_id", ""))
                if selected_page.get("category_id", "") in category_options
                else 0,
                format_func=category_label,
                key=f"{key_prefix}_category",
            )
            page_published = st.toggle(
                "Công khai page trên menu trang web",
                value=bool(selected_page.get("published", False)),
                key=f"{key_prefix}_published",
            )

            niche_items = niche_catalog.get("items", [])
            niche_by_id = {str(item["id"]): item for item in niche_items}
            attached_niches = st.multiselect(
                "Gắn các file/ngách đã cào vào page",
                list(niche_by_id),
                default=[
                    niche_id
                    for niche_id in selected_page.get("niche_ids", [])
                    if niche_id in niche_by_id
                ],
                format_func=lambda niche_id: str(
                    niche_by_id[niche_id].get("keyword", "Không xác định")
                ),
                key=f"{key_prefix}_niches",
                help="Các ngách được chọn sẽ hiện kèm link thư mục Google Drive trên page.",
            )

            uploaded_table = st.file_uploader(
                "Nhập dữ liệu từ CSV hoặc Excel",
                type=["csv", "xlsx"],
                key=f"{key_prefix}_upload",
                help="Khi nhập, bảng hiện tại sẽ được thay bằng nội dung của file.",
            )
            confirm_import = st.checkbox(
                "Tôi xác nhận thay bảng hiện tại bằng file đã chọn",
                key=f"{key_prefix}_confirm_import",
                disabled=uploaded_table is None,
            )
            if st.button(
                "Nhập file vào page",
                icon=":material/upload_file:",
                disabled=uploaded_table is None or not confirm_import,
                key=f"{key_prefix}_import",
            ):
                try:
                    imported_frame = _read_uploaded_table(uploaded_table)
                    _save_custom_page(
                        custom_store,
                        selected_page_id,
                        title=page_title,
                        description=page_description,
                        category_id=page_category,
                        published=page_published,
                        frame=imported_frame,
                        niche_ids=attached_niches,
                    )
                    _rerun_with_message(
                        f"Đã nhập {len(imported_frame)} hàng từ {uploaded_table.name}."
                    )
                except Exception as error:
                    st.error(f"Không nhập được file: {error}")

            editor_frame = frame_from_page(selected_page)
            st.markdown("**Sửa trực tiếp bảng dữ liệu**")
            st.caption(
                "Nhấp đúp vào ô để sửa. Dùng nút + dưới bảng để thêm hàng và chọn "
                "hàng rồi xóa trong thanh công cụ của bảng."
            )
            edited_frame = st.data_editor(
                editor_frame,
                num_rows="dynamic",
                hide_index=True,
                height=430,
                key=f"{key_prefix}_editor",
            )

            with st.expander(
                "Quản lý cột",
                icon=":material/view_column:",
                on_change="rerun",
            ) as column_tools:
                if column_tools.open:
                    new_column_name = st.text_input(
                        "Tên cột mới",
                        placeholder="Ví dụ: Trạng thái",
                        key=f"{key_prefix}_new_column",
                    )
                    if st.button(
                        "Thêm cột",
                        icon=":material/add_column_right:",
                        key=f"{key_prefix}_add_column",
                    ):
                        clean_name = new_column_name.strip()
                        if not clean_name:
                            st.error("Vui lòng nhập tên cột.")
                        elif clean_name.casefold() in {
                            str(column).casefold() for column in edited_frame.columns
                        }:
                            st.error("Tên cột đã tồn tại.")
                        else:
                            edited_frame[clean_name] = ""
                            try:
                                _save_custom_page(
                                    custom_store,
                                    selected_page_id,
                                    title=page_title,
                                    description=page_description,
                                    category_id=page_category,
                                    published=page_published,
                                    frame=edited_frame,
                                    niche_ids=attached_niches,
                                )
                                _rerun_with_message(f"Đã thêm cột {clean_name}.")
                            except Exception as error:
                                st.error(str(error))

                    if len(edited_frame.columns):
                        selected_column = st.selectbox(
                            "Cột cần đổi tên hoặc xóa",
                            list(edited_frame.columns),
                            key=f"{key_prefix}_selected_column",
                        )
                        renamed_column = st.text_input(
                            "Tên mới",
                            value=str(selected_column),
                            key=f"{key_prefix}_renamed_column",
                        )
                        column_actions = st.container(horizontal=True)
                        with column_actions:
                            if st.button(
                                "Đổi tên cột",
                                icon=":material/edit:",
                                key=f"{key_prefix}_rename_column",
                            ):
                                clean_name = renamed_column.strip()
                                duplicate = any(
                                    str(column).casefold() == clean_name.casefold()
                                    and str(column) != str(selected_column)
                                    for column in edited_frame.columns
                                )
                                if not clean_name:
                                    st.error("Tên mới không được để trống.")
                                elif duplicate:
                                    st.error("Tên cột mới đã tồn tại.")
                                else:
                                    edited_frame = edited_frame.rename(
                                        columns={selected_column: clean_name}
                                    )
                                    try:
                                        _save_custom_page(
                                            custom_store,
                                            selected_page_id,
                                            title=page_title,
                                            description=page_description,
                                            category_id=page_category,
                                            published=page_published,
                                            frame=edited_frame,
                                            niche_ids=attached_niches,
                                        )
                                        _rerun_with_message("Đã đổi tên cột.")
                                    except Exception as error:
                                        st.error(str(error))

                        confirm_delete_column = st.checkbox(
                            f"Xác nhận xóa cột {selected_column} và toàn bộ dữ liệu của cột",
                            key=f"{key_prefix}_confirm_delete_column",
                        )
                        if st.button(
                            "Xóa cột",
                            icon=":material/delete:",
                            disabled=not confirm_delete_column
                            or len(edited_frame.columns) <= 1,
                            key=f"{key_prefix}_delete_column",
                        ):
                            edited_frame = edited_frame.drop(columns=[selected_column])
                            try:
                                _save_custom_page(
                                    custom_store,
                                    selected_page_id,
                                    title=page_title,
                                    description=page_description,
                                    category_id=page_category,
                                    published=page_published,
                                    frame=edited_frame,
                                    niche_ids=attached_niches,
                                )
                                _rerun_with_message("Đã xóa cột.")
                            except Exception as error:
                                st.error(str(error))

            if st.button(
                "Lưu page và bảng dữ liệu",
                type="primary",
                icon=":material/save:",
                key=f"{key_prefix}_save_page",
            ):
                try:
                    _save_custom_page(
                        custom_store,
                        selected_page_id,
                        title=page_title,
                        description=page_description,
                        category_id=page_category,
                        published=page_published,
                        frame=edited_frame,
                        niche_ids=attached_niches,
                    )
                    _rerun_with_message("Đã lưu page và bảng dữ liệu lên Google Drive.")
                except Exception as error:
                    st.error(str(error))

            st.caption(
                f"Đường dẫn sau khi công khai: /{selected_page.get('slug', '')}"
            )
            confirm_delete_page = st.checkbox(
                f"Tôi xác nhận xóa vĩnh viễn page {selected_page['title']}",
                key=f"{key_prefix}_confirm_delete_page",
            )
            if st.button(
                "Xóa page",
                icon=":material/delete_forever:",
                disabled=not confirm_delete_page,
                key=f"{key_prefix}_delete_page",
            ):
                try:
                    custom_store.delete_page(selected_page_id)
                    st.session_state.pop("admin_selected_custom_page", None)
                    _rerun_with_message("Đã xóa page.")
                except Exception as error:
                    st.error(str(error))

    if custom_store.last_warning:
        st.warning(custom_store.last_warning)

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
