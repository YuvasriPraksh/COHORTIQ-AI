"""AI Regulation Assistant page for CohortIQ AI."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from app.ui.common import (
    card,
    display_value,
    empty_state,
    load_regulations,
    page_header,
    section_title,
    status_category,
)
from app.workflow import answer_student_question

SUGGESTED_QUESTIONS = [
    "What attendance requirements apply to my cohort and programme?",
    "What are the progression or promotion criteria stated in the approved regulations?",
    "Are there any assessment or grading rules I should be aware of?",
    "What policies apply to re-examination, supplementary exams, or arrears?",
    "What academic conduct or disciplinary provisions are specified for my cohort?",
]


def _approved_cohort_options(regulations: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    batches: list[str] = []
    programmes: list[str] = []
    for regulation in regulations:
        if status_category(regulation.get("verification_status")) != "approved":
            continue
        for batch in regulation.get("applicable_batches") or []:
            text = str(batch).strip()
            if text and text not in batches:
                batches.append(text)
        for programme in regulation.get("applicable_programmes") or []:
            text = str(programme).strip()
            if text and text not in programmes:
                programmes.append(text)
    return batches, programmes


def _render_status_badge(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "answered":
        return '<span class="status-pill status-approved">Answered with evidence</span>'
    if s == "conflicting_evidence":
        return '<span class="status-pill status-pending">Conflicting evidence</span>'
    return '<span class="status-pill status-rejected">Insufficient evidence</span>'


def _render_citations(citations: list[dict[str, Any]]) -> None:
    if not citations:
        st.info("No validated citations are available for this response.")
        return
    for idx, citation in enumerate(citations, start=1):
        doc_name = display_value(citation.get("document_name"), "Unknown document")
        version = display_value(citation.get("regulation_version"), "N/A")
        page_number = citation.get("page_number")
        page_display = str(page_number) if page_number is not None else "N/A"
        chunk_id = display_value(citation.get("chunk_id"), "N/A")
        supporting_text = display_value(
            citation.get("relevant_supporting_text"), "No supporting text provided."
        )
        st.markdown(
            f"""
            <div class="citation-card">
                <div class="citation-title">Source {idx}: {escape(doc_name)}</div>
                <div class="citation-meta">
                    <strong>Regulation document:</strong> {escape(doc_name)} &nbsp;·&nbsp;
                    <strong>Version:</strong> {escape(version)} &nbsp;·&nbsp;
                    <strong>Page:</strong> {escape(page_display)} &nbsp;·&nbsp;
                    <strong>Chunk ID:</strong> {escape(chunk_id)}
                </div>
                <div class="citation-text"><strong>Supporting text:</strong> {escape(supporting_text)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_conflict_context(result: dict[str, Any]) -> None:
    retrieval = result.get("retrieval") or {}
    retrieved_results = retrieval.get("results") or []
    if not retrieved_results:
        return
    versions: dict[tuple[Any, Any, Any], set[Any]] = {}
    for item in retrieved_results:
        key = (
            item.get("document_name") or "Unknown document",
            item.get("regulation_version") or "Unknown version",
            item.get("regulation_id"),
        )
        versions.setdefault(key, set())
        if item.get("page_number") is not None:
            versions[key].add(item.get("page_number"))
    if len(versions) <= 1:
        return
    st.markdown("**Relevant regulation versions/sources in retrieved evidence (all preserved):**")
    for (doc_name, version, _reg_id), pages in sorted(versions.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
        page_list = ", ".join(str(p) for p in sorted(pages)) if pages else "N/A"
        st.write(f"- {doc_name} — version {version} (pages: {page_list})")


def _render_answer_result(result: dict[str, Any], question: str, batch: str, programme: str) -> None:
    answer_payload = result.get("answer") or {}
    status = str(result.get("status") or answer_payload.get("status") or "insufficient_evidence").strip().lower()
    answer_text = str(answer_payload.get("answer") or "No grounded answer is available.")
    limitations = answer_payload.get("limitations")
    citations = result.get("citations") or []
    validation_issues = result.get("validation_issues") or []
    retrieval = result.get("retrieval") or {}

    st.markdown(
        f"""
        <div class="chat-user">
            <div class="chat-label">Your question</div>
            <div><strong>Admission batch:</strong> {escape(batch or "N/A")} &nbsp;·&nbsp; <strong>Programme:</strong> {escape(programme or "N/A")}</div>
            <div style="margin-top:0.4rem; color:#172B4D; line-height:1.6;">{escape(question or "(No question provided)")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    badge_html = _render_status_badge(status)
    st.markdown(
        f'<div style="margin: 0.2rem 0 0.5rem 0;">{badge_html}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="chat-assistant">
            <div class="chat-label">CohortIQ AI response</div>
            <div class="answer-text">{escape(answer_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if status == "answered":
        st.success("Answer generated from retrieved, administrator-approved evidence for the selected cohort.")
    elif status == "conflicting_evidence":
        st.warning(
            limitations
            or "Retrieved approved regulations contain conflicting evidence. Review the cited sources below; CohortIQ AI does not automatically select the newest version."
        )
        _render_conflict_context(result)
    else:
        st.info(
            limitations
            or "Insufficient approved, cohort-applicable evidence was found to provide a fully grounded answer."
        )

    limitation_text = str(limitations or "").lower()
    if "gemini_api_key" in limitation_text or "not configured" in limitation_text:
        st.error(
            "Gemini is not configured. Set `GEMINI_API_KEY` in your `.env` file and restart the app to enable grounded answer generation."
        )
    elif "gemini" in limitation_text and (
        "failed" in limitation_text
        or "rate limit" in limitation_text
        or "unavailable" in limitation_text
        or "quota" in limitation_text
    ):
        st.error(f"Gemini service issue: {limitations}")
    elif "invalid model output" in limitation_text or "citation validation error" in limitation_text:
        st.error(f"Answer generation or validation issue: {limitations}")

    with st.expander("Evidence and citations", expanded=(status in {"answered", "conflicting_evidence"})):
        st.caption("Validated citations supporting the response. Each citation includes document, version, page, and supporting text.")
        _render_citations(citations)

        if validation_issues:
            st.markdown("**Citation validation notes**")
            for issue in validation_issues:
                st.write(f"- {issue}")

        st.markdown("**Retrieval details**")
        st.write(f"Retrieval status: {retrieval.get('status', 'unknown')}")
        st.write(retrieval.get("message") or "No retrieval message available.")
        results = retrieval.get("results") or []
        if results:
            st.caption("Retrieved evidence candidates (all preserved for review):")
            st.dataframe(
                [
                    {
                        "Document Name": item.get("document_name"),
                        "Regulation Version": item.get("regulation_version"),
                        "Page Number": item.get("page_number"),
                        "Chunk ID": item.get("chunk_id"),
                        "Retrieval Score": item.get("retrieval_score"),
                    }
                    for item in results
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No retrieved evidence candidates to display.")


def render(db_path: Path) -> None:
    page_header(
        "AI Regulation Assistant",
        "Ask cohort-specific questions and receive evidence-grounded answers with validated citations from approved regulations.",
        breadcrumb="CohortIQ AI / AI Regulation Assistant",
    )

    regulations = load_regulations(db_path)
    batch_options, programme_options = _approved_cohort_options(regulations)

    if not batch_options or not programme_options:
        st.warning(
            "No approved regulations are currently available for cohort-specific answering. "
            "Upload and explicitly approve applicable regulations in Regulation Management to enable grounded responses."
        )

    col_main, col_side = st.columns([1.45, 1], gap="large")

    with col_side:
        section_title("Cohort context", "Select the cohort context used for retrieval.")
        card(
            """
            <div class="cq-section-desc" style="color:#172B4D;">
                CohortIQ AI retrieves evidence only from administrator-approved regulations applicable to the selected
                admission batch and programme. Answers include validated citations or clearly state evidence limitations.
            </div>
            """,
            compact=True,
        )
        section_title("Suggested questions", "Use a prompt to start a cohort-specific query.")
        for i, suggestion in enumerate(SUGGESTED_QUESTIONS):
            if st.button(suggestion, key=f"suggest_{i}", use_container_width=True):
                st.session_state["assistant_question_input"] = suggestion
                st.rerun()

        if st.button("Clear question", use_container_width=True):
            st.session_state["assistant_question_input"] = ""
            st.rerun()

    with col_main:
        section_title("Conversation workspace", "Ask a question grounded in approved, cohort-applicable regulations.")

        with st.form("ask_question_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            with c1:
                if batch_options:
                    admission_batch = st.selectbox(
                        "Admission batch",
                        options=batch_options,
                        help="Select the admission batch for cohort-specific applicability.",
                    )
                else:
                    admission_batch = st.text_input(
                        "Admission batch",
                        placeholder="e.g. 2024",
                        help="Enter the admission batch for cohort-specific applicability.",
                    )
            with c2:
                if programme_options:
                    programme = st.selectbox(
                        "Programme",
                        options=programme_options,
                        help="Select the academic programme for cohort-specific applicability.",
                    )
                else:
                    programme = st.text_input(
                        "Programme",
                        placeholder="e.g. BSc Computer Science",
                        help="Enter the academic programme for cohort-specific applicability.",
                    )

            question = st.text_area(
                "Question",
                placeholder="Ask a question about the applicable academic regulations...",
                height=160,
                help="Ask about rules, eligibility, requirements, or policies relevant to the selected cohort.",
                key="assistant_question_input",
            )
            asked = st.form_submit_button("Ask CohortIQ AI", type="primary", use_container_width=True)

        last = st.session_state.get("assistant_last_result")
        if asked:
            clean_batch = str(admission_batch).strip()
            clean_programme = str(programme).strip()
            clean_question = question.strip() if isinstance(question, str) else str(question or "").strip()

            with st.spinner("Retrieving approved cohort evidence and generating a grounded answer..."):
                try:
                    result = answer_student_question(
                        admission_batch=clean_batch,
                        programme=clean_programme,
                        question=question,
                        db_path=db_path,
                    )
                except Exception as exc:
                    st.error(f"Unable to answer the question due to an unexpected error: {exc}")
                    result = None

            if result is not None:
                st.session_state["assistant_last_result"] = {
                    "question": clean_question,
                    "batch": clean_batch,
                    "programme": clean_programme,
                    "result": result,
                }
                last = st.session_state["assistant_last_result"]

        if last and isinstance(last, dict) and last.get("result"):
            _render_answer_result(
                last["result"],
                question=str(last.get("question") or ""),
                batch=str(last.get("batch") or ""),
                programme=str(last.get("programme") or ""),
            )
        else:
            empty_state(
                "✦",
                "Ask a grounded regulation question",
                "Select a cohort, enter or choose a question, and submit to receive an answer with validated citations from approved regulations.",
            )
