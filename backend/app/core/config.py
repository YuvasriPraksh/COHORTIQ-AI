"""Environment-based configuration for the CohortIQ AI FastAPI backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
)

KIB = 1024
MIB = 1024 * 1024

# Defaults of the student question request; configured limits must allow them.
DEFAULT_TOP_K = 5
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 200


def _parse_csv_origins(value: str | None) -> list[str]:
    """Parse a comma-separated origins string into a cleaned list."""
    if value is None:
        return list(DEFAULT_CORS_ORIGINS)

    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or list(DEFAULT_CORS_ORIGINS)


def _env_int(name: str, default: int) -> int:
    """Read an integer limit from the environment, falling back to ``default``."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ValueError(f"Invalid configuration: {name} must be an integer.") from None


def _limit(name: str, default: int) -> int:
    """Dataclass field for an integer limit overridable via environment variable ``name``."""
    return field(default_factory=lambda: _env_int(name, default), metadata={"env": name})


@dataclass(frozen=True)
class Settings:
    """Backend settings loaded from environment variables."""

    project_name: str = field(
        default_factory=lambda: os.getenv("PROJECT_NAME", "CohortIQ AI API")
    )
    api_v1_prefix: str = field(
        default_factory=lambda: os.getenv("API_V1_PREFIX", "/api/v1")
    )
    cors_allow_origins: list[str] = field(
        default_factory=lambda: _parse_csv_origins(os.getenv("BACKEND_CORS_ORIGINS"))
    )

    # --- Request size limits -------------------------------------------------
    max_upload_bytes: int = _limit("MAX_UPLOAD_BYTES", 20 * MIB)
    # Allowance for multipart boundaries and metadata fields on top of the file
    # itself, so a PDF of exactly ``max_upload_bytes`` is never rejected early.
    upload_multipart_overhead_bytes: int = _limit("UPLOAD_MULTIPART_OVERHEAD_BYTES", 1 * MIB)
    max_json_body_bytes: int = _limit("MAX_JSON_BODY_BYTES", 64 * KIB)
    max_pdf_pages: int = _limit("MAX_PDF_PAGES", 500)

    # --- Student question limits ---------------------------------------------
    max_question_length: int = _limit("MAX_QUESTION_LENGTH", 2000)
    max_identifier_length: int = _limit("MAX_IDENTIFIER_LENGTH", 100)
    max_top_k: int = _limit("MAX_TOP_K", 20)
    min_chunk_size: int = _limit("MIN_CHUNK_SIZE", 200)
    max_chunk_size: int = _limit("MAX_CHUNK_SIZE", 4000)
    max_overlap: int = _limit("MAX_OVERLAP", 1000)

    # --- Regulation ingestion metadata limits --------------------------------
    max_document_name_length: int = _limit("MAX_DOCUMENT_NAME_LENGTH", 200)
    max_regulation_version_length: int = _limit("MAX_REGULATION_VERSION_LENGTH", 50)
    max_effective_date_length: int = _limit("MAX_EFFECTIVE_DATE_LENGTH", 32)
    max_applicability_values: int = _limit("MAX_APPLICABILITY_VALUES", 50)
    max_form_fields: int = _limit("MAX_FORM_FIELDS", 120)
    max_form_part_size: int = _limit("MAX_FORM_PART_SIZE", 16 * KIB)

    def __post_init__(self) -> None:
        """Validate limits so misconfiguration fails at startup, not per request."""
        for item in fields(self):
            env_name = item.metadata.get("env")
            if env_name is None:
                continue
            value = getattr(self, item.name)
            minimum = 0 if item.name == "max_overlap" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"Invalid configuration: {env_name} must be an integer >= {minimum}.")

        if self.min_chunk_size > self.max_chunk_size:
            raise ValueError("Invalid configuration: MIN_CHUNK_SIZE must not exceed MAX_CHUNK_SIZE.")
        if self.max_top_k < DEFAULT_TOP_K:
            raise ValueError(f"Invalid configuration: MAX_TOP_K must be >= the default top_k ({DEFAULT_TOP_K}).")
        if not self.min_chunk_size <= DEFAULT_CHUNK_SIZE <= self.max_chunk_size:
            raise ValueError(
                "Invalid configuration: MIN_CHUNK_SIZE/MAX_CHUNK_SIZE must include the "
                f"default chunk_size ({DEFAULT_CHUNK_SIZE})."
            )
        if self.max_overlap < DEFAULT_OVERLAP:
            raise ValueError(f"Invalid configuration: MAX_OVERLAP must be >= the default overlap ({DEFAULT_OVERLAP}).")
        if self.max_effective_date_length < len("YYYY-MM-DD"):
            raise ValueError("Invalid configuration: MAX_EFFECTIVE_DATE_LENGTH must be >= 10.")

    @property
    def max_upload_request_bytes(self) -> int:
        """Largest accepted multipart ingestion request (file plus form overhead)."""
        return self.max_upload_bytes + self.upload_multipart_overhead_bytes


def get_settings() -> Settings:
    """Return backend settings resolved from the current environment."""
    return Settings()


def format_byte_size(size: int) -> str:
    """Human-readable size for client-facing limit messages (e.g. ``20 MB``)."""
    if size >= MIB and size % MIB == 0:
        return f"{size // MIB} MB"
    if size >= KIB and size % KIB == 0:
        return f"{size // KIB} KB"
    return f"{size} bytes"
