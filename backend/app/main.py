"""FastAPI application entry point for the CohortIQ AI backend foundation."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import get_settings


settings = get_settings()

app = FastAPI(title=settings.project_name)

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


@app.get(f"{settings.api_v1_prefix}/health")
def health_check() -> dict[str, str]:
    """Return a basic health response indicating the API is running."""
    return {
        "status": "ok",
        "service": settings.project_name,
        "message": "API is running",
    }
