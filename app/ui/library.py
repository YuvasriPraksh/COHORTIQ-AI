"""Regulation Library page for CohortIQ AI."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from app.database import get_document_pages
from app.ui.common import (
    display_value,
    empty_state,
    format_datetime_display,
    load_regulations,
    page_header,
    parse_datetime_for_sort,
    processing_status_pill,
    section_title,
    status_category,
    status_pill,
)


def _matches_search(regulation: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = query.strip().lower()
    fields = [
        display_value(regulation.get("document_name"), ""),
        display_value(regulation.get("regulation_version"), ""),
        display_value(regulation.get("effective_date"), ""),
        display_value(regulation.get("applicable_batches"), ""),
        display_value(regulation.get("applicable_programmes"), ""),
        display_value(regulation.get("verification_status"), ""),
        display_value(regulation.get("processing_status"), ""),
    ]
    return any(q in str(field).lower() for field in fields)


def _passes_status_filter(regulation: dict[str, Any], status_filter: str) -> bool:
    category = status_category(regulation.get("verification_status"))
    if status_filter == "All statuses":
        return True
    if status_filter == "Approved":
        return category == "approved"
    if status_filter == "Pending / Unverified":
        return category == "pending"
    if status_filter == "Rejected":
        return category == "rejected"
    return True


def _render_document_detail(regulation_id: int, db_path: Path) -> None:
    try:
        pages = get_document_pages(regulation_id, db_path=db_path)
    except Exception as exc:
        st.error(f"Unable to load extracted pages: {exc}")
        return
    if not pages:
        st.info("No extracted page records are stored for this regulation.")
        return
    st.caption(f"{len(pages)} stored page record(s).")
    for page in pages:
        page_no = page.get("page_number")
        extraction_status = display_value(page.get("extraction_status"), "Unknown")
        text = page.get("extracted_text")
        text_str = "" if text is None else str(text)
        with st.expander(f"Page {page_no} · Extraction: {extraction_status}", expanded=False):
            if text_str.strip():
                st.text_area(
                    "Extracted text",
                    value=text_str,
                    height=200,
                    key=f"lib_page_{regulation_id}_{page_no}_{page.get('id', 'x')}",
                    disabled=True,
                    label_visibility="collapsed",
                )
            else:
                st.info("No extracted text available for this page.")


def render(db_path: Path) -> None:
    page_header(
        "Regulation Library",
        "Browse, search, and inspect stored regulation documents, applicability metadata, and verification status.",
        breadcrumb="CohortIQ AI / Regulation Library",
    )

    regulations = load_regulations(db_path)
    if not regulations:
        empty_state(
            "▥",
            "No regulations in the library",
            "Uploaded regulations will appear here with document details, applicability, and verification status once records are stored.",
        )
        st.caption("Use Regulation Management to upload and process your first regulation document.")
        return

    section_title("Search and filters", "Find regulations by document details and verification status.")
    filter_col1, filter_col2 = st.columns([2.2, 1])
    with filter_col1:
        search_query = st.text_input(
            "Search regulations",
            placeholder="Search by document name, regulation version, batch, programme, or status",
            help="Search across stored document and applicability fields.",
        )
    with filter_col2:
        status_filter = st.selectbox(
            "Verification status filter",
            options=["All statuses", "Approved", "Pending / Unverified", "Rejected"],
            help="Filter regulations by verification outcome.",
        )

    filtered: list[dict[str, Any]] = []
    for regulation in regulations:
        if not _passes_status_filter(regulation, status_filter):
            continue
        if not _matches_search(regulation, search_query or ""):
            continue
        filtered.append(regulation)

    st.caption(f"Showing {len(filtered)} of {len(regulations)} regulation(s).")

    if not filtered:
        empty_state(
            "⌕",
            "No matching regulations",
            "Adjust your search terms or verification status filter to see stored regulations.",
        )
        return

    def sort_key(item: dict[str, Any]) -> tuple[int, float]:
        dt = parse_datetime_for_sort(item.get("upload_date"))
        if dt is None:
            return (0, 0.0)
        return (1, dt.timestamp())

    sorted_regs = sorted(filtered, key=sort_key, reverse=True)

    section_title("Document cards", "Stored regulation records with applicability and processing details.")
    for regulation in sorted_regs:
        reg_id = regulation.get("id")
        doc_name = display_value(regulation.get("document_name"), "Untitled regulation")
        version = display_value(regulation.get("regulation_version"))
        effective_date = display_value(regulation.get("effective_date"))
        upload_date = format_datetime_display(regulation.get("upload_date"))
        batches = display_value(regulation.get("applicable_batches"))
        programmes = display_value(regulation.get("applicable_programmes"))
        verification_html = status_pill(regulation.get("verification_status"))
        processing_html = processing_status_pill(regulation.get("processing_status"))
        total_pages = regulation.get("total_pages")
        total_pages_display = str(total_pages) if total_pages is not None else "N/A"
        processing_status = display_value(regulation.get("processing_status"))
        verification_status = display_value(regulation.get("verification_status"))

        st.markdown(
            f"""
            <div class="lib-card">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:0.8rem; flex-wrap:wrap;">
                    <div>
                        <p class="lib-title">{escape(doc_name)}</p>
                        <div class="lib-meta">Version {escape(version)} · Effective {escape(effective_date)}</div>
                    </div>
                    <div style="display:flex; gap:0.4rem; flex-wrap:wrap; justify-content:flex-end;">
                        {verification_html}
                        {processing_html}
                    </div>
                </div>
                <div class="lib-grid">
                    <div><div class="lib-field-label">Applicable Admission Batches</div><div class="lib-field-value">{escape(batches)}</div></div>
                    <div><div class="lib-field-label">Applicable Programmes</div><div class="lib-field-value">{escape(programmes)}</div></div>
                    <div><div class="lib-field-label">Verification Status</div><div class="lib-field-value">{escape(verification_status)}</div></div>
                    <div><div class="lib-field-label">Processing Status</div><div class="lib-field-value">{escape(processing_status)}</div></div>
                    <div><div class="lib-field-label">Upload Date</div><div class="lib-field-value">{escape(upload_date)}</div></div>
                    <div><div class="lib-field-label">Total Pages</div><div class="lib-field-value">{escape(total_pages_display)}</div></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("View details", expanded=False):
            detail_cols = st.columns(2)
            with detail_cols[0]:
                st.markdown(f"**Document name:** {escape(doc_name)}", unsafe_allow_html=True)
                st.markdown(f"**Regulation version:** {escape(version)}", unsafe_allow_html=True)
                st.markdown(f"**Effective date:** {escape(effective_date)}", unsafe_allow_html=True)
                st.markdown(f"**Upload date:** {escape(upload_date)}", unsafe_allow_html=True)
            with detail_cols[1]:
                st.markdown(f"**Applicable batches:** {escape(batches)}", unsafe_allow_html=True)
                st.markdown(f"**Applicable programmes:** {escape(programmes)}", unsafe_allow_html=True)
                st.markdown(f"**Verification status:** {escape(verification_status)}", unsafe_allow_html=True)
                st.markdown(f"**Processing status / page count:** {escape(processing_status)} / {escape(total_pages_display)}", unsafe_allow_html=True)

            if reg_id is not None:
                st.markdown("**Extracted page text (document detail)**")
                _render_document_detail(int(reg_id), db_path)
            else:
                st.info("Document ID unavailable; extracted page details cannot be loaded.")

    section_title("Table view", "Tabular view of stored regulation metadata for quick comparison.")
    rows = []
    for regulation in sorted_regs:
        rows.append(
            {
                "ID": regulation.get("id"),
                "Document Name": regulation.get("document_name"),
                "Regulation Version": regulation.get("regulation_version"),
                "Effective Date": regulation.get("effective_date") or "N/A",
                "Applicable Batches": ", ".join(regulation.get("applicable_batches") or []) or "N/A",
                "Applicable Programmes": ", ".join(regulation.get("applicable_programmes") or []) or "N/A",
                "Verification Status": regulation.get("verification_status") or "N/A",
                "Processing Status": regulation.get("processing_status") or "N/A",
                "Total Pages": regulation.get("total_pages") if regulation.get("total_pages") is not None else "N/A",
                "Upload Date": regulation.get("upload_date") or "N/A",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
