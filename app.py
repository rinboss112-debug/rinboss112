from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from custom_page_view import render_custom_page
from custom_pages import CustomPageStore, default_content
from niche_catalog import NicheCatalogStore, default_catalog


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"


def _secrets_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
        return {key: section[key] for key in section}
    except (FileNotFoundError, KeyError):
        return {}


@st.cache_data(ttl="30s", max_entries=4, show_spinner=False)
def _load_navigation_data(drive_config_json: str) -> tuple[dict[str, Any], dict[str, Any]]:
    drive_config = json.loads(drive_config_json) if drive_config_json else {}
    content_store = CustomPageStore(
        OUTPUT_DIR / "custom_pages.json",
        drive_config,
    )
    niche_store = NicheCatalogStore(
        OUTPUT_DIR / "niche_catalog.json",
        drive_config,
    )
    try:
        content = content_store.load()
    except Exception:
        content = default_content()
    try:
        niche_catalog = niche_store.load()
    except Exception:
        niche_catalog = default_catalog()
    return content, niche_catalog


def _page_renderer(
    page_data: dict[str, Any],
    category_name: str,
    niche_catalog: dict[str, Any],
):
    def render() -> None:
        render_custom_page(page_data, category_name, niche_catalog)

    return render


st.set_page_config(
    page_title="RinBoss Commerce",
    page_icon=":material/shopping_bag:",
    layout="wide",
)

scraper_page = st.Page(
    "scraper_page.py",
    title="Cào sản phẩm",
    icon=":material/shopping_bag:",
    default=True,
)
tiktok_export_page = st.Page(
    "app_pages/tiktok_export.py",
    title="Xuất TikTok",
    icon=":material/table_view:",
    url_path="tiktok-shop-us",
)
admin_page = st.Page(
    "app_pages/admin.py",
    title="Quản trị",
    icon=":material/admin_panel_settings:",
    url_path="admin",
    visibility="hidden",
)

drive_config = _secrets_section("google_drive")
drive_ready = all(
    str(drive_config.get(key, "")).strip()
    for key in ("client_id", "client_secret", "refresh_token")
)
content, niche_catalog = _load_navigation_data(
    json.dumps(drive_config if drive_ready else {}, sort_keys=True, default=str)
)
category_names = {
    str(category.get("id", "")): str(category.get("name", ""))
    for category in content.get("categories", [])
}

published_pages = [
    page for page in content.get("pages", []) if bool(page.get("published", False))
]
navigation_pages: dict[str, list[Any]] = {"": [scraper_page, tiktok_export_page]}
for category in content.get("categories", []):
    category_id = str(category.get("id", ""))
    category_pages = [
        page for page in published_pages if page.get("category_id", "") == category_id
    ]
    if category_pages:
        navigation_pages[str(category.get("name", "Danh mục"))] = [
            st.Page(
                _page_renderer(page, str(category.get("name", "")), niche_catalog),
                title=str(page.get("title", "Trang dữ liệu")),
                icon=":material/table_view:",
                url_path=str(page.get("slug", "")),
            )
            for page in category_pages
        ]

uncategorized = [
    page
    for page in published_pages
    if str(page.get("category_id", "")) not in category_names
]
if uncategorized:
    navigation_pages["Trang khác"] = [
        st.Page(
            _page_renderer(page, "", niche_catalog),
            title=str(page.get("title", "Trang dữ liệu")),
            icon=":material/table_view:",
            url_path=str(page.get("slug", "")),
        )
        for page in uncategorized
    ]

navigation_pages[""].append(admin_page)
navigation = st.navigation(
    navigation_pages,
    position="top",
)
navigation.run()
