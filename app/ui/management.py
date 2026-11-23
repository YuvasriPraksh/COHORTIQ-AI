"""Regulation Management page for CohortIQ AI."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from app.config import get_settings
from app.database import get_document_pages
from app.ui.common import (
    card,
    display_value,
    empty_state,
    format_datetime_display,
    load_regulations,
    metric_card,
    page_header,
    parse_multivalue_input,
    processing_status_pill,
    section_title,
    status_category,
    status_pill,
    unique_upload_path,
)
from app.workflow import approve_regulation, ingest_uploaded_regulation


def _render_extraction_summary(summary: dict[str, Any] | None) -> None:
    if not summary:
        st.info("No extraction summary available.")
        return

    total_pages = int(summary.get("total_pages") or 0)
    successful_pages = int(summary.get("successful_pages") or 0)
    attention_pages = int(summary.get("pages_needing_attention") or 0)
    cols = st.columns(3)
    for col, (label, value, hint) in zip(
        cols,
        [
            ("Total Pages", total_pages, "Pages detected in the uploaded PDF"),
            ("Successful Pages", successful_pages, "Pages extracted without issues"),
            ("Pages Needing Attention", attention_pages, "Pages requiring review"),
        ],
    ):
        with col:
            st.markdown(metric_card(label, value, hint), unsafe_allow_html=True)

    page_rows = summary.get("pages") or []
    if page_rows:
        with st.expander("Page extraction details", expanded=False):
            st.dataframe(page_rows, use_container_width=True, hide_index=True)


def _render_document_pages(regulation_id: int, db_path: Path, key_prefix: str) -> None:
    """Show extracted page text for a regulation (document detail view)."""
    with st.expander("Document detail: extracted page text", expanded=False):
        try:
            pages = get_document_pages(regulation_id, db_path=db_path)
        except Exception as exc:
            st.error(f"Unable to load extracted pages: {exc}")
            return
        if not pages:
            st.info("No extracted pages are stored for this regulation.")
            return
        st.caption(f"{len(pages)} stored page record(s). Page text is shown as extracted.")
        for page in pages:
            page_no = page.get("page_number")
            extraction_status = display_value(page.get("extraction_status"), "Unknown")
            text = page.get("extracted_text")
            text_str = "" if text is None else str(text)
            label = f"Page {page_no} · Extraction: {extraction_status}"
            with st.expander(label, expanded=False):
                if text_str.strip():
                    st.text_area(
                        "Extracted text",
                        value=text_str,
                        height=220,
                        key=f"{key_prefix}_{regulation_id}_{page_no}",
                        disabled=True,
                        label_visibility="collapsed",
                    )
                else:
                    st.info("No extracted text available for this page.")


def render(db_path: Path) -> None:
    page_header(
        "Regulation Management",
        "Upload regulation documents, capture applicability metadata, review extraction results, and manage verification decisions.",
        breadcrumb="CohortIQ AI / Regulation Management",
    )
    settings = get_settings()

    section_title(
        "Document Upload",
        "Provide required metadata and upload a regulation PDF for extraction and pending verification.",
    )
    card(
        """
        <div class="cq-kicker">Upload workflow</div>
        <div class="cq-section-desc" style="color:#172B4D;">
            Uploaded regulations are ingested and stored as pending until an administrator explicitly approves or rejects them.
            Only approved regulations are eligible for grounded cohort-aware answers.
        </div>
        """,
        compact=True,
    )

    with st.form("upload_regulation_form", clear_on_submit=False):
        st.markdown(
            """
            <div class="upload-zone">
                <p class="upload-zone-title">PDF upload area</p>
                <p class="upload-zone-sub">Select an official regulation PDF document to extract and store for verification.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "Regulation PDF",
            type=["pdf"],
            accept_multiple_files=False,
            help="Upload the regulation document in PDF format.",
        )

        st.markdown("**Document metadata**")
        col1, col2 = st.columns(2)
        with col1:
            document_name = st.text_input(
                "Document name",
                placeholder="e.g. Academic Regulations Handbook",
                help="Official title of the regulation document.",
            )
            regulation_version = st.text_input(
                "Regulation version",
                placeholder="e.g. v2.1 / 2024 Revision",
                help="Version or revision identifier used in citations and comparisons.",
            )
        with col2:
            effective_date = st.date_input(
                "Effective date",
                value=date.today(),
                help="Date the regulation version becomes effective.",
            )
            st.caption("Enter the effective date as defined by the issuing authority.")

        st.markdown("**Cohort applicability**")
        col3, col4 = st.columns(2)
        with col3:
            applicable_batches_raw = st.text_area(
                "Applicable admission batches",
                placeholder="2023, 2024, 2025",
                help="Comma- or line-separated admission batches (cohorts) covered by this regulation.",
                height=110,
            )
        with col4:
            applicable_programmes_raw = st.text_area(
                "Applicable programmes",
                placeholder="BSc Computer Science, BEng Electrical Engineering",
                help="Comma- or line-separated programmes covered by this regulation.",
                height=110,
            )

        submitted = st.form_submit_button(
            "Upload, Extract, and Save as Pending",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if uploaded_file is None:
            st.error("Please upload a PDF regulation document before submitting.")
        else:
            batches = parse_multivalue_input(applicable_batches_raw)
            programmes = parse_multivalue_input(applicable_programmes_raw)
            upload_signature = (
                uploaded_file.name,
                uploaded_file.size,
                document_name.strip(),
                regulation_version.strip(),
                str(effective_date),
                tuple(batches),
                tuple(programmes),
            )
            if st.session_state.get("last_upload_signature") == upload_signature:
                st.warning(
                    "This upload appears to have already been submitted. Modify the file or metadata to submit again."
                )
            elif not document_name.strip() or not regulation_version.strip() or not batches or not programmes:
                st.error(
                    "All document metadata fields are required: document name, regulation version, "
                    "effective date, applicable admission batches, and applicable programmes."
                )
            else:
                upload_path = unique_upload_path(settings.upload_dir, uploaded_file.name)
                try:
                    with st.spinner("Uploading and extracting the regulation document..."):
                        upload_path.write_bytes(uploaded_file.getbuffer())
                        metadata = {
                            "document_name": document_name.strip(),
                            "regulation_version": regulation_version.strip(),
                            "effective_date": effective_date.isoformat(),
                            "applicable_batches": batches,
                            "applicable_programmes": programmes,
                            "upload_date": datetime.now().isoformat(),
                        }
                        result = ingest_uploaded_regulation(upload_path, metadata, db_path=db_path)
                except Exception as exc:
                    st.error(f"Failed to process the uploaded regulation: {exc}")
                else:
                    if result.get("status") == "ingested":
                        st.session_state["last_upload_signature"] = upload_signature
                        st.success(
                            f"Regulation ingested and saved as pending verification (ID: {result.get('regulation_id')}). "
                            "Administrator approval is required before it can be used for grounded answers."
                        )
                        section_title("Processing summary", "Extraction status and page-level processing results.")
                        summary = result.get("extraction_summary") or {}
                        p_cols = st.columns(3)
                        p_cols[0].markdown(
                            f"**Extraction status:** {escape(display_value((result.get('extraction') or {}).get('status')))}",
                            unsafe_allow_html=True,
                        )
                        p_cols[1].markdown(
                            f"**Page count:** {escape(str(summary.get('total_pages', result.get('total_pages', 'N/A'))))}",
                            unsafe_allow_html=True,
                        )
                        reg_id = result.get("regulation_id")
                        processing_state = "Ingested (pending verification)"
                        try:
                            from app.database import get_regulation_by_id

                            reg = get_regulation_by_id(int(reg_id), db_path=db_path) if reg_id is not None else None
                            if reg:
                                processing_state = display_value(reg.get("processing_status"), processing_state)
                        except Exception:
                            pass
                        p_cols[2].markdown(
                            f"**Processing status:** {escape(processing_state)}",
                            unsafe_allow_html=True,
                        )
                        _render_extraction_summary(summary)
                    else:
                        st.error(result.get("message") or "Failed to ingest the uploaded regulation.")

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
    section_title(
        "Pending verification",
        "Review uploaded regulations, inspect extracted details, and explicitly approve or reject them.",
    )

    regulations = load_regulations(db_path)
    pending = [r for r in regulations if status_category(r.get("verification_status")) == "pending"]

    if not pending:
        empty_state(
            "✓",
            "No pending regulations",
            "There are no regulations awaiting verification. Newly uploaded documents will appear here for review.",
        )
        return

    st.caption(f"{len(pending)} regulation(s) awaiting verification.")

    for regulation in pending:
        reg_id = regulation.get("id")
        if reg_id is None:
            continue
        doc_name = display_value(regulation.get("document_name"), "Untitled regulation")
        version = display_value(regulation.get("regulation_version"))
        effective = display_value(regulation.get("effective_date"))
        uploaded = format_datetime_display(regulation.get("upload_date"))
        total_pages = regulation.get("total_pages")
        total_pages_display = str(total_pages) if total_pages is not None else "N/A"
        batches_display = display_value(regulation.get("applicable_batches"))
        programmes_display = display_value(regulation.get("applicable_programmes"))
        verification_html = status_pill(regulation.get("verification_status"))
        processing_html = processing_status_pill(regulation.get("processing_status"))

        st.markdown(
            f"""
            <div class="lib-card">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:0.8rem; flex-wrap:wrap;">
                    <div>
                        <p class="lib-title">{escape(doc_name)}</p>
                        <div class="lib-meta">Version {escape(version)} · Effective {escape(effective)}</div>
                    </div>
                    <div style="display:flex; gap:0.4rem; flex-wrap:wrap;">{verification_html}{processing_html}</div>
                </div>
                <div class="lib-grid">
                    <div><div class="lib-field-label">Applicable Admission Batches</div><div class="lib-field-value">{escape(batches_display)}</div></div>
                    <div><div class="lib-field-label">Applicable Programmes</div><div class="lib-field-value">{escape(programmes_display)}</div></div>
                    <div><div class="lib-field-label">Extraction / Processing Status</div><div class="lib-field-value">{escape(display_value(regulation.get('processing_status')))}</div></div>
                    <div><div class="lib-field-label">Page Count</div><div class="lib-field-value">{escape(total_pages_display)}</div></div>
                    <div><div class="lib-field-label">Upload Date</div><div class="lib-field-value">{escape(uploaded)}</div></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _render_document_pages(int(reg_id), db_path, key_prefix="mgmt_page")

        action_cols = st.columns([1, 1, 4])
        with action_cols[0]:
            if st.button(
                "Approve",
                key=f"approve_{reg_id}",
                type="primary",
                use_container_width=True,
            ):
                result = approve_regulation(reg_id, verification_status="approved", db_path=db_path)
                if result.get("status") == "updated":
                    st.success(f"Regulation '{doc_name}' (ID {reg_id}) approved.")
                    st.rerun()
                else:
                    st.error(result.get("message") or "Failed to approve regulation.")
        with action_cols[1]:
            if st.button("Reject", key=f"reject_{reg_id}", use_container_width=True):
                result = approve_regulation(reg_id, verification_status="rejected", db_path=db_path)
                if result.get("status") == "updated":
                    st.warning(f"Regulation '{doc_name}' (ID {reg_id}) rejected.")
                    st.rerun()
                else:
                    st.error(result.get("message") or "Failed to reject regulation.")
        st.markdown("<div style='height:0.2rem'></div>", unsafe_allow_html=True)
