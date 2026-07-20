from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st

from custom_pages import frame_from_page


def _column_config(frame: pd.DataFrame) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for column in frame.columns:
        key = str(column).strip().casefold()
        if key in {"image_url", "image", "ảnh", "hình ảnh"}:
            config[column] = st.column_config.ImageColumn(str(column))
        elif "url" in key or "link" in key or "liên kết" in key:
            config[column] = st.column_config.LinkColumn(str(column))
    return config


def render_custom_page(
    page: Mapping[str, Any],
    category_name: str,
    niche_catalog: Mapping[str, Any],
) -> None:
    st.title(str(page.get("title", "Trang dữ liệu")))
    if category_name:
        st.badge(category_name, color="blue")
    if description := str(page.get("description", "")).strip():
        st.markdown(description)

    frame = frame_from_page(page)
    search = st.text_input(
        "Tìm trong bảng",
        placeholder="Nhập nội dung cần tìm...",
        icon=":material/search:",
        key=f"public_page_search_{page.get('id', '')}",
    )
    visible = frame
    if search.strip() and not frame.empty:
        needle = search.strip().casefold()
        mask = frame.fillna("").astype(str).apply(
            lambda column: column.str.casefold().str.contains(
                needle, regex=False, na=False
            )
        ).any(axis=1)
        visible = frame.loc[mask]

    with st.container(border=True):
        st.subheader("Bảng dữ liệu", anchor=False)
        if visible.empty:
            st.caption("Page này chưa có dữ liệu phù hợp.")
        else:
            st.dataframe(
                visible,
                hide_index=True,
                column_config=_column_config(visible),
                key=f"public_page_table_{page.get('id', '')}",
            )
        st.download_button(
            "Tải bảng CSV",
            visible.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{page.get('slug', 'data')}.csv",
            mime="text/csv",
            icon=":material/download:",
            key=f"public_page_download_{page.get('id', '')}",
        )

    niche_ids = set(str(value) for value in page.get("niche_ids", []))
    attached = [
        item
        for item in niche_catalog.get("items", [])
        if str(item.get("id", "")) in niche_ids
    ]
    if attached:
        with st.container(border=True):
            st.subheader("File ngách được gắn vào page", anchor=False)
            rows = [
                {
                    "Ngách": item.get("keyword", ""),
                    "Sản phẩm": item.get("product_count", 0),
                    "Cập nhật": item.get("last_scraped_at", ""),
                    "Google Drive": item.get("drive_folder_url", ""),
                }
                for item in attached
            ]
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                column_config={
                    "Google Drive": st.column_config.LinkColumn(
                        "Dữ liệu", display_text="Mở trên Drive"
                    )
                },
                key=f"public_page_niches_{page.get('id', '')}",
            )

    st.caption(f"Cập nhật lần cuối: {page.get('updated_at', '')}")
