from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tiktok_export import (
    EXPORT_FIELDS,
    TIKTOK_XLSX_MIME,
    build_preparation_workbook,
    detect_data_start_row,
    detect_header_row,
    fill_official_template,
    preparation_filename,
    prepare_products,
    read_product_file,
    selected_products,
    suggest_template_mapping,
    template_headers,
    tiktok_template_style_repair_count,
    validate_products,
    workbook_sheet_names,
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
            "Chưa cấu hình phần admin password trong Streamlit Secrets. "
            "Trang xuất TikTok đang được khóa an toàn.",
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
        st.title("Đăng nhập để xuất TikTok Shop", text_alignment="center")
        password = st.text_input(
            "Mật khẩu admin",
            type="password",
            width=360,
            key="tiktok_admin_password",
        )
        if st.button(
            "Đăng nhập",
            type="primary",
            icon=":material/login:",
            key="tiktok_admin_login",
        ):
            if hmac.compare_digest(password, expected):
                st.session_state.admin_authenticated = True
                st.rerun()
            st.error("Mật khẩu admin không đúng.")
    st.stop()


@st.cache_data(max_entries=8, show_spinner=False)
def _read_source(filename: str, raw: bytes) -> pd.DataFrame:
    return read_product_file(filename, raw)


@st.cache_data(max_entries=8, show_spinner=False)
def _build_draft(
    frame: pd.DataFrame,
    multiplier: float,
    fixed_cost: float,
    divisor: float,
) -> bytes:
    return build_preparation_workbook(
        frame,
        multiplier=multiplier,
        fixed_cost=fixed_cost,
        divisor=divisor,
    )


_require_admin()

with st.container(border=True):
    with st.container(horizontal=True):
        st.badge(
            "RinBoss Commerce",
            icon=":material/storefront:",
            color="orange",
        )
        st.badge(
            "Bản thử nghiệm",
            icon=":material/science:",
            color="blue",
        )
    st.title("Xuất sản phẩm cho TikTok Shop US")
    st.caption(
        "Chuẩn bị dữ liệu, tính giá bán và điền vào template Excel chính thức "
        "của từng category TikTok Shop US."
    )

st.warning(
    "TikTok chỉ chấp nhận template tải trực tiếp từ Seller Center theo đúng "
    "category. Không dùng Amazon để giao thẳng đơn hàng tới khách TikTok và "
    "không ghi “No brand” cho sản phẩm có thương hiệu.",
    icon=":material/policy:",
)

current_frame = pd.DataFrame()
controller = st.session_state.get("controller")
if controller is not None:
    try:
        current_frame = pd.DataFrame(controller.snapshot().get("results", []))
    except Exception:
        current_frame = pd.DataFrame()

source_options = ["Tải CSV/XLSX"]
if not current_frame.empty:
    source_options.insert(0, "Kết quả phiên cào hiện tại")
source_mode = st.segmented_control(
    "Nguồn sản phẩm",
    source_options,
    default=source_options[0],
    key="tiktok_source_mode",
)

source_frame = pd.DataFrame()
source_name = ""
if source_mode == "Kết quả phiên cào hiện tại":
    source_frame = current_frame
    source_name = "current_scrape.csv"
    st.success(
        f"Đã nhận {len(source_frame)} sản phẩm từ phiên cào hiện tại.",
        icon=":material/check_circle:",
    )
else:
    source_file = st.file_uploader(
        "Tải file kết quả sản phẩm",
        type=["csv", "xlsx"],
        help="Có thể dùng file CSV do scraper tạo hoặc bảng đã chuẩn bị trước đó.",
        key="tiktok_source_file",
    )
    if source_file is not None:
        try:
            source_frame = _read_source(source_file.name, source_file.getvalue())
            source_name = source_file.name
            st.success(
                f"Đã đọc {len(source_frame)} dòng từ {source_file.name}.",
                icon=":material/check_circle:",
            )
        except Exception as error:
            st.error(f"Không đọc được file sản phẩm: {error}")

if source_frame.empty:
    with st.container(border=True):
        st.subheader("Cách dùng nhanh", anchor=False)
        st.markdown(
            "1. Tải CSV kết quả cào hoặc quay lại trang cào và hoàn tất một phiên.\n"
            "2. Kiểm tra giá, SKU, mô tả, brand, ảnh và thông tin đóng gói.\n"
            "3. Tải bảng chuẩn bị hoặc tải template TikTok để điền trực tiếp."
        )
    st.stop()

with st.container(border=True):
    st.subheader("Công thức giá", anchor=False)
    pricing = st.container(horizontal=True)
    with pricing:
        multiplier = st.number_input(
            "Nhân giá gốc",
            min_value=0.0,
            value=2.0,
            step=0.1,
            key="tiktok_price_multiplier",
        )
        fixed_cost = st.number_input(
            "Cộng thêm (USD)",
            min_value=0.0,
            value=12.0,
            step=1.0,
            key="tiktok_fixed_cost",
        )
        divisor = st.number_input(
            "Chia cho",
            min_value=0.01,
            value=0.8,
            step=0.05,
            key="tiktok_price_divisor",
        )
    st.code(
        "Giá bán TikTok = "
        f"(Giá gốc × {float(multiplier):g} + {float(fixed_cost):g}) "
        f"÷ {float(divisor):g}",
        language=None,
    )

prepared = prepare_products(
    source_frame,
    multiplier=float(multiplier),
    fixed_cost=float(fixed_cost),
    divisor=float(divisor),
)

with st.container(border=True):
    st.subheader("Chỉnh dữ liệu sản phẩm", anchor=False)
    st.caption(
        "Cột giá công thức được khóa. Bạn vẫn có thể sửa giá bán TikTok cuối cùng, "
        "thêm mô tả, brand, tồn kho, kích thước và GTIN/UPC."
    )
    edited = st.data_editor(
        prepared,
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "keyword",
            "asin",
            "original_price",
            "calculated_price",
            "product_url",
            "validation",
        ],
        column_order=[
            "selected",
            "seller_sku",
            "product_title",
            "description",
            "brand",
            "original_price",
            "calculated_price",
            "tiktok_price",
            "stock",
            "image_1",
            "image_2",
            "package_weight_lb",
            "package_length_in",
            "package_width_in",
            "package_height_in",
            "gtin_upc",
            "variation_name",
            "variation_value",
            "validation",
            "keyword",
            "asin",
            "product_url",
        ],
        column_config={
            "selected": st.column_config.CheckboxColumn("Xuất", pinned=True),
            "seller_sku": st.column_config.TextColumn("Seller SKU", pinned=True),
            "product_title": st.column_config.TextColumn("Tên sản phẩm", width="large"),
            "description": st.column_config.TextColumn("Mô tả", width="large"),
            "brand": st.column_config.TextColumn("Brand"),
            "original_price": st.column_config.NumberColumn(
                "Giá gốc", format="$%.2f"
            ),
            "calculated_price": st.column_config.NumberColumn(
                "Giá công thức", format="$%.2f"
            ),
            "tiktok_price": st.column_config.NumberColumn(
                "Giá bán TikTok", min_value=0.0, format="$%.2f"
            ),
            "stock": st.column_config.NumberColumn(
                "Tồn kho", min_value=0, step=1
            ),
            "image_1": st.column_config.ImageColumn("Ảnh chính"),
            "image_2": st.column_config.TextColumn("URL ảnh 2"),
            "package_weight_lb": st.column_config.NumberColumn(
                "Cân nặng (lb)", min_value=0.0
            ),
            "package_length_in": st.column_config.NumberColumn(
                "Dài (in)", min_value=0.0
            ),
            "package_width_in": st.column_config.NumberColumn(
                "Rộng (in)", min_value=0.0
            ),
            "package_height_in": st.column_config.NumberColumn(
                "Cao (in)", min_value=0.0
            ),
            "gtin_upc": st.column_config.TextColumn("GTIN/UPC"),
            "variation_name": st.column_config.TextColumn("Tên biến thể 1"),
            "variation_value": st.column_config.TextColumn("Giá trị biến thể 1"),
            "validation": st.column_config.TextColumn("Kiểm tra", width="large"),
            "keyword": st.column_config.TextColumn("Ngách"),
            "asin": st.column_config.TextColumn("ASIN"),
            "product_url": st.column_config.LinkColumn("Link nguồn"),
        },
        key=f"tiktok_products_editor_{source_name}",
    )

