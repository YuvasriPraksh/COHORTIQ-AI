"""FastAPI application entry point for the CohortIQ AI backend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import ensure_app_directories
from app.config import get_settings as get_storage_settings
from app.database import init_database
from backend.app.api.v1 import api_router
from backend.app.core.config import format_byte_size, get_settings
from backend.app.core.limits import BodyLimit, RequestSizeLimitMiddleware

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

INGEST_PATH = f"{settings.api_v1_prefix}/regulations/ingest"
UPLOAD_TOO_LARGE_DETAIL = (
    f"The uploaded file exceeds the maximum allowed size of {format_byte_size(settings.max_upload_bytes)}."
)
REQUEST_TOO_LARGE_DETAIL = (
    f"Request body exceeds the maximum allowed size of {format_byte_size(settings.max_json_body_bytes)}."
)


def safe_validation_errors(errors: Any) -> list[dict[str, Any]]:
    """Keep only ``type``, ``loc`` and ``msg`` from validation errors.

    FastAPI's default 422 body echoes the submitted ``input`` (and internal
    ``ctx``/``url`` details); those are removed so client data, secrets or
    oversized values are never reflected back.
    """
    safe: list[dict[str, Any]] = []
    for error in errors or []:
        if not isinstance(error, dict):
            continue
        safe.append(
            {
                "type": str(error.get("type", "value_error")),
                "loc": [item if isinstance(item, (str, int)) else str(item) for item in error.get("loc", ())],
                "msg": str(error.get("msg", "Invalid value.")),
            }
        )
    return safe


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 422 validation errors without echoing client input."""
    return JSONResponse(status_code=422, content={"detail": safe_validation_errors(exc.errors())})


# Added before CORS so CORS stays the outermost layer and 413 responses still
# carry CORS headers for browser clients.
app.add_middleware(
    RequestSizeLimitMiddleware,
    default_limit=BodyLimit(settings.max_json_body_bytes, REQUEST_TOO_LARGE_DETAIL),
    path_limits={INGEST_PATH: BodyLimit(settings.max_upload_request_bytes, UPLOAD_TOO_LARGE_DETAIL)},
)

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
