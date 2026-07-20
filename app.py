from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="Amazon Product Scraper",
    page_icon=":material/shopping_bag:",
    layout="wide",
)

scraper_page = st.Page(
    "scraper_page.py",
    title="Amazon Product Scraper",
    icon=":material/shopping_bag:",
    default=True,
)
admin_page = st.Page(
    "app_pages/admin.py",
    title="Quản trị",
    icon=":material/admin_panel_settings:",
    url_path="admin",
    visibility="hidden",
)

navigation = st.navigation([scraper_page, admin_page], position="hidden")
navigation.run()