validated = validate_products(edited)
selected = selected_products(validated)
ready_count = (
    int((selected["validation"] == "Sẵn sàng").sum())
    if not selected.empty
    else 0
)
with st.container(horizontal=True):
    st.metric("Tổng dòng", len(validated), border=True)
    st.metric("Đã chọn xuất", len(selected), border=True)
    st.metric("Sẵn sàng", ready_count, border=True)
    st.metric("Cần bổ sung", max(len(selected) - ready_count, 0), border=True)

issues = selected.loc[
    selected["validation"] != "Sẵn sàng", ["seller_sku", "validation"]
]
if not issues.empty:
    issue_panel = st.expander(
        f"Có {len(issues)} sản phẩm cần bổ sung thông tin",
        icon=":material/warning:",
        on_change="rerun",
    )
    if issue_panel.open:
        with issue_panel:
            st.dataframe(
                issues,
                hide_index=True,
                column_config={
                    "seller_sku": st.column_config.TextColumn("Seller SKU"),
                    "validation": st.column_config.TextColumn(
                        "Thông tin cần bổ sung", width="large"
                    ),
                },
            )

with st.container(border=True):
    st.subheader("Tải bảng chuẩn bị", anchor=False)
    st.caption(
        "File này dùng để kiểm tra nội bộ. Sheet Pricing Settings giữ công thức "
        "và các hệ số để dễ đối chiếu."
    )
    draft_bytes = _build_draft(
        validated,
        float(multiplier),
        float(fixed_cost),
        float(divisor),
    )
    st.download_button(
        "Tải bảng chuẩn bị XLSX",
        draft_bytes,
        file_name=preparation_filename(validated),
        mime=TIKTOK_XLSX_MIME,
        icon=":material/download:",
        on_click="ignore",
        key="download_tiktok_draft",
    )

