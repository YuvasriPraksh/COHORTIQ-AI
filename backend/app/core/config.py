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

# --- Authentication -----------------------------------------------------------
APP_ENVIRONMENTS = ("development", "test", "production")
MIN_JWT_SECRET_BYTES = 32
MIN_JWT_SECRET_DISTINCT_CHARACTERS = 8
_PLACEHOLDER_SECRET_MARKERS = (
    "changeme",
    "change-me",
    "change_me",
    "replace-me",
    "replace_me",
    "replaceme",
    "your-secret",
    "your_secret",
    "yoursecret",
    "secret-key",
    "secret_key",
    "placeholder",
    "example",
)
DEFAULT_JWT_ISSUER = "cohortiq-ai-api"
DEFAULT_JWT_AUDIENCE = "cohortiq-ai-clients"


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


def _env_str(name: str, default: str) -> str:
    """Read a non-secret string setting; blank values fall back to ``default``."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_secret(name: str) -> str | None:
    """Read a secret; blank values are treated as missing. Never logged or echoed."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _auth_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Dataclass field for a bounded authentication integer setting."""
    return field(
        default_factory=lambda: _env_int(name, default),
        metadata={"auth_env": name, "min": minimum, "max": maximum},
    )


def jwt_secret_weakness(secret: str) -> str | None:
    """Return why ``secret`` is too weak for signing tokens, or ``None`` if acceptable.

    The returned reason never contains the secret itself.
    """
    if len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        return f"must be at least {MIN_JWT_SECRET_BYTES} bytes long"
    if len(set(secret)) < MIN_JWT_SECRET_DISTINCT_CHARACTERS:
        return "must not be a low-entropy (repetitive) value"
    lowered = secret.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_SECRET_MARKERS):
        return "must not be a placeholder value"
    return None


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

    # --- Authentication -------------------------------------------------------
    # Deployment environment: development, test or production.
    app_env: str = field(default_factory=lambda: _env_str("APP_ENV", "development").lower())
    # HS256 signing secret. Required (and must be strong) in production; there is
    # deliberately no default. Excluded from repr so it never appears in logs.
    jwt_secret_key: str | None = field(
        default_factory=lambda: _env_secret("JWT_SECRET_KEY"), repr=False
    )
    jwt_issuer: str = field(default_factory=lambda: _env_str("JWT_ISSUER", DEFAULT_JWT_ISSUER))
    jwt_audience: str = field(default_factory=lambda: _env_str("JWT_AUDIENCE", DEFAULT_JWT_AUDIENCE))
    access_token_expire_minutes: int = _auth_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30, 1, 1440)
    jwt_leeway_seconds: int = _auth_int("JWT_LEEWAY_SECONDS", 30, 0, 300)

    def __post_init__(self) -> None:
        """Validate limits so misconfiguration fails at startup, not per request."""
        self._validate_authentication()
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

    def _validate_authentication(self) -> None:
        """Validate authentication settings. Error messages never include secret values."""
        if self.app_env not in APP_ENVIRONMENTS:
            raise ValueError(
                "Invalid configuration: APP_ENV must be one of " + ", ".join(APP_ENVIRONMENTS) + "."
            )

        for item in fields(self):
            env_name = item.metadata.get("auth_env")
            if env_name is None:
                continue
            value = getattr(self, item.name)
            minimum, maximum = item.metadata["min"], item.metadata["max"]
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(
                    f"Invalid configuration: {env_name} must be an integer between {minimum} and {maximum}."
                )

        for env_name, value in (("JWT_ISSUER", self.jwt_issuer), ("JWT_AUDIENCE", self.jwt_audience)):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"Invalid configuration: {env_name} must be a non-empty string.")

        secret = self.jwt_secret_key
        if secret is None:
            if self.app_env == "production":
                raise ValueError("Invalid configuration: JWT_SECRET_KEY is required in production.")
            return
        if not isinstance(secret, str):
            raise ValueError("Invalid configuration: JWT_SECRET_KEY must be a string.")
        weakness = jwt_secret_weakness(secret)
        if weakness is not None:
            # A configured secret must always be strong, in every environment.
            raise ValueError(f"Invalid configuration: JWT_SECRET_KEY {weakness}.")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

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
