"""Environment-based configuration for the CohortIQ AI FastAPI backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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


def _parse_csv_origins(value: str | None) -> list[str]:
    """Parse a comma-separated origins string into a cleaned list."""
    if value is None:
        return list(DEFAULT_CORS_ORIGINS)

    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or list(DEFAULT_CORS_ORIGINS)


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


def get_settings() -> Settings:
    """Return backend settings resolved from the current environment."""
    return Settings()
