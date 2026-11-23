"""Theme and global styling for the CohortIQ AI Streamlit frontend."""

from __future__ import annotations

import streamlit as st

PRODUCT_NAME = "CohortIQ AI"
PRODUCT_DESCRIPTOR = "Intelligent Academic Regulation & Cohort Impact Navigator"
PRODUCT_TAGLINE = "Every Rule. Every Cohort. The Right Answer."

APPROVED_STATUSES = {
    "approved",
    "verified",
    "administrator_verified",
    "administrator_approved",
    "verified_and_approved",
}

NAV_ITEMS = [
    ("dashboard", "Dashboard", "◫"),
    ("management", "Regulation Management", "▤"),
    ("assistant", "AI Regulation Assistant", "✦"),
    ("library", "Regulation Library", "▥"),
]
NAV_PAGE_TO_LABEL = {key: label for key, label, _ in NAV_ITEMS}
NAV_PAGE_TO_ICON = {key: icon for key, _, icon in NAV_ITEMS}

PALETTE = {
    "primary_navy": "#102A43",
    "dark_navy": "#0B1F35",
    "secondary_blue": "#173F67",
    "primary_accent": "#3B82F6",
    "light_bg": "#F5F7FB",
    "card_bg": "#FFFFFF",
    "primary_text": "#172B4D",
    "secondary_text": "#64748B",
    "success": "#16A34A",
    "warning": "#D97706",
    "error": "#DC2626",
    "border": "#D9E2EC",
}


