"""Shared UI helpers and components for CohortIQ AI."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from app.database import get_all_regulations
from app.ui.theme import APPROVED_STATUSES


def ensure_state(key: str, default: Any) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def safe_filename(filename: str) -> str:
    base_name = Path(filename or "uploaded_regulation.pdf").name
    stem = Path(base_name).stem
    suffix = Path(base_name).suffix or ".pdf"
    cleaned_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "uploaded_regulation"
    cleaned_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix) or ".pdf"
    if not cleaned_suffix.startswith("."):
        cleaned_suffix = f".{cleaned_suffix}"
    return f"{cleaned_stem}{cleaned_suffix.lower()}"


def unique_upload_path(upload_dir: Path, original_filename: str) -> Path:
    safe_name = safe_filename(original_filename)
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = upload_dir / f"{stem}_{timestamp}_{uuid.uuid4().hex[:8]}{suffix}"
    while candidate.exists():
        candidate = upload_dir / f"{stem}_{timestamp}_{uuid.uuid4().hex[:8]}{suffix}"
    return candidate


def parse_multivalue_input(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    parts = re.split(r"[,\n]+", raw_value)
    values = [part.strip() for part in parts if part and part.strip()]
    return list(dict.fromkeys(values))


def load_regulations(db_path: Path) -> list[dict[str, Any]]:
    try:
        return get_all_regulations(db_path=db_path)
    except Exception as exc:
        st.error(f"Unable to load regulations from the database: {exc}")
        return []


def display_value(value: Any, fallback: str = "N/A") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(items) if items else fallback
    text = str(value).strip()
    return text if text else fallback


def parse_datetime_for_sort(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def format_datetime_display(value: Any) -> str:
    dt = parse_datetime_for_sort(value)
    if dt is None:
        return display_value(value)
    raw = str(value)
    if dt.time().hour == 0 and dt.time().minute == 0 and dt.time().second == 0 and "T" not in raw and " " not in raw.strip():
        return dt.strftime("%d %b %Y")
    return dt.strftime("%d %b %Y, %I:%M %p")


def status_category(status: Any) -> str:
    value = str(status or "").strip().lower()
    if value in APPROVED_STATUSES:
        return "approved"
    if value == "rejected":
        return "rejected"
    return "pending"


def status_pill(status: Any, *, default_label: str = "Unknown") -> str:
    raw = str(status) if status is not None and str(status).strip() else default_label
    normalized = raw.strip().lower().replace(" ", "_")
    if normalized in APPROVED_STATUSES:
        css = "status-approved"
    elif normalized == "rejected":
        css = "status-rejected"
    elif normalized in {"pending", "unverified", "pending_verification"}:
        css = "status-pending"
    elif normalized in {"unknown", default_label.lower()}:
        css = "status-neutral"
    else:
        category = status_category(status)
        css = {
            "approved": "status-approved",
            "pending": "status-pending",
            "rejected": "status-rejected",
        }.get(category, "status-neutral")
    label = raw.replace("_", " ").strip().title() or default_label
    return f'<span class="status-pill {css}">{escape(label)}</span>'


def processing_status_pill(status: Any) -> str:
    raw = str(status) if status is not None and str(status).strip() else "Unknown"
    normalized = raw.strip().lower()
    if normalized in {"ingested", "processed", "completed", "success"}:
        css = "status-approved"
    elif normalized in {"failed", "error"}:
        css = "status-rejected"
    elif normalized in {"pending", "processing", "in_progress"}:
        css = "status-pending"
    else:
        css = "status-neutral"
    label = raw.replace("_", " ").strip().title() or "Unknown"
    return f'<span class="status-pill {css}">{escape(label)}</span>'


def page_header(title: str, description: str | None = None, breadcrumb: str | None = None) -> None:
    crumb = breadcrumb or f"CohortIQ AI / {title}"
    desc_html = (
        f'<p class="cq-page-desc">{escape(description)}</p>' if description else ""
    )
    st.markdown(
        f"""
        <div class="cq-page-header">
            <div class="cq-breadcrumb">{escape(crumb)}</div>
            <h1 class="cq-page-title">{escape(title)}</h1>
            {desc_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(title: str, description: str | None = None) -> None:
    desc_html = (
        f'<p class="cq-section-desc">{escape(description)}</p>' if description else ""
    )
    st.markdown(
        f'<div style="margin: 0.2rem 0 0.65rem 0;"><h3 style="margin:0 0 0.2rem 0; font-size:1.15rem;">{escape(title)}</h3>{desc_html}</div>',
        unsafe_allow_html=True,
    )


def card(content_html: str, *, compact: bool = False) -> None:
    klass = "cq-card compact" if compact else "cq-card"
    st.markdown(f'<div class="{klass}">{content_html}</div>', unsafe_allow_html=True)


def metric_card(label: str, value: Any, hint: str = "") -> str:
    hint_html = f'<div class="metric-hint">{escape(hint)}</div>' if hint else ""
    return (
        f'<div class="metric-card"><div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(str(value))}</div>{hint_html}</div>'
    )


def empty_state(icon: str, title: str, message: str) -> None:
    st.markdown(
        f"""
        <div class="empty-state">
            <div style="font-size:1.5rem;">{escape(icon)}</div>
            <h4>{escape(title)}</h4>
            <p>{escape(message)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
