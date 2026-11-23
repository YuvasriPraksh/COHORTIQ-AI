"""Streamlit entry point for the CohortIQ AI application.

This module provides the application shell and routes to page renderers while
preserving the existing backend workflows for regulation ingestion, explicit
approval, and grounded cohort-aware question answering.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from app.config import ensure_app_directories, get_settings
from app.database import init_database
from app.ui import assistant, dashboard, library, management
from app.ui.theme import NAV_ITEMS, PRODUCT_DESCRIPTOR, PRODUCT_NAME, PRODUCT_TAGLINE, inject_styles


def _ensure_initialized() -> Path:
    """Initialize database and configured directories; return database path."""
    settings = ensure_app_directories(get_settings())
    init_database(settings.database_path)
    return settings.database_path



def main() -> None:
    """Run the CohortIQ AI Streamlit application."""
    st.set_page_config(
        page_title=f"{PRODUCT_NAME} | {PRODUCT_DESCRIPTOR}",
        page_icon="◫",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()

    try:
        db_path = _ensure_initialized()
    except Exception as exc:
        st.error(f"Failed to initialize application storage: {exc}")
        st.stop()

    nav_labels = [f"{icon}  {label}" for _, label, icon in NAV_ITEMS]
    label_to_page = {f"{icon}  {label}": key for key, label, icon in NAV_ITEMS}

    with st.sidebar:
        st.markdown(
            f"""
            <div class="sidebar-brand">
                <div class="sidebar-product">{escape(PRODUCT_NAME)}</div>
                <div class="sidebar-descriptor">{escape(PRODUCT_DESCRIPTOR)}</div>
                <div class="sidebar-tagline">{escape(PRODUCT_TAGLINE)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<hr />", unsafe_allow_html=True)
        selected_label = st.radio(
            "Navigation",
            options=nav_labels,
            index=0,
            help="Navigate between CohortIQ AI workspaces.",
        )
        st.markdown("<hr />", unsafe_allow_html=True)
        st.markdown(
            '<div class="sidebar-note">'
            "Grounded answers use administrator-approved regulations only. "
            "Citations reference the source document, version, and page."
            "</div>",
            unsafe_allow_html=True,
        )

    page = label_to_page.get(selected_label, "dashboard")

    if page == "dashboard":
        dashboard.render(db_path)
    elif page == "management":
        management.render(db_path)
    elif page == "assistant":
        assistant.render(db_path)
    elif page == "library":
        library.render(db_path)


if __name__ == "__main__":
    main()
