"""FastAPI application entry point for the CohortIQ AI backend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ensure_app_directories
from app.config import get_settings as get_storage_settings
from app.database import init_database
from backend.app.api.v1 import api_router
from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def initialize_storage() -> Path:
    """Create application directories and SQLite tables; return the database path.

    Uses the same shared configuration and helpers as the Streamlit app, so both
    entry points operate on the same configured database. Table creation is
    idempotent (``CREATE TABLE IF NOT EXISTS``), so existing records are kept.
    """
    storage_settings = ensure_app_directories(get_storage_settings())
    init_database(storage_settings.database_path)
    return Path(storage_settings.database_path)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize database storage before the API starts serving requests.

    Initialization failures are logged and re-raised so the server refuses to
    start instead of serving requests against a missing or broken database.
    """
    try:
        database_path = initialize_storage()
    except Exception as exc:
        logger.exception("CohortIQ AI API startup failed: database initialization error.")
        raise RuntimeError(f"Failed to initialize the CohortIQ AI database: {exc}") from exc

    application.state.database_path = database_path
    logger.info("CohortIQ AI database initialized at %s", database_path)
    yield


app = FastAPI(title=settings.project_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def read_root() -> dict[str, str]:
    """Return a simple welcome response and API documentation path."""
    return {
        "message": "Welcome to CohortIQ AI API",
        "docs": "/docs",
    }


app.include_router(api_router, prefix=settings.api_v1_prefix)