def inject_styles() -> None:
    """Apply the CohortIQ AI design system and layout styles."""
    st.markdown(
        """
        <style>
            :root {
                --cq-primary-navy: #102A43;
                --cq-dark-navy: #0B1F35;
                --cq-secondary-blue: #173F67;
                --cq-primary-accent: #3B82F6;
                --cq-primary-accent-hover: #2563EB;
                --cq-light-bg: #F5F7FB;
                --cq-card-bg: #FFFFFF;
                --cq-primary-text: #172B4D;
                --cq-secondary-text: #64748B;
                --cq-success: #16A34A;
                --cq-warning: #D97706;
                --cq-error: #DC2626;
                --cq-border: #D9E2EC;
                --cq-border-strong: #CBD5E1;
                --cq-soft: #EEF4FF;
                --cq-radius: 14px;
                --cq-radius-sm: 10px;
                --cq-shadow: 0 8px 24px rgba(16, 42, 67, 0.08);
                --cq-shadow-soft: 0 4px 14px rgba(16, 42, 67, 0.06);
            }

            html, body, [class*="css"] {
                color: var(--cq-primary-text);
                font-family: "Inter", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            }

            .stApp {
                background: var(--cq-light-bg);
                color: var(--cq-primary-text);
            }

            .block-container {
                padding-top: 1.2rem;
                padding-bottom: 2.5rem;
                max-width: 1320px;
            }

            h1, h2, h3, h4, h5, h6 {
                color: var(--cq-primary-navy);
                letter-spacing: -0.015em;
            }
            p, li, span, div, label {
                color: var(--cq-primary-text);
            }
            .cq-muted, .stCaption, [data-testid="stCaptionContainer"], small {
                color: var(--cq-secondary-text) !important;
            }

            /* Sidebar */
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, var(--cq-primary-navy) 0%, var(--cq-dark-navy) 100%);
                border-right: 1px solid rgba(255,255,255,0.06);
            }
            [data-testid="stSidebar"] > div:first-child {
                padding-top: 1rem;
            }
            [data-testid="stSidebar"] .sidebar-brand,
            [data-testid="stSidebar"] .sidebar-brand * {
                color: #FFFFFF !important;
            }
            [data-testid="stSidebar"] .sidebar-product {
                font-size: 1.4rem;
                font-weight: 800;
                line-height: 1.1;
                letter-spacing: -0.02em;
            }
            [data-testid="stSidebar"] .sidebar-descriptor {
                color: #D6E6FF !important;
                font-size: 0.86rem;
                line-height: 1.4;
                margin-top: 0.35rem;
            }
            [data-testid="stSidebar"] .sidebar-tagline {
                color: #AFCBFF !important;
                font-size: 0.82rem;
                margin-top: 0.45rem;
                font-weight: 600;
            }
            [data-testid="stSidebar"] hr {
                border-color: rgba(255,255,255,0.14);
                margin: 0.9rem 0;
            }
            [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
            [data-testid="stSidebar"] label {
                color: #EAF2FF !important;
                font-weight: 600 !important;
            }
            [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 10px;
                padding: 0.45rem 0.65rem;
                margin-bottom: 0.35rem;
                transition: all 0.15s ease;
            }
            [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
                background: rgba(255,255,255,0.10);
                border-color: rgba(255,255,255,0.14);
            }
            [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label p {
                color: #EAF2FF !important;
                font-weight: 600;
            }
            [data-testid="stSidebar"] .sidebar-note {
                color: #D6E6FF !important;
                font-size: 0.82rem;
                line-height: 1.5;
            }

            /* Inputs - consistent, readable, no dark backgrounds */
            [data-testid="stWidgetLabel"] p,
            .stTextInput label, .stTextArea label, .stSelectbox label,
            .stDateInput label, .stFileUploader label, .stMultiSelect label {
                color: var(--cq-primary-text) !important;
                font-weight: 600 !important;
                font-size: 0.94rem !important;
            }
            .stTextInput input,
            .stTextArea textarea,
            .stDateInput input,
            input[type="text"], input[type="search"] {
                background: #FFFFFF !important;
                color: var(--cq-primary-text) !important;
                -webkit-text-fill-color: var(--cq-primary-text) !important;
                border: 1px solid var(--cq-border) !important;
                border-radius: 10px !important;
            }
            .stTextInput input::placeholder,
            .stTextArea textarea::placeholder {
                color: #94A3B8 !important;
                -webkit-text-fill-color: #94A3B8 !important;
                opacity: 1 !important;
            }
            div[data-baseweb="select"] > div,
            div[data-baseweb="base-input"] > div {
                background: #FFFFFF !important;
                border-color: var(--cq-border) !important;
                border-radius: 10px !important;
                color: var(--cq-primary-text) !important;
            }
            div[data-baseweb="select"] span,
            div[data-baseweb="select"] input,
            div[data-baseweb="select"] div {
                color: var(--cq-primary-text) !important;
                -webkit-text-fill-color: var(--cq-primary-text) !important;
            }
            div[data-baseweb="select"] svg { fill: var(--cq-secondary-text) !important; }
            div[data-baseweb="popover"], ul[role="listbox"], li[role="option"] {
                background: #FFFFFF !important;
                color: var(--cq-primary-text) !important;
            }

            /* File uploader */
            [data-testid="stFileUploader"] section {
                background: #FFFFFF !important;
                border: 1.5px dashed #B8C7DA !important;
                border-radius: 12px !important;
                padding: 0.8rem !important;
                transition: border-color 0.15s ease, background 0.15s ease;
            }
            [data-testid="stFileUploader"] section:hover {
                border-color: var(--cq-primary-accent) !important;
                background: #F8FBFF !important;
            }
            [data-testid="stFileUploader"] * { color: var(--cq-primary-text) !important; }
            [data-testid="stFileUploader"] small { color: var(--cq-secondary-text) !important; }

            /* Buttons */
            .stButton > button, .stFormSubmitButton > button {
                border-radius: 10px !important;
                font-weight: 600 !important;
                border: 1px solid var(--cq-border) !important;
                padding: 0.55rem 1rem !important;
                min-height: 2.55rem;
                transition: all 0.15s ease;
            }
            .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
                background: var(--cq-primary-accent) !important;
                color: #FFFFFF !important;
                border-color: var(--cq-primary-accent) !important;
                box-shadow: 0 4px 12px rgba(59, 130, 246, 0.22);
            }
            .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
                background: var(--cq-primary-accent-hover) !important;
                border-color: var(--cq-primary-accent-hover) !important;
            }
            .stButton > button:not([kind="primary"]) {
                background: #FFFFFF !important;
                color: var(--cq-primary-text) !important;
            }
            .stButton > button:not([kind="primary"]):hover {
                border-color: var(--cq-border-strong) !important;
                background: #F8FAFC !important;
            }

            /* Page header */
            .cq-page-header {
                margin: 0 0 1rem 0;
                padding-bottom: 0.2rem;
            }
            .cq-breadcrumb {
                color: var(--cq-secondary-text);
                font-size: 0.82rem;
                font-weight: 600;
                margin-bottom: 0.25rem;
                letter-spacing: 0.01em;
            }
            .cq-page-title {
                margin: 0;
                font-size: 1.85rem;
                line-height: 1.2;
                color: var(--cq-primary-navy);
                font-weight: 750;
            }
            .cq-page-desc {
                margin: 0.3rem 0 0 0;
                color: var(--cq-secondary-text);
                font-size: 0.98rem;
                line-height: 1.55;
                max-width: 900px;
            }

            /* Cards */
            .cq-card {
                background: var(--cq-card-bg);
                border: 1px solid var(--cq-border);
                border-radius: var(--cq-radius);
                padding: 1.1rem 1.2rem;
                box-shadow: var(--cq-shadow);
                margin-bottom: 0.9rem;
            }
            .cq-card.compact { padding: 0.9rem 1rem; margin-bottom: 0.7rem; box-shadow: var(--cq-shadow-soft); }
            .cq-kicker {
                color: var(--cq-primary-accent);
                font-size: 0.76rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-bottom: 0.25rem;
            }
            .cq-section-title {
                color: var(--cq-primary-navy);
                font-size: 1.05rem;
                font-weight: 700;
                margin: 0 0 0.3rem 0;
            }
            .cq-section-desc {
                color: var(--cq-secondary-text);
                font-size: 0.93rem;
                line-height: 1.55;
                margin: 0;
            }

            /* Metric cards */
            .metric-card {
                background: #FFFFFF;
                border: 1px solid var(--cq-border);
                border-radius: var(--cq-radius);
                padding: 1rem 1.1rem;
                box-shadow: var(--cq-shadow-soft);
                height: 100%;
            }
            .metric-label { color: var(--cq-secondary-text); font-size: 0.88rem; margin-bottom: 0.25rem; font-weight: 600; }
            .metric-value { color: var(--cq-primary-navy); font-size: 1.95rem; font-weight: 750; line-height: 1.05; }
            .metric-hint { color: var(--cq-secondary-text); font-size: 0.8rem; margin-top: 0.25rem; line-height: 1.35; }

            /* Status badges */
            .status-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.22rem 0.62rem;
                border-radius: 999px;
                font-size: 0.8rem;
                font-weight: 700;
                border: 1px solid transparent;
                white-space: nowrap;
                line-height: 1.2;
            }
            .status-approved { background: #ECFDF3; color: #166534; border-color: #BBF7D0; }
            .status-pending { background: #FFFBEB; color: #92400E; border-color: #FDE68A; }
            .status-rejected { background: #FEF2F2; color: #991B1B; border-color: #FECACA; }
            .status-neutral { background: #EFF6FF; color: #1E40AF; border-color: #BFDBFE; }

            /* Capability cards */
            .cap-card {
                background: #FFFFFF;
                border: 1px solid var(--cq-border);
                border-radius: var(--cq-radius);
                padding: 1rem 1.05rem;
                height: 100%;
                box-shadow: var(--cq-shadow-soft);
            }
            .cap-icon { font-size: 1.3rem; margin-bottom: 0.35rem; }
            .cap-title { color: var(--cq-primary-navy); font-weight: 700; margin-bottom: 0.3rem; font-size: 0.98rem; }
            .cap-text { color: var(--cq-secondary-text); font-size: 0.92rem; line-height: 1.55; margin: 0; }

            /* Workflow */
            .workflow-wrap {
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                align-items: center;
                margin-top: 0.4rem;
            }
            .workflow-step {
                background: #F8FAFC;
                border: 1px solid var(--cq-border);
                color: var(--cq-primary-navy);
                border-radius: 999px;
                padding: 0.4rem 0.75rem;
                font-size: 0.86rem;
                font-weight: 600;
            }
            .workflow-arrow { color: var(--cq-secondary-text); font-weight: 700; font-size: 0.95rem; }

            /* Upload zone */
            .upload-zone {
                border: 1.5px dashed #B8C7DA;
                border-radius: 14px;
                background: linear-gradient(180deg, #F8FBFF 0%, #FFFFFF 100%);
                padding: 0.85rem 1rem;
                margin-bottom: 0.5rem;
            }
            .upload-zone-title { color: var(--cq-primary-navy); font-weight: 700; margin: 0; font-size: 0.98rem; }
            .upload-zone-sub { color: var(--cq-secondary-text); font-size: 0.9rem; margin: 0.15rem 0 0 0; }

            /* Chat / assistant */
            .chat-user {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 14px 14px 4px 14px;
                padding: 0.9rem 1rem;
                margin: 0.4rem 0 0.7rem 0;
            }
            .chat-assistant {
                background: #FFFFFF;
                border: 1px solid var(--cq-border);
                border-radius: 14px 14px 14px 4px;
                padding: 1rem 1.1rem;
                margin: 0.2rem 0 0.8rem 0;
                box-shadow: var(--cq-shadow-soft);
            }
            .chat-label {
                font-size: 0.76rem; font-weight: 700; color: var(--cq-secondary-text);
                text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.3rem;
            }
            .answer-text { color: var(--cq-primary-text); font-size: 1rem; line-height: 1.7; white-space: pre-wrap; }

            /* Citation cards */
            .citation-card {
                background: #F8FAFC;
                border: 1px solid var(--cq-border);
                border-left: 4px solid var(--cq-primary-accent);
                border-radius: 10px;
                padding: 0.8rem 0.95rem;
                margin-bottom: 0.65rem;
            }
            .citation-title { color: var(--cq-primary-navy); font-weight: 700; font-size: 0.94rem; margin-bottom: 0.2rem; }
            .citation-meta { color: var(--cq-secondary-text); font-size: 0.86rem; margin-bottom: 0.35rem; }
            .citation-text { color: var(--cq-primary-text); font-size: 0.92rem; line-height: 1.55; }

            /* Empty states */
            .empty-state {
                background: linear-gradient(180deg, #FFFFFF 0%, #F8FBFF 100%);
                border: 1px dashed #C9D8EA;
                border-radius: 16px;
                padding: 1.5rem 1.2rem;
                text-align: center;
            }
            .empty-state h4 { margin: 0.25rem 0 0.3rem 0; color: var(--cq-primary-navy); }
            .empty-state p { margin: 0; color: var(--cq-secondary-text); line-height: 1.5; }

            /* Library cards */
            .lib-card {
                background: #FFFFFF;
                border: 1px solid var(--cq-border);
                border-radius: 14px;
                padding: 1rem 1.1rem;
                margin-bottom: 0.75rem;
                box-shadow: var(--cq-shadow-soft);
            }
            .lib-title { color: var(--cq-primary-navy); font-weight: 700; font-size: 1.02rem; margin: 0; }
            .lib-meta { color: var(--cq-secondary-text); font-size: 0.9rem; margin-top: 0.15rem; }
            .lib-grid {
                display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 0.55rem 0.9rem; margin-top: 0.65rem;
            }
            .lib-field-label {
                color: var(--cq-secondary-text); font-size: 0.76rem; text-transform: uppercase;
                letter-spacing: 0.05em; font-weight: 700; margin-bottom: 0.1rem;
            }
            .lib-field-value { color: var(--cq-primary-text); font-size: 0.92rem; line-height: 1.4; }

            /* Expanders / dataframes */
            div[data-testid="stExpander"] {
                background: #FFFFFF;
                border: 1px solid var(--cq-border);
                border-radius: 12px;
            }
            [data-testid="stDataFrame"] { border: 1px solid var(--cq-border); border-radius: 12px; overflow: hidden; }
            div[data-testid="stForm"] { background: transparent; border: none; padding: 0; }
            [data-testid="stAlert"] { border-radius: 12px; }

            /* Focus */
            button:focus-visible, input:focus-visible, textarea:focus-visible {
                outline: 2px solid rgba(59,130,246,0.35) !important;
                outline-offset: 1px;
            }

            @media (max-width: 768px) {
                .block-container { padding-top: 0.8rem; padding-left: 0.8rem; padding-right: 0.8rem; }
                .cq-page-title { font-size: 1.5rem; }
                .metric-value { font-size: 1.6rem; }
                .cq-card, .lib-card { padding: 0.9rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
