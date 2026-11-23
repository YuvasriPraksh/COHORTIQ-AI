"""Configuration management for CohortIQ AI.

This module is responsible for loading environment variables and exposing
application settings without hardcoding secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/cohortiq.db"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
    extracted_dir: Path = Path(os.getenv("EXTRACTED_DIR", "data/extracted"))


def get_settings() -> Settings:
    """Return the current application settings."""
    return Settings()


def ensure_app_directories(settings: Settings | None = None) -> Settings:
    """Ensure configured application directories exist and return settings."""
    resolved_settings = settings or get_settings()
    for path in (
        resolved_settings.database_path.parent,
        resolved_settings.upload_dir,
        resolved_settings.extracted_dir,
    ):
        if path and str(path) not in ("", "."):
            path.mkdir(parents=True, exist_ok=True)
    return resolved_settings