with st.container(border=True):
    st.subheader("Điền template chính thức TikTok Shop US", anchor=False)
    st.caption(
        "Tải template của đúng category từ Seller Center. Tool chỉ ghi dữ liệu "
        "vào các cột bạn ánh xạ và không thêm hoặc xóa cột."
    )
    template_file = st.file_uploader(
        "Template TikTok Shop (.xlsx)",
        type=["xlsx"],
        key="tiktok_official_template",
    )
    if template_file is not None:
        template_bytes = template_file.getvalue()
        template_signature = hashlib.sha256(template_bytes).hexdigest()
        if st.session_state.get("tiktok_template_signature") != template_signature:
            st.session_state["tiktok_template_signature"] = template_signature
            st.session_state.pop("tiktok_filled_template", None)
            st.session_state.pop("tiktok_filled_filename", None)
        try:
            repair_count = tiktok_template_style_repair_count(template_bytes)
            if repair_count:
                st.info(
                    "Template chính thức có giá trị màu không hợp lệ do TikTok "
                    f"tạo ra ({repair_count} vị trí). Tool sẽ tự sửa trên bản sao "
                    "khi xử lý; file gốc của bạn không bị thay đổi.",
                    icon=":material/build:",
                )
            sheets = workbook_sheet_names(template_bytes)
            selected_sheet = st.selectbox(
                "Sheet chứa bảng sản phẩm",
                sheets,
                key="tiktok_template_sheet",
            )
            detected_row = detect_header_row(template_bytes, selected_sheet)
            header_row = st.number_input(
                "Dòng tiêu đề cột",
                min_value=1,
                value=int(detected_row),
                step=1,
                key="tiktok_template_header_row",
            )
            detected_data_row = detect_data_start_row(
                template_bytes,
                selected_sheet,
                int(header_row),
            )
            data_start_row = st.number_input(
                "Dòng bắt đầu ghi sản phẩm",
                min_value=int(header_row) + 1,
                value=int(detected_data_row),
                step=1,
                help=(
                    "Tool tự nhận diện dòng 7 với template Seller Center V5 và "
                    "giữ nguyên các dòng cấu hình phía trên."
                ),
                key="tiktok_template_data_start_row",
            )
            headers = template_headers(
                template_bytes,
                selected_sheet,
                int(header_row),
            )
            if not headers:
                st.error("Không tìm thấy tiêu đề cột tại dòng đã chọn.")
            else:
                header_labels = [str(item["label"]) for item in headers]
                suggested = suggest_template_mapping(headers)
                mapping_frame = pd.DataFrame(
                    [
                        {
                            "field_key": field.key,
                            "Dữ liệu từ tool": field.label,
                            "Cột trong template": suggested.get(field.key, ""),
                        }
                        for field in EXPORT_FIELDS
                    ]
                )
                edited_mapping = st.data_editor(
                    mapping_frame,
                    hide_index=True,
                    disabled=["field_key", "Dữ liệu từ tool"],
                    column_order=["Dữ liệu từ tool", "Cột trong template"],
                    column_config={
                        "field_key": None,
                        "Dữ liệu từ tool": st.column_config.TextColumn(
                            "Dữ liệu từ tool", pinned=True
                        ),
                        "Cột trong template": st.column_config.SelectboxColumn(
                            "Cột trong template",
                            options=[""] + header_labels,
                        ),
                    },
                    key=(
                        f"tiktok_mapping_{template_file.name}_"
                        f"{selected_sheet}_{int(header_row)}"
                    ),
                )
                mapped_count = int(
                    edited_mapping["Cột trong template"]
                    .fillna("")
                    .astype(bool)
                    .sum()
                )
                st.caption(
                    f"Đã ánh xạ {mapped_count}/{len(EXPORT_FIELDS)} trường dữ liệu."
                )
                if st.button(
                    "Tạo file TikTok từ template",
                    type="primary",
                    icon=":material/table_view:",
                    key="build_tiktok_official_file",
                ):
                    mapping = {
                        str(row["field_key"]): str(
                            row["Cột trong template"] or ""
                        ).strip()
                        for _, row in edited_mapping.iterrows()
                    }
                    try:
                        filled = fill_official_template(
                            template_bytes,
                            sheet_name=selected_sheet,
                            header_row=int(header_row),
                            data_start_row=int(data_start_row),
                            mapping=mapping,
                            products=validated,
                        )
                        st.session_state["tiktok_filled_template"] = filled
                        st.session_state["tiktok_filled_filename"] = (
                            f"{Path(template_file.name).stem}_filled.xlsx"
                        )
                        st.success(
                            f"Đã điền {len(selected)} sản phẩm vào template.",
                            icon=":material/check_circle:",
                        )
                    except Exception as error:
                        st.error(f"Không tạo được file TikTok: {error}")
                if st.session_state.get("tiktok_filled_template"):
                    st.download_button(
                        "Tải file TikTok đã điền",
                        st.session_state["tiktok_filled_template"],
                        file_name=st.session_state.get(
                            "tiktok_filled_filename",
                            "tiktok_shop_filled.xlsx",
                        ),
                        mime=TIKTOK_XLSX_MIME,
                        icon=":material/download:",
                        on_click="ignore",
                        key="download_tiktok_official",
                    )
        except Exception as error:
            st.error(f"Không đọc được template TikTok: {error}")
