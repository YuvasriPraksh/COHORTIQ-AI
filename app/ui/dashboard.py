"""Dashboard page for CohortIQ AI."""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from app.ui.common import (
    card,
    display_value,
    empty_state,
    format_datetime_display,
    load_regulations,
    metric_card,
    page_header,
    parse_datetime_for_sort,
    section_title,
    status_category,
    status_pill,
)


def render(db_path: Path) -> None:
    page_header(
        "Academic Intelligence Overview",
        "Monitor regulation coverage, verification status, and recent activity across the CohortIQ AI platform.",
        breadcrumb="CohortIQ AI / Dashboard",
    )

    regulations = load_regulations(db_path)
    total = len(regulations)
    counts = {"approved": 0, "pending": 0, "rejected": 0}
    for regulation in regulations:
        counts[status_category(regulation.get("verification_status"))] += 1

    metrics = [
        ("Total Regulations", total, "All regulation records stored in the system"),
        ("Approved Regulations", counts["approved"], "Verified and eligible for grounded answers"),
        ("Pending Verification", counts["pending"], "Awaiting administrator review"),
        ("Rejected Regulations", counts["rejected"], "Reviewed and excluded from approved evidence"),
    ]
    cols = st.columns(4)
    for col, (label, value, hint) in zip(cols, metrics):
        with col:
            st.markdown(metric_card(label, value, hint), unsafe_allow_html=True)

    st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

    left, right = st.columns([1.25, 1], gap="large")

    with left:
        section_title(
            "Core Intelligence Capabilities",
            "Key capabilities supported by the current CohortIQ AI workflow and stored regulation evidence.",
        )
        c1, c2, c3 = st.columns(3)
        capabilities = [
            (
                "Applicability Intelligence",
                "Identifies regulations applicable to a particular student cohort.",
            ),
            (
                "Change Intelligence",
                "Helps compare regulatory versions and identify changes.",
            ),
            (
                "Cohort Impact Intelligence",
                "Helps identify potentially affected admission batches and programmes.",
            ),
        ]
        for col, (title, text) in zip((c1, c2, c3), capabilities):
            with col:
                st.markdown(
                    f"""
                    <div class="cap-card">
                        <div class="cap-title">{escape(title)}</div>
                        <p class="cap-text">{escape(text)}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
        section_title(
            "Regulation Processing Workflow",
            "End-to-end flow from document ingestion to cited, evidence-grounded answers.",
        )
        steps = ["Upload", "Extract", "Verify", "Retrieve", "Answer", "Cite"]
        step_html = '<div class="workflow-step">{}</div>'
        arrow_html = '<div class="workflow-arrow">→</div>'
        parts = []
        for i, step in enumerate(steps):
            parts.append(step_html.format(escape(step)))
            if i < len(steps) - 1:
                parts.append(arrow_html)
        card('<div class="workflow-wrap">' + "".join(parts) + "</div>", compact=True)

    with right:
        section_title(
            "Recent Regulation Activity",
            "Latest uploaded regulations based on stored upload timestamps.",
        )
        recent = []
        for regulation in regulations:
            upload_dt = parse_datetime_for_sort(regulation.get("upload_date"))
            if upload_dt is not None:
                recent.append((upload_dt, regulation))
        recent.sort(key=lambda item: item[0], reverse=True)

        if not recent:
            empty_state(
                "◷",
                "No recent activity yet",
                "Upload a regulation document to begin tracking activity and verification progress.",
            )
        else:
            for upload_dt, regulation in recent[:6]:
                doc_name = display_value(regulation.get("document_name"), "Untitled regulation")
                version = display_value(regulation.get("regulation_version"))
                uploaded = format_datetime_display(regulation.get("upload_date"))
                status_html = status_pill(regulation.get("verification_status"))
                processing = display_value(regulation.get("processing_status"), "Unknown")
                st.markdown(
                    f"""
                    <div class="cq-card compact" style="margin-bottom:0.6rem;">
                        <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                            <div>
                                <div style="font-weight:700; color:#102A43; line-height:1.35;">{escape(doc_name)}</div>
                                <div class="cq-muted" style="font-size:0.86rem; margin-top:0.15rem;">
                                    Version {escape(version)} · Uploaded {escape(uploaded)}
                                </div>
                                <div class="cq-muted" style="font-size:0.84rem; margin-top:0.1rem;">
                                    Processing: {escape(processing)}
                                </div>
                            </div>
                            <div>{status_html}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
        section_title("Platform Summary", "How CohortIQ AI supports regulation management and guidance.")
        card(
            """
            <div class="cq-section-desc" style="color:#172B4D;">
                CohortIQ AI helps institutions manage regulation documents, identify cohort-applicable rules,
                retrieve relevant clauses from approved sources, and generate evidence-grounded answers with citations.
                Verification status and stored metadata determine which regulations can be used for cohort-aware responses.
            </div>
            """,
            compact=True,
        )
